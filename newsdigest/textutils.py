"""Мелкие функции для текста, адресов и дат."""

import datetime
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def is_fresh(date_iso, site, today=None):
    """False, если у сайта задан max_age_days и материал старше. Без даты материал считается свежим."""
    days = site.get("max_age_days")
    if not days or not date_iso:
        return True
    try:
        published = datetime.date.fromisoformat(date_iso[:10])
    except ValueError:
        return True
    return (today or datetime.date.today()) - published <= datetime.timedelta(days=days)


def clean_text(text):
    """Убирает лишние пробелы и пустые строки (на Отзовике текст приходит с отступами)."""
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def strip_tracking(url):
    """Убирает из адреса метки отслеживания (utm_*), остальные параметры оставляет."""
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qs(parts.query).items() if not k.startswith("utm_")]
    return urlunparse(parts._replace(query=urlencode(query, doseq=True)))
