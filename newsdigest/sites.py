"""Настройки источников. Новый сайт добавляется записью в SITES, код менять не нужно.

Общие поля
  key           короткое имя (для --site и для файлов в data/)
  name          название в сводке
  type          news | reviews | blog | forum | mixed (влияет на промпты)
  enabled       False = сайт пропускается при обычном запуске
  list_url      страница со списком материалов
  max_items     сколько новых материалов брать за один запуск
  max_age_days  не брать материалы старше N дней (даже если скрипт их ещё не видел)
  transport     "curl": скачивать сайт программой curl, если requests не может соединиться
  note          заметка для себя

Режим сбора (поле mode; без него: список ссылок -> страницы материалов)
  (по умолчанию)    scope_css и link_regex выбирают ссылки на материалы на странице-списке
  rss_url           материалы берутся из RSS-ленты (полный текст обычно уже в ленте)
  list_reviews      отзывы лежат на странице-списке: selectors (CSS-селекторы полей),
                    fetch_full (заходить на страницу отзыва за полным текстом)
  product_reviews   список объектов -> отзывы на их страницах: max_products,
                    reviews_per_product, fetch_full
  forum             список тем -> последняя страница темы: topic_selector, max_topics,
                    posts_per_topic
"""

SITES = [
    {
        "key": "5koleso",
        "name": "5 колесо (LiveJournal)",
        "type": "blog",
        "enabled": True,
        "list_url": "https://5koleso.livejournal.com/",
        # У части сетей Python не может установить соединение с LiveJournal, а curl может:
        # берём официальную RSS-ленту и скачиваем её через curl.
        "rss_url": "https://5koleso.livejournal.com/data/rss",
        "transport": "curl",
        "scope_css": "h3 a",
        "link_regex": r"^https://5koleso\.livejournal\.com/\d+\.html$",
        "max_age_days": 14,
        "max_items": 5,
        "note": "RSS: заголовок, дата, текст поста (до ката, если автор его поставил).",
    },
    {
        "key": "otzovik_banks",
        "name": "Otzovik: банки и финансовые продукты",
        "type": "reviews",
        "enabled": True,
        # Без параметра ?order=...: адреса с параметрами сайт может закрывать в robots.txt.
        # Эта страница по умолчанию отсортирована по дате.
        "list_url": "https://otzovik.com/money_systems/banks/",
        "scope_css": "h3 a",
        "link_regex": r"^https://otzovik\.com/reviews/[^/]+/$",
        "mode": "product_reviews",
        "max_products": 6,
        "reviews_per_product": 3,
        "max_age_days": 30,
        "max_items": 10,
        "fetch_full": True,  # на странице продукта отзывы обрезаны («...»): заходим за полным текстом
        "note": "В списке объекты (продукты). Отзывы берутся со страниц объектов: у каждого "
        "настоящие дата, автор и оценка; дедупликация по адресу отзыва.",
    },
    {
        "key": "habr_news",
        "name": "Хабр: новости",
        "type": "news",
        "enabled": True,
        "list_url": "https://habr.com/ru/rss/news/?fl=ru",
        "rss_url": "https://habr.com/ru/rss/news/?fl=ru",
        "max_age_days": 3,
        "max_items": 5,
        "note": "IT-новости. В ленте анонс около 500 символов.",
    },
    # Ниже сайты, которые пока выключены: при проверке они отказали в автоматическом
    # доступе или структура страниц неизвестна. Включай только после проверки
    # robots.txt и правил сайта, и после заполнения scope_css и link_regex.
    {
        "key": "irecommend",
        "name": "IRecommend: Ozon Travel",
        "type": "reviews",
        "enabled": True,
        "list_url": "https://irecommend.ru/content/sait-ozontravel-0",
        # Страница сама содержит список отзывов (начало текста, дата, автор, оценка).
        # Порядок на сайте не по дате, поэтому код сортирует по дате и берёт самые свежие.
        "mode": "list_reviews",
        "selectors": {
            "item": "div.reviews-list-item",
            "link": 'a[href^="/content/"]',
            "date": ".created",
            "date_format": "%d.%m.%Y",
            "author": ".authorName",
            "rating_on": ".starsRating .star .on",
            "title": ".reviewTitle",
            "snippet": ".reviewTextSnippet",
        },
        "fetch_full": True,  # заходить на страницу отзыва за полным текстом (если robots.txt позволяет)
        "max_age_days": 30,
        "max_items": 5,
        "note": "Оценка = число закрашенных звёзд.",
    },
    {
        "key": "dzen_computers",
        "name": "Дзен: новости, компьютеры",
        "type": "news",
        "enabled": False,
        "list_url": "https://dzen.ru/news/rubric/computers",
        "scope_css": None,
        "link_regex": None,
        "max_items": 5,
        "note": "Вместо новостей сервер отдаёт заглушку с переадресацией на вход. Не подходит.",
    },
    {
        "key": "4pda_security",
        "name": "4PDA: раздел «Безопасность»",
        "type": "forum",
        "enabled": True,
        "list_url": "https://4pda.to/forum/index.php?showforum=320",
        # Темы на форуме живут годами, поэтому единица сводки: тема с новыми сообщениями.
        # Берём последнюю страницу каждой из первых тем списка и новые сообщения на ней.
        "mode": "forum",
        "topic_selector": ".topic_title",
        "max_topics": 5,
        "posts_per_topic": 10,
        "max_age_days": 7,
        "max_items": 5,
        "note": "Цитаты заменяются на «[цитата]». Просмотренными считаются все сообщения страницы.",
    },
    {
        "key": "drive2_safety",
        "name": "Drive2: подборка «Безопасность»",
        "type": "mixed",
        "enabled": False,
        "list_url": "https://www.drive2.ru/featured-topics/CVQ0gEAAcHQ/",
        "scope_css": None,
        "link_regex": None,
        "max_items": 5,
        "note": "robots.txt запрещает автоматический доступ к этой странице. Не подходит.",
    },
]
