# news-digest

Учебный проект: ежедневная краткая сводка по сайтам разных типов (блог, новости, отзывы, форум).

Скрипт собирает свежие материалы, достаёт из них текст, автора и дату, а языковая модель
[GigaChat](https://developers.sber.ru/docs/ru/gigachat/api/overview) пишет по каждому источнику
короткую сводку на русском языке. Результат сохраняется в markdown-файл.

Перед обращением к сайту читается `robots.txt`; если автоматический доступ запрещён,
сайт пропускается. Между запросами делаются паузы, защита от ботов не обходится.

## Запуск

```bash
pip install -r requirements.txt
cp .env.example .env        # впишите ключ GigaChat в GIGACHAT_CREDENTIALS
python main.py --help
```

Источники настраиваются в `newsdigest/sites.py`. Тесты: `python -m unittest discover -s tests`.
