// Сайт парсера на GitHub Pages. Данные читаются из репозитория (data/, output/), сбор запускается задачей GitHub Actions.
(function () {
  'use strict';
  var host = location.hostname;
  var OWNER = /\.github\.io$/.test(host) ? host.split('.')[0] : 'takedown-desing';
  var REPO = /\.github\.io$/.test(host) ? (location.pathname.split('/')[1] || 'ruchki-parser') : 'ruchki-parser';
  var API = 'https://api.github.com/repos/' + OWNER + '/' + REPO;
  var WF = 'collect.yml';
  var app = document.getElementById('app');
  var state = { sites: [], token: '', user: '' };
  document.getElementById('repo-link').href = 'https://github.com/' + OWNER + '/' + REPO;

  try { state.token = localStorage.getItem('gh_token') || ''; state.user = localStorage.getItem('gh_user') || ''; } catch (e) {}

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmtPrice(v, cur) { if (!v) return '<span class="muted">цена не указана</span>'; var rub = !cur || /^(RUB|RUR)$/i.test(cur); return Math.round(v).toLocaleString('ru-RU') + ' ' + (rub ? '₽' : esc(cur)); }
  function out(p) { return 'output/' + p.split('/').map(encodeURIComponent).join('/'); }
  function getJSON(path) { return fetch(path + (path.indexOf('?') < 0 ? '?' : '&') + 't=' + Date.now()).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }
  function gh(path, opts) {
    opts = opts || {};
    var headers = { 'Accept': 'application/vnd.github+json' };
    if (state.token) headers.Authorization = 'Bearer ' + state.token;
    if (opts.body) headers['Content-Type'] = 'application/json';
    return fetch(path.indexOf('http') === 0 ? path : API + path, { method: opts.method || 'GET', headers: headers, body: opts.body ? JSON.stringify(opts.body) : undefined })
      .then(function (r) { if (r.status === 204) return {}; return r.json().then(function (j) { if (!r.ok) { var e = new Error(j.message || r.status); e.status = r.status; throw e; } return j; }); });
  }

  // ---------- вход
  function renderAuth() {
    var el = document.getElementById('auth');
    el.innerHTML = state.token ? (esc(state.user || 'вход выполнен') + ' · <button type="button" id="logout">выйти</button>') : '<button type="button" id="login-btn">Войти, чтобы собирать</button>';
    var b = document.getElementById(state.token ? 'logout' : 'login-btn');
    b.onclick = state.token ? function () { try { localStorage.removeItem('gh_token'); localStorage.removeItem('gh_user'); } catch (e) {} state.token = ''; state.user = ''; renderAuth(); route(); } : openLogin;
  }
  function openLogin() {
    var d = document.getElementById('login'); document.getElementById('login-err').textContent = ''; d.showModal();
    return new Promise(function (resolve) { d.onclose = function () { resolve(d.returnValue === 'ok' && state.token); }; });
  }
  document.getElementById('login-form').addEventListener('submit', function (e) {
    if (e.submitter && e.submitter.value === 'cancel') return;
    e.preventDefault();
    var t = document.getElementById('token').value.trim(); var err = document.getElementById('login-err');
    if (!t) { err.textContent = 'Вставьте ключ'; return; }
    err.textContent = 'Проверяю ключ…';
    state.token = t;
    gh('/actions/workflows/' + WF).then(function () { return gh('https://api.github.com/user').catch(function () { return {}; }); }).then(function (u) {
      state.user = u.login || 'вход выполнен';
      try { localStorage.setItem('gh_token', t); localStorage.setItem('gh_user', state.user); } catch (x) {}
      renderAuth(); document.getElementById('login').close('ok'); route();
    }).catch(function (x) { state.token = ''; err.textContent = 'Ключ не подошёл: ' + x.message + '. Проверьте доступ к репозиторию и право Actions: Read and write.'; });
  });
  function needLogin() { return state.token ? Promise.resolve(true) : openLogin(); }

  // ---------- запуск сбора
  var watching = null;
  function dispatch(inputs, title) {
    return needLogin().then(function (ok) {
      if (!ok) return;
      var since = Date.now() - 15000;
      showJob(title, 'отправляю задание…', []);
      return gh('/actions/workflows/' + WF + '/dispatches', { method: 'POST', body: { ref: 'main', inputs: inputs } }).then(function () {
        findRun(since, 0, title);
      }).catch(function (e) { showJob(title, 'не запустилось: ' + e.message, [], true); });
    });
  }
  function findRun(since, tries, title) {
    gh('/actions/workflows/' + WF + '/runs?per_page=5&event=workflow_dispatch').then(function (j) {
      var run = (j.workflow_runs || []).filter(function (r) { return new Date(r.created_at).getTime() >= since; })[0];
      if (run) { watchRun(run.id, title); return; }
      if (tries < 20) setTimeout(function () { findRun(since, tries + 1, title); }, 3000);
      else showJob(title, 'задание отправлено, но не видно в списке запусков', [], true);
    }).catch(function () { setTimeout(function () { findRun(since, tries + 1, title); }, 4000); });
  }
  function watchRun(id, title) {
    clearTimeout(watching);
    document.getElementById('job-link').href = 'https://github.com/' + OWNER + '/' + REPO + '/actions/runs/' + id;
    var before = JSON.stringify(state.sites.map(function (s) { return [s.id, (s.last_run || {}).when]; }));
    (function tick() {
      Promise.all([gh('/actions/runs/' + id), gh('/actions/runs/' + id + '/jobs').catch(function () { return {}; })]).then(function (res) {
        var run = res[0], jobs = (res[1].jobs || [])[0] || {};
        var steps = (jobs.steps || []).filter(function (s) { return !/^(Set up job|Post |Complete job|Run actions\/)/.test(s.name); }).map(function (s) {
          var mark = s.status === 'completed' ? (s.conclusion === 'success' ? '✓' : '✗') : (s.status === 'in_progress' ? '…' : '·');
          return mark + ' ' + s.name;
        });
        var label = { queued: 'в очереди', in_progress: 'идёт сбор', completed: 'готово' }[run.status] || run.status;
        if (run.status !== 'completed') { showJob(title, label, steps); watching = setTimeout(tick, 5000); return; }
        if (run.conclusion !== 'success') { showJob(title, 'завершилось с ошибкой, откройте журнал', steps, true); return; }
        showJob(title, 'готово, жду публикации результатов…', steps);
        waitData(before, 0);
      }).catch(function () { watching = setTimeout(tick, 8000); });
    })();
  }
  function waitData(before, tries) {
    getJSON('data/sites.json').then(function (sites) {
      var now = JSON.stringify(sites.map(function (s) { return [s.id, (s.last_run || {}).when]; }));
      if (now !== before || tries > 40) {
        state.sites = sites;
        return getJSON('data/task.json').catch(function () { return {}; }).then(function (t) {
          showJob('Сбор', 'готово', (t.log || []).slice(-60), false, true); route();
        });
      }
      setTimeout(function () { waitData(before, tries + 1); }, 6000);
    }).catch(function () { setTimeout(function () { waitData(before, tries + 1); }, 6000); });
  }
  function showJob(title, progress, lines, isErr, done) {
    var box = document.getElementById('job'); box.hidden = false;
    document.getElementById('job-title').textContent = title;
    document.getElementById('job-progress').textContent = progress;
    document.getElementById('job-progress').style.color = isErr ? '#ff9a8a' : '';
    var log = document.getElementById('job-log'); log.textContent = (lines || []).join('\n'); log.scrollTop = log.scrollHeight;
    document.querySelectorAll('[data-run],[data-run-all],[data-add]').forEach(function (b) { b.disabled = !done && !isErr; });
  }
  document.getElementById('job-close').onclick = function () { document.getElementById('job').hidden = true; clearTimeout(watching); };

  // ---------- экраны
  function statusCell(s) {
    var lr = s.last_run || {};
    if (lr.stopped) return '<span class="tag err">не собирается</span><div class="small reason">' + esc(lr.problem) + '</div>';
    if (lr.error) return '<span class="tag err">ошибка</span><div class="small reason">' + esc(lr.error) + '</div>';
    if (lr.how) return '<span class="tag ' + (/^фид/.test(lr.how) ? 'feed' : 'pages') + '">' + esc(lr.how) + '</span>';
    return '<span class="tag">ещё не собирали</span>';
  }
  function changesCell(c) {
    if (!c) return '—';
    var o = '';
    if (c.new) o += '<span class="new">+' + c.new + ' новых</span>';
    if (c.price) o += '<span class="price">цена: ' + c.price + '</span>';
    if (c.stock) o += '<span class="stock">наличие: ' + c.stock + '</span>';
    if (c.gone) o += '<span class="gone">−' + c.gone + ' пропало</span>';
    return o || '<span class="muted">без изменений</span>';
  }
  function renderIndex() {
    var rows = state.sites.map(function (s) {
      var lr = s.last_run || {};
      var counts = lr.models != null ? (lr.models + ' / ' + lr.variants + '<div class="small muted">фото ' + lr.images + (lr.no_price ? ', без цены ' + lr.no_price : '') + '</div>' +
        (lr.warnings && lr.warnings.length ? '<div class="small warn-text" title="' + esc(lr.warnings.join('; ')) + '">есть замечания</div>' : '')) : '—';
      return '<tr><td><a href="#/site/' + esc(s.id) + '"><b>' + esc(s.name) + '</b></a><div class="url">' + esc(s.url) + '</div>' +
        ((s.brand || s.filter) ? '<div class="small muted">' + (s.brand ? 'бренд: ' + esc(s.brand) : '') + (s.filter ? ' · отбор: «' + esc(s.filter) + '»' : '') + '</div>' : '') + '</td>' +
        '<td>' + statusCell(s) + '</td><td class="small">' + (lr.when ? esc(lr.when) + '<div class="muted">' + (s.limit ? 'проба: до ' + s.limit + ' тов.' : 'все товары') + '</div>' : '—') + '</td>' +
        '<td class="num">' + counts + '</td><td class="chg small">' + changesCell(lr.changes) + '</td>' +
        '<td><div class="actions"><button class="btn btn-sm btn-accent" type="button" data-run="' + esc(s.id) + '">Собрать</button>' +
        (lr.models != null ? '<a class="btn btn-sm" href="' + out(s.id + '/products.xlsx') + '">Excel</a>' : '') + '</div></td></tr>';
    }).join('');
    app.innerHTML =
      '<div class="head"><div><h1>Источники товаров</h1><div class="muted small">Вставьте адрес сайта, раздела или поиска и нажмите «Добавить и собрать». Парсер сначала ищет фид товаров, а если его нет, собирает товары со страниц. Сбор идёт на серверах GitHub, обычно 2–5 минут.</div></div>' +
      '<div class="actions"><a class="btn" href="' + out('все-товары.xlsx') + '">Скачать все товары, Excel</a>' + (state.sites.length ? '<button class="btn btn-accent" type="button" data-run-all>Собрать все</button>' : '') + '</div></div>' +
      (state.token ? '' : '<div class="note">Смотреть результаты и скачивать Excel можно без входа. Чтобы запускать сбор, нажмите «Войти, чтобы собирать» вверху справа.</div>') +
      '<section class="card"><h2>Добавить источник</h2><form class="grid" id="add-form">' +
      '<div class="wide"><label class="fl" for="f-url">Адрес *</label><input type="url" id="f-url" required placeholder="https://site.ru/  или страница бренда, раздела, поиска, или прямая ссылка на фид">' +
      '<div class="hint">Главная страница: парсер ищет фид, затем идёт по карте сайта. Страница раздела или поиска: берутся товары из этого списка. Ссылка на фид (yml, xml): читается сразу.</div></div>' +
      '<div><label class="fl" for="f-name">Название</label><input type="text" id="f-name" placeholder="например, TUPAI: свой магазин"></div>' +
      '<div><label class="fl" for="f-brand">Бренд для всех товаров</label><input type="text" id="f-brand" placeholder="если не указан на сайте"></div>' +
      '<div><label class="fl" for="f-filter">Отбор по слову</label><input type="text" id="f-filter" placeholder="например, FIMET"></div>' +
      '<div><label class="fl" for="f-limit">Сколько товаров</label><input type="number" id="f-limit" value="3" min="0"><div class="hint">0 = все</div></div>' +
      '<div class="wide actions" style="justify-content:flex-end"><button class="btn btn-accent" data-add>Добавить и собрать</button></div></form></section>' +
      '<section class="card" style="padding:0">' + (rows ? '<table class="tbl"><thead><tr><th>Источник</th><th>Как собирается</th><th>Последний сбор</th><th class="num">Моделей / покрытий</th><th>Изменения</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>' : '<div class="empty">Источников пока нет.</div>') + '</section>' +
      '<p class="small muted">Excel готов к загрузке в админке ручкидлядверей.рф: «Excel / CSV: загрузка и выгрузка». Колонки «Источник: …» служебные, сайт их пропускает.</p>';
    document.getElementById('add-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var v = function (id) { return document.getElementById(id).value.trim(); };
      dispatch({ action: 'add', url: v('f-url'), name: v('f-name'), brand: v('f-brand'), filter: v('f-filter'), limit: v('f-limit') || '3' }, 'Новый источник');
    });
  }
  function renderSite(id) {
    var s = state.sites.filter(function (x) { return x.id === id; })[0];
    if (!s) { app.innerHTML = '<div class="empty">Источник не найден. <a href="#/">К списку</a></div>'; return; }
    var lr = s.last_run || {};
    app.innerHTML = '<div class="empty">Загружаю товары…</div>';
    Promise.all([getJSON(out(id + '/products.json')).catch(function () { return {}; }), getJSON(out(id + '/history.json')).catch(function () { return []; })]).then(function (res) {
      var data = res[0], hist = res[1], models = data.models || [];
      var top = '<div class="head"><div><div class="small"><a href="#/">← Источники</a></div><h1>' + esc(s.name) + '</h1><div class="url"><a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc(s.url) + '</a></div></div>' +
        '<div class="actions">' + (models.length ? '<a class="btn" href="' + out(id + '/products.xlsx') + '">Скачать Excel</a><a class="btn" href="' + out(id + '/changes.xlsx') + '">Изменения, Excel</a>' : '') +
        '<button class="btn btn-accent" type="button" data-run="' + esc(id) + '">Собрать сейчас</button></div></div>';
      var banner = '';
      if (lr.stopped) banner = '<div class="card stop"><b>Сбор остановлен.</b> ' + esc(lr.problem) + '<div class="small muted" style="margin-top:6px">Проверено ' + esc(lr.when) + '. Можно добавить другой адрес этого сайта, например страницу раздела или фид.</div></div>';
      else if (lr.when) {
        if (lr.warnings && lr.warnings.length) banner += '<div class="card warn"><b>Замечания:</b> ' + esc(lr.warnings.join('; ')) + '.</div>';
        banner += '<div class="stats"><div class="stat"><b>' + lr.models + '</b><span>моделей</span></div><div class="stat"><b>' + lr.variants + '</b><span>покрытий (строк Excel)</span></div>' +
          '<div class="stat"><b>' + lr.images + '</b><span>фото сохранено</span></div><div class="stat"><b>' + lr.no_price + '</b><span>без цены</span></div>' +
          '<div class="stat"><b>' + lr.no_photo + '</b><span>без фото</span></div><div class="stat"><b style="font-size:15px">' + esc(lr.how) + '</b><span>' + esc(lr.when) + ', ' + lr.seconds + ' с</span></div></div>';
      }
      var settings = '<section class="card"><h2>Настройки</h2><div class="small">' +
        'Бренд для всех товаров: <b>' + esc(s.brand || '—') + '</b> · Отбор по слову: <b>' + esc(s.filter || '—') + '</b> · Сколько товаров: <b>' + (s.limit || 'все') + '</b>' +
        (s.feed_url ? '<br>Фид: <a href="' + esc(s.feed_url) + '" target="_blank" rel="noopener">' + esc(s.feed_url) + '</a>' : '') + '</div>' +
        '<div class="actions" style="margin-top:12px"><button class="btn btn-sm btn-danger" type="button" id="remove">Убрать источник</button></div></section>';
      var histHtml = hist.length ? '<section class="card"><h2>История сборов</h2><table class="tbl"><thead><tr><th>Когда</th><th>Как</th><th class="num">Моделей</th><th class="num">Покрытий</th><th>Изменения</th></tr></thead><tbody>' +
        hist.slice(0, 10).map(function (h) { return '<tr><td class="small">' + esc(h.when) + '</td><td class="small">' + (h.stopped ? '<span class="tag err">остановлен</span> ' + esc(h.problem) : esc(h.how)) + '</td><td class="num">' + (h.models != null ? h.models : '—') + '</td><td class="num">' + (h.variants != null ? h.variants : '—') + '</td><td class="chg small">' + (h.changes ? changesCell(h.changes) : '') + '</td></tr>'; }).join('') +
        '</tbody></table></section>' : '';
      var prods = '<section class="card"><h2>Товары' + (models.length ? ' · ' + models.length : '') + '</h2>' + (models.length ? '' : '<p class="muted">Товаров нет.</p>') + models.map(function (m) {
        var imgs = []; m.variants.forEach(function (v) { (v.local_images || []).forEach(function (i) { imgs.push(i); }); });
        var main = imgs[0];
        return '<div class="prod">' + (main ? '<img src="' + out(id + '/images/' + main) + '" alt="" loading="lazy">' : '<div class="noimg">нет фото</div>') + '<div><h3>' + esc(m.name) + '</h3>' +
          '<div class="small muted">' + (m.brand ? esc(m.brand) + ' · ' : '') + (m.sku ? 'арт. ' + esc(m.sku) + ' · ' : '') + esc((m.category || []).join(' › ') || 'раздел не определён') + '</div>' +
          '<table class="vars">' + m.variants.map(function (v) {
            return '<tr><td>' + esc(v.finish || '—') + '</td><td class="muted">' + esc(v.sku) + '</td><td>' + fmtPrice(v.price, v.currency) + '</td><td class="small">' + (v.in_stock == null ? '<span class="muted">наличие ?</span>' : (v.in_stock ? 'в наличии' : 'под заказ')) + '</td><td class="small"><a href="' + esc(v.url) + '" target="_blank" rel="noopener">источник ↗</a></td></tr>';
          }).join('') + '</table>' +
          (imgs.length > 1 ? '<div class="thumbs">' + imgs.slice(0, 12).map(function (i) { return '<a href="' + out(id + '/images/' + i) + '" target="_blank"><img src="' + out(id + '/images/' + i) + '" alt="" loading="lazy"></a>'; }).join('') + '</div>' : '') +
          ((Object.keys(m.specs || {}).length || m.description) ? '<details><summary>характеристики и описание</summary>' +
            (Object.keys(m.specs || {}).length ? '<div class="specs">' + Object.keys(m.specs).map(function (k) { return '<div><b>' + esc(k) + ':</b> ' + esc(m.specs[k]) + '</div>'; }).join('') + '</div>' : '') +
            (m.description ? '<p class="small">' + esc(m.description.slice(0, 1200)) + '</p>' : '') + '</details>' : '') + '</div></div>';
      }).join('') + '</section>';
      app.innerHTML = top + banner + settings + histHtml + prods;
      document.getElementById('remove').onclick = function () { if (confirm('Убрать источник «' + s.name + '» из списка?')) dispatch({ action: 'remove', site_id: id }, 'Убираю источник'); };
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-run]');
    if (b) { var s = state.sites.filter(function (x) { return x.id === b.dataset.run; })[0]; dispatch({ action: 'run', site_id: b.dataset.run }, 'Сбор: ' + (s ? s.name : b.dataset.run)); return; }
    if (e.target.closest('[data-run-all]') && confirm('Собрать все источники? Это займёт заметное время.')) dispatch({ action: 'run' }, 'Сбор всех источников');
  });

  function route() {
    var m = location.hash.match(/^#\/site\/(.+)$/);
    if (m) renderSite(decodeURIComponent(m[1])); else renderIndex();
  }
  window.addEventListener('hashchange', route);
  renderAuth();
  getJSON('data/sites.json').then(function (sites) { state.sites = sites; route(); }).catch(function () { state.sites = []; route(); });
  // если на этом устройстве уже идёт сбор — показать его ход
  if (state.token) gh('/actions/workflows/' + WF + '/runs?per_page=1').then(function (j) {
    var r = (j.workflow_runs || [])[0]; if (r && r.status !== 'completed') watchRun(r.id, 'Идёт сбор');
  }).catch(function () {});
})();
