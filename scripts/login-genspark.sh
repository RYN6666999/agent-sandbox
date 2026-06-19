#!/bin/bash
# login-genspark.sh — 一次性 GenSpark 登入設定
# 完成登入後，ask.ts 可透過 --profile 參數直接重用 session

set -euo pipefail

DIR="$(cd "$(dirname "$0")/../super-engine" && pwd)"

echo "▶ 啟動 GenSpark 登入設定..."
echo "  瀏覽器開啟後，請完成：登入 → AI 聊天 → 選模型"
echo "  完成後回終端機按 Enter"
echo ""

cd "$DIR"

node login.ts

echo ""
echo "✅ 完成！現在可以執行:"
echo "   cd $DIR && node ask.ts --provider genspark --profile ./profile-genspark --prompt '你的問題'"