"""Диагностика: на каком этапе Python не может соединиться с сайтом.

Запуск:  python tools/tls_check.py
Скрипт ничего не скачивает со страниц: он только устанавливает защищённое соединение
и закрывает его. Результат (весь вывод) пришли в чат.
"""

import socket
import ssl
import sys
import time

HOSTS = [
    "5koleso.livejournal.com",  # проблемный сайт
    "otzovik.com",  # с ним скрипт работает (контроль)
    "www.python.org",  # посторонний сайт (контроль)
]


def connect(host, family, max_version, timeout=20):
    """Возвращает строку-результат одной попытки."""
    ctx = ssl.create_default_context()
    if max_version is not None:
        ctx.maximum_version = max_version
    started = time.time()
    try:
        infos = socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)
    except OSError as e:
        return f"не удалось определить адрес: {e}"
    fam, kind, proto, _, sockaddr = infos[0]
    sock = socket.socket(fam, kind, proto)
    sock.settimeout(timeout)
    try:
        sock.connect(sockaddr)
        tcp = time.time() - started
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            total = time.time() - started
            return f"OK: TCP {tcp:.1f} с, TLS готов за {total:.1f} с ({tls.version()}), адрес {sockaddr[0]}"
    except Exception as e:
        return f"ОШИБКА после {time.time() - started:.1f} с: {type(e).__name__}: {e} (адрес {sockaddr[0]})"
    finally:
        sock.close()


def main():
    print("Python:", sys.version.split()[0], "| OpenSSL:", ssl.OPENSSL_VERSION)
    print()
    variants = [
        ("любой адрес, TLS по умолчанию", socket.AF_UNSPEC, None),
        ("только IPv4, TLS по умолчанию", socket.AF_INET, None),
        ("только IPv4, не выше TLS 1.2", socket.AF_INET, ssl.TLSVersion.TLSv1_2),
    ]
    for host in HOSTS:
        print(f"== {host}")
        for label, family, max_version in variants:
            print(f"  {label}: {connect(host, family, max_version)}")
        print()


if __name__ == "__main__":
    main()
