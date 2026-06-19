#!/usr/bin/env node
/**
 * super-engine ask.ts — Playwright-driven web LLM client.
 *
 * Usage:
 *   node ask.ts --provider genspark --prompt "your question" [--profile ./genspark-auth.json] [--headless]
 *
 * Outputs JSON to stdout:
 *   {"output": "response text", "timing": 12.3}
 *   {"error": "error message"}
 */

import { chromium, type Page } from "playwright";
import { PROVIDERS, type ProviderConfig } from "./config.js";
import { parseArgs } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";

interface Args {
  provider: string;
  prompt: string;
  profile?: string;
  headless: boolean;
}

function usage(): never {
  console.error(
    `Usage: node ask.ts --provider <name> --prompt <text> [--profile <path>] [--headless]`
  );
  console.error(`Available providers: ${Object.keys(PROVIDERS).join(", ")}`);
  process.exit(1);
}

function parseCliArgs(): Args {
  const { values } = parseArgs({
    options: {
      provider: { type: "string", short: "p" },
      prompt: { type: "string", short: "m" },
      profile: { type: "string" },
      headless: { type: "boolean", default: false },
    },
  });

  if (!values.provider || !values.prompt) {
    usage();
  }

  return {
    provider: values.provider,
    prompt: values.prompt,
    profile: values.profile || path.resolve(__dirname, "brave-profile"),
    headless: values.headless ?? false,
  };
}

function errorExit(msg: string, code = 1): never {
  console.log(JSON.stringify({ error: msg }));
  process.exit(code);
}

async function main(): Promise<void> {
  const args = parseCliArgs();
  const config: ProviderConfig | undefined = PROVIDERS[args.provider];
  if (!config) {
    errorExit(`Unknown provider '${args.provider}'. Available: ${Object.keys(PROVIDERS).join(", ")}`);
  }

  const startTime = Date.now();

  let browser, context;
  let page: Page | undefined;
  const fs = await import("node:fs");

  // If profile is a directory → use launchPersistentContext (full browser profile)
  // If profile is a JSON file → use storageState (cookies only)
  if (args.profile && fs.existsSync(args.profile) && fs.statSync(args.profile).isDirectory()) {
    // Persistent profile mode (supports passkey/fingerprint login)
    context = await chromium.launchPersistentContext(args.profile, {
      headless: args.headless,
      executablePath: BRAVE_PATH,
      args: [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
      ],
    });
    browser = context;
    page = context.pages()[0] || await context.newPage();
    // Anti-detection: hide automation fingerprints
    await page.addInitScript(() => {
      Object.defineProperty(navigator, "webdriver", { get: () => false });
    });
    await page.goto(config.url, { waitUntil: "load", timeout: 60_000 });
  } else {
    // Standard launch mode (with optional storageState)
    const b = await chromium.launch({
      executablePath: BRAVE_PATH,
      headless: args.headless,
      args: [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
      ],
    });
    browser = b;

    if (args.profile && fs.existsSync(args.profile)) {
      context = await b.newContext({ storageState: args.profile });
    } else {
      if (args.profile) {
        console.error(`⚠️ Profile not found: ${args.profile} — proceeding unauthenticated`);
      }
      context = await b.newContext();
    }
    page = await context.newPage();
  }

  try {
    // Navigate to provider
    await page.goto(config.url, { waitUntil: "load", timeout: 60_000 });

    // Wait for input element to be ready
    await page.waitForSelector(config.inputSelector, { timeout: 15_000 });

    // Type prompt
    const input = page.locator(config.inputSelector);
    await input.fill(args.prompt);

        // Submit
    if (config.submitSelector === config.inputSelector) {
      await input.press("Enter");
    } else {
      const submitBtn = page.locator(config.submitSelector);
      await submitBtn.click();
    }

    // Fast polling: count message elements, break on increase
    const msgSelector = "[class*=message], [class*=msg-item], .chat-wrapper > *, [class*=turn]";
    const prevCount = await page.evaluate((sel) => document.querySelectorAll(sel).length, msgSelector);
    const pollDeadline = Date.now() + (config.responseTimeoutMs || 120_000);

    while (Date.now() < pollDeadline) {
      await page.waitForTimeout(200);
      const curCount = await page.evaluate((sel) => document.querySelectorAll(sel).length, msgSelector);
      if (curCount > prevCount) {
        await page.waitForTimeout(500);  // brief settling for streaming
        break;
      }
    }

    // Extract AI response
    const output = await page.evaluate(() => {
      // Try provider-specific selectors first
      const msgSelectors = [
        // Common chat message containers
        "[class*=message-content], [class*=msg-content], [class*=answer-content]",
        // Gemini-specific
        ".conversation-turn, [class*=turn], .response-container, article",
        // Generic last text block
        ".chat-wrapper [class*=text], .chat-wrapper p, .chat-wrapper li",
        // Any message-like element
        "[class*=message], [class*=msg-item]",
      ];
      for (const sel of msgSelectors) {
        const els = document.querySelectorAll(sel);
        if (els.length > 0) {
          // Get the last element (latest response)
          const text = (els[els.length - 1].textContent || "").trim();
          // Filter out common UI noise
          const noise = ["麥克風", "新對話", "搜尋", "編輯提示詞", "複製", "答得好", "重做", "顯示更多"];
          const filtered = text.split("\n").filter(line =>
            !noise.some(n => line.includes(n))
          ).join("\n");
          if (filtered.length > 3) return filtered;
        }
      }
      // Fallback: wrapper text
      const wrapper = document.querySelector(".chat-wrapper, main, [role=main]");
      return wrapper ? wrapper.textContent || "" : "";
    });

    const timing = (Date.now() - startTime) / 1000;

    console.log(JSON.stringify({ output: output.trim(), timing }));
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    errorExit(msg);
  } finally {
    await browser.close();
  }
}

main();