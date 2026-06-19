#!/usr/bin/env node
/**
 * super-engine login.ts — 一次性登入設定工具
 *
 * 用 Brave 瀏覽器開啟 GenSpark → 你手動登入 + 選 AI 聊天 → profile 存下來
 * 包含反自動化偵測參數，繞過 GenSpark 的安全檢查。
 *
 * 用法:
 *   node login.ts [--profile ./genspark-auth.json]
 *
 * 輸出: genspark-auth.json（Playwright storageState，含 cookies + localStorage）
 */
import { chromium } from "playwright";
import { parseArgs } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser";

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: { profile: { type: "string" } },
  });

  const profilePath = path.resolve(values.profile || "./genspark-auth.json");

  console.log("=".repeat(60));
  console.log("🧬 super-engine — GenSpark 登入設定 (Brave)");
  console.log("=".repeat(60));
  console.log("");
  console.log("瀏覽器即將開啟（使用你的 Brave）。請完成以下步驟：");
  console.log("");
  console.log("  ① 登入你的 GenSpark 帳號");
  console.log("  ② 進入 AI 聊天模式（非超級智能體）");
  console.log("  ③ 選擇你要用的模型（如 Opus 4.8）");
  console.log("  ④ 回到此終端機，按 Enter 儲存登入狀態");
  console.log("");
  console.log(`儲存路徑: ${profilePath}`);
  console.log("");

  const browser = await chromium.launch({
    executablePath: BRAVE_PATH,
    headless: false,
    args: [
      "--no-sandbox",
      "--disable-blink-features=AutomationControlled",
    ],
  });

  const context = await browser.newContext({
    locale: "zh-TW",
  });

  const page = await context.newPage();
  await page.goto("https://www.genspark.ai", {
    waitUntil: "networkidle",
    timeout: 30_000,
  });

  // Wait for user to press Enter
  await new Promise<void>((resolve) => {
    console.log("⏳ 完成登入後按 Enter 繼續...");
    process.stdin.once("data", () => resolve());
  });

  // Save storage state (cookies + localStorage)
  await context.storageState({ path: profilePath });

  await browser.close();
  console.log(`\n✅ 登入狀態已儲存至: ${profilePath}`);
  console.log("   現在可以用 ask.ts 搭配 --profile 參數使用了。");
}

main().catch((err) => {
  console.error("❌ 錯誤:", err.message);
  process.exit(1);
});