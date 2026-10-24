"""Как собирать сайт: сначала ищем фид, если его нет, берём товары со страниц (карта сайта или страница списка)."""
import gzip
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit, parse_qs

from . import feeds
from .pages import soup_of, PRODUCT_HINT, NOT_PRODUCT

# типичные адреса фидов разных платформ
FEED_PATHS = [
    '/yml.xml', '/market.xml', '/yandex.xml', '/yandex_market.xml', '/yandexmarket.xml', '/yandex-market.xml', '/ym.xml',
    '/feed.xml', '/feed.yml', '/products.xml', '/export.xml', '/catalog.xml', '/price.xml', '/goods.xml', '/offers.xml',
    '/export/yml.xml', '/upload/yml.xml', '/upload/yandex.xml', '/upload/market.xml', '/upload/catalog.xml',
    '/bitrix/catalog_export/yandex.php', '/bitrix/catalog_export/yml.php', '/bitrix/catalog_export/export_yandex.xml',
    '/index.php?route=extension/feed/yandex_market', '/index.php?route=feed/yandex_market', '/index.php?route=extension/feed/yandex_yml',
    '/index.php?route=extension/feed/google_base', '/yandexmarket/', '/shop/yandexmarket/', '/marketplace/yml/',
    '/assets/yml.xml', '/assets/export/yml.xml', '/core/export/yml.xml', '/google.xml', '/google_merchant.xml', '/merchant.xml',
    '/feeds/google.xml', '/feed/google/', '/products.json', '/wp-json/wc/store/v1/products?per_page=100',
]
SEARCH_PARAMS = ('q', 'query', 'search', 's', 'text', 'keyword', 'searchstring', 'filter_name')


def site_root(url):
    p = urlsplit(url)
    return f'{p.scheme}://{p.netloc}'


def keyword_of(url):
    """Слово для отбора товаров, если дан адрес поиска или страницы бренда: ?q=FIMET → FIMET."""
    p = urlsplit(url)
    qs = parse_qs(p.query)
    for k in SEARCH_PARAMS:
        if qs.get(k) and qs[k][0].strip():
            return qs[k][0].strip()
    return ''


def is_root(url):
    """Главная сайта, в том числе языковая: /, /en/, /ru/, /it/."""
    p = urlsplit(url)
    return (p.path in ('', '/') or bool(re.fullmatch(r'/[a-z]{2}(-[a-z]{2})?/?', p.path))) and not p.query


def find_feed(fx, url, log):
    """Адрес и тип фида или (None, None). fx — parser.http.Fetcher."""
    head = fx.get(url, max_bytes=65536, quiet=True)
    kind = feeds.detect(head)
    if kind:
        log(f'Адрес сам является фидом ({kind})')
        return url, kind
    root = site_root(url)
    cands = []
    home = fx.get(root + '/', quiet=True)
    if home:
        soup = soup_of(home)
        for l in soup.find_all('link', href=True):
            t = (l.get('type') or '').lower()
            if 'xml' in t or 'rss' in t or 'json' in t:
                cands.append(urljoin(root, l['href']))
        for a in soup.find_all('a', href=True):
            if re.search(r'(?i)(yml|feed|market|price)[^/]*\.(xml|yml)$', a['href']):
                cands.append(urljoin(root, a['href']))
    robots = fx.get(root + '/robots.txt', quiet=True) or ''
    for line in robots.splitlines():
        m = re.search(r'(https?://\S+)', line)
        if m and re.search(r'(?i)yml|feed|market|merchant|price', m.group(1)) and 'sitemap' not in m.group(1).lower():
            cands.append(m.group(1))
    cands += [root + p for p in FEED_PATHS]
    uniq = list(dict.fromkeys(cands))
    log(f'Ищу фид: {len(uniq)} возможных адресов')

    def probe(c):
        head = fx.get(c, max_bytes=65536, quiet=True, retries=0, delay=0, timeout=20)
        return feeds.detect(head)
    found = {}
    with ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(probe, c): i for i, c in enumerate(uniq)}
        for f in as_completed(futs):
            try:
                k = f.result()
            except Exception:
                k = None
            if k:
                found[futs[f]] = k
    if found:
        i = min(found)
        log(f'Найден фид ({found[i]}): {uniq[i]}')
        return uniq[i], found[i]
    log('Фид не найден, собираю со страниц сайта')
    return None, None


def sitemap_urls(fx, root, log, cap=60000):
    """Все адреса из карт сайта (с вложенными картами). Карты с товарами идут первыми."""
    robots = fx.get(root + '/robots.txt', quiet=True) or ''
    queue = re.findall(r'(?im)^\s*sitemap:\s*(\S+)', robots) or [root + '/sitemap.xml', root + '/sitemap_index.xml']
    seen, urls = set(), []
    while queue and len(urls) < cap and len(seen) < 60:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        raw = fx.get(sm, binary=True, quiet=True)
        if not raw:
            continue
        if raw[:2] == b'\x1f\x8b':
            try:
                raw = gzip.decompress(raw)
            except OSError:
                continue
        text = raw.decode('utf-8', 'replace')
        locs = re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', text)
        if '<sitemapindex' in text:
            kids = sorted(locs, key=lambda u: 0 if re.search(r'(?i)product|tovar|goods|catalog|shop|iblock|item', u) else 1)
            queue = kids + queue
        else:
            urls += [u.replace('&amp;', '&') for u in locs]
    log(f'Карта сайта: {len(urls)} адресов')
    return urls


def _template(u):
    """Группа адреса: путь без последнего сегмента (/en/catalogo/ref-1784/ → /en/catalogo/*)."""
    segs = [x for x in urlsplit(u).path.split('/') if x]
    return '/'.join(segs[:-1]) + '/*' if segs else '/'


def rank_candidates(urls, keyword=''):
    """Адреса, похожие на карточки товаров, от самых похожих. Самая многочисленная группа адресов карты сайта
    обычно и есть товары, поэтому её адреса идут выше."""
    import math
    kw = keyword.lower()
    groups = {}
    for u in urls:
        groups[_template(u)] = groups.get(_template(u), 0) + 1
    out = []
    for u in urls:
        if NOT_PRODUCT.search(u):
            continue
        path = urlsplit(u).path
        depth = len([x for x in path.split('/') if x])
        size = groups.get(_template(u), 1)
        s = (3 if PRODUCT_HINT.search(u) else 0) + min(depth, 4) * 0.3 + (5 if kw and kw in u.lower() else 0) \
            + (min(4, math.log10(size) * 1.6) if size >= 5 else 0)
        out.append((s, u))
    out.sort(key=lambda x: -x[0])
    return [u for _, u in out]
