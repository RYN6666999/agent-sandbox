#!/usr/bin/env node
/**
 * ask-daemon.ts — Keep-warm HTTP server for super-engine.
 *
 * Opens Brave once, keeps it alive. Accepts HTTP requests.
 *
 * Usage:
 *   node ask-daemon.ts --port 3456 --profile ./brave-profile
 *
 * API:
 *   POST /ask  {"provider":"gemini","prompt":"hello"} → {"output":"Hi!","timing":2.1}
 *   GET  /health                                      → {"ok":true}
 *   POST /newchat                                     → {"ok":true} (clear chat)
 */
import * as http from "node:http";
import { parseArgs } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import { chromium, type Page, type BrowserContext } from "playwright";
import { PROVIDERS } from "./config.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";

let page: Page | undefined;
let context: BrowserContext | undefined;

function readBody(req: http.IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString()));
    req.on("error", reject);
  });
}

function jsonResp(res: http.ServerResponse, data: unknown, status = 200) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}

async function initBrowser(profileDir: string) {
  context = await chromium.launchPersistentContext(profileDir, {
    headless: false,
    args: ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
  });
  page = context.pages()[0] || await context.newPage();
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "webdriver", { get: () => false });
  });
}

async function ask(provider: string, prompt: string): Promise<{ output: string; timing: number }> {
  if (!page) throw new Error("Browser not initialized");
  const config = PROVIDERS[provider as keyof typeof PROVIDERS];
  if (!config) throw new Error(`Unknown provider: ${provider}`);

  const startTime = Date.now();

  // Navigate if needed
  const currentUrl = page.url();
  if (!currentUrl.startsWith(config.url)) {
    await page.goto(config.url, { waitUntil: "load", timeout: 30_000 });
  }

  // Wait for input
  await page.waitForSelector(config.inputSelector, { timeout: 10_000 });

  // Type + submit
  const input = page.locator(config.inputSelector);
  await input.fill(prompt);
  if (config.submitSelector === config.inputSelector) {
    await input.press("Enter");
  } else {
    await page.locator(config.submitSelector).click();
  }

  // Fast polling
  const msgSelector = "[class*=message], [class*=msg-item], .chat-wrapper > *, [class*=turn]";
  const prevCount = await page.evaluate((sel: string) => document.querySelectorAll(sel).length, msgSelector);
  const deadline = Date.now() + (config.responseTimeoutMs || 120_000);

  while (Date.now() < deadline) {
    await page.waitForTimeout(200);
    const curCount = await page.evaluate((sel: string) => document.querySelectorAll(sel).length, msgSelector);
    if (curCount > prevCount) {
      await page.waitForTimeout(500);
      break;
    }
  }

  // Extract response
  const output = await page.evaluate(() => {
    const sels = [
      "[class*=message-content], [class*=msg-content], [class*=answer-content]",
      ".conversation-turn, [class*=turn], .response-container, article",
      ".chat-wrapper [class*=text], .chat-wrapper p, .chat-wrapper li",
      "[class*=message], [class*=msg-item]",
    ];
    for (const sel of sels) {
      const els = document.querySelectorAll(sel);
      if (els.length > 0) {
        const text = (els[els.length - 1].textContent || "").trim();
        const noise = ["麥克風", "新對話", "搜尋", "編輯提示詞", "複製", "答得好", "重做", "顯示更多"];
        const filtered = text.split("\n").filter(l => !noise.some(n => l.includes(n))).join("\n");
        if (filtered.length > 3) return filtered;
      }
    }
    return "";
  });

  const timing = (Date.now() - startTime) / 1000;
  return { output, timing };
}

async function main() {
  const { values } = parseArgs({
    options: {
      port: { type: "string", default: "3456" },
      profile: { type: "string", default: path.resolve(__dirname, "brave-profile") },
    },
  });

  const port = parseInt(values.port || "3456", 10);
  const profileDir = path.resolve(values.profile || "./brave-profile");

  console.log(`🚀 Starting super-engine daemon on port ${port}`);
  console.log(`   Profile: ${profileDir}`);

  // Init browser
  const profileExists = fs.existsSync(profileDir);
  if (!profileExists) {
    console.error(`❌ Profile not found: ${profileDir}`);
    console.error("   Run 'node setup-profile.ts' first.");
    process.exit(1);
  }
  await initBrowser(profileDir);
  console.log("✅ Browser ready");

  // HTTP server
  const server = http.createServer(async (req, res) => {
    try {
      if (req.method === "GET" && req.url === "/health") {
        jsonResp(res, { ok: true, browserReady: !!page });
        return;
      }

      if (req.method === "POST" && req.url === "/newchat") {
        // Navigate fresh to clear chat history
        await page?.goto("about:blank");
        jsonResp(res, { ok: true });
        return;
      }

      if (req.method === "POST" && req.url === "/ask") {
        const body = JSON.parse(await readBody(req));
        const { provider, prompt } = body;
        if (!provider || !prompt) {
          jsonResp(res, { error: "provider and prompt required" }, 400);
          return;
        }
        const result = await ask(provider, prompt);
        jsonResp(res, result);
        return;
      }

      jsonResp(res, { error: "Not found" }, 404);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      jsonResp(res, { error: msg }, 500);
    }
  });

  server.listen(port, "127.0.0.1", () => {
    console.log(`✅ Listening on http://127.0.0.1:${port}`);
    console.log(`   POST /ask  {"provider":"gemini","prompt":"..."}`);
    console.log(`   GET  /health`);
  });

  // Graceful shutdown
  const shutdown = async () => {
    console.log("\n🛑 Shutting down...");
    if (context) await context.close();
    server.close();
    process.exit(0);
  };
  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((err) => {
  console.error("❌ Fatal:", err.message);
  process.exit(1);
});