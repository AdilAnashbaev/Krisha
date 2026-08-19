"""Search criteria and constants for the krisha.kz house search."""

BASE_URL = "https://krisha.kz"

# https://krisha.kz/prodazha/doma-dachi/almaty-medeuskij/ lists houses/dachas
# for sale in Almaty's Medeu district. das[house.type_object]=1 restricts the
# results to houses (excludes dachas/summer cottages).
SEARCH_PATH = "/prodazha/doma-dachi/almaty-medeuskij/"

DEFAULT_CRITERIA = {
    "price_from": 100_000_000,
    "price_to": 140_000_000,
    "rooms_min": 5,
    "rooms_max": 6,
    "floors": 1,
    "require_photo": True,
    # Keywords (lowercase, matched as substrings) that count as "fresh renovation".
    "renovation_keywords": ["свежий ремонт", "евроремонт"],
    # Keywords that count as "central" for a given utility field.
    "central_keywords": ["централ"],
}

# Approximate coordinates of the Abay Ave / Dostyk Ave intersection (Republic
# Palace), used as the reference point for "above" (towards the mountains,
# i.e. south / lower latitude) filtering. Verify/adjust on a map if the
# results look off - this is a rough box, not an official boundary.
ABAY_DOSTYK_LAT = 43.2385
ABAY_DOSTYK_LON = 76.9565

DEFAULT_GEO_BOX = {
    # South edge: towards Medeu foothills.
    "lat_min": 43.15,
    # North edge: the Abay/Dostyk intersection itself - nothing further north.
    "lat_max": ABAY_DOSTYK_LAT,
    "lon_min": 76.90,
    "lon_max": 77.02,
}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

REQUEST_DELAY_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 15
