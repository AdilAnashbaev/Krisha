#!/usr/bin/env python3
"""CLI: find houses for sale in Almaty (Medeu district) on krisha.kz
matching the desired criteria (rooms, price, renovation, utilities, ...).

Usage:
    python main.py --max-pages 5 --max-listings 60 --output-dir ./output

See README.md for details, including how to run against local fixtures
with --mock (no network access needed) to sanity-check the parser.
"""

import argparse
import datetime as dt
import os
import sys
import time

import requests

from krisha_finder import config, filters, parse_detail, report, search


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--price-from", type=int, default=config.DEFAULT_CRITERIA["price_from"])
    parser.add_argument("--price-to", type=int, default=config.DEFAULT_CRITERIA["price_to"])
    parser.add_argument("--rooms-min", type=int, default=config.DEFAULT_CRITERIA["rooms_min"])
    parser.add_argument("--rooms-max", type=int, default=config.DEFAULT_CRITERIA["rooms_max"])
    parser.add_argument("--max-pages", type=int, default=5, help="Search result pages to scan")
    parser.add_argument("--max-listings", type=int, default=60, help="Cap on ad detail pages to fetch")
    parser.add_argument("--delay", type=float, default=config.REQUEST_DELAY_SECONDS)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument(
        "--no-geo-filter",
        action="store_true",
        help="Skip the Abay/Dostyk 'higher ground' bounding-box check",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run against local HTML fixtures instead of krisha.kz (offline test)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only print the search URL and exit")
    return parser.parse_args()


def load_mock_links_and_pages():
    fixtures_dir = os.path.join(os.path.dirname(__file__), "krisha_finder", "tests", "fixtures")
    detail_path = os.path.join(fixtures_dir, "sample_detail_match.html")
    detail_path_reject = os.path.join(fixtures_dir, "sample_detail_reject.html")
    pages = {
        "/a/show/1": open(detail_path, encoding="utf-8").read(),
        "/a/show/2": open(detail_path_reject, encoding="utf-8").read(),
    }
    return list(pages.keys()), pages


def main():
    args = parse_args()
    criteria = dict(config.DEFAULT_CRITERIA)
    criteria["price_from"] = args.price_from
    criteria["price_to"] = args.price_to
    criteria["rooms_min"] = args.rooms_min
    criteria["rooms_max"] = args.rooms_max
    geo_box = None if args.no_geo_filter else config.DEFAULT_GEO_BOX

    search_url = search.build_search_url(args.price_from, args.price_to)
    print(f"Search URL: {search_url}")
    if args.dry_run:
        return

    session = requests.Session()
    mock_pages = {}
    if args.mock:
        links, mock_pages = load_mock_links_and_pages()
        print(f"[mock] using {len(links)} local fixture listing(s)")
    else:
        try:
            links = search.collect_candidate_links(
                args.price_from,
                args.price_to,
                args.max_pages,
                session=session,
                delay=args.delay,
            )
        except requests.RequestException as exc:
            print(f"Failed to reach krisha.kz: {exc}", file=sys.stderr)
            print(
                "If this environment has no internet access, open the search "
                "URL above in a browser, or run with --mock to test parsing "
                "against local fixtures.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"Found {len(links)} candidate listing(s)")

    links = links[: args.max_listings]
    results = []
    for i, link in enumerate(links, 1):
        url = f"{config.BASE_URL}{link}"
        try:
            if args.mock:
                html = mock_pages[link]
            else:
                html = search.fetch(url, session)
        except requests.RequestException as exc:
            print(f"  [{i}/{len(links)}] failed to fetch {url}: {exc}", file=sys.stderr)
            continue

        listing = parse_detail.parse_listing(html, url)
        evaluation = filters.evaluate(listing, criteria=criteria, geo_box=geo_box)
        results.append({"listing": listing, "evaluation": evaluation})
        print(f"  [{i}/{len(links)}] {evaluation['status']:<13} {listing['title'] or url}")

        if not args.mock and i < len(links):
            time.sleep(args.delay)

    os.makedirs(args.output_dir, exist_ok=True)
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    html_path = os.path.join(args.output_dir, "report.html")
    json_path = os.path.join(args.output_dir, "results.json")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(report.render_html(results, generated_at))
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(report.render_json(results))

    matched = sum(1 for r in results if r["evaluation"]["status"] == "matched")
    review = sum(1 for r in results if r["evaluation"]["status"] == "needs_review")
    print(f"\nDone. {matched} matched, {review} need manual review.")
    print(f"Report: {html_path}")


if __name__ == "__main__":
    main()
