"""Сохраняет HTML одной страницы в data/debug/, чтобы подобрать селекторы.

Запуск из папки проекта:
  python tools/dump_page.py https://example.com/page имя_файла
Страница скачивается тем же Fetcher, что и в основном скрипте (проверка robots.txt, пауза).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsdigest.fetcher import FetchError, Fetcher  # noqa: E402


def main(url, name="page"):
    try:
        html = Fetcher(delay=2.0, timeout=60).get(url)
    except FetchError as error:
        raise SystemExit(f"Не вышло: {error}") from error
    out = Path("data/debug")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.html").write_text(html, encoding="utf-8")
    print(f"Сохранено: {out / (name + '.html')} ({len(html)} символов)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(*sys.argv[1:3])
