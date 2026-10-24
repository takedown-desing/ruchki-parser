"""Склейка покрытий в модели: у многих магазинов каждый цвет — отдельный товар, на нашем сайте это одна карточка."""
import os
import re

from .item import split_color


def _common_prefix(skus):
    skus = [s for s in skus if s]
    if len(skus) < 2:
        return skus[0] if skus else ''
    p = os.path.commonprefix(skus)
    # общая часть обрывается посреди кода покрытия («CC11RSB.C0») — режем до последнего разделителя
    if p and p[-1].isalnum() and any(len(s) > len(p) and s[len(p)].isalnum() for s in skus):
        p = re.sub(r'[.\-/ _][^.\-/ _]*$', '', p) if re.search(r'[.\-/ _]', p) else ''
    p = p.rstrip(' .-_/')
    return p if len(p) >= 3 else ''


CODE_TAIL = re.compile(r'^(.*\S)\s+([A-Za-z]{0,3}\d{1,4}[A-Za-z]{0,3}|[A-Z]{2,3})$')


def _code_bases(items):
    """«Ручка Tupai 4213 5S 158» и «… 153»: последний короткий код, совпадающий с концом артикула, считается кодом покрытия.
    Срабатывает, только если хотя бы два товара сходятся к одной основе, иначе размер в конце названия не трогаем."""
    cand = {}
    for i, it in enumerate(items):
        name = it['name'].strip()
        # «… CC11RSB.C01»: код покрытия после точки, дефиса или косой черты в артикуле
        m = re.match(r'^(.*\S[A-Za-z0-9])([.\-/])([A-Za-z]{0,3}\d{1,4}[A-Za-z]{0,3})$', name)
        if m and (not it['sku'] or it['sku'].endswith(m.group(2) + m.group(3))):
            cand[i] = (m.group(1), m.group(3)); continue
        m = CODE_TAIL.match(name)
        if m and (not it['sku'] or it['sku'].replace(' ', '').endswith(m.group(2).replace(' ', ''))):
            cand[i] = (m.group(1), m.group(2))
    counts = {}
    for base, _ in cand.values():
        counts[base.lower()] = counts.get(base.lower(), 0) + 1
    return {i: v for i, v in cand.items() if counts[v[0].lower()] >= 2}


def build_models(items, merge=True, brand_override=''):
    """Список моделей: {name, brand, sku, category, description, specs, url, variants:[...]}."""
    groups, order = {}, []
    codes = _code_bases(items) if merge else {}
    for idx, it in enumerate(items):
        base, color = split_color(it['name'])
        if idx in codes and not color:
            base = codes[idx][0]
            color = '' if it['finish'] else codes[idx][1]
        finish = it['finish'] or color
        if it['finish'] and base == it['name']:
            # цвет пришёл отдельным полем, убираем его хвост из названия, если он там есть
            low = it['name'].lower()
            f = it['finish'].lower()
            if low.endswith(f):
                base = it['name'][: -len(f)].rstrip(' ,-–')
        brand = brand_override or it['brand']
        key = (brand.lower(), (it['group'] or base).lower()) if merge else (brand.lower(), it['url'] or it['name'], it['sku'])
        if key not in groups:
            groups[key] = {'name': base if merge else it['name'], 'brand': brand, 'sku': '', 'category': it['category'],
                           'description': it['description'], 'specs': dict(it['specs']), 'url': it['url'], 'variants': []}
            order.append(key)
        m = groups[key]
        for k, v in it['specs'].items():
            m['specs'].setdefault(k, v)
        if not m['description'] and it['description']:
            m['description'] = it['description']
        if not m['category'] and it['category']:
            m['category'] = it['category']
        m['variants'].append({'finish': finish, 'sku': it['sku'], 'price': it['price'], 'currency': it['currency'],
                              'in_stock': it['in_stock'], 'images': it['images'], 'local_images': it.get('local_images', []),
                              'url': it['url'], 'source': it['source']})
    out = []
    for k in order:
        m = groups[k]
        # одинаковые покрытия внутри модели не дублируем
        seen, vs = set(), []
        for v in m['variants']:
            vk = (v['finish'].lower(), v['sku'])
            if vk not in seen:
                seen.add(vk); vs.append(v)
        m['variants'] = vs
        m['sku'] = _common_prefix([v['sku'] for v in vs]) if len(vs) > 1 else (vs[0]['sku'] if vs else '')
        out.append(m)
    return out


def variant_key(m, v):
    """Ключ покрытия для сравнения прогонов: артикул, иначе адрес + покрытие."""
    return v['sku'] or f"{v['url']}|{v['finish']}"


def diff(old_models, new_models):
    """Что изменилось с прошлого прогона: новые, пропавшие, цена, наличие."""
    def index(models):
        out = {}
        for m in models or []:
            for v in m['variants']:
                out[variant_key(m, v)] = (m, v)
        return out
    a, b = index(old_models), index(new_models)
    res = {'new': [], 'gone': [], 'price': [], 'stock': []}
    for k, (m, v) in b.items():
        if k not in a:
            res['new'].append({'name': m['name'], 'finish': v['finish'], 'sku': v['sku'], 'price': v['price']})
            continue
        om, ov = a[k]
        if (ov.get('price') or 0) != (v.get('price') or 0):
            res['price'].append({'name': m['name'], 'finish': v['finish'], 'sku': v['sku'], 'old': ov.get('price'), 'new': v.get('price')})
        if ov.get('in_stock') != v.get('in_stock'):
            res['stock'].append({'name': m['name'], 'finish': v['finish'], 'sku': v['sku'], 'old': ov.get('in_stock'), 'new': v.get('in_stock')})
    for k, (m, v) in a.items():
        if k not in b:
            res['gone'].append({'name': m['name'], 'finish': v['finish'], 'sku': v['sku'], 'price': v.get('price')})
    return res
