"""Build krisha.kz search URLs and collect candidate listing links."""

import re
import time
from urllib.parse import urlencode

import requests

from . import config

AD_LINK_RE = re.compile(r'href="(/a/show/\d+[^"]*)"')


def build_search_url(price_from, price_to, page=1, sort_by="price-asc"):
    params = {
        "das[house.type_object]": 1,
        "das[price][from]": price_from,
        "das[price][to]": price_to,
        "sort_by": sort_by,
    }
    if page > 1:
        params["page"] = page
    return f"{config.BASE_URL}{config.SEARCH_PATH}?{urlencode(params)}"


def fetch(url, session):
    response = session.get(
        url,
        headers=config.REQUEST_HEADERS,
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.text


def extract_ad_links(html):
    """Return a deduplicated, ordered list of /a/show/<id> ad paths found in html."""
    seen = []
    for path in AD_LINK_RE.findall(html):
        base_path = path.split("?", 1)[0]
        if base_path not in seen:
            seen.append(base_path)
    return seen


def collect_candidate_links(
    price_from,
    price_to,
    max_pages,
    session=None,
    delay=config.REQUEST_DELAY_SECONDS,
):
    """Walk search result pages and return unique candidate ad links.

    Stops early once a page yields no new links (end of results, or the
    site served an anti-bot challenge page instead of listings).
    """
    session = session or requests.Session()
    all_links = []
    for page in range(1, max_pages + 1):
        url = build_search_url(price_from, price_to, page=page)
        html = fetch(url, session)
        page_links = extract_ad_links(html)
        new_links = [link for link in page_links if link not in all_links]
        if not new_links:
            break
        all_links.extend(new_links)
        if page < max_pages:
            time.sleep(delay)
    return all_links
