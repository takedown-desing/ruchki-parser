"""Запуск без интерфейса:
  python cli.py list                       — сайты
  python cli.py add <адрес> [--brand X] [--limit 3]
  python cli.py run [id ...] [--no-push]   — собрать (все сайты, если id не указаны)
"""
import argparse
import sys

from parser import store, runner, gitsync


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('list')
    a = sub.add_parser('add'); a.add_argument('url'); a.add_argument('--brand', default=''); a.add_argument('--limit', type=int, default=3); a.add_argument('--name', default='')
    r = sub.add_parser('run'); r.add_argument('ids', nargs='*'); r.add_argument('--no-push', action='store_true')
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
    else:
        ap.print_help(); sys.exit(1)


if __name__ == '__main__':
    main()
