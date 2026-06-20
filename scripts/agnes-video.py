#!/usr/bin/env python3
"""CLI: generate video + poll status via Agnes video model."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from orchestrator.agnes import generate_video, get_video_status, wait_for_video


def main():
    p = argparse.ArgumentParser(description="Generate video with Agnes")
    p.add_argument("--prompt", required=True, help="Video description")
    p.add_argument("--wait", action="store_true", help="Block until complete")
    p.add_argument("--poll-interval", type=int, default=3, help="Seconds between polls")
    p.add_argument("--max-polls", type=int, default=60, help="Max polls before timeout")
    args = p.parse_args()

    submit = generate_video(prompt=args.prompt)
    if submit.get("error"):
        print(json.dumps(submit, ensure_ascii=False, indent=2))
        sys.exit(1)

    if args.wait and submit.get("task_id"):
        result = wait_for_video(
            submit["task_id"],
            poll_interval=args.poll_interval,
            max_polls=args.max_polls,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(submit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()