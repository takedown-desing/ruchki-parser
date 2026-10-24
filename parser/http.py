"""Загрузка страниц: один клиент на всё, вежливые паузы, повторы, кэш на диске, правильная кодировка."""
import hashlib
import os
import time
import threading
from urllib.parse import urlsplit

import requests

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, 'cache')


class Fetcher:
    """GET с паузой между запросами к одному сайту и кэшем ответов (кэш живёт в папке cache/, в git не попадает)."""

    def __init__(self, delay=1.0, timeout=30, use_cache=True, cache_ttl=6 * 3600, log=None):
        self.delay = delay
        self.timeout = timeout
        self.use_cache = use_cache
        self.cache_ttl = cache_ttl
        self.log = log or (lambda msg: None)
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': UA, 'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.7'})
        self._last = {}
        self._lock = threading.Lock()

    def _wait(self, url):
        host = urlsplit(url).netloc
        with self._lock:
            pause = self.delay - (time.time() - self._last.get(host, 0))
            if pause > 0:
                time.sleep(pause)
            self._last[host] = time.time()

    def _cache_path(self, url):
        return os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest()[:20])

    def get(self, url, binary=False, max_bytes=None, quiet=False, retries=2, delay=None, timeout=None):
        """Текст (или байты) страницы. None, если страница недоступна. max_bytes: прочитать только начало (для проверки фидов)."""
        cp = self._cache_path(url) + ('.bin' if binary else '.txt')
        if self.use_cache and not max_bytes and os.path.exists(cp) and time.time() - os.path.getmtime(cp) < self.cache_ttl:
            with open(cp, 'rb') as f:
                data = f.read()
            return data if binary else data.decode('utf-8', 'replace')
        last_err = None
        for attempt in range(retries + 1):
            if delay is None:
                self._wait(url)
            else:
                time.sleep(delay)
            try:
                r = self.session.get(url, timeout=timeout or self.timeout, stream=bool(max_bytes), allow_redirects=True)
                if r.status_code in (429, 503) and attempt < retries:
                    time.sleep(5 * (attempt + 1)); continue
                if r.status_code >= 400:
                    if not quiet:
                        self.log(f'  {r.status_code} {url}')
                    return None
                if max_bytes:
                    raw = b''
                    for chunk in r.iter_content(8192):
                        raw += chunk
                        if len(raw) >= max_bytes:
                            break
                    r.close()
                else:
                    raw = r.content
                self.last_url = r.url
                self.last_type = r.headers.get('Content-Type', '')
                if binary:
                    data = raw
                else:
                    enc = r.encoding if 'charset' in self.last_type.lower() else None
                    if not enc:
                        head = raw[:3000].decode('ascii', 'ignore').lower()
                        enc = 'windows-1251' if ('windows-1251' in head or 'cp1251' in head) else 'utf-8'
                    data = raw.decode(enc, 'replace')
                if self.use_cache and not max_bytes:
                    os.makedirs(CACHE_DIR, exist_ok=True)
                    with open(cp, 'wb') as f:
                        f.write(raw if binary else data.encode('utf-8'))
                return data
            except requests.RequestException as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
        if not quiet:
            self.log(f'  нет ответа: {url} ({type(last_err).__name__})')
        return None
