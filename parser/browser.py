"""Браузер без окна для сайтов, которые достраивают страницу скриптом (фото и цены появляются только в браузере).
Включается сам, когда обычной загрузкой фото не нашлись. Нужен пакет playwright и его Chromium (ставятся при первом запуске)."""
import hashlib
import os
import time

from .http import CACHE_DIR


def available():
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


class Renderer:
    """Один браузер на прогон. Создаётся и закрывается в том же потоке, где идёт сбор."""

    def __init__(self, log=None, cache_ttl=6 * 3600):
        self.log = log or (lambda m: None)
        self.cache_ttl = cache_ttl
        self._pw = self._browser = self._page = None

    def _start(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        ctx = self._browser.new_context(viewport={'width': 1366, 'height': 900}, locale='ru-RU',
                                        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                                                   '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
        self._page = ctx.new_page()
        self.log('Открываю страницы в браузере: сайт достраивает их скриптом')

    def get(self, url, wait=2.5):
        cp = os.path.join(CACHE_DIR, 'r-' + hashlib.sha1(url.encode()).hexdigest()[:20] + '.txt')
        if os.path.exists(cp) and time.time() - os.path.getmtime(cp) < self.cache_ttl:
            with open(cp, encoding='utf-8') as f:
                return f.read()
        try:
            if not self._page:
                self._start()
            self._page.goto(url, wait_until='domcontentloaded', timeout=60000)
            try:
                self._page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass
            # прокрутка: отложенные картинки подгружаются при появлении на экране
            for _ in range(4):
                self._page.mouse.wheel(0, 1400)
                time.sleep(0.4)
            time.sleep(wait)
            html = self._page.content()
        except Exception as e:
            self.log(f'  браузер не открыл {url}: {type(e).__name__}')
            return None
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cp, 'w', encoding='utf-8') as f:
            f.write(html)
        return html

    def close(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = self._browser = self._page = None
