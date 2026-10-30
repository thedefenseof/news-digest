"""Разбор HTML и RSS: из сырого текста страницы получаем список материалов.

Функции здесь ничего не скачивают, поэтому их легко проверять на сохранённых страницах.
"""

import contextlib
import datetime
import json
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urljoin, urlparse

import trafilatura
from bs4 import BeautifulSoup
from lxml import etree

from .fetcher import FetchError
from .textutils import clean_text, strip_tracking


def extract_links(html, base_url, scope_css=None, link_regex=None):
    """Ссылки на материалы со страницы-списка: [{'url', 'title'}] в порядке на странице."""
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select(scope_css) if scope_css else soup.find_all("a")
    pattern = re.compile(link_regex) if link_regex else None
    found = {}
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
        url = urljoin(base_url, href)
        if pattern and not pattern.search(url):
            continue
        title = a.get_text(" ", strip=True)
        if url not in found or not found[url] and title:
            found[url] = title
    return [{"url": u, "title": t} for u, t in found.items()]


def extract_article(html):
    """Основной текст и метаданные страницы через trafilatura."""
    raw = trafilatura.extract(
        html,
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=False,
    )
    if not raw:
        return None
    data = json.loads(raw)
    return {
        "title": data.get("title") or "",
        "author": data.get("author") or "",
        "date": data.get("date") or "",
        "text": data.get("text") or "",
    }


def _text(node, selector):
    """Текст первого элемента по селектору (пустая строка, если элемента нет)."""
    element = node.select_one(selector) if selector else None
    return element.get_text(" ", strip=True) if element else ""


def _rss_field(item, name):
    """Текст дочернего тега RSS-элемента без учёта пространства имён (dc:creator -> creator)."""
    for child in item:
        if isinstance(child.tag, str) and child.tag.split("}")[-1] == name and child.text:
            return child.text.strip()
    return ""


def parse_rss(xml_text):
    """RSS-лента -> [{'url', 'title', 'author', 'date', 'text'}] в порядке ленты."""
    data = xml_text.lstrip("\ufeff").encode("utf-8")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        # Лента с мелкими ошибками разметки (например, неэкранированный «&»): lxml умеет «чинить».
        root = etree.fromstring(data, etree.XMLParser(recover=True, resolve_entities=False))
        if root is None:
            raise FetchError(f"RSS-лента не разобралась: {error}") from error
    items = []
    for node in root.iter("item"):
        date = _rss_field(node, "pubDate")
        with contextlib.suppress(TypeError, ValueError):
            date = parsedate_to_datetime(date).date().isoformat() if date else ""
        body = BeautifulSoup(_rss_field(node, "description"), "html.parser").get_text("\n")
        items.append(
            {
                "url": strip_tracking(_rss_field(node, "link")),
                "title": _rss_field(node, "title"),
                "author": _rss_field(node, "creator") or _rss_field(node, "author"),
                "date": date,
                "text": clean_text(body),
            }
        )
    return items


def parse_reviews(html, base_url):
    """Отзывы со страницы продукта (разметка schema.org: div[itemprop=review]).

    Возвращает [{'url', 'title', 'author', 'date', 'rating', 'text'}] в порядке на странице.
    Текст на странице продукта — начало отзыва (обрезано «...») плюс «Достоинства/Недостатки».
    """
    soup = BeautifulSoup(html, "html.parser")
    reviews = []
    for node in soup.select('[itemprop="review"]'):
        link = node.select_one('link[itemprop="url"]')
        if link is None or not link.get("href"):
            continue
        date = node.select_one('[itemprop="datePublished"]')
        rating = node.select_one('[itemprop="ratingValue"]')
        parts = [
            _text(node, '[itemprop="description"]'),
            _text(node, ".review-plus"),
            _text(node, ".review-minus"),
        ]
        reviews.append(
            {
                "url": urljoin(base_url, link["href"]),
                "title": _text(node, ".review-title"),
                "author": _text(node, '[itemprop="author"] [itemprop="name"]'),
                "date": date.get("content", "")[:10] if date else "",
                "rating": rating.get("content", "") if rating else "",
                "text": clean_text("\n".join(part for part in parts if part)),
            }
        )
    return reviews


def parse_list_reviews(html, base_url, cfg):
    """Отзывы прямо со страницы-списка (IRecommend): у каждого свои дата, автор, оценка.

    cfg: селекторы из sites.py (item, date, date_format, author, rating_on, title, snippet).
    Возвращает отзывы, новые сверху (сортировка по дате: сайт по умолчанию сортирует иначе).
    """
    soup = BeautifulSoup(html, "html.parser")
    base_path = urlparse(base_url).path
    reviews = []
    for node in soup.select(cfg["item"]):
        href = ""
        for a in node.select(cfg["link"]):
            path = urlparse(urljoin(base_url, a.get("href", ""))).path
            if path and path != base_path:
                href = urljoin(base_url, a["href"]).split("?")[0]
                break
        if not href:
            continue
        date = _text(node, cfg["date"])
        try:
            date = datetime.datetime.strptime(date, cfg["date_format"]).date().isoformat()
        except ValueError:
            date = ""
        stars = len(node.select(cfg["rating_on"])) if cfg.get("rating_on") else 0
        reviews.append(
            {
                "url": href,
                "title": _text(node, cfg["title"]),
                "author": _text(node, cfg["author"]),
                "date": date,
                "rating": str(stars) if stars else "",
                "text": clean_text(_text(node, cfg["snippet"])),
            }
        )
    reviews.sort(key=lambda r: r["date"], reverse=True)
    return reviews


def _forum_date(raw, today=None):
    """«22.06.19, 07:53» / «Сегодня, 16:15» / «Вчера, 21:00» -> 'ГГГГ-ММ-ДД' (или '')."""
    today = today or datetime.date.today()
    head = raw.split(",")[0].strip().lower()
    if head == "сегодня":
        return today.isoformat()
    if head == "вчера":
        return (today - datetime.timedelta(days=1)).isoformat()
    try:
        return datetime.datetime.strptime(head, "%d.%m.%y").date().isoformat()
    except ValueError:
        return ""


def parse_forum_posts(html, topic_url, today=None):
    """Сообщения со страницы темы 4PDA: [{'url','number','author','date','text'}] по порядку."""
    soup = BeautifulSoup(html, "html.parser")
    topic_id = parse_qs(urlparse(topic_url).query).get("showtopic", [""])[0]
    base = f"{urlparse(topic_url).scheme}://{urlparse(topic_url).netloc}{urlparse(topic_url).path}"
    posts = []
    for node in soup.select("div[data-post]"):
        body = node.select_one(".post_body")
        date_el = node.select_one(".post_date")
        if body is None or date_el is None:
            continue
        for quote in body.select(".post-block.quote"):
            quote.replace_with("[цитата] ")
        for junk in body.select("img, script, style"):
            junk.decompose()
        nick = node.select_one('.post_nick a[href*="showuser"]')
        author = nick.get_text(" ", strip=True).replace("ᵥ", "").strip() if nick else ""
        raw_date = date_el.get_text(" ", strip=True)
        number = re.search(r"#(\d+)", raw_date)
        posts.append(
            {
                "url": f"{base}?showtopic={topic_id}&view=findpost&p={node['data-post']}",
                "number": number.group(1) if number else "",
                "author": author,
                "date": _forum_date(raw_date.split("|")[0], today),
                "text": re.sub(
                    r"\n?Сообщение отредактировал\n.*?\n- [^\n]+$",
                    "",
                    clean_text(body.get_text("\n")),
                    flags=re.S,
                ),
            }
        )
    return posts
