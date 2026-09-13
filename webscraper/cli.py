"""CLI: python -m webscraper.cli <url> <query> [--threshold N] [--timeout S]"""
from __future__ import annotations

import argparse
import json
import sys

from .scraper import ScrapeError, scrape_and_search


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webscraper",
        description="Scrape a webpage and fuzzy-search its content blocks.",
    )
    parser.add_argument("url", help="Target webpage URL")
    parser.add_argument("query", help="Search keyword or phrase")
    parser.add_argument(
        "--threshold", type=int, default=60,
        help="Minimum fuzzy match score, 0-100 (default: 60)",
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0,
        help="Request timeout in seconds (default: 10)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not 0 <= args.threshold <= 100:
        print("error: --threshold must be between 0 and 100", file=sys.stderr)
        return 2

    try:
        payload = scrape_and_search(args.url, args.query, threshold=args.threshold, timeout=args.timeout)
    except ScrapeError as exc:
        print(json.dumps({"error": str(exc), "target_url": args.url, "query": args.query}, indent=2))
        return 1

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
