"""Parse a single krisha.kz ad (detail) page into a plain dict."""

import re

from bs4 import BeautifulSoup

LAT_RE = re.compile(r'data-lat="(-?[\d.]+)"')
LON_RE = re.compile(r'data-lon="(-?[\d.]+)"')
PRICE_DIGITS_RE = re.compile(r"[\d\s]{5,}")


def _text(node):
    return node.get_text(" ", strip=True) if node else ""


def parse_listing(html, url):
    soup = BeautifulSoup(html, "html.parser")

    title_node = soup.select_one(".a-header-wrapper h1") or soup.select_one("h1")
    title = _text(title_node)

    price_node = soup.select_one(".price") or soup.select_one("[class*='price']")
    price_text = _text(price_node)
    price = None
    match = PRICE_DIGITS_RE.search(price_text.replace("\xa0", " "))
    if match:
        price = int(re.sub(r"\s", "", match.group()))

    characteristics = {}
    for dl in soup.select("dl[class*='parameters']"):
        terms = dl.find_all("dt")
        defs = dl.find_all("dd")
        for dt, dd in zip(terms, defs):
            label = _text(dt).rstrip(":").strip()
            value = _text(dd)
            if label:
                characteristics[label] = value

    description = ""
    desc_node = soup.select_one("[class*='a-text']") or soup.select_one(
        "[class*='description']"
    )
    if desc_node:
        description = _text(desc_node)

    photo_count = len(
        soup.select(
            "[class*='gallery'] img, [class*='photo'] img, [class*='carousel'] img"
        )
    )
    has_photo = photo_count > 0 and "нет фото" not in html.lower()

    lat_match = LAT_RE.search(html)
    lon_match = LON_RE.search(html)
    lat = float(lat_match.group(1)) if lat_match else None
    lon = float(lon_match.group(1)) if lon_match else None

    return {
        "url": url,
        "title": title,
        "price": price,
        "characteristics": characteristics,
        "description": description,
        "has_photo": has_photo,
        "photo_count": photo_count,
        "lat": lat,
        "lon": lon,
    }
