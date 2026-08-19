"""Render collected results as an HTML report and a JSON dump."""

import html
import json

CHECK_LABELS = {
    "price": "Цена 100–140 млн ₸",
    "rooms": "5–6 комнат",
    "floors": "Один этаж",
    "sewage": "Центральная канализация",
    "water": "Центральное водоснабжение",
    "heating": "Центральное отопление",
    "renovation": "Свежий ремонт",
    "has_photo": "Есть фото",
    "location": "Выше Абая/Достык",
}

STATUS_LABELS = {
    "matched": "Подходит",
    "needs_review": "Проверить вручную",
    "rejected": "Не подходит",
}


def _check_icon(ok):
    if ok is True:
        return "✅"
    if ok is False:
        return "❌"
    return "❓"


def _render_listing(listing, evaluation):
    checks_html = "".join(
        f"<li>{_check_icon(ok)} {html.escape(CHECK_LABELS[key])}"
        f"<span class='value'>{html.escape(str(value) if value else '—')}</span></li>"
        for key, (ok, value) in evaluation["checks"].items()
    )
    price_label = listing.get("price")
    price_str = f"{price_label:,} тг".replace(",", " ") if price_label else "—"
    title = html.escape(listing.get("title") or listing["url"])
    return f"""
    <article class="listing status-{evaluation['status']}">
      <h2><a href="{html.escape(listing['url'])}" target="_blank" rel="noopener">{title}</a></h2>
      <p class="price">{price_str}</p>
      <p class="status">{STATUS_LABELS[evaluation['status']]}</p>
      <ul class="checks">{checks_html}</ul>
    </article>
    """


def render_html(results, generated_at):
    matched = [r for r in results if r["evaluation"]["status"] == "matched"]
    review = [r for r in results if r["evaluation"]["status"] == "needs_review"]
    rejected = [r for r in results if r["evaluation"]["status"] == "rejected"]

    def section(title, items):
        if not items:
            return ""
        cards = "".join(
            _render_listing(item["listing"], item["evaluation"]) for item in items
        )
        return f"<section><h1>{html.escape(title)} ({len(items)})</h1>{cards}</section>"

    body = (
        section("Подходят по всем критериям", matched)
        + section("Требуют ручной проверки", review)
        + section("Не подходят", rejected)
    )

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Дома в Алматы — подбор krisha.kz</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
  h1 {{ font-size: 1.2rem; margin-top: 2rem; border-bottom: 2px solid #ddd; padding-bottom: .3rem; }}
  .listing {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin: 1rem 0; }}
  .status-matched {{ border-color: #2e8b57; }}
  .status-needs_review {{ border-color: #d9a300; }}
  .status-rejected {{ border-color: #ccc; opacity: .6; }}
  .price {{ font-weight: bold; font-size: 1.1rem; }}
  .status {{ font-size: .9rem; color: #555; }}
  ul.checks {{ list-style: none; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: .25rem; }}
  ul.checks li {{ font-size: .9rem; }}
  .value {{ color: #777; margin-left: .3rem; }}
  small.meta {{ color: #888; }}
</style>
</head>
<body>
<h1 style="border:none;">Поиск домов в Алматы (krisha.kz)</h1>
<p><small class="meta">Сформировано: {html.escape(generated_at)}. Всего просмотрено объявлений: {len(results)}.</small></p>
{body}
</body>
</html>
"""


def render_json(results):
    return json.dumps(
        [
            {
                "listing": item["listing"],
                "status": item["evaluation"]["status"],
                "checks": {
                    key: {"ok": ok, "value": value}
                    for key, (ok, value) in item["evaluation"]["checks"].items()
                },
            }
            for item in results
        ],
        ensure_ascii=False,
        indent=2,
    )
