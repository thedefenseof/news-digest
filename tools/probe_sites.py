"""Проверяет выключенные сайты из newsdigest/sites.py: можно ли их читать автоматически.

Запуск из папки проекта:  python tools/probe_sites.py
Для каждого сайта: что говорит robots.txt, какой код ответа, сколько пришло HTML.
Страницы сохраняются в data/debug/<ключ>.html, чтобы подобрать селекторы.
Если сайт запрещает автоматический доступ или отдаёт страницу-заглушку, он остаётся
выключенным: обходить защиту проект не будет.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsdigest import sites as sites_config  # noqa: E402
from newsdigest.fetcher import FetchError, Fetcher  # noqa: E402
from newsdigest.pipeline import curl_hosts  # noqa: E402

SUSPICIOUS = ("captcha", "капча", "доступ ограничен", "enable javascript")


def main():
    fetcher = Fetcher(delay=2.0, timeout=45, retries=1, curl_hosts=curl_hosts(sites_config.SITES))
    out = Path("data/debug")
    out.mkdir(parents=True, exist_ok=True)
    for site in sites_config.SITES:
        if site["enabled"]:
            continue
        print(f"== {site['key']}: {site['list_url']}")
        try:
            html = fetcher.get(site["list_url"])
        except FetchError as error:
            print(f"   НЕЛЬЗЯ/НЕ ВЫШЛО: {error}\n")
            continue
        (out / f"{site['key']}.html").write_text(html, encoding="utf-8")
        flags = [word for word in SUSPICIOUS if word in html.lower()]
        print(f"   OK: {len(html)} символов; подозрительные слова: {flags or 'нет'}\n")


if __name__ == "__main__":
    main()
