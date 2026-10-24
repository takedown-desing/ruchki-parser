"""Один прогон сбора по сайту: найти источник → собрать товары → фото → модели → Excel → сравнение → сохранить в git."""
import os
import threading
import time
import traceback
from urllib.parse import urlsplit

from . import discover, feeds, pages, store, excel, gitsync, browser, diagnose
from .http import Fetcher
from .images import save_image
from .item import slug
from .models import build_models, diff

JOBS = {}
_run_lock = threading.Lock()


class Job:
    def __init__(self, site_ids):
        self.id = time.strftime('%Y%m%d-%H%M%S')
        self.site_ids = site_ids
        self.status = 'queued'
        self.log_lines = []
        self.progress = ''
        self.started = time.time()
        self.result = {}

    def log(self, msg):
        line = time.strftime('%H:%M:%S ') + msg
        self.log_lines.append(line)
        print(line, flush=True)

    def as_dict(self):
        return {'id': self.id, 'status': self.status, 'progress': self.progress, 'log': self.log_lines[-400:],
                'result': self.result, 'seconds': int(time.time() - self.started)}


def start(site_ids, push=True):
    job = Job(site_ids)
    JOBS[job.id] = job
    threading.Thread(target=_run_all, args=(job, push), daemon=True).start()
    return job


def _run_all(job, push):
    with _run_lock:
        job.status = 'running'
        done = []
        for n, sid in enumerate(job.site_ids, 1):
            site = store.get(sid)
            if not site:
                continue
            job.progress = f'{n} из {len(job.site_ids)}: {site["name"]}'
            job.log(f'=== {site["name"]} ({site["url"]})')
            try:
                summary = run_site(site, job.log)
                job.result[sid] = summary
                done.append(f'{site["name"]}: {summary["models"]} мод., {summary["variants"]} покр.')
            except diagnose.Stop as e:
                job.log(f'ОСТАНОВЛЕНО: {e.reason}')
                lr = {'when': time.strftime('%Y-%m-%d %H:%M'), 'ok': False, 'stopped': True, 'problem': e.reason}
                store.update(sid, last_run=lr)
                hist_path = os.path.join(store.site_dir(sid), 'history.json')
                hist = store.load_json(hist_path, [])
                hist.insert(0, lr); store.save_json(hist_path, hist[:100])
                job.result[sid] = {'problem': e.reason}
                done.append(f'{site["name"]}: остановлен')
            except Exception as e:
                job.log(f'ОШИБКА: {e}')
                job.log(traceback.format_exc().splitlines()[-1])
                store.update(sid, last_run={'when': time.strftime('%Y-%m-%d %H:%M'), 'ok': False, 'error': str(e)[:300]})
                job.result[sid] = {'error': str(e)}
        if push and done:
            gitsync.save('Сбор: ' + '; '.join(done)[:300], job.log)
        job.status = 'done'
        job.progress = 'готово'


def collect_items(site, fx, log, rd=None, state=None):
    """Товары сайта списком записей. Сначала фид, потом страницы."""
    url = site['url'].strip()
    limit = int(site.get('limit') or 0)
    # слово из адреса поиска (?q=FIMET) отбирает товары фида; со страниц поиска сайт уже отобрал товары сам,
    # поэтому для страниц работает только явная настройка «Отбор по слову»
    own_kw = (site.get('filter') or '').strip()
    kw = own_kw or discover.keyword_of(url)
    method, feed_url, kind = site.get('method', 'auto'), site.get('feed_url') or '', site.get('feed_kind') or ''
    problem = diagnose.access_problem(fx, feed_url or url)
    if problem:
        raise diagnose.Stop(problem)
    if method in ('auto', 'feed') and not feed_url:
        feed_url, kind = discover.find_feed(fx, url, log)
        if feed_url:
            store.update(site['id'], feed_url=feed_url, feed_kind=kind)
    items, how = [], ''
    if method in ('auto', 'feed') and feed_url:
        text = fx.get(feed_url)
        kind = kind or feeds.detect(text)
        items = feeds.parse(text or '', kind, discover.site_root(url))
        log(f'В фиде {len(items)} товаров')
        if kw:
            k = kw.lower()
            items = [i for i in items if matches(i, k)]
            log(f'Отбор по «{kw}»: {len(items)}')
        how = f'фид {kind}'
        if limit:
            items = items[:limit]
    if not items and method in ('auto', 'pages'):
        items = collect_pages(site, fx, log, url, limit, kw, rd, state)
        if not items and kw and not own_kw and state.get('named'):
            # поиск сайта уже отобрал товары, а в их названиях нет слова поиска (свой сайт бренда): берём без отбора
            log(f'Под «{kw}» ни одна карточка не подошла, беру результаты поиска без отбора по слову')
            state['samples'] = []
            items = collect_pages(site, fx, log, url, limit, '', rd, state)
        how = 'страницы сайта'
    return items, how


def matches(it, kw):
    """Подходит ли товар под «Отбор по слову»: слово есть в названии, бренде, разделе или адресе."""
    if not kw:
        return True
    hay = ' '.join([it['name'], it['brand'], it['url'], ' '.join(it['category'] or [])]).lower()
    return all(w in hay for w in kw.lower().split())


def collect_pages(site, fx, log, url, limit, kw, rd=None, state=None):
    if discover.is_root(url):
        cands = discover.rank_candidates(discover.sitemap_urls(fx, discover.site_root(url), log), kw)
        if not cands or len(cands) < (limit or 3) * 3:
            home = fx.get(url) or ''
            cands = cands + [c for c in pages.product_links(home, url) if c not in cands]
            # мало ссылок на товары: разделы каталога из меню, товары возьмутся из них
            cats = pages.catalog_links(home, url)
            cands += [c for c in cats if c not in cands]
            log(f'Карты сайта нет или в ней мало товаров: ссылок с главной {len(cands)}, из них разделов каталога {len(cats)}')
    else:
        cands, page, guard = [], url, 0
        while page and guard < 20 and (not limit or len(cands) < limit * 5):
            html = fx.get(page)
            if not html:
                break
            if guard == 0 and pages.is_product_page(html) and not pages.product_links(html, page)[:3]:
                cands = [page]; break
            cands += [c for c in pages.product_links(html, page) if c not in cands]
            page = pages.next_page(html, page); guard += 1
        if len(cands) < 3 and rd and state and state['mode'] != 'never':
            html = rd.get(url) or ''
            more = [c for c in pages.product_links(html, url) if c not in cands]
            if more:
                log(f'Список товаров достроен скриптом: в браузере {len(more)} ссылок')
                cands += more; state['mode'] = 'always'
        log(f'Ссылок на товары со страницы списка: {len(cands)}')
    if state is not None:
        state['candidates'] = state.get('candidates', 0) + len(cands)
    items, tried = try_candidates(fx, log, cands, limit, kw, trusted=not discover.is_root(url), rd=rd, state=state)
    if not items and not discover.is_root(url):
        # со страницы списка ничего: карта сайта в пределах того же раздела адресов (/en/ → только /en/…)
        prefix = urlsplit(url).path.rstrip('/') + '/'
        urls = [u for u in discover.sitemap_urls(fx, discover.site_root(url), log) if urlsplit(u).path.startswith(prefix)]
        if urls:
            log(f'Пробую карту сайта в разделе {prefix}: {len(urls)} адресов')
            state['candidates'] = state.get('candidates', 0) + len(urls)
            more, t2 = try_candidates(fx, log, discover.rank_candidates(urls, kw), limit, kw, rd=rd, state=state)
            items += more; tried += t2
    log(f'Собрано со страниц: {len(items)} (проверено адресов: {tried})')
    return items


def _judge(html, c, trust):
    """(запись товара или None, это раздел?) для одной страницы."""
    sure = pages.is_product_page(html)
    listing = pages.is_listing(html, c)
    if listing:
        # раздел, даже если у него разметка товара (Битрикс ставит AggregateOffer и на разделы)
        return None, True
    if not sure and (not (trust or pages.STRONG_HINT.search(c)) or listing or pages.is_article(html)):
        return None, listing
    it = pages.extract(html, c)
    if it and pages.looks_like_section_name(it['name']) and pages.card_grid(html, c) >= 8:
        # «Дверные ручки FORME» с сеткой карточек: это раздел, товары берутся из него
        return None, True
    if it and not sure and len(it['images']) < 1:
        return None, listing
    return it, listing


def try_candidates(fx, log, cands, limit, kw, trusted=False, rd=None, state=None):
    """Открывает адреса по очереди и оставляет карточки товаров. Раздел вместо карточки: берёт ссылки из него, на один уровень.
    trusted: адреса взяты из списка товаров на странице сайта, поэтому «товарный» вид адреса не обязателен.
    rd: браузер без окна. В режиме auto пробуется на первых трёх страницах без фото; помог — дальше все страницы через него."""
    state = state if state is not None else {'mode': 'never'}
    items, tried, seen = [], 0, set(cands)
    queue = [(c, 0, trusted) for c in cands]
    max_try = (limit * (15 if kw else 8) + 12) if limit else len(cands) * 2
    while queue:
        c, depth, trust = queue.pop(0)
        if limit and len(items) >= limit or tried >= max_try:
            break
        tried += 1
        html = fx.get(c)
        if rd and state['mode'] == 'always':
            html = rd.get(c) or html
        if not html:
            continue
        it, listing = _judge(html, c, trust)
        if rd and state['mode'] == 'auto' and state.get('tries', 0) < 3 and not listing and (it is None or not it['images']) \
                and (trust or pages.STRONG_HINT.search(c)):
            state['tries'] = state.get('tries', 0) + 1
            rhtml = rd.get(c)
            if rhtml:
                it2, listing2 = _judge(rhtml, c, trust)
                if it2 and it2['images']:
                    log('  браузер нашёл то, чего нет в разметке страницы: дальше открываю страницы сайта в браузере')
                    state['mode'] = 'always'
                    it, listing, html = it2, listing2, rhtml
        if len(state.setdefault('samples', [])) < 8 and not (it and it.get('images')):
            # для диагностики нужна и отброшенная запись: название есть, а фото нет
            raw = it if it else (None if listing else pages.extract(html, c))
            state['samples'].append((c, html, raw))
        if listing and depth == 0:
            kids = [k for k in pages.product_links(html, c, limit=max(12, limit * 4) if limit else 200) if k not in seen]
            seen.update(kids)
            state['candidates'] = state.get('candidates', 0) + len(kids)
            queue = [(k, 1, True) for k in kids] + queue
        if it and it['name']:
            state['named'] = state.get('named', 0) + 1
        if it and it['name'] and matches(it, kw):
            items.append(it)
            log(f'  товар: {it["name"][:70]} | {it["price"] or "без цены"} | фото {len(it["images"])} | {it["source"]}')
    return items, tried


def run_site(site, log):
    t0 = time.time()
    fx = Fetcher(delay=float(site.get('delay') or 1.0), log=log)
    render = site.get('render') or 'auto'
    rd = browser.Renderer(log) if render != 'never' and browser.available() else None
    state = {'mode': render if rd else 'never'}
    try:
        items, how = collect_items(site, fx, log, rd, state)
    finally:
        if rd:
            rd.close()
    if state.get('mode') == 'always' and how == 'страницы сайта':
        how = 'страницы сайта (через браузер)'
    if not items:
        raise diagnose.Stop(diagnose.empty_reason(state, (site.get('filter') or '').strip(), search=discover.keyword_of(site['url'])))
    folder = store.site_dir(site['id'])
    img_dir = os.path.join(folder, 'images')
    n_img = 0
    for it in items:
        it['local_images'] = []
        base = slug(f"{it['name']} {it['finish']}", 60)
        for u in it['images'][:6]:
            name = save_image(fx, u, img_dir, base)
            if name:
                it['local_images'].append(name); n_img += 1
    log(f'Фото сохранено: {n_img}')
    models = build_models(items, merge=site.get('merge', True), brand_override=site.get('brand') or '')
    old = store.load_json(os.path.join(folder, 'products.json'), {}).get('models')
    changes = diff(old, models) if old is not None else {'new': [], 'gone': [], 'price': [], 'stock': []}
    if old is None:
        changes['new'] = [{'name': m['name'], 'finish': v['finish'], 'sku': v['sku'], 'price': v['price']} for m in models for v in m['variants']]
    when = time.strftime('%Y-%m-%d %H:%M')
    store.save_json(os.path.join(folder, 'products.json'), {'site': site['url'], 'when': when, 'how': how, 'models': models})
    n_rows = excel.write_products(os.path.join(folder, 'products.xlsx'), models, site, images_prefix=f'output/{site["id"]}/images/')
    excel.write_changes(os.path.join(folder, 'changes.xlsx'), changes)
    hist = store.load_json(os.path.join(folder, 'history.json'), [])
    summary = {'when': when, 'ok': True, 'how': how, 'models': len(models), 'variants': n_rows, 'images': n_img,
               'no_price': sum(1 for m in models for v in m['variants'] if not v['price']),
               'no_photo': sum(1 for m in models for v in m['variants'] if not v['images']),
               'changes': {k: len(v) for k, v in changes.items()}, 'seconds': int(time.time() - t0),
               'warnings': diagnose.warnings_for(models)}
    hist.insert(0, summary)
    store.save_json(os.path.join(folder, 'history.json'), hist[:100])
    store.update(site['id'], last_run=summary)
    write_all_products()
    log(f'Готово за {summary["seconds"]} с: моделей {summary["models"]}, покрытий {n_rows}, источник: {how}')
    return summary


def write_all_products():
    """Общий Excel по всем сайтам: output/все-товары.xlsx."""
    models_all = []
    for s in store.all_sites():
        data = store.load_json(os.path.join(store.site_dir(s['id']), 'products.json'), {})
        for m in data.get('models', []):
            models_all.append((s, m))
    if not models_all:
        return
    from openpyxl import Workbook
    specs, rows_all = [], []
    for s, m in models_all:
        head, rows = excel.rows_for([m], s, images_prefix=f'output/{s["id"]}/images/')
        specs += [h for h in head if h.startswith('Х: ') and h not in specs]
        rows_all += [dict(zip(head, r)) for r in rows]
    head_all = excel.BASE_COLS + specs + excel.SRC_COLS
    wb = Workbook(); ws = wb.active; ws.title = 'Все товары'
    ws.append(head_all)
    for d in rows_all:
        ws.append([d.get(h, '') for h in head_all])
    excel._style(ws, head_all)
    wb.save(os.path.join(store.OUTPUT, 'все-товары.xlsx'))


def rebuild_excel(site_id):
    """Пересобрать Excel из уже собранных данных (после правки разделов, бренда или настройки описаний)."""
    site = store.get(site_id)
    folder = store.site_dir(site_id)
    data = store.load_json(os.path.join(folder, 'products.json'), {})
    models = data.get('models', [])
    if site.get('brand'):
        for m in models:
            m['brand'] = site['brand']
    excel.write_products(os.path.join(folder, 'products.xlsx'), models, site, images_prefix=f'output/{site_id}/images/')
    write_all_products()
    return len(models)


def our_sections(refresh=False):
    """Разделы каталога ручкидлядверей.рф (адреса из карты сайта) для подсказок при сопоставлении."""
    path = os.path.join(store.DATA, 'our_sections.json')
    if not refresh and os.path.exists(path):
        return store.load_json(path, [])
    import re
    fx = Fetcher(delay=0, use_cache=False)
    xml = fx.get('https://xn--b1adafanmbl0ch2a6c0g.xn--p1ai/sitemap.xml') or ''
    secs = sorted({re.sub(r'^https?://[^/]+', '', u) for u in re.findall(r'<loc>([^<]+)</loc>', xml)
                   if '/catalog/' in u and '/page-' not in u})
    if secs:
        store.save_json(path, secs)
    return secs
