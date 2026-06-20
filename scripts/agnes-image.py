#!/usr/bin/env python3
"""CLI: generate image via Agnes image model."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from orchestrator.agnes import generate_image


def main():
    p = argparse.ArgumentParser(description="Generate image with Agnes")
    p.add_argument("--prompt", required=True, help="Image description")
    p.add_argument("--size", default="1024x1024", help="Size (e.g. 1024x1024)")
    p.add_argument("--n", type=int, default=1, help="Number of images")
    args = p.parse_args()

    result = generate_image(prompt=args.prompt, size=args.size, n=args.n)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()