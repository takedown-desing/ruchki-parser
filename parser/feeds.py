"""Фиды товаров: YML (Яндекс Маркет), Google Merchant (RSS/Atom), произвольный XML с товарами, JSON Shopify и WooCommerce.
Каждый формат превращается в одинаковые записи товара (см. parser/item.py)."""
import json
import re

from lxml import etree

from .item import new_item, clean_text, to_price

GOOGLE_NS = 'http://base.google.com/ns/1.0'


def detect(text):
    """Тип фида по началу ответа или None, если это не фид."""
    if not text:
        return None
    head = text.lstrip()[:6000]
    low = head.lower()
    if '<yml_catalog' in low or ('<shop' in low and '<offer' in low):
        return 'yml'
    if 'base.google.com/ns' in low and ('<item' in low or '<entry' in low):
        return 'google'
    if head.startswith('{') or head.startswith('['):
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if isinstance(data, dict) and isinstance(data.get('products'), list) and data['products'] and 'variants' in data['products'][0]:
            return 'shopify'
        if isinstance(data, list) and data and isinstance(data[0], dict) and 'prices' in data[0] and 'name' in data[0]:
            return 'woo'
        return None
    if low.startswith('<?xml') or low.startswith('<'):
        if re.search(r'<(offer|product|item|good|tovar)[\s>]', low) and re.search(r'<(price|цена)[\s>]', low):
            return 'xml'
    return None


def parse(text, kind, base_url=''):
    """Все товары фида списком записей."""
    if kind == 'yml':
        return list(_yml(text))
    if kind == 'google':
        return list(_google(text))
    if kind == 'xml':
        return list(_generic_xml(text))
    if kind == 'shopify':
        return list(_shopify(json.loads(text), base_url))
    if kind == 'woo':
        return list(_woo(json.loads(text)))
    return []


def _xml_root(text):
    data = text.encode('utf-8') if isinstance(text, str) else text
    parser = etree.XMLParser(recover=True, huge_tree=True, resolve_entities=False)
    # объявление кодировки в заголовке мешает разбору уже декодированной строки
    data = re.sub(rb'^\s*<\?xml[^>]*\?>', b'', data)
    return etree.fromstring(data, parser)


def _is_file_url(u):
    """Ссылка ведёт на файл, а не на главную сайта (в фидах бывает пустая картинка = адрес сайта)."""
    from urllib.parse import urlsplit
    path = urlsplit(u.strip()).path
    return len(path.strip('/')) > 0


def _t(el, tag):
    x = el.find(tag)
    return clean_text(x.text) if x is not None and x.text else ''


def _yml(text):
    root = _xml_root(text)
    cats = {}
    for c in root.iter('category'):
        cats[c.get('id')] = (clean_text(c.text or ''), c.get('parentId'))

    def cat_path(cid):
        out, guard = [], 0
        while cid and cid in cats and guard < 10:
            name, parent = cats[cid]
            out.insert(0, name); cid = parent; guard += 1
        return out

    for o in root.iter('offer'):
        it = new_item('feed:yml')
        name = _t(o, 'name')
        if not name:
            name = ' '.join(x for x in [_t(o, 'typePrefix'), _t(o, 'vendor'), _t(o, 'model')] if x)
        it['name'] = name
        it['brand'] = _t(o, 'vendor')
        it['sku'] = _t(o, 'vendorCode') or o.get('id') or ''
        it['url'] = _t(o, 'url')
        it['price'] = to_price(_t(o, 'price'))
        it['currency'] = _t(o, 'currencyId') or 'RUB'
        av = (o.get('available') or _t(o, 'availability') or _t(o, 'available') or '').lower()
        it['in_stock'] = None if not av else av in ('true', '1', 'yes', 'active', 'in_stock', 'instock', 'в наличии', 'есть')
        cnt = _t(o, 'count') or _t(o, 'stock') or _t(o, 'quantity')
        if it['in_stock'] is None and cnt:
            it['in_stock'] = to_price(cnt) is not None
        it['category'] = cat_path(_t(o, 'categoryId'))
        it['description'] = clean_text(_t(o, 'description'), html=True)
        it['images'] = [clean_text(p.text) for p in o.findall('picture') if p.text and _is_file_url(p.text)]
        for tag, label in (('country_of_origin', 'Страна производства'), ('weight', 'Вес, кг'), ('dimensions', 'Габариты'),
                           ('sales_notes', 'Условия продажи')):
            if _t(o, tag):
                it['specs'][label] = _t(o, tag)
        it['group'] = o.get('group_id') or ''
        for p in o.findall('param'):
            k = clean_text(p.get('name') or '')
            v = clean_text(p.text or '')
            if k and v:
                unit = p.get('unit')
                it['specs'][k] = f'{v} {unit}' if unit and unit not in v else v
        it['finish'] = it['specs'].pop('Цвет', '') or it['specs'].pop('Покрытие', '') or it['specs'].pop('Отделка', '')
        yield it


def _google(text):
    root = _xml_root(text)
    g = '{%s}' % GOOGLE_NS
    entries = list(root.iter('item')) or list(root.iter('{http://www.w3.org/2005/Atom}entry'))
    for e in entries:
        def gv(name):
            x = e.find(g + name)
            return clean_text(x.text) if x is not None and x.text else ''
        it = new_item('feed:google')
        it['name'] = gv('title') or _t(e, 'title')
        it['brand'] = gv('brand')
        it['sku'] = gv('mpn') or gv('id')
        link = e.find('link')
        it['url'] = gv('link') or (clean_text(link.text) if link is not None and link.text else (link.get('href') if link is not None else ''))
        price = gv('sale_price') or gv('price')
        it['price'] = to_price(price)
        m = re.search(r'[A-Z]{3}', price or '')
        it['currency'] = m.group(0) if m else 'RUB'
        av = gv('availability').lower()
        it['in_stock'] = None if not av else av.replace(' ', '_') in ('in_stock', 'preorder', 'backorder')
        it['category'] = [x.strip() for x in re.split(r'\s*>\s*', gv('product_type')) if x.strip()]
        it['description'] = clean_text(gv('description') or _t(e, 'description'), html=True)
        imgs = [gv('image_link')] + [clean_text(x.text) for x in e.findall(g + 'additional_image_link') if x.text]
        it['images'] = [x for x in imgs if x]
        it['group'] = gv('item_group_id')
        it['finish'] = gv('color')
        for k in ('material', 'pattern', 'size'):
            if gv(k):
                it['specs'][{'material': 'Материал', 'pattern': 'Узор', 'size': 'Размер'}[k]] = gv(k)
        yield it


TAG_ALIASES = {
    'name': ['name', 'title', 'model', 'наименование', 'название'],
    'sku': ['vendorcode', 'sku', 'article', 'artikul', 'артикул', 'code', 'mpn'],
    'price': ['price', 'цена', 'retail_price', 'rrp'],
    'brand': ['vendor', 'brand', 'manufacturer', 'производитель', 'бренд'],
    'url': ['url', 'link'],
    'description': ['description', 'описание', 'desc'],
    'category': ['category', 'categoryname', 'категория', 'раздел'],
    'stock': ['available', 'stock', 'quantity', 'наличие', 'instock'],
}


def _generic_xml(text):
    """Любой XML, где товары лежат одинаковыми элементами с ценой внутри."""
    root = _xml_root(text)
    counts = {}
    for el in root.iter():
        if isinstance(el.tag, str) and len(el):
            kids = {c.tag.lower() for c in el if isinstance(c.tag, str)}
            if kids & set(TAG_ALIASES['price']) and kids & set(TAG_ALIASES['name']):
                counts[el.tag] = counts.get(el.tag, 0) + 1
    if not counts:
        return
    tag = max(counts, key=counts.get)
    for el in root.iter(tag):
        kids = {}
        for c in el:
            if isinstance(c.tag, str):
                kids.setdefault(c.tag.lower(), []).append(c)

        def first(field):
            for a in TAG_ALIASES[field]:
                if a in kids and kids[a][0].text:
                    return clean_text(kids[a][0].text)
            return el.get(field) or ''
        it = new_item('feed:xml')
        it['name'] = first('name'); it['sku'] = first('sku'); it['brand'] = first('brand')
        it['url'] = first('url'); it['price'] = to_price(first('price'))
        it['description'] = clean_text(first('description'), html=True)
        cat = first('category'); it['category'] = [cat] if cat else []
        st = first('stock').lower()
        it['in_stock'] = None if not st else not (st in ('0', 'false', 'нет', 'no') )
        for k in ('picture', 'image', 'photo', 'img', 'фото', 'изображение'):
            it['images'] += [clean_text(x.text) for x in kids.get(k, []) if x.text]
        if it['name']:
            yield it


def _shopify(data, base_url):
    for p in data.get('products', []):
        imgs = [i.get('src') for i in p.get('images', []) if i.get('src')]
        for v in p.get('variants', []):
            it = new_item('feed:shopify')
            it['name'] = p.get('title', ''); it['brand'] = p.get('vendor', '')
            it['sku'] = v.get('sku') or str(v.get('id', ''))
            it['finish'] = '' if (v.get('title') or '').lower() == 'default title' else v.get('title', '')
            it['price'] = to_price(v.get('price')); it['currency'] = ''
            it['in_stock'] = v.get('available')
            it['category'] = [p['product_type']] if p.get('product_type') else []
            it['description'] = clean_text(p.get('body_html', ''), html=True)
            it['url'] = base_url.rstrip('/') + '/products/' + p.get('handle', '')
            it['images'] = imgs
            it['group'] = str(p.get('id', ''))
            yield it


def _woo(data):
    for p in data:
        it = new_item('feed:woo')
        it['name'] = clean_text(p.get('name', ''), html=True)
        it['sku'] = p.get('sku', '')
        pr = p.get('prices') or {}
        minor = int(pr.get('currency_minor_unit') or 0)
        if pr.get('price'):
            it['price'] = round(int(pr['price']) / (10 ** minor), 2)
        it['currency'] = pr.get('currency_code', '')
        it['in_stock'] = p.get('is_in_stock')
        it['url'] = p.get('permalink', '')
        it['description'] = clean_text(p.get('description') or p.get('short_description') or '', html=True)
        it['category'] = [c.get('name', '') for c in p.get('categories', [])][:1]
        it['images'] = [i.get('src') for i in p.get('images', []) if i.get('src')]
        for a in p.get('attributes', []):
            vals = ', '.join(t.get('name', '') for t in a.get('terms', []))
            if a.get('name') and vals:
                it['specs'][a['name']] = vals
        yield it
