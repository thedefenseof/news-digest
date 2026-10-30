"""Скачивание страниц с соблюдением правил вежливости.

Перед каждым запросом проверяется robots.txt, между запросами к одному сайту делается
пауза, повторы идут только при сбоях сети и ошибках сервера (5xx). Обхода защиты нет.
"""

import shutil
import subprocess
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = "Mozilla/5.0 (compatible; personal-news-digest/0.1)"


class FetchError(Exception):
    pass


class CurlResponse:
    """Минимальный ответ в том же виде, что у requests: status_code, text, encoding."""

    def __init__(self, status_code, body):
        self.status_code = status_code
        self.text = body.decode("utf-8", errors="replace")
        self.encoding = "utf-8"


class Fetcher:
    def __init__(self, delay=2.0, timeout=60, retries=2, session=None, trust_env=True, curl_hosts=()):
        """trust_env=False: игнорировать прокси из настроек системы и переменных окружения.

        curl_hosts: сайты, которые скачиваются через программу curl вместо requests
        (для случая, когда Python не может соединиться с сайтом, а curl может).
        Запрос тот же самый: обычный GET с тем же честным User-Agent.
        """
        self.curl_hosts = set(curl_hosts)
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self.session.trust_env = trust_env
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._robots = {}
        self._last_request = {}

    def _curl_get(self, url):
        curl = shutil.which("curl")
        if not curl:
            raise requests.ConnectionError("программа curl не найдена в системе")
        cmd = [
            curl,
            "-sS",
            "-L",
            "--max-time",
            str(self.timeout),
            "-A",
            USER_AGENT,
            "-w",
            "\n%{http_code}",
            url,
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise requests.ConnectionError(f"curl завершился с кодом {proc.returncode}: {err}")
        body, _, code = proc.stdout.rpartition(b"\n")
        return CurlResponse(int(code or 0), body)

    def _request(self, url):
        """GET с повторами при таймауте и обрыве соединения (сайт мог просто замешкаться)."""
        last_error = None
        use_curl = urlparse(url).netloc in self.curl_hosts
        for attempt in range(self.retries + 1):
            try:
                resp = self._curl_get(url) if use_curl else self.session.get(url, timeout=self.timeout)
            except (requests.Timeout, requests.ConnectionError) as e:
                last_error = e
                time.sleep(3 * (attempt + 1))
                continue
            if resp.status_code >= 500 and attempt < self.retries:
                # сбой на стороне сайта или его CDN (502, 503, 521…): чаще всего проходит через пару секунд
                time.sleep(3 * (attempt + 1))
                continue
            return resp
        if last_error is None:
            raise requests.ConnectionError("сайт не ответил")
        raise last_error

    def _robots_for(self, url):
        parts = urlparse(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host in self._robots:
            return self._robots[host]
        parser = robotparser.RobotFileParser()
        try:
            r = self._request(host + "/robots.txt")
        except requests.RequestException as error:
            raise FetchError(f"не удалось получить robots.txt ({host}): {error}") from error
        if r.status_code == 200:
            parser.parse(r.text.splitlines())
        elif r.status_code == 404:
            parser.parse([])  # robots.txt нет: ограничений нет
        else:
            raise FetchError(f"robots.txt ({host}) ответил кодом {r.status_code}, сайт пропущен")
        self._robots[host] = parser
        return parser

    def allowed(self, url):
        return self._robots_for(url).can_fetch(USER_AGENT, url)

    def get(self, url):
        """Возвращает HTML страницы. Бросает FetchError, если нельзя или не вышло."""
        if not self.allowed(url):
            raise FetchError(f"robots.txt запрещает автоматический доступ: {url}")
        host = urlparse(url).netloc
        wait = self.delay - (time.time() - self._last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        try:
            r = self._request(url)
        except requests.RequestException as error:
            raise FetchError(f"ошибка запроса {url}: {error}") from error
        finally:
            self._last_request[host] = time.time()
        if r.status_code != 200:
            raise FetchError(f"код ответа {r.status_code}: {url}")
        r.encoding = r.encoding or "utf-8"
        return r.text
