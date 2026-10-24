"""Админка парсера: http://127.0.0.1:8765 (запуск — файл «Запустить.command» или python app.py)."""
import os
import webbrowser
from threading import Timer

from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, abort

from parser import store, runner, gitsync

app = Flask(__name__)
PORT = int(os.environ.get('PORT', 8765))


def current_job():
    running = [j for j in runner.JOBS.values() if j.status in ('queued', 'running')]
    return running[-1] if running else (list(runner.JOBS.values())[-1] if runner.JOBS else None)


@app.route('/')
def index():
    sites = store.all_sites()
    all_xlsx = os.path.exists(os.path.join(store.OUTPUT, 'все-товары.xlsx'))
    job = current_job()
    return render_template('index.html', sites=sites, git=gitsync.status(), all_xlsx=all_xlsx,
                           job=job.as_dict() if job else None)


@app.post('/sites')
def add_site():
    url = (request.form.get('url') or '').strip()
    if not url:
        return redirect(url_for('index'))
    if not url.startswith('http'):
        url = 'https://' + url
    site = store.add(url, name=request.form.get('name', '').strip(), brand=request.form.get('brand', '').strip(),
                     filter=request.form.get('filter', '').strip(), limit=int(request.form.get('limit') or 0),
                     merge=bool(request.form.get('merge')))
    if request.form.get('run'):
        runner.start([site['id']], push=True)
    return redirect(url_for('index'))


@app.get('/site/<sid>')
def site_page(sid):
    site = store.get(sid) or abort(404)
    folder = store.site_dir(sid)
    data = store.load_json(os.path.join(folder, 'products.json'), {})
    history = store.load_json(os.path.join(folder, 'history.json'), [])
    cats = []
    for m in data.get('models', []):
        c = ' > '.join(m.get('category') or [])
        if c and c not in cats:
            cats.append(c)
    job = current_job()
    return render_template('site.html', site=site, data=data, history=history, cats=cats, sections=runner.our_sections(),
                           has_xlsx=os.path.exists(os.path.join(folder, 'products.xlsx')),
                           has_changes=os.path.exists(os.path.join(folder, 'changes.xlsx')), job=job.as_dict() if job else None)


@app.post('/site/<sid>/settings')
def save_settings(sid):
    store.get(sid) or abort(404)
    f = request.form
    fields = {'url': f.get('url', '').strip(), 'name': f.get('name', '').strip(), 'brand': f.get('brand', '').strip(),
              'filter': f.get('filter', '').strip(), 'limit': int(f.get('limit') or 0), 'merge': bool(f.get('merge')),
              'use_description': bool(f.get('use_description')), 'method': f.get('method', 'auto'),
              'render': f.get('render', 'auto'),
              'feed_url': f.get('feed_url', '').strip()}
    if not fields['feed_url']:
        fields['feed_kind'] = ''
    store.update(sid, **fields)
    if os.path.exists(os.path.join(store.site_dir(sid), 'products.json')):
        runner.rebuild_excel(sid)
    return redirect(url_for('site_page', sid=sid))


@app.post('/site/<sid>/mapping')
def save_mapping(sid):
    store.get(sid) or abort(404)
    mapping = {}
    for k, v in request.form.items():
        if k.startswith('map::') and v.strip():
            mapping[k[5:]] = v.strip()
    store.update(sid, mapping=mapping)
    runner.rebuild_excel(sid)
    return redirect(url_for('site_page', sid=sid) + '#mapping')


@app.post('/site/<sid>/delete')
def delete_site(sid):
    store.remove(sid)
    return redirect(url_for('index'))


@app.post('/run')
def run():
    ids = request.form.getlist('id') or [s['id'] for s in store.all_sites()]
    job = runner.start(ids, push=True)
    return jsonify(job.as_dict())


@app.get('/job')
def job_status():
    job = current_job()
    return jsonify(job.as_dict() if job else {})


@app.post('/sections/refresh')
def refresh_sections():
    runner.our_sections(refresh=True)
    return redirect(request.referrer or url_for('index'))


@app.get('/out/<path:path>')
def out_file(path):
    return send_from_directory(store.OUTPUT, path, as_attachment=path.endswith('.xlsx'))


if __name__ == '__main__':
    if not os.environ.get('NO_BROWSER'):
        Timer(1.2, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}')).start()
    app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)
