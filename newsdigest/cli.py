"""Командная строка.

Примеры:
  python main.py --debug --no-llm      только проверить, что находится на сайтах
  python main.py                       полный запуск
  python main.py --site 5koleso -n 3   один сайт, 3 материала
"""

import argparse

from .pipeline import run


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Ежедневная сводка по сайтам через GigaChat")
    parser.add_argument("--site", help="ключ одного сайта из sites.py (работает и для выключенных)")
    parser.add_argument("-n", "--limit", type=int, help="сколько новых материалов брать с сайта")
    parser.add_argument("--no-llm", action="store_true", help="только собрать тексты, без GigaChat")
    parser.add_argument("--debug", action="store_true", help="показать найденные ссылки")
    parser.add_argument("--delay", type=float, default=2.0, help="пауза между запросами к сайту, сек")
    parser.add_argument("--timeout", type=int, default=60, help="сколько ждать ответ сайта, сек")
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="не использовать прокси из настроек системы "
        "(если сайты открываются в браузере и curl, а в скрипте зависают)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    run(parse_args(argv))
