#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Krisha.kz watcher — ищет дома на продажу под конкретные критерии
(район выше Абая/Достык + Бесагаш не дальше ЖК Hayat Apartments,
5-6 комнат, 100-140 млн тг, свежий ремонт, 1-2 этажа, от 170 м²,
отопление центральное или газовое, канализация центральная, фото
есть) и пишет data/listings.json.

Запускается вручную (`python scraper.py`) или по расписанию через
GitHub Actions (.github/workflows/daily-scan.yml).

Дизайн: сайт не даёт официального API и часть нужных критериев
(водоснабжение, отопление, канализация, состояние ремонта) не всегда
надёжно фильтруется через query-параметры поиска, поэтому скрипт:
  1) сначала узнаёт кандидатов дёшево — по тексту карточек в списке
     (комнаты, цена, район/мкр видны прямо в списке);
  2) и только для кандидатов, прошедших грубый фильтр, открывает
     страницу объявления и проверяет точные характеристики.
Это делает скрипт устойчивым, даже если какой-то query-параметр
в фильтрах krisha.kz окажется не тем, что мы предполагаем.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"
LISTINGS_PATH = DATA_DIR / "listings.json"
SEEN_PATH = DATA_DIR / "seen_ids.json"

BASE = "https://krisha.kz"


def log(msg):
    print(f"[krisha-watcher] {msg}", flush=True)


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_json(path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class KrishaClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": cfg.get("user_agent", "Mozilla/5.0"),
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def get(self, url, params=None):
        # Короткий таймаут и всего 2 попытки: если krisha.kz блокирует
        # соединение (а не отвечает ошибкой), долгие повторные попытки
        # только впустую тратят время прогона.
        for attempt in range(2):
            try:
                resp = self.session.get(url, params=params, timeout=10)
                if resp.status_code == 200:
                    return resp.text
                log(f"  HTTP {resp.status_code} for {url} (попытка {attempt + 1})")
            except requests.RequestException as e:
                log(f"  Ошибка запроса: {e} (попытка {attempt + 1})")
            time.sleep(2 * (attempt + 1))
        return None


def list_url(district_slug):
    return f"{BASE}/prodazha/doma-dachi/{district_slug}/"


def build_search_params(cfg, page):
    # Лучшие догадки по query-параметрам krisha.kz. Даже если какой-то
    # из них не сработает (сайт молча его проигнорирует), карточки всё
    # равно перепроверяются по тексту ниже — так что это только
    # оптимизация, а не единственный источник фильтрации.
    params = {}
    params["das[house.type_object]"] = 1  # Отдельный дом
    for i, room in enumerate(cfg["rooms_allowed"]):
        params[f"das[live.rooms][{i}]"] = room
    params["das[price][from]"] = cfg["price_from"]
    params["das[price][to]"] = cfg["price_to"]
    params["das[_sys.hasphoto]"] = 1
    if page > 1:
        params["page"] = page
    return params


CARD_ID_RE = re.compile(r'^/a/show/(\d+)')
PRICE_RE = re.compile(r'([\d\s\u00a0]{5,})\s*₸')
ROOMS_RE = re.compile(r'(\d+)\s*комнат')
AREA_RE = re.compile(r'(\d+[.,]?\d*)\s*м²')
PLOT_RE = re.compile(r'(\d+[.,]?\d*)\s*сот')
FLOORS_SUMMARY_RE = re.compile(r'(\d+)\s*этаж(?:а|ей)?\s*,')
DISTRICT_LINE_RE = re.compile(
    r'(Медеуский|Бостандыкский|Алатауский|Алмалинский|Ауэзовский|Жетысуский|Наурызбайский|Турксибский)'
    r'\s*р-н[^\d]{0,90}?(?=\s\d|\s*$)'
)


def _find_card_container(link_tag):
    """Поднимаемся от ссылки /a/show/ID вверх по DOM, пока не найдём
    контейнер, который содержит ровно одну такую ссылку (=> это карточка
    одного объявления, а не общий блок списка)."""
    node = link_tag
    for _ in range(8):
        if node.parent is None:
            break
        node = node.parent
        own_links = {a.get('href', '') for a in node.find_all('a', href=True)
                     if CARD_ID_RE.match(a.get('href', '').split('?')[0].replace(BASE, ''))}
        if len(own_links) == 1 and len(node.get_text(strip=True)) > 60:
            candidate = node
            # продолжаем подниматься, пока условие ещё выполняется, чтобы
            # захватить более полный блок карточки (с ценой и адресом)
            parent = node.parent
            steps = 0
            while parent is not None and steps < 4:
                p_links = {a.get('href', '') for a in parent.find_all('a', href=True)
                           if CARD_ID_RE.match(a.get('href', '').split('?')[0].replace(BASE, ''))}
                if len(p_links) == 1:
                    candidate = parent
                    parent = parent.parent
                    steps += 1
                else:
                    break
            return candidate
    return link_tag.parent


def parse_list_cards(html_text):
    """Грубый парсинг списка объявлений: id, цена, комнаты, площадь, район.

    Опирается на структуру DOM (через BeautifulSoup), а не на точные CSS-
    классы krisha.kz, которые периодически меняются при редизайне сайта —
    так парсинг устойчивее к вёрстке, но чувствителен к самим фактам
    (наличие "N комнат", "N ₸" и т.п. в тексте карточки).
    """
    if not html_text:
        return []
    soup = BeautifulSoup(html_text, "html.parser")
    ids_seen = set()
    cards = []

    for a in soup.find_all('a', href=True):
        href = a['href']
        path = href.replace(BASE, '')
        m = CARD_ID_RE.match(path.split('?')[0])
        if not m:
            continue
        ad_id = m.group(1)
        if ad_id in ids_seen:
            continue
        ids_seen.add(ad_id)

        container = _find_card_container(a)
        text = re.sub(r'\s+', ' ', container.get_text(' ', strip=True))

        rooms_m = ROOMS_RE.search(text)
        price_m = PRICE_RE.search(text)
        if not rooms_m or not price_m:
            continue
        area_m = AREA_RE.search(text)
        plot_m = PLOT_RE.search(text)
        floors_m = FLOORS_SUMMARY_RE.search(text)
        district_m = DISTRICT_LINE_RE.search(text)

        price = int(re.sub(r'[\s\u00a0]', '', price_m.group(1)))
        cards.append({
            "id": ad_id,
            "url": f"{BASE}/a/show/{ad_id}",
            "rooms": int(rooms_m.group(1)),
            "price": price,
            "area_m2": float(area_m.group(1).replace(',', '.')) if area_m else None,
            "plot_sotka": float(plot_m.group(1).replace(',', '.')) if plot_m else None,
            "floors_summary": int(floors_m.group(1)) if floors_m else None,
            "district_line": district_m.group(0).strip() if district_m else "",
        })
    return cards


def prefilter_candidates(cards, cfg):
    out = []
    for c in cards:
        if c["rooms"] not in cfg["rooms_allowed"]:
            continue
        if not (cfg["price_from"] <= c["price"] <= cfg["price_to"]):
            continue
        out.append(c)
    return out


def mkr_matches(text_lower, allowlist):
    return any(mkr in text_lower for mkr in allowlist)


LAT_LON_PATTERNS = [
    re.compile(r'"lat(?:itude)?"\s*:\s*"?(-?\d{1,3}\.\d+)"?[^}]{0,80}?"lon(?:gitude)?"\s*:\s*"?(-?\d{1,3}\.\d+)"?', re.IGNORECASE),
    re.compile(r'data-lat="(-?\d{1,3}\.\d+)"\s+data-lon="(-?\d{1,3}\.\d+)"', re.IGNORECASE),
    re.compile(r'center=(-?\d{1,3}\.\d+)%2C(-?\d{1,3}\.\d+)'),
]


def extract_lat_lon(detail_html):
    for pat in LAT_LON_PATTERNS:
        m = pat.search(detail_html)
        if m:
            try:
                a, b = float(m.group(1)), float(m.group(2))
                # определяем, где широта (лежит в 40-50 для Алматы), а где долгота (~76-77)
                if 40 <= a <= 50 and 70 <= b <= 82:
                    return a, b
                if 40 <= b <= 50 and 70 <= a <= 82:
                    return b, a
            except ValueError:
                continue
    return None, None


PHOTO_URL_RE = re.compile(r'https://krisha-photos\.kcdn\.online/webp/[^\s"\'\\)]+?-\d+x\d+\.(?:jpg|webp)')


def has_photos(detail_html):
    # На странице объявления фотографии лежат в galery/slider блоке с
    # доменом krisha-photos.kcdn.online — если такие url есть, фото есть.
    return bool(PHOTO_URL_RE.search(detail_html))


def extract_photo_url(detail_html):
    m = PHOTO_URL_RE.search(detail_html)
    if not m:
        return None
    # берём самую крупную доступную версию, меняя размер в конце пути
    url = m.group(0)
    return re.sub(r'-\d+x\d+\.', '-800x600.', url)


def check_keyword(detail_text_lower, phrases):
    return any(p in detail_text_lower for p in phrases)


def check_proximity(text_lower, label_words, value_word, window=25):
    """Ищет 'label ... value' в пределах window символов — устойчиво к тому,
    рендерится ли пара как 'Отопление: центральное' или 'Отопление центральное'
    (двоеточие часто теряется при извлечении текста из <dt>/<dd>)."""
    for label in label_words:
        for m in re.finditer(re.escape(label), text_lower):
            snippet = text_lower[m.end():m.end() + window]
            if value_word in snippet:
                return True
    return False


def analyze_detail(detail_html, cfg):
    """Возвращает dict с проверками точных критериев по странице объявления."""
    soup = BeautifulSoup(detail_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(' ', strip=True)
    text_lower = re.sub(r'\s+', ' ', text).lower()

    floors_m = re.search(r'этажность[^\d]{0,10}(\d+)', text_lower)
    if not floors_m:
        floors_m = FLOORS_SUMMARY_RE.search(text_lower)
    floors = int(floors_m.group(1)) if floors_m else None

    fresh_renovation = check_keyword(text_lower, ["свежий ремонт"])
    central_heating = (
        check_keyword(text_lower, ["центральное отопление"])
        or check_proximity(text_lower, ["отопление"], "централь")
    )
    gas_heating = (
        check_keyword(text_lower, ["отопление: на газе", "отопление на газе", "газовое отопление"])
        or check_proximity(text_lower, ["отопление"], "газ")
    )
    heating_ok = central_heating or gas_heating
    central_sewerage = (
        check_keyword(text_lower, ["центральная канализация", "центральное канализация"])
        or check_proximity(text_lower, ["канализация"], "централь")
    )
    central_water = (
        check_keyword(text_lower, ["центральное водоснабжение"])
        or check_proximity(text_lower, ["водоснабжение", "питьевая вода"], "централь")
    )
    photos_ok = has_photos(detail_html)
    photo_url = extract_photo_url(detail_html)
    lat, lon = extract_lat_lon(detail_html)

    return {
        "floors": floors,
        "fresh_renovation": fresh_renovation,
        "central_heating": central_heating,
        "gas_heating": gas_heating,
        "heating_ok": heating_ok,
        "central_sewerage": central_sewerage,
        "central_water": central_water,
        "has_photos": photos_ok,
        "photo_url": photo_url,
        "lat": lat,
        "lon": lon,
        "full_text_lower": text_lower,
    }


def geo_ok(region, mkr_hit, lat, lon):
    """Проверка гео-критерия — правило зависит от региона:
    - район Медеу: попадание в список микрорайонов ИЛИ широта южнее
      (= выше в горы) линии Абая/Достык;
    - Бесагаш: долгота не дальше опорной точки (ЖК Hayat Apartments) —
      то есть не глубже в посёлок, чем этот комплекс.
    Если нужных координат нет — по умолчанию считаем, что подходит
    (единственный сигнал в этом случае — сам район/мкр), чтобы не
    терять объявления только из-за того, что не удалось вытащить
    координаты со страницы."""
    if "mkr_allowlist" in region:
        boundary = region["lat_max"]
        mode = region.get("geo_filter_mode", "either")
        coord_hit = (lat is not None and lat <= boundary)
        if mode == "both":
            if lat is None:
                return mkr_hit
            return mkr_hit and coord_hit
        return mkr_hit or coord_hit
    if "lon_max" in region:
        if lon is None:
            return True
        return lon <= region["lon_max"]
    return True


def scan_district(client, cfg, district_slug):
    candidates = {}
    max_pages = cfg.get("max_pages_per_district", 90)
    empty_streak = 0
    for page in range(1, max_pages + 1):
        params = build_search_params(cfg, page)
        url = list_url(district_slug)
        log(f"  Страница {page}: {url}?{urlencode(params)}")
        page_html = client.get(url, params=params)
        if not page_html:
            break
        cards = parse_list_cards(page_html)
        if not cards:
            empty_streak += 1
            if empty_streak >= 2:
                log("  Пустые страницы подряд — похоже, дошли до конца списка.")
                break
            continue
        empty_streak = 0
        matched = prefilter_candidates(cards, cfg)
        for c in matched:
            candidates[c["id"]] = c
        time.sleep(cfg.get("request_delay_seconds", 1.5))
        if "Найдено 0 объявлений" in page_html or "не найдено" in page_html.lower():
            break
    return candidates


def run():
    cfg = load_config()
    client = KrishaClient(cfg)

    # all_candidates: ad_id -> (card, region)
    all_candidates = {}
    for region in cfg["regions"]:
        slug = region["district_slug"]
        log(f"Сканирую район: {slug}")
        found = scan_district(client, cfg, slug)
        log(f"  Кандидатов после грубого фильтра (комнаты/цена): {len(found)}")
        for ad_id, card in found.items():
            all_candidates[ad_id] = (card, region)

    log(f"Всего кандидатов на детальную проверку: {len(all_candidates)}")

    final_matches = []
    blocked = False
    consecutive_failures = 0
    max_consecutive_failures = 5

    for i, (ad_id, (card, region)) in enumerate(all_candidates.items(), 1):
        if blocked:
            break
        log(f"[{i}/{len(all_candidates)}] Проверяю объявление {ad_id}")
        detail_html = client.get(card["url"])
        time.sleep(cfg.get("detail_request_delay_seconds", 2.0))
        if not detail_html:
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                log(
                    f"  {consecutive_failures} подряд неудачных запросов — похоже, "
                    "krisha.kz временно блокирует соединения с этого сервера. "
                    "Останавливаю проверку деталей на этом прогоне, чтобы не тратить "
                    "время впустую. Список объявлений, кандидатов и статус запишу как есть."
                )
                blocked = True
            continue
        consecutive_failures = 0

        analysis = analyze_detail(detail_html, cfg)
        district_and_body = (card["district_line"] + " " + analysis["full_text_lower"]).lower()
        mkr_allowlist = [m.lower() for m in region.get("mkr_allowlist", [])]
        mkr_hit = mkr_matches(district_and_body, mkr_allowlist) if mkr_allowlist else False

        floors = analysis["floors"] if analysis["floors"] is not None else card["floors_summary"]
        area_ok = (
            card["area_m2"] is not None
            and card["area_m2"] >= cfg.get("min_area_m2", 0)
        )

        checks = {
            "rooms": card["rooms"] in cfg["rooms_allowed"],
            "price": cfg["price_from"] <= card["price"] <= cfg["price_to"],
            "floors": (floors is not None) and (floors in cfg["floors_allowed"]),
            "min_area": area_ok,
            "fresh_renovation": (not cfg["require_fresh_renovation"]) or analysis["fresh_renovation"],
            "heating": (not cfg["require_heating_gas_or_central"]) or analysis["heating_ok"],
            "central_sewerage": (not cfg["require_central_sewerage"]) or analysis["central_sewerage"],
            "central_water": analysis["central_water"],  # информационно, не влияет на итог
            "has_photos": (not cfg["require_photos"]) or analysis["has_photos"],
            "geo_area": geo_ok(region, mkr_hit, analysis["lat"], analysis["lon"]),
        }
        required_keys = [k for k in checks if k != "central_water"]

        if all(checks[k] for k in required_keys):
            title_area = f'{card["rooms"]}-комнатный дом'
            final_matches.append({
                "id": ad_id,
                "url": card["url"],
                "title": title_area,
                "price": card["price"],
                "rooms": card["rooms"],
                "area_m2": card["area_m2"],
                "plot_sotka": card["plot_sotka"],
                "floors": floors,
                "district_line": card["district_line"],
                "region": region.get("name", region["district_slug"]),
                "photo_url": analysis["photo_url"],
                "lat": analysis["lat"],
                "lon": analysis["lon"],
                "checks": checks,
            })
        else:
            failed = [k for k in required_keys if not checks[k]]
            log(f"    Не подходит: {', '.join(failed)}")

    log(f"Итоговых совпадений: {len(final_matches)}")
    if blocked:
        log(
            "ВНИМАНИЕ: прогон остановлен досрочно из-за повторяющихся сетевых "
            "ошибок при обращении к krisha.kz — часть кандидатов не была "
            "проверена. Возможно, сайт временно блокирует запросы с сервера "
            "GitHub Actions."
        )

    seen_ids = set(load_json(SEEN_PATH, []))
    new_ids = [m["id"] for m in final_matches if m["id"] not in seen_ids]

    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+05:00", time.localtime()),
        "criteria": {
            "rooms": cfg["rooms_allowed"],
            "price_from": cfg["price_from"],
            "price_to": cfg["price_to"],
            "floors_allowed": cfg["floors_allowed"],
            "min_area_m2": cfg.get("min_area_m2", 0),
            "districts": [r["district_slug"] for r in cfg["regions"]],
        },
        "blocked_early": blocked,
        "count": len(final_matches),
        "listings": sorted(final_matches, key=lambda m: m["price"]),
    }
    save_json(LISTINGS_PATH, output)
    save_json(SEEN_PATH, sorted(set(seen_ids) | {m["id"] for m in final_matches}))

    if new_ids:
        notify_telegram([m for m in final_matches if m["id"] in new_ids])
    else:
        log("Новых объявлений с прошлого запуска нет — уведомление не отправляется.")


def format_price(p):
    return f"{p:,}".replace(",", " ") + " ₸"


def notify_telegram(new_matches):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не заданы — пропускаю уведомление.")
        return

    lines = [f"🏡 Найдено новых домов по критериям: {len(new_matches)}\n"]
    for m in new_matches[:10]:
        area_str = f", {m['area_m2']:.0f} м²" if m.get('area_m2') else ""
        lines.append(
            f"• {m['rooms']} комн., {format_price(m['price'])}{area_str}"
            f"\n  {m['district_line'] or ''}\n  {m['url']}"
        )
    if len(new_matches) > 10:
        lines.append(f"\n… и ещё {len(new_matches) - 10}. Полный список — в приложении.")
    text = "\n".join(lines)

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        if resp.status_code != 200:
            log(f"Telegram API вернул {resp.status_code}: {resp.text}")
        else:
            log("Уведомление в Telegram отправлено.")
    except requests.RequestException as e:
        log(f"Не удалось отправить уведомление в Telegram: {e}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        log(f"ФАТАЛЬНАЯ ОШИБКА: {e}")
        raise
