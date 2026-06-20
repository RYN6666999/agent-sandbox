#!/usr/bin/env python3
"""CLI wrapper for web search — used by executor registry (subprocess type).

Usage:
    python scripts/search-web.py "your search query"
    python scripts/search-web.py --count 10 "your search query"
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.search import search_web


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the web via DuckDuckGo")
    parser.add_argument("query", nargs="+", help="Search query")
    parser.add_argument("--count", type=int, default=5, help="Number of results (max 20)")
    args = parser.parse_args()

    query = " ".join(args.query)
    result = search_web(query, count=args.count)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
