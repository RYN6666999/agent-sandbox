#!/usr/bin/env python3
"""Agnes video generator — calls Agnes Video API, returns task info.
Video generation is async — returns a task_id to poll for completion."""
import json
import os
import sys
import urllib.request
import urllib.error

API_BASE = "https://apihub.agnes-ai.com/v1"
API_KEY = os.environ.get("AGNES_API_KEY", "")

if not API_KEY:
    print(json.dumps({"error": "AGNES_API_KEY not set"}))
    sys.exit(1)

prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
if not prompt:
    print(json.dumps({"error": "no prompt provided"}))
    sys.exit(1)

payload = json.dumps({
    "model": "agnes-video-v2.0",
    "prompt": prompt,
}).encode()

req = urllib.request.Request(
    f"{API_BASE}/video/generations",
    data=payload,
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    resp = urllib.request.urlopen(req, timeout=120)
    data = json.loads(resp.read())
    result = {
        "task_id": data.get("task_id", ""),
        "video_id": data.get("video_id", ""),
        "status": data.get("status", ""),
        "progress": data.get("progress", 0),
        "seconds": data.get("seconds", "5.0"),
        "size": data.get("size", ""),
        "prompt": prompt,
    }
    print(json.dumps(result, ensure_ascii=False))
except urllib.error.HTTPError as e:
    print(json.dumps({"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}))
    sys.exit(1)
except Exception as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(1)