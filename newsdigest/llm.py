"""Обёртка над GigaChat API.

Бесплатный режим даёт один поток, поэтому запросы идут строго по очереди.
Ключ берётся из переменных окружения (файл .env), в коде его нет.
"""

import os
import time

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole


class GigaChatClient:
    def __init__(self):
        credentials = os.environ.get("GIGACHAT_CREDENTIALS")
        if not credentials:
            raise RuntimeError("Не задан GIGACHAT_CREDENTIALS. Скопируй .env.example в .env и впиши ключ.")
        verify = os.environ.get("GIGACHAT_VERIFY_SSL", "true").lower() != "false"
        kwargs = {
            "credentials": credentials,
            "scope": os.environ.get("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            "verify_ssl_certs": verify,
            "timeout": 120,
        }
        ca = os.environ.get("GIGACHAT_CA_BUNDLE")
        if ca:
            kwargs["ca_bundle_file"] = ca
        self._client = GigaChat(**kwargs)
        self.model_fast = os.environ.get("GIGACHAT_MODEL_FAST", "GigaChat-2")
        self.model_strong = os.environ.get("GIGACHAT_MODEL_STRONG", "GigaChat-2-Pro")

    def ask(self, system, user, strong=False, retries=2):
        chat = Chat(
            model=self.model_strong if strong else self.model_fast,
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=system),
                Messages(role=MessagesRole.USER, content=user),
            ],
            temperature=0.2,
            max_tokens=700,
        )
        last_error = None
        for attempt in range(retries + 1):
            try:
                response = self._client.chat(chat)
                return response.choices[0].message.content.strip()
            except Exception as e:  # сетевые сбои и лимиты: повторяем с паузой
                last_error = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"GigaChat не ответил: {last_error}")
