"""Товар со страницы сайта, когда фида нет.
Порядок: разметка для поисковиков (JSON-LD Product, microdata, Open Graph), затем типичные признаки вёрстки
(заголовок H1, цена рядом с ₽, «Артикул», галерея, таблица характеристик, хлебные крошки)."""
import json
import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .item import new_item, clean_text, to_price

IMG_EXT = re.compile(r'\.(jpe?g|png|webp)(\?|$)', re.I)
SKIP_IMG = re.compile(r'(?i)logo|icon|sprite|banner|placeholder|no[-_]?photo|noimage|blank|loader|avatar|flag|payment|/colors?/|social|svg|pixel|counter|rating|star')
STOCK_YES = re.compile(r'(?i)в\s+наличии|есть\s+в\s+наличии|на\s+складе|in\s+stock|available')
STOCK_NO = re.compile(r'(?i)нет\s+в\s+наличии|под\s+заказ|ожидается|out\s+of\s+stock|sold\s+out|предзаказ')


def soup_of(html):
    return BeautifulSoup(html, 'lxml')


# ---------- JSON-LD ----------

def _ld_objects(soup):
    out = []
    for s in soup.find_all('script', type=re.compile(r'ld\+json', re.I)):
        raw = s.string or s.get_text() or ''
        raw = raw.strip().rstrip(';')
        try:
            data = json.loads(raw)
        except ValueError:
            try:
                data = json.loads(re.sub(r'[\x00-\x1f]', ' ', raw))
            except ValueError:
                continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                stack.extend(o); continue
            if not isinstance(o, dict):
                continue
            if '@graph' in o:
                stack.extend(o['@graph'] if isinstance(o['@graph'], list) else [o['@graph']])
            out.append(o)
    return out


def _types(o):
    t = o.get('@type', '')
    return [x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]


def _ld_value(v):
    if isinstance(v, dict):
        return v.get('name') or v.get('@id') or ''
    if isinstance(v, list):
        return _ld_value(v[0]) if v else ''
    return v or ''


def _ld_images(v):
    out = []
    for x in (v if isinstance(v, list) else [v]):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            out.append(x.get('contentUrl') or x.get('url') or '')
    return [x for x in out if x]


def _from_ld(soup, it):
    objs = _ld_objects(soup)
    prod = next((o for o in objs if 'product' in _types(o)), None)
    if not prod:
        group = next((o for o in objs if 'productgroup' in _types(o)), None)
        if group and group.get('hasVariant'):
            prod = dict(group); prod.update(group['hasVariant'][0] if isinstance(group['hasVariant'], list) else group['hasVariant'])
    crumbs = next((o for o in objs if 'breadcrumblist' in _types(o)), None)
    if crumbs:
        names = []
        for el in crumbs.get('itemListElement', []) or []:
            if isinstance(el, dict):
                n = el.get('name') or _ld_value(el.get('item'))
                if isinstance(el.get('item'), dict):
                    n = el['item'].get('name') or n
                if n:
                    names.append(clean_text(n))
        it['category'] = names
    if not prod:
        return False
    it['name'] = clean_text(prod.get('name', ''))
    it['sku'] = clean_text(str(prod.get('sku') or prod.get('mpn') or prod.get('productID') or ''))
    it['brand'] = clean_text(_ld_value(prod.get('brand') or prod.get('manufacturer')))
    it['description'] = clean_text(prod.get('description', ''), html=True)
    it['images'] = _ld_images(prod.get('image'))
    it['finish'] = clean_text(_ld_value(prod.get('color')))
    offers = prod.get('offers')
    offers = offers if isinstance(offers, list) else [offers] if offers else []
    for off in offers:
        if not isinstance(off, dict):
            continue
        price = off.get('price') or off.get('lowPrice')
        if price is None and isinstance(off.get('priceSpecification'), dict):
            price = off['priceSpecification'].get('price')
        if price not in (None, '') and it['price'] is None:
            it['price'] = to_price(price)
            it['currency'] = off.get('priceCurrency') or it['currency']
        av = str(off.get('availability') or '').lower()
        if av and it['in_stock'] is None:
            it['in_stock'] = not any(w in av for w in ('outofstock', 'discontinued', 'soldout'))
    for p in prod.get('additionalProperty', []) or []:
        if isinstance(p, dict) and p.get('name') and p.get('value') not in (None, ''):
            it['specs'][clean_text(p['name'])] = clean_text(str(p['value']))
    for k, label in (('material', 'Материал'), ('weight', 'Вес'), ('countryOfOrigin', 'Страна производства')):
        if prod.get(k):
            it['specs'].setdefault(label, clean_text(_ld_value(prod[k])))
    return bool(it['name'])


# ---------- microdata и Open Graph ----------

def _from_microdata(soup, it):
    scope = soup.find(attrs={'itemtype': re.compile('schema.org/Product', re.I)})
    if not scope:
        return False

    def prop(name):
        el = scope.find(attrs={'itemprop': name})
        if not el:
            return ''
        return el.get('content') or el.get('src') or el.get('href') or el.get_text(' ', strip=True)
    it['name'] = it['name'] or clean_text(prop('name'))
    it['sku'] = it['sku'] or clean_text(prop('sku') or prop('mpn'))
    it['brand'] = it['brand'] or clean_text(prop('brand'))
    it['description'] = it['description'] or clean_text(prop('description'), html=True)
    if it['price'] is None:
        it['price'] = to_price(prop('price') or prop('lowPrice'))
        cur = prop('priceCurrency')
        if cur:
            it['currency'] = cur
    if it['in_stock'] is None:
        av = prop('availability').lower()
        if av:
            it['in_stock'] = 'outofstock' not in av
    imgs = [el.get('content') or el.get('src') or el.get('href') for el in scope.find_all(attrs={'itemprop': 'image'})]
    it['images'] = it['images'] or [x for x in imgs if x]
    return bool(it['name'])


def _meta(soup, prop):
    el = soup.find('meta', attrs={'property': prop}) or soup.find('meta', attrs={'name': prop})
    return (el.get('content') or '').strip() if el else ''


# ---------- признаки вёрстки ----------

def _price_from_dom(soup):
    for el in soup.select('[class*="price"], [id*="price"], [itemprop="price"]'):
        cls = ' '.join(el.get('class', [])).lower()
        if re.search(r'old|crossed|was|prev|economy|discount', cls):
            continue
        txt = el.get('content') or el.get_text(' ', strip=True)
        if txt and re.search(r'\d', txt) and len(txt) < 60:
            p = to_price(txt)
            if p and p >= 10:
                return p
    m = re.search(r'(\d[\d\s\xa0]{1,9}(?:[.,]\d{2})?)\s*(?:₽|руб)', soup.get_text(' ', strip=True)[:20000])
    return to_price(m.group(1)) if m else None


def _sku_from_dom(soup):
    txt = soup.get_text('\n', strip=True)
    m = re.search(r'(?im)^\s*(?:артикул|арт\.|код товара|sku|код)\s*[:№#]?\s*([A-Za-zА-Яа-я0-9][\w .\-/]{1,40})$', txt)
    if not m:
        m = re.search(r'(?i)(?:артикул|арт\.|sku)\s*[:№#]\s*([A-Za-z0-9][\w.\-/]{1,30})', txt)
    return m.group(1).strip() if m else ''


TEMPLATE_IMG = re.compile(r'(?i)/(templates?|themes?|assets/(img|images|icons)|static/(img|images|icons)|local/templates|bitrix/templates|img/(icons?|ui))/')


def _images_from_dom(soup, base):
    """Фото товара: ссылки на увеличенные фото и картинки во всех блоках галереи; если галереи не нашлось, по всей странице
    без картинок оформления (логотипы, иконки, файлы шаблона)."""
    areas = soup.select('[class*="gallery"], [class*="product-image"], [class*="product__image"], [class*="photos"], [class*="photo"], '
                        '[class*="slider"], [class*="carousel"], [class*="card-sect"], [class*="product-gallery"], [class*="detail"], '
                        '[class*="images"], [class*="picture"], [itemprop="image"]')

    def collect(roots):
        found = []
        for area in roots:
            for a in area.find_all('a', href=True):
                if IMG_EXT.search(a['href']):
                    found.append(a['href'])
            for img in ([area] if area.name == 'img' else []) + area.find_all('img'):
                for attr in ('data-zoom-image', 'data-large', 'data-full', 'data-original', 'data-src', 'data-lazy', 'src'):
                    v = img.get(attr)
                    if v and IMG_EXT.search(v):
                        found.append(v); break
                if img.get('srcset'):
                    last = img['srcset'].split(',')[-1].strip().split(' ')[0]
                    if IMG_EXT.search(last):
                        found.append(last)
        return found
    found = collect(areas)
    # фото из основного содержимого: у части сайтов галерея не размечена отдельным блоком
    main = soup.find('main') or soup.find(attrs={'role': 'main'}) or soup.find(id=re.compile('content|main', re.I)) or soup.body or soup
    found += collect([main])
    out = []
    for u in found:
        u = urljoin(base, u.strip())
        if SKIP_IMG.search(u) or TEMPLATE_IMG.search(u):
            continue
        m = re.search(r'(?i)[-_.](\d{2,4})x(\d{2,4})\.', u) or re.search(r'/resize_cache/.*?/(\d{2,4})_(\d{2,4})_\d/', u) \
            or re.search(r'(?i)[/_-](?:w|width)?(\d{2,3})[x_](\d{2,3})/', u)
        if m and int(m.group(1)) < 200:
            continue
        if u not in out:
            out.append(u)
    return out


def _specs_from_dom(soup):
    specs = {}
    for tbl in soup.select('table'):
        rows = tbl.find_all('tr')
        if not 2 <= len(rows) <= 80:
            continue
        pairs = []
        for tr in rows:
            cells = tr.find_all(['td', 'th'])
            if len(cells) == 2:
                k, v = clean_text(cells[0].get_text(' ')), clean_text(cells[1].get_text(' '))
                if k and v and len(k) < 60 and len(v) < 200:
                    pairs.append((k.rstrip(':'), v))
        if len(pairs) >= 2 and len(pairs) >= len(rows) * 0.6:
            specs.update(pairs)
    for dl in soup.select('dl'):
        for dt in dl.find_all('dt'):
            dd = dt.find_next_sibling('dd')
            k, v = clean_text(dt.get_text(' ')), clean_text(dd.get_text(' ')) if dd else ''
            if k and v and len(k) < 60 and len(v) < 200:
                specs[k.rstrip(':')] = v
    if not specs:
        box = soup.select_one('[class*="char"], [class*="spec"], [class*="prop"], [class*="param"], [class*="attribute"], [class*="feature"]')
        if box:
            for li in box.find_all(['li', 'div', 'p'], recursive=True):
                t = clean_text(li.get_text(' '))
                m = re.match(r'^([^:]{2,50}):\s*(.{1,150})$', t)
                if m and m.group(1) not in specs:
                    specs[m.group(1).strip()] = m.group(2).strip()
    junk = re.compile(r'(?i)^(цена|количество|итого|сумма|доставка|оплата|телефон|e-?mail)$')
    return {k: v for k, v in specs.items() if not junk.match(k)}


def _crumbs_from_dom(soup):
    box = soup.select_one('[class*="breadcrumb"], [class*="crumbs"], [itemprop="breadcrumb"], [class^="bread"], [class*=" bread"], '
                          'nav[aria-label*="крошк" i], [itemtype*="BreadcrumbList"]')
    if not box:
        return []
    items = [clean_text(x.get_text(' ')) for x in box.find_all(['a', 'span', 'li']) if clean_text(x.get_text(' '))]
    out = []
    for x in items:
        if x not in out and len(x) < 80 and x not in ('/', '>', '›', '»'):
            out.append(x)
    return out


def _description_from_dom(soup):
    for sel in ['[itemprop="description"]', '[class*="description"]', '[id*="description"]', '[class*="opisanie"]',
                '[id*="opisanie"]', '[class*="product-text"]', '[class*="detail-text"]', '[class*="about"]']:
        el = soup.select_one(sel)
        if el:
            t = clean_text(el.get_text('\n'))
            if len(t) > 60:
                return t[:4000]
    return ''


def is_article(html):
    """Статья или новость: в разметке Article/BlogPosting/NewsArticle и нет Product."""
    low = (html or '').lower()
    return bool(re.search(r'"@type"\s*:\s*\[?\s*"(article|blogposting|newsarticle)"', low)) and '"product"' not in low


def is_product_page(html):
    """Похожа ли страница на карточку товара: разметка Product, og:type=product или цена + кнопка покупки."""
    if not html:
        return False
    low = html.lower()
    if re.search(r'"@type"\s*:\s*\[?\s*"product(group)?"', low) or 'schema.org/product' in low:
        return True
    if re.search(r'og:type"\s+content="(product|og:product)', low) or 'product:price:amount' in low:
        return True
    buy = re.search(r'в\s+корзину|купить|add\s+to\s+cart|добавить\s+в\s+корзину|оформить\s+заказ', low)
    price = re.search(r'\d[\d\s\xa0]{1,9}\s*(₽|руб)', low)
    return bool(buy and price and '<h1' in low)


def extract(html, url):
    """Запись товара со страницы или None, если это не карточка."""
    soup = soup_of(html)
    it = new_item('page')
    it['url'] = url
    via = 'jsonld' if _from_ld(soup, it) else ''
    if _from_microdata(soup, it) and not via:
        via = 'microdata'
    h1el = soup.find('h1')
    h1 = clean_text(h1el.get_text(' ')) if h1el else ''
    if h1 and it['name'] and it['name'].startswith(h1) and re.search(r'(?i)фото|изображени|ракурс|photo|image', it['name'][len(h1):]):
        it['name'] = h1
    if not it['name']:
        h1 = soup.find('h1')
        it['name'] = clean_text(h1.get_text(' ')) if h1 else clean_text(_meta(soup, 'og:title'))
        via = via or 'dom'
    if not it['name']:
        return None
    it['name'] = re.sub(r'(?i)\s*[-–—]\s*(фото|изображение)\s+товара.*$', '', it['name'])
    # «Ref. 1781 - Tupai»: хвост с названием сайта из заголовка вкладки
    host = urlsplit(url).netloc.replace('www.', '').split('.')[0].lower()
    m = re.match(r'^(.*\S)\s+[-–—|]\s+([^-–—|]{2,30})$', it['name'])
    if m and (m.group(2).strip().lower().replace(' ', '') in host or host in m.group(2).strip().lower().replace(' ', '')):
        it['name'] = m.group(1)
    if it['price'] is None:
        it['price'] = to_price(_meta(soup, 'product:price:amount')) or _price_from_dom(soup)
        cur = _meta(soup, 'product:price:currency')
        if cur:
            it['currency'] = cur
    if not it['sku']:
        it['sku'] = _sku_from_dom(soup)
    if not it['description']:
        it['description'] = _description_from_dom(soup) or clean_text(_meta(soup, 'og:description') or _meta(soup, 'description'))
    dom_imgs = _images_from_dom(soup, url)
    imgs = [urljoin(url, x) for x in it['images']] + dom_imgs
    og = _meta(soup, 'og:image')
    if og:
        imgs.append(urljoin(url, og))
    seen, uniq = set(), []
    for x in imgs:
        key = re.sub(r'\?.*$', '', x)
        if key not in seen and not SKIP_IMG.search(x) and not x.startswith('data:'):
            seen.add(key); uniq.append(x)
    it['images'] = uniq[:12]
    if not it['category']:
        it['category'] = _crumbs_from_dom(soup)
    # хлебные крошки без «Главной» и без самого товара
    it['category'] = [c for c in it['category'] if not re.match(r'(?i)^(главная|home|homepage|início|inicio|start|startseite|accueil|каталог|catalog|catalogo|магазин|shop|portfolios?)$', c)
                      and c != it['name'] and c not in it['name']]
    dom_specs = _specs_from_dom(soup)
    for k, v in dom_specs.items():
        it['specs'].setdefault(k, v)
    if not it['finish']:
        for k in list(it['specs']):
            if re.match(r'(?i)^(цвет|покрытие|отделка|цвет покрытия|finish|colou?r)$', k):
                it['finish'] = it['specs'].pop(k); break
    if it['in_stock'] is None:
        txt = soup.get_text(' ', strip=True)[:30000]
        if STOCK_NO.search(txt):
            it['in_stock'] = False
        elif STOCK_YES.search(txt):
            it['in_stock'] = True
    for k in list(it['specs']):
        if re.match(r'(?i)^(бренд|производитель|brand|торговая марка|марка)$', k):
            v = it['specs'].pop(k)
            it['brand'] = it['brand'] or v
        elif re.match(r'(?i)^(артикул|арт\.?|код|код товара|sku|модель)$', k):
            v = it['specs'].pop(k)
            it['sku'] = it['sku'] or v
    it['source'] = 'page:' + via
    return it


# ---------- ссылки на товары ----------

PRODUCT_HINT = re.compile(r'(?i)/(product|products|produkt|produkty|prodotto|prodotti|produit|produits|produto|catalogo/[^/]+|catalogue/[^/]+|tovar|tovary|goods|item|items|p|shop/[^/]+)/|/(catalog|katalog)/[^/]+/[^/]+|\.html?$|[?&](product_id|id)=\d')
STRONG_HINT = re.compile(r'(?i)/(product|products|produkt|produkty|prodotto|prodotti|produit|produits|produto|catalogo/[^/]+|catalogue/[^/]+|tovar|tovary|goods|item|items|p)/|/(catalog|katalog)/[^/]+/[^/]+|[?&](product_id)=\d')
NOT_PRODUCT = re.compile(r'(?i)/(cart|basket|korzina|login|register|account|personal|compare|wishlist|search|news|novosti|blog|stati|statya|articles?|journal|press|shkola[\w-]*|about|o-nas|o-kompanii|contacts?|kontakty|dostavka|oplata|delivery|payment|privacy|policy|brands?|tag|filter|sort|sertifikat\w*|certificat\w*|docs?|faq|vacanc\w*|vakansii)(/|$|\?|\.)|\.(pdf|jpg|png|zip|doc)$|#|mailto:|tel:')


def product_links(html, base, limit=200):
    """Ссылки со страницы списка на карточки товаров того же сайта, от самых похожих на товар."""
    soup = soup_of(html)
    host = urlsplit(base).netloc
    scored = {}
    for a in soup.find_all('a', href=True):
        u = urljoin(base, a['href']).split('#')[0]
        if urlsplit(u).netloc != host or NOT_PRODUCT.search(u) or u.rstrip('/') == base.rstrip('/'):
            continue
        s = 0
        if PRODUCT_HINT.search(u):
            s += 2
        cls = ' '.join(a.get('class', []) + (a.parent.get('class', []) if a.parent else [])).lower()
        if re.search(r'product|card|item|tovar|goods|catalog', cls):
            s += 2
        if a.find('img'):
            s += 1
        depth = len([x for x in urlsplit(u).path.split('/') if x])
        s += min(depth, 4) * 0.3
        if s >= 2:
            scored[u] = max(scored.get(u, 0), s)
    return [u for u, _ in sorted(scored.items(), key=lambda x: -x[1])][:limit]


def catalog_links(html, base, limit=40):
    """Ссылки на разделы каталога из меню главной: /catalog/…, /katalog/…, /shop/…, /collection/…"""
    soup = soup_of(html)
    host = urlsplit(base).netloc
    out = []
    for a in soup.find_all('a', href=True):
        u = urljoin(base, a['href']).split('#')[0]
        if urlsplit(u).netloc != host or NOT_PRODUCT.search(u):
            continue
        if re.search(r'(?i)/(catalog|katalog|shop|products?|produkty|tovary|collections?|category|categories|kategorii)/[^/?]+', u) and u not in out:
            out.append(u)
    return out[:limit]


SECTION_WORDS = re.compile(r'(?i)(ручки|петли|замки|накладки|завертки|упоры|ограничители|доводчики|механизмы|системы|комплекты|аксессуары|'
                           r'фурнитура|цилиндры|задвижки|шпингалеты|ригели|каталог|коллекции|серии|'
                           r'handles|hinges|locks|knobs|pulls|stops|systems|frames|accessories|collections|series|doors|windows|'
                           r'maniglie|cerniere|serrature|griffe|poign[ée]es)\b')


def looks_like_section_name(name):
    """«Дверные ручки», «Concealed hinges»: общее название без модели и цифр, во множественном числе."""
    n = (name or '').strip()
    return bool(n) and not re.search(r'\d', n) and len(n.split()) <= 7 and bool(SECTION_WORDS.search(n))


def card_grid(html, url):
    """Сколько разных ссылок с картинками в основной части страницы (без шапки, подвала, меню и блоков «похожие»)."""
    soup = soup_of(html)
    for x in soup.select('header, footer, nav, [class*="header"], [class*="footer"], [class*="menu"], [class*="related"], '
                         '[class*="similar"], [class*="recommend"], [class*="viewed"], [class*="upsell"], [class*="cross"]'):
        x.decompose()
    host = urlsplit(url).netloc
    hrefs = set()
    for a in soup.find_all('a', href=True):
        u = urljoin(url, a['href']).split('#')[0]
        if urlsplit(u).netloc == host and a.find('img') and not NOT_PRODUCT.search(u) and u.rstrip('/') != url.rstrip('/'):
            hrefs.add(u)
    return len(hrefs)


def is_listing(html, url):
    """Страница раздела: много ссылок на товары внутри её же адреса (/catalog/ruchki/ → /catalog/ruchki/модель/)."""
    own = re.sub(r'\.(html?|php)$', '', url.split('?')[0].split('#')[0]).rstrip('/') + '/'
    kids = [l for l in product_links(html, url, limit=80) if l.startswith(own) and l.rstrip('/') + '/' != own]
    return len(kids) >= 4


def next_page(html, base):
    soup = soup_of(html)
    el = soup.find('link', rel='next') or soup.find('a', rel='next') or soup.find('a', string=re.compile(r'^\s*(›|»|→|далее|следующая|next)\s*$', re.I))
    return urljoin(base, el['href']) if el and el.get('href') else None
