"""Проверка потока данных без сети и без GigaChat: страницы и модель заменены заглушками.

Запуск из папки проекта: python -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsdigest import collectors, fetcher, parsers, pipeline, textutils  # noqa: E402

LIST_HTML = """
<html><body>
<h3><a href="https://example.test/101.html">Новый пост про шины</a></h3>
<h3><a href="https://example.test/102.html">Отзыв владельца</a></h3>
<ul><li><a href="https://example.test/3.html">Старый популярный пост</a></li></ul>
<a href="https://example.test/101.html?view=comments">0 comments</a>
</body></html>
"""

ARTICLE_HTML = """
<html><head><title>Пост</title>
<meta property="article:published_time" content="2026-10-29T08:00:00+03:00">
</head><body><article>
<h1>Новый пост про шины</h1>
<p>Первый абзац достаточно длинный, чтобы извлекатель посчитал его основным текстом страницы.
В нём описано, что клуб провёл испытания зимних шин и сравнил тридцать две модели.</p>
<p>Второй абзац рассказывает про торможение на льду и сухом асфальте, а также про износ шин
и влияние на расход топлива. Это тоже достаточно длинный текст для проверки.</p>
</article></body></html>
"""


class FakeFetcher:
    def __init__(self):
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        if url.endswith("/list"):
            return LIST_HTML
        return ARTICLE_HTML


class FakeLLM:
    def __init__(self):
        self.calls = []

    def ask(self, system, user, strong=False):
        self.calls.append(strong)
        return "Заглушка ответа модели"


class PipelineTest(unittest.TestCase):
    def test_extract_links_scope_and_regex(self):
        links = parsers.extract_links(
            LIST_HTML,
            "https://example.test/list",
            scope_css="h3 a",
            link_regex=r"^https://example\.test/\d+\.html$",
        )
        self.assertEqual(
            [link["url"] for link in links],
            ["https://example.test/101.html", "https://example.test/102.html"],
        )
        self.assertEqual(links[0]["title"], "Новый пост про шины")

    def test_extract_article(self):
        art = parsers.extract_article(ARTICLE_HTML)
        self.assertIsNotNone(art)
        self.assertIn("зимних шин", art["text"])

    def test_collect_skips_seen_and_respects_limit(self):
        site = {
            "key": "t",
            "name": "Тест",
            "type": "blog",
            "list_url": "https://example.test/list",
            "scope_css": "h3 a",
            "link_regex": r"^https://example\.test/\d+\.html$",
            "max_items": 5,
        }
        f = FakeFetcher()
        items = collectors.collect_site(site, f, {"https://example.test/101.html"}, log=lambda *_: None)
        self.assertEqual([i["url"] for i in items], ["https://example.test/102.html"])

    def test_full_run_writes_digest_and_updates_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pipeline.DATA_DIR = tmp / "data"
            pipeline.OUTPUT_DIR = tmp / "output"
            pipeline.SEEN_FILE = pipeline.DATA_DIR / "seen.json"
            pipeline.sites_config.SITES = [
                {
                    "key": "t",
                    "name": "Тест",
                    "type": "blog",
                    "enabled": True,
                    "list_url": "https://example.test/list",
                    "scope_css": "h3 a",
                    "link_regex": r"^https://example\.test/\d+\.html$",
                    "max_items": 5,
                }
            ]
            args = SimpleNamespace(site=None, limit=None, no_llm=False, debug=True, delay=0)
            llm = FakeLLM()
            out = pipeline.run(args, fetcher=FakeFetcher(), llm=llm, log=lambda *_: None)
            text = out.read_text(encoding="utf-8")
            self.assertIn("Заглушка ответа модели", text)
            self.assertIn("https://example.test/101.html", text)
            # 2 выжимки (быстрая модель) + 1 итоговая сводка (сильная модель)
            self.assertEqual(llm.calls, [False, False, True])
            self.assertEqual(len(pipeline.load_seen()["t"]), 2)
            # повторный запуск: новых материалов нет, модель не вызывается
            llm2 = FakeLLM()
            out2 = pipeline.run(args, fetcher=FakeFetcher(), llm=llm2, log=lambda *_: None)
            self.assertIn("Новых материалов нет", out2.read_text(encoding="utf-8"))
            self.assertEqual(llm2.calls, [])


class FakeResponse:
    def __init__(self, status_code, text="", encoding="utf-8"):
        self.status_code = status_code
        self.text = text
        self.encoding = encoding


class FlakySession:
    """Первые два запроса к каждому адресу падают по таймауту, третий проходит."""

    def __init__(self, robots_text="User-agent: *\nDisallow: /private/\n"):
        self.headers = {}
        self.attempts = {}
        self.robots_text = robots_text

    def get(self, url, timeout=None):
        self.attempts[url] = self.attempts.get(url, 0) + 1
        if self.attempts[url] <= 2:
            raise fetcher.requests.Timeout("read timed out")
        if url.endswith("/robots.txt"):
            return FakeResponse(200, self.robots_text)
        return FakeResponse(200, "<html>ok</html>")


class FetcherTest(unittest.TestCase):
    def setUp(self):
        self._sleep = fetcher.time.sleep
        fetcher.time.sleep = lambda *_: None

    def tearDown(self):
        fetcher.time.sleep = self._sleep

    def test_retries_after_timeouts(self):
        f = fetcher.Fetcher(delay=0, session=FlakySession())
        self.assertEqual(f.get("https://example.test/page"), "<html>ok</html>")

    def test_robots_disallow_is_respected(self):
        f = fetcher.Fetcher(delay=0, session=FlakySession())
        with self.assertRaises(fetcher.FetchError):
            f.get("https://example.test/private/page")

    def test_no_proxy_flag_disables_env_proxies(self):
        self.assertTrue(fetcher.Fetcher(delay=0).session.trust_env)
        self.assertFalse(fetcher.Fetcher(delay=0, trust_env=False).session.trust_env)

    def test_gives_up_after_retries(self):
        f = fetcher.Fetcher(delay=0, retries=1, session=FlakySession())
        with self.assertRaises(fetcher.FetchError):
            f.get("https://example.test/page")


RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>Блог</title>
<item><title>Пост про шины</title><link>https://example.test/201.html</link>
<pubDate>Wed, 29 Oct 2026 08:00:00 GMT</pubDate><dc:creator>avtor</dc:creator>
<description>&lt;p&gt;Первый абзац.&lt;/p&gt;&lt;p&gt;Второй абзац.&lt;/p&gt;</description></item>
<item><title>Чужая ссылка</title><link>https://other.test/1</link><description>x</description></item>
<item><title>Старый пост</title><link>https://example.test/200.html</link>
<description>Старый текст</description></item>
</channel></rss>"""


class RssTest(unittest.TestCase):
    def test_parse_rss(self):
        items = parsers.parse_rss(RSS_XML)
        self.assertEqual(items[0]["title"], "Пост про шины")
        self.assertEqual(items[0]["date"], "2026-10-29")
        self.assertEqual(items[0]["author"], "avtor")
        self.assertEqual(items[0]["text"], "Первый абзац.\nВторой абзац.")

    def test_collect_rss_filters_and_skips_seen(self):
        class F:
            def get(self, url):
                return RSS_XML

        site = {
            "key": "r",
            "rss_url": "https://example.test/rss",
            "link_regex": r"^https://example\.test/\d+\.html$",
            "max_items": 5,
        }
        items = collectors.collect_site(site, F(), {"https://example.test/200.html"}, log=lambda *_: None)
        self.assertEqual([i["url"] for i in items], ["https://example.test/201.html"])

    def test_strip_tracking(self):
        self.assertEqual(
            textutils.strip_tracking("https://h.test/n/1/?utm_source=a&utm_medium=b"), "https://h.test/n/1/"
        )
        self.assertEqual(textutils.strip_tracking("https://h.test/n?id=5&utm_x=1"), "https://h.test/n?id=5")

    def test_clean_text(self):
        self.assertEqual(textutils.clean_text("   a  b \n\n\n   c\n"), "a b\nc")

    def test_curl_hosts_use_curl(self):
        f = fetcher.Fetcher(delay=0, curl_hosts={"example.test"})
        calls = []
        f._curl_get = lambda url: calls.append(url) or fetcher.CurlResponse(200, b"ok")
        self.assertEqual(f._request("https://example.test/x").text, "ok")
        self.assertEqual(calls, ["https://example.test/x"])


PRODUCT_HTML = """<html><body>
<div class="item" itemprop="review" itemscope>
<link href="https://otzovik.com/review_1.html" itemprop="url"/>
<div itemprop="author" itemscope><span itemprop="name">HotMar</span></div>
<div class="review-postdate" content="2026-02-08T21:04:33+03:00" itemprop="datePublished"></div>
<span itemprop="reviewRating"><meta content="4" itemprop="ratingValue"/></span>
<h3><a class="review-title" href="/review_1.html" itemprop="name">Удобно</a></h3>
<div class="review-teaser" itemprop="description">Пользуюсь 15 лет.</div>
<div class="review-plus"><b>Достоинства:</b> быстро</div>
<div class="review-minus"><b>Недостатки:</b> нет</div>
</div>
<div class="item" itemprop="review" itemscope>
<link href="https://otzovik.com/review_2.html" itemprop="url"/>
<h3><a class="review-title" itemprop="name">Старый</a></h3>
<div class="review-teaser" itemprop="description">Уже видели.</div>
</div></body></html>"""


class ProductReviewsTest(unittest.TestCase):
    def test_parse_reviews(self):
        r = parsers.parse_reviews(PRODUCT_HTML, "https://otzovik.com/reviews/x/")
        self.assertEqual(r[0]["url"], "https://otzovik.com/review_1.html")
        self.assertEqual((r[0]["author"], r[0]["date"], r[0]["rating"]), ("HotMar", "2026-02-08", "4"))
        self.assertIn("Достоинства: быстро", r[0]["text"])

    def test_collect_product_reviews_skips_seen(self):
        class F:
            def get(self, url):
                return PRODUCT_HTML if "/reviews/x/" in url else '<h3><a href="/reviews/x/">Банк X</a></h3>'

        site = {
            "key": "o",
            "mode": "product_reviews",
            "list_url": "https://otzovik.com/list/",
            "scope_css": "h3 a",
            "link_regex": r"/reviews/[^/]+/$",
            "max_items": 10,
        }
        items = collectors.collect_site(site, F(), {"https://otzovik.com/review_2.html"}, log=lambda *_: None)
        self.assertEqual([i["url"] for i in items], ["https://otzovik.com/review_1.html"])
        self.assertTrue(items[0]["title"].startswith("Банк X: "))


LIST_REVIEWS_HTML = """<ul>
<li><div class="reviews-list-item"><div class="starsRating"><div class="star"><div class="on"></div></div>
<div class="star"><div class="off"></div></div></div><div class="authorName"><a>Аня</a></div>
<div class="created">03.04.2025</div><div class="reviewTitle"><a href="/content/old">Старый</a></div>
<div class="reviewTextSnippet">Начало старого</div><a href="/content/sait-x">сайт</a>
<a href="/content/old?x=1">ссылка</a></div></li>
<li><div class="reviews-list-item"><div class="created">17.09.2026</div>
<div class="reviewTitle"><a href="/content/new">Новый</a></div>
<div class="reviewTextSnippet">Начало нового</div><a href="/content/new">ссылка</a></div></li></ul>"""

LR_SELECTORS = {
    "item": "div.reviews-list-item",
    "link": 'a[href^="/content/"]',
    "date": ".created",
    "date_format": "%d.%m.%Y",
    "author": ".authorName",
    "rating_on": ".starsRating .star .on",
    "title": ".reviewTitle",
    "snippet": ".reviewTextSnippet",
}


class ListReviewsTest(unittest.TestCase):
    def test_sorted_newest_first_with_fields(self):
        r = parsers.parse_list_reviews(LIST_REVIEWS_HTML, "https://irec.test/content/sait-x", LR_SELECTORS)
        self.assertEqual(
            [x["url"] for x in r], ["https://irec.test/content/new", "https://irec.test/content/old"]
        )
        self.assertEqual((r[1]["author"], r[1]["date"], r[1]["rating"]), ("Аня", "2025-04-03", "1"))

    def test_full_text_falls_back_to_snippet_when_blocked(self):
        class F:
            def get(self, url):
                if url.endswith("/list"):
                    return LIST_REVIEWS_HTML
                raise fetcher.FetchError("robots")

        site = {
            "key": "i",
            "mode": "list_reviews",
            "list_url": "https://irec.test/list",
            "selectors": LR_SELECTORS,
            "fetch_full": True,
            "max_items": 1,
        }
        items = collectors.collect_site(site, F(), set(), log=lambda *_: None)
        self.assertEqual(items[0]["text"], "Начало нового")


FORUM_LIST = """<div class="topic_title"><a href="https://f.test/forum/index.php?showtopic=7">Тема</a>
<a href="https://f.test/forum/index.php?showtopic=7&amp;st=0">1</a>
<a href="https://f.test/forum/index.php?showtopic=7&amp;st=20">2</a></div>"""


def _post(pid, num, date, nick, text):
    return (
        f'<div data-post="{pid}"><span class="post_date">{date} | <a>#{num}</a></span>'
        f'<span class="post_nick"><a href="https://f.test/forum/index.php?showuser=1">{nick}<i>ᵥ</i></a></span>'
        f'<div class="post_body">{text}</div></div>'
    )


FORUM_TOPIC = (
    "<html><body>"
    + _post(1, 1, "22.06.19, 07:53", "Автор", "Шапка темы с описанием программы и ссылками")
    + _post(2, 21, "29.10.26, 10:00", "Аня", "Вышла версия 2.0, всё работает отлично")
    + _post(
        3,
        22,
        "Сегодня, 16:15",
        "Боря",
        '<div class="post-block quote">цитата</div>Не согласен, у меня вылетает',
    )
    + "</body></html>"
)


class ForumTest(unittest.TestCase):
    def test_parse_forum_posts(self):
        posts = parsers.parse_forum_posts(
            FORUM_TOPIC,
            "https://f.test/forum/index.php?showtopic=7&st=20",
            today=__import__("datetime").date(2026, 10, 30),
        )
        self.assertEqual(len(posts), 3)
        self.assertEqual(
            (posts[1]["author"], posts[1]["date"], posts[1]["number"]), ("Аня", "2026-10-29", "21")
        )
        self.assertEqual(posts[2]["date"], "2026-10-30")
        self.assertIn("[цитата]", posts[2]["text"])
        self.assertTrue(posts[2]["url"].endswith("showtopic=7&view=findpost&p=3"))

    def test_collect_forum_skips_header_and_seen(self):
        class F:
            def get(self, url):
                return FORUM_LIST if "showforum" in url else FORUM_TOPIC

        site = {
            "key": "f",
            "mode": "forum",
            "list_url": "https://f.test/forum/index.php?showforum=1",
            "max_items": 5,
        }
        seen = {"https://f.test/forum/index.php?showtopic=7&view=findpost&p=2"}
        items = collectors.collect_site(site, F(), seen, log=lambda *_: None)
        self.assertEqual(len(items), 1)
        self.assertIn("Не согласен", items[0]["text"])
        self.assertNotIn("Шапка темы", items[0]["text"])
        self.assertNotIn("Вышла версия", items[0]["text"])
        self.assertEqual(len(items[0]["seen_keys"]), 2)


class FreshTest(unittest.TestCase):
    def test_is_fresh(self):
        import datetime

        today = datetime.date(2026, 10, 30)
        site = {"max_age_days": 14}
        self.assertTrue(textutils.is_fresh("2026-10-20", site, today))
        self.assertFalse(textutils.is_fresh("2026-08-25", site, today))
        self.assertTrue(textutils.is_fresh("", site, today))
        self.assertTrue(textutils.is_fresh("2020-01-01", {}, today))


class ServerErrorRetryTest(unittest.TestCase):
    def setUp(self):
        self._sleep = fetcher.time.sleep
        fetcher.time.sleep = lambda *_: None

    def tearDown(self):
        fetcher.time.sleep = self._sleep

    def test_retries_on_521_then_ok(self):
        class S:
            headers = {}
            n = 0

            def get(self, url, timeout=None):
                S.n += 1
                return FakeResponse(521 if S.n <= 2 else 200, "ok")

        f = fetcher.Fetcher(delay=0, retries=2, session=S())
        self.assertEqual(f._request("https://example.test/x").status_code, 200)

    def test_returns_last_5xx_when_it_never_recovers(self):
        class S:
            headers = {}

            def get(self, url, timeout=None):
                return FakeResponse(521, "down")

        f = fetcher.Fetcher(delay=0, retries=1, session=S())
        self.assertEqual(f._request("https://example.test/x").status_code, 521)


class PromptsTest(unittest.TestCase):
    def test_news_digest_has_no_reaction_section(self):
        from newsdigest import prompts

        brief = [({"title": "Т", "date": ""}, "суть")]
        self.assertNotIn("реагируют", prompts.digest_prompt("news", "Хабр", brief))
        self.assertNotIn("реагируют", prompts.digest_prompt("reviews", "Отзовик", brief))
        self.assertIn("реагируют", prompts.digest_prompt("forum", "4PDA", brief))

    def test_shorten_keeps_head_and_tail(self):
        from newsdigest import prompts

        text = "НАЧАЛО" + "x" * 10000 + "ВЫВОД"
        short = prompts.shorten(text)
        self.assertLessEqual(len(short), prompts.MAX_CHARS_PER_ITEM + 60)
        self.assertTrue(short.startswith("НАЧАЛО") and short.endswith("ВЫВОД"))
        self.assertEqual(prompts.shorten("коротко"), "коротко")


if __name__ == "__main__":
    unittest.main()
