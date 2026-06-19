#!/usr/bin/env python3
"""Extract GenSpark cookies from Brave browser and save as Playwright storageState.

Usage:
  python3 extract_cookies.py [--output ./genspark-auth.json]

Reads Brave's SQLite cookie database, filters for genspark.ai,
and writes a Playwright-compatible storageState JSON file.
"""
import json
import sqlite3
import shutil
import tempfile
from pathlib import Path

BRAVE_BASE = Path.home() / "Library/Application Support/BraveSoftware/Brave-Browser"
BRAVE_PROFILE = "Profile 8"
BRAVE_COOKIES = BRAVE_BASE / BRAVE_PROFILE / "Cookies"
DEFAULT_OUTPUT = Path(__file__).parent / "genspark-auth.json"


def extract_genspark_cookies(cookies_path: Path) -> list[dict]:
    """Read Brave cookie DB and return genspark.ai cookies."""
    if not cookies_path.exists():
        print(f"❌ Brave cookie DB not found at: {cookies_path}")
        return []

    # Copy to temp file to avoid locked-DB errors
    tmp = tempfile.NamedTemporaryFile(delete=False)
    shutil.copy2(cookies_path, tmp.name)

    try:
        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT host_key, name, value, path, expires_utc, is_secure, is_httponly, "
            "encrypted_value, samesite, priority "
            "FROM cookies WHERE host_key LIKE '%genspark%' OR host_key LIKE '%gspark%'"
        )
        rows = cursor.fetchall()
        conn.close()

        cookies = []
        for row in rows:
            cookie = {
                "name": row["name"],
                "value": row["value"],
                "domain": row["host_key"],
                "path": row["path"],
                "expires": row["expires_utc"] / 1_000_000 if row["expires_utc"] else -1,
                "httpOnly": bool(row["is_httponly"]),
                "secure": bool(row["is_secure"]),
                "sameSite": ["None", "Lax", "Strict"][row["samesite"]] if row["samesite"] in (0, 1, 2) else "Lax",
            }
            cookies.append(cookie)

        return cookies
    except Exception as e:
        print(f"❌ Error reading cookies: {e}")
        return []
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Extract GenSpark cookies from Brave")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output path for storageState JSON")
    args = parser.parse_args()

    output_path = Path(args.output)

    print(f"🔍 Reading Brave cookies from: {BRAVE_COOKIES}")

    cookies = extract_genspark_cookies(BRAVE_COOKIES)

    if not cookies:
        print("⚠️  No GenSpark cookies found.")
        print("   請確認你已經在 Brave 登入 GenSpark 並進到 AI 聊天頁面。")
        print("   然後再跑一次。")
        return

    storage_state = {
        "cookies": cookies,
        "origins": [],
    }

    output_path.write_text(json.dumps(storage_state, indent=2))
    print(f"\n✅ Found {len(cookies)} GenSpark cookies")
    for c in cookies:
        print(f"   {c['name']}: {c['domain']}")
    print(f"\n✅ Storage state saved to: {output_path}")
    print("   現在可以用 ask.ts 搭配 --profile 參數使用了。")


if __name__ == "__main__":
    main()