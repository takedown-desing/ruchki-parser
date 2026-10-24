"""Сводка по всем источникам: сколько собрано, есть ли цена, фото, раздел, характеристики. python tools/report.py [--md]"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from parser import store  # noqa: E402


def main():
    md = '--md' in sys.argv
    rows = []
    for s in store.all_sites():
        data = store.load_json(os.path.join(store.site_dir(s['id']), 'products.json'), {})
        ms = data.get('models', [])
        vs = [v for m in ms for v in m['variants']]
        lr = s.get('last_run') or {}
        rows.append({
            'name': s['name'], 'url': s['url'], 'how': lr.get('how') or lr.get('error') or '—', 'models': len(ms), 'variants': len(vs),
            'price': sum(1 for v in vs if v['price']), 'photo': sum(1 for v in vs if v.get('local_images')),
            'cat': sum(1 for m in ms if m.get('category')), 'specs': sum(1 for m in ms if m.get('specs')),
            'desc': sum(1 for m in ms if m.get('description')), 'sku': sum(1 for v in vs if v['sku']),
            'example': (ms[0]['name'][:60] if ms else ''),
        })
    if md:
        print('| Источник | Как собран | Моделей / покрытий | С ценой | С фото | С разделом | С характеристиками | Пример |')
        print('|---|---|---|---|---|---|---|---|')
        for r in rows:
            print(f"| {r['name']} | {r['how']} | {r['models']} / {r['variants']} | {r['price']} | {r['photo']} | {r['cat']} | {r['specs']} | {r['example']} |")
    else:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))


if __name__ == '__main__':
    main()
