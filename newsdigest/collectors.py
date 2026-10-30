"""Сбор новых материалов с сайта. Режим выбирается полем mode в настройках сайта.

(по умолчанию)    страница-список -> страницы материалов
rss_url           материалы берутся из RSS-ленты
list_reviews      отзывы лежат прямо на странице-списке
product_reviews   список объектов -> отзывы на страницах объектов
forum             список тем -> новые сообщения на последней странице темы
"""

import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from .fetcher import FetchError
from .parsers import (
    extract_article,
    extract_links,
    parse_forum_posts,
    parse_list_reviews,
    parse_reviews,
    parse_rss,
)
from .textutils import clean_text, is_fresh


def collect_rss(site, fetcher, seen_urls, limit, log, verbose):
    """Материалы из RSS: полный текст уже в ленте, ходить на страницы постов не нужно."""
    entries = parse_rss(fetcher.get(site["rss_url"]))
    pattern = re.compile(site["link_regex"]) if site.get("link_regex") else None
    entries = [e for e in entries if e["url"] and (not pattern or pattern.search(e["url"]))]
    entries = [e for e in entries if is_fresh(e["date"], site)]
    log(f"  в RSS-ленте материалов: {len(entries)}")
    if verbose:
        for e in entries[:10]:
            log(f"    - {e['title'][:70]!r} {e['url']}")
    items = []
    for e in entries:
        if e["url"] in seen_urls:
            continue
        if len(items) >= limit:
            break
        if not e["text"]:
            log(f"  пустой текст: {e['url']}")
            continue
        items.append({"site": site["key"], **e})
    return items


def collect_list_reviews(site, fetcher, seen_urls, limit, log, verbose):
    """Страница-список отзывов -> самые новые непросмотренные; по желанию полный текст отзыва."""
    html = fetcher.get(site["list_url"])
    reviews = [
        r for r in parse_list_reviews(html, site["list_url"], site["selectors"]) if is_fresh(r["date"], site)
    ]
    log(f"  отзывов на странице: {len(reviews)}")
    if verbose:
        for r in reviews[:10]:
            log(f"    - {r['date']} {r['title'][:60]!r} {r['url']}")
    items = []
    for r in reviews:
        if r["url"] in seen_urls:
            continue
        if len(items) >= limit:
            break
        if site.get("fetch_full"):
            try:
                art = extract_article(fetcher.get(r["url"]))
                if art and len(art["text"]) > len(r["text"]):
                    r["text"] = clean_text(art["text"])
            except FetchError as e:
                log(f"  полный текст недоступен, беру начало отзыва: {e}")
        items.append({"site": site["key"], **r})
    return items


def collect_forum(site, fetcher, seen_urls, limit, log, verbose):
    """Список тем форума -> последняя страница каждой темы -> новые сообщения (одна запись на тему)."""
    list_url = site["list_url"]
    soup = BeautifulSoup(fetcher.get(list_url), "html.parser")
    topics = []
    for box in soup.select(site.get("topic_selector", ".topic_title")):
        a = box.select_one('a[href*="showtopic="]')
        if a is None:
            continue
        main_url = urljoin(list_url, a["href"])
        pages = [urljoin(list_url, x["href"]) for x in box.select('a[href*="st="]')]
        topics.append(
            {
                "title": a.get_text(" ", strip=True),
                "url": main_url,
                "page_url": pages[-1] if pages else main_url,
            }
        )
    topics = topics[: site.get("max_topics", 5)]
    log(f"  тем на странице-списке: {len(topics)}")
    items = []
    for topic in topics:
        if len(items) >= limit:
            break
        try:
            html = fetcher.get(topic["page_url"])
        except FetchError as e:
            log(f"  пропуск: {e}")
            continue
        posts = parse_forum_posts(html, topic["page_url"])
        start = int(parse_qs(urlparse(topic["page_url"]).query).get("st", ["0"])[0])
        if start > 0:
            posts = posts[1:]  # на каждой странице сверху повторяется шапка темы
        new = [
            p
            for p in posts
            if p["url"] not in seen_urls and len(p["text"]) >= 20 and is_fresh(p["date"], site)
        ]
        new = new[-site.get("posts_per_topic", 10) :]
        log(f"  {topic['title'][:50]!r}: новых сообщений {len(new)}")
        if not new:
            continue
        per_post = site.get("max_chars_per_post", 1200)
        text = "\n\n".join(f"[{p['date']}, {p['author']}] {p['text'][:per_post]}" for p in new)
        items.append(
            {
                "site": site["key"],
                "url": topic["url"],
                "title": topic["title"],
                "author": ", ".join(dict.fromkeys(p["author"] for p in new if p["author"])),
                "date": new[-1]["date"],
                "text": text,
                # все сообщения страницы считаются просмотренными, даже те, что не вошли в выжимку
                "seen_keys": [p["url"] for p in posts],
            }
        )
    return items


def collect_product_reviews(site, fetcher, seen_urls, limit, log, verbose):
    """Страница-список объектов -> страницы объектов -> новые отзывы (а не сами объекты)."""
    list_html = fetcher.get(site["list_url"])
    products = extract_links(list_html, site["list_url"], site.get("scope_css"), site.get("link_regex"))
    products = products[: site.get("max_products", 5)]
    log(f"  объектов на странице-списке: {len(products)}")
    per_product = site.get("reviews_per_product", 3)
    items = []
    for product in products:
        if len(items) >= limit:
            break
        try:
            html = fetcher.get(product["url"])
        except FetchError as e:
            log(f"  пропуск: {e}")
            continue
        new = [r for r in parse_reviews(html, product["url"]) if r["url"] not in seen_urls]
        new = [r for r in new if r["text"] and is_fresh(r["date"], site)][:per_product]
        log(f"  {product['title'][:50]!r}: новых отзывов {len(new)}")
        for r in new:
            if len(items) >= limit:
                break
            if site.get("fetch_full"):
                try:
                    art = extract_article(fetcher.get(r["url"]))
                    if art and len(art["text"]) > len(r["text"]):
                        r["text"] = clean_text(art["text"])
                except FetchError as e:
                    log(f"  полный текст недоступен, беру начало отзыва: {e}")
            title = r["title"] or "отзыв"
            items.append({"site": site["key"], **r, "title": f"{product['title']}: {title}"})
    return items


def collect_site(site, fetcher, seen_urls, limit=None, log=print, verbose=False):
    """Собирает до limit новых материалов сайта. Возвращает список словарей."""
    limit = limit or site.get("max_items", 5)
    if site.get("mode") == "forum":
        return collect_forum(site, fetcher, seen_urls, limit, log, verbose)
    if site.get("mode") == "list_reviews":
        return collect_list_reviews(site, fetcher, seen_urls, limit, log, verbose)
    if site.get("mode") == "product_reviews":
        return collect_product_reviews(site, fetcher, seen_urls, limit, log, verbose)
    if site.get("rss_url"):
        return collect_rss(site, fetcher, seen_urls, limit, log, verbose)
    list_html = fetcher.get(site["list_url"])
    links = extract_links(list_html, site["list_url"], site.get("scope_css"), site.get("link_regex"))
    log(f"  найдено ссылок на материалы: {len(links)}")
    if verbose:
        for link in links[:10]:
            log(f"    - {link['title'][:70]!r} {link['url']}")
    items = []
    for link in links:
        if link["url"] in seen_urls:
            continue
        if len(items) >= limit:
            break
        try:
            html = fetcher.get(link["url"])
        except FetchError as e:
            log(f"  пропуск: {e}")
            continue
        art = extract_article(html)
        if not art or not art["text"].strip():
            log(f"  пустой текст: {link['url']}")
            continue
        items.append(
            {
                "site": site["key"],
                "url": link["url"],
                "title": art["title"] or link["title"],
                "author": art["author"],
                "date": art["date"],
                "text": clean_text(art["text"]),
            }
        )
    return items
