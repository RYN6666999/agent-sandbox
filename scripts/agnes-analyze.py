#!/usr/bin/env python3
"""CLI: analyze image via Agnes vision model."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from orchestrator.agnes import analyze_image


def main():
    p = argparse.ArgumentParser(description="Analyze image with Agnes vision")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--image-url", help="Public image URL")
    g.add_argument("--image-base64", help="Base64 data:image/...;base64,...")
    p.add_argument("--prompt", default="Describe this image in detail.")
    args = p.parse_args()

    result = analyze_image(
        image_url=args.image_url,
        image_base64=args.image_base64,
        prompt=args.prompt,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()