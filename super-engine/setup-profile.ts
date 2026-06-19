#!/usr/bin/env node
/**
 * setup-profile.ts — 建立可重用的 Brave profile（支援指紋/金鑰登入）
 *
 * 流程：
 *  1. 複製你 Brave 的 Profile 8（含既有 cookies）
 *  2. 用 Playwright Chromium 載入此 profile
 *  3. 你手動指紋登入 GenSpark + 進 AI 聊天
 *  4. 按 Enter 儲存完整 profile
 *
 * 用法:
 *   node setup-profile.ts [--dir ./brave-profile]
 */
import { chromium } from "playwright";
import { parseArgs } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import { execSync } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BRAVE_PROFILE_SRC = path.join(
  process.env.HOME || "",
  "Library/Application Support/BraveSoftware/Brave-Browser/Profile 8"
);

async function copyProfile(src: string, dest: string): Promise<void> {
  if (fs.existsSync(dest)) {
    console.log(`⚠️  目標目錄已存在: ${dest}`);
    console.log("   移除舊的...");
    fs.rmSync(dest, { recursive: true, force: true });
  }
  console.log(`📋 複製 Brave Profile 8 → ${dest} ...`);
  execSync(`cp -R "${src}" "${dest}"`, { stdio: "pipe" });
  console.log("✅ 複製完成");
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: { dir: { type: "string" } },
  });

  const profileDir = path.resolve(values.dir || "./brave-profile");

  console.log("=".repeat(60));
  console.log("🧬 super-engine — Profile 設定（指紋登入支援）");
  console.log("=".repeat(60));
  console.log("");

  // Copy existing Brave profile
  if (fs.existsSync(BRAVE_PROFILE_SRC)) {
    await copyProfile(BRAVE_PROFILE_SRC, profileDir);
  } else {
    console.log("⚠️  找不到 Brave Profile 8，使用全新 profile");
  }

  console.log("");
  console.log("Brave 瀏覽器即將開啟。請完成：");
  console.log("  ① 登入 GenSpark（用你的指紋/金鑰）");
  console.log("  ② 進 AI 聊天模式，選 Opus 4.8");
  console.log("  ③ 回到此終端機，按 Enter 儲存 profile");
  console.log(`\nProfile 路徑: ${profileDir}`);
  console.log("");

  const browser = await chromium.launchPersistentContext(profileDir, {
    headless: false,
    args: [
      "--no-sandbox",
      "--disable-blink-features=AutomationControlled",
    ],
    locale: "zh-TW",
  });

  const page = await browser.newPage();
  await page.goto("https://www.genspark.ai/agents?type=ai_chat", {
    waitUntil: "load",
    timeout: 60_000,
  });

  console.log("✅ GenSpark 已載入，請開始登入...");

  // Wait for user to press Enter
  await new Promise<void>((resolve) => {
    process.stdin.once("data", () => resolve());
  });

  await browser.close();
  console.log(`\n✅ Profile 已儲存至: ${profileDir}`);
  console.log("   現在 ask.ts 可以用 --profile 參數載入此 profile。");
}

main().catch((err) => {
  console.error("❌ 錯誤:", err.message);
  process.exit(1);
});