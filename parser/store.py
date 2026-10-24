"""Список сайтов и результаты сборов. Всё в обычных файлах, чтобы лежало в репозитории:
data/sites.json — сайты и их настройки; output/<сайт>/ — товары, Excel, фото, история изменений."""
import json
import os
import threading
import time
from urllib.parse import urlsplit

from .item import slug

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUTPUT = os.path.join(ROOT, 'output')
SITES = os.path.join(DATA, 'sites.json')
_lock = threading.Lock()

DEFAULTS = {'name': '', 'brand': '', 'filter': '', 'limit': 3, 'merge': True, 'use_description': False, 'method': 'auto',
            'feed_url': '', 'feed_kind': '', 'mapping': {}, 'last_run': None}


def _read():
    if not os.path.exists(SITES):
        return []
    with open(SITES, encoding='utf-8') as f:
        return json.load(f)


def _write(sites):
    os.makedirs(DATA, exist_ok=True)
    tmp = SITES + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(sites, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SITES)


def all_sites():
    with _lock:
        return [dict(DEFAULTS, **s) for s in _read()]


def get(site_id):
    return next((s for s in all_sites() if s['id'] == site_id), None)


def make_id(url, existing):
    p = urlsplit(url)
    base = slug(p.netloc.replace('www.', '') + ('-' + p.path.strip('/') if p.path.strip('/') else '') + ('-' + p.query if p.query else ''), 60)
    sid, n = base, 2
    while sid in existing:
        sid = f'{base}-{n}'; n += 1
    return sid


def add(url, **opts):
    with _lock:
        sites = _read()
        sid = make_id(url, {s['id'] for s in sites})
        site = dict(DEFAULTS, id=sid, url=url, added=time.strftime('%Y-%m-%d %H:%M'))
        site.update({k: v for k, v in opts.items() if k in DEFAULTS})
        if not site['name']:
            site['name'] = urlsplit(url).netloc.replace('www.', '')
        sites.append(site)
        _write(sites)
        return site


def update(site_id, **fields):
    with _lock:
        sites = _read()
        for s in sites:
            if s['id'] == site_id:
                s.update({k: v for k, v in fields.items() if k in DEFAULTS or k in ('url',)})
        _write(sites)


def remove(site_id):
    with _lock:
        _write([s for s in _read() if s['id'] != site_id])


def site_dir(site_id):
    return os.path.join(OUTPUT, site_id)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
