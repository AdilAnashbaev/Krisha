"""Evaluate a parsed listing against the desired house criteria.

krisha.kz's "characteristics" table uses Russian labels that vary a bit
between listings and site revisions (e.g. "Отопление" vs "Вид отопления"),
so each check looks up its field by a label *substring* rather than an
exact key, and matches the value against keyword substrings. Any field
that can't be found is reported as unknown (None) rather than treated as
a fail, so a parsing gap doesn't silently drop a real match - unknown
criteria are surfaced for manual review instead.
"""

from . import config


def _find_characteristic(characteristics, label_substrings):
    for label, value in characteristics.items():
        label_lower = label.lower()
        if any(sub in label_lower for sub in label_substrings):
            return value
    return None


def _contains_any(text, keywords):
    if text is None:
        return None
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in keywords)


def _extract_int(text):
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def evaluate(listing, criteria=None, geo_box=None):
    criteria = criteria or config.DEFAULT_CRITERIA
    characteristics = listing["characteristics"]

    rooms_value = _find_characteristic(characteristics, ["комнат"])
    rooms = _extract_int(rooms_value)
    rooms_ok = (
        None
        if rooms is None
        else criteria["rooms_min"] <= rooms <= criteria["rooms_max"]
    )

    floors_value = _find_characteristic(
        characteristics, ["этажность дома", "этажей в доме", "этажность"]
    )
    floors = _extract_int(floors_value)
    floors_ok = None if floors is None else floors == criteria["floors"]

    sewage_value = _find_characteristic(characteristics, ["канализ"])
    sewage_ok = _contains_any(sewage_value, criteria["central_keywords"])

    water_value = _find_characteristic(characteristics, ["водоснаб"])
    water_ok = _contains_any(water_value, criteria["central_keywords"])

    heating_value = _find_characteristic(characteristics, ["отоплен"])
    heating_ok = _contains_any(heating_value, criteria["central_keywords"])

    condition_value = _find_characteristic(characteristics, ["состояние"])
    renovation_in_field = _contains_any(
        condition_value, criteria["renovation_keywords"]
    )
    renovation_in_description = _contains_any(
        listing.get("description"), criteria["renovation_keywords"]
    )
    if renovation_in_field is None and renovation_in_description is None:
        renovation_ok = None
    else:
        renovation_ok = bool(renovation_in_field) or bool(renovation_in_description)

    price = listing.get("price")
    price_ok = (
        None
        if price is None
        else criteria["price_from"] <= price <= criteria["price_to"]
    )

    photo_ok = listing["has_photo"] if criteria["require_photo"] else None

    geo_ok = None
    if geo_box and listing.get("lat") is not None and listing.get("lon") is not None:
        geo_ok = (
            geo_box["lat_min"] <= listing["lat"] <= geo_box["lat_max"]
            and geo_box["lon_min"] <= listing["lon"] <= geo_box["lon_max"]
        )

    checks = {
        "price": (price_ok, price_value_label(price)),
        "rooms": (rooms_ok, rooms_value),
        "floors": (floors_ok, floors_value),
        "sewage": (sewage_ok, sewage_value),
        "water": (water_ok, water_value),
        "heating": (heating_ok, heating_value),
        "renovation": (renovation_ok, condition_value),
        "has_photo": (photo_ok, f"{listing['photo_count']} фото"),
        "location": (geo_ok, f"{listing.get('lat')}, {listing.get('lon')}"),
    }

    has_fail = any(ok is False for ok, _ in checks.values())
    has_unknown = any(ok is None for ok, _ in checks.values())

    if has_fail:
        status = "rejected"
    elif has_unknown:
        status = "needs_review"
    else:
        status = "matched"

    return {"status": status, "checks": checks}


def price_value_label(price):
    if price is None:
        return None
    return f"{price:,} тг".replace(",", " ")
