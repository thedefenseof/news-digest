"""Основной сценарий: сайты -> новые материалы -> GigaChat -> markdown-файл со сводкой."""

import datetime
import json
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from . import prompts
from . import sites as sites_config
from .collectors import collect_site
from .fetcher import Fetcher, FetchError

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
SEEN_FILE = DATA_DIR / "seen.json"


def load_seen():
    """Адреса и идентификаторы уже просмотренных материалов: {ключ сайта: set(...)}."""
    if SEEN_FILE.exists():
        raw = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return {key: set(values) for key, values in raw.items()}
    return {}


def save_seen(seen):
    DATA_DIR.mkdir(exist_ok=True)
    SEEN_FILE.write_text(
        json.dumps({key: sorted(values) for key, values in seen.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def curl_hosts(sites):
    """Домены сайтов, которые нужно скачивать через curl (поле transport в настройках)."""
    return {
        urlparse(site[field]).netloc
        for site in sites
        if site.get("transport") == "curl"
        for field in ("list_url", "rss_url")
        if site.get(field)
    }


def select_sites(sites, only=None):
    """Один сайт по ключу (даже выключенный) или все включённые."""
    if only:
        return [site for site in sites if site["key"] == only]
    return [site for site in sites if site["enabled"]]


def summarize_site(site, items, llm):
    """Шаг 1: выжимка каждого материала. Шаг 2: сводка по сайту. Запросы идут по очереди."""
    briefs = []
    for item in items:
        brief = llm.ask(prompts.SYSTEM, prompts.item_prompt(site["type"], item))
        briefs.append((item, brief))
    summary = llm.ask(
        prompts.SYSTEM,
        prompts.digest_prompt(site["type"], site["name"], briefs),
        strong=True,
    )
    return summary


def render_markdown(day, results):
    lines = [f"# Ежедневная сводка за {day}", ""]
    for result in results:
        lines += [f"## {result['name']}", ""]
        if result.get("error"):
            lines.append(f"Не удалось собрать: {result['error']}")
        elif not result["items"]:
            lines.append("Новых материалов нет.")
        else:
            lines += [result.get("summary") or "(сводка не запрашивалась)", "", "Материалы:"]
            for item in result["items"]:
                date = f" ({item['date']})" if item.get("date") else ""
                lines.append(f"- [{item['title'] or item['url']}]({item['url']}){date}")
        lines.append("")
    return "\n".join(lines)


def process_site(site, fetcher, llm, seen, day, args, log):
    """Собирает и (если есть модель) суммирует один сайт. Ошибки сайта не роняют весь запуск."""
    log(f"[{site['key']}] {site['name']}")
    result = {"name": site["name"], "key": site["key"], "items": []}
    try:
        items = collect_site(
            site,
            fetcher,
            seen.get(site["key"], set()),
            limit=args.limit,
            log=log,
            verbose=args.debug,
        )
        result["items"] = items
        log(f"  новых материалов: {len(items)}")
        if items:
            day_dir = DATA_DIR / day
            day_dir.mkdir(parents=True, exist_ok=True)
            (day_dir / f"{site['key']}.json").write_text(
                json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if llm is not None:
                result["summary"] = summarize_site(site, items, llm)
                # просмотренными считаем материалы только после удачной сводки
                seen.setdefault(site["key"], set()).update(
                    key for item in items for key in item.get("seen_keys", [item["url"]])
                )
                save_seen(seen)
    except (FetchError, RuntimeError) as error:
        result["error"] = str(error)
        log(f"  ошибка: {error}")
    return result


def run(args, fetcher=None, llm=None, log=print):
    load_dotenv()
    day = datetime.date.today().isoformat()
    selected = select_sites(sites_config.SITES, args.site)
    if not selected:
        raise SystemExit("Нет сайтов для запуска: проверь newsdigest/sites.py и параметр --site.")
    fetcher = fetcher or Fetcher(
        delay=args.delay,
        timeout=args.timeout,
        trust_env=not args.no_proxy,
        curl_hosts=curl_hosts(sites_config.SITES),
    )
    if llm is None and not args.no_llm:
        from .llm import GigaChatClient

        llm = GigaChatClient()

    seen = load_seen()
    results = [process_site(site, fetcher, llm, seen, day, args, log) for site in selected]

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"digest_{day}.md"
    out_path.write_text(render_markdown(day, results), encoding="utf-8")
    log(f"Готово: {out_path}")
    return out_path
