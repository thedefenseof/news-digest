"""Проверяет, есть ли у сайта читаемая RSS-лента и можно ли её получать автоматически.

Запуск из папки проекта:
  python tools/probe_feeds.py https://habr.com/ru/rss/news/?fl=ru https://3dnews.ru/news/rss/
Каждый адрес скачивается тем же Fetcher, что и в основном скрипте: сначала robots.txt
сайта, потом лента. Для каждой ленты печатаются число материалов, средняя длина текста
(≈200 символов значит, что в ленте только анонсы) и первые заголовки.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsdigest.fetcher import FetchError, Fetcher  # noqa: E402
from newsdigest.parsers import parse_rss  # noqa: E402


def main(urls):
    fetcher = Fetcher(delay=2.0, timeout=30, retries=1)
    for url in urls:
        print(f"== {url}")
        body = ""
        try:
            body = fetcher.get(url)
            items = parse_rss(body)
        except FetchError as error:
            print(f"   НЕЛЬЗЯ/НЕ ВЫШЛО: {error}")
            if body:
                print(f"   начало ответа: {body[:200]!r}")
            continue
        if not items:
            print("   лента пришла, но материалов не разобралось")
            continue
        average = sum(len(item["text"]) for item in items) // len(items)
        print(
            f"   OK: материалов {len(items)}, средняя длина текста {average}, последняя дата {items[0]['date']}"
        )
        for item in items[:3]:
            print(f"     - {item['title'][:70]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
