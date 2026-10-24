"""Запуск без интерфейса:
  python cli.py list                       — сайты
  python cli.py add <адрес> [--brand X] [--limit 3]
  python cli.py run [id ...] [--no-push]   — собрать (все сайты, если id не указаны)
  python cli.py web-task                   — задание с сайта парсера (GitHub Actions): берёт ACTION, SITE_ID, URL… из окружения
"""
import argparse
import os
import sys
import time

from parser import store, runner, gitsync


def web_task():
    """Задание от кнопки на сайте: добавить источник, собрать, убрать. Журнал пишется в data/task.json, чтобы сайт показал ход."""
    env = os.environ.get
    action, sid, url = (env('ACTION') or 'run').strip(), (env('SITE_ID') or '').strip(), (env('URL') or '').strip()
    task = {'action': action, 'started': time.strftime('%Y-%m-%d %H:%M'), 'status': 'running', 'log': [], 'run_id': env('GITHUB_RUN_ID', '')}
    path = os.path.join(store.DATA, 'task.json')

    def log(msg):
        line = time.strftime('%H:%M:%S ') + msg
        print(line, flush=True)
        task['log'].append(line)
        task['log'] = task['log'][-300:]

    ids = []
    if action == 'add':
        if not url:
            log('Не указан адрес'); sys.exit(1)
        if not url.startswith('http'):
            url = 'https://' + url
        try:
            limit = int(env('LIMIT') or 3)
        except ValueError:
            limit = 3
        site = store.add(url, name=(env('NAME') or '').strip(), brand=(env('BRAND') or '').strip(),
                         filter=(env('FILTER') or '').strip(), limit=limit)
        log(f'Добавлен источник: {site["name"]} ({site["url"]})')
        ids = [site['id']]
    elif action == 'remove':
        if sid and store.get(sid):
            store.remove(sid); log(f'Источник убран: {sid}')
        store.save_json(path, dict(task, status='done'))
        gitsync.save(f'Источник убран: {sid}', log)
        return
    else:
        ids = [sid] if sid else [s['id'] for s in store.all_sites()]
    task['site_ids'] = ids
    job = runner.Job(ids)
    job.log = log
    runner._run_all(job, push=False)
    task['status'] = 'done'
    task['finished'] = time.strftime('%Y-%m-%d %H:%M')
    task['result'] = job.result
    store.save_json(path, task)
    names = ', '.join((store.get(i) or {}).get('name', i) for i in ids)[:200]
    gitsync.save(f'Сбор с сайта парсера: {names}', log)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('list')
    a = sub.add_parser('add'); a.add_argument('url'); a.add_argument('--brand', default=''); a.add_argument('--limit', type=int, default=3); a.add_argument('--name', default='')
    r = sub.add_parser('run'); r.add_argument('ids', nargs='*'); r.add_argument('--no-push', action='store_true')
    sub.add_parser('web-task')
    args = ap.parse_args()
    if args.cmd == 'list':
        for s in store.all_sites():
            lr = s.get('last_run') or {}
            print(f"{s['id']:40} {s['url'][:60]:60} {lr.get('how', '')} {lr.get('models', '')}")
    elif args.cmd == 'add':
        s = store.add(args.url, brand=args.brand, limit=args.limit, name=args.name)
        print('добавлен:', s['id'])
    elif args.cmd == 'run':
        ids = args.ids or [s['id'] for s in store.all_sites()]
        job = runner.Job(ids)
        runner._run_all(job, push=not args.no_push)
    elif args.cmd == 'web-task':
        web_task()
    else:
        ap.print_help(); sys.exit(1)


if __name__ == '__main__':
    main()
