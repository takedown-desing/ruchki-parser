// Кнопки «Собрать», окно журнала сбора, обновление страницы после окончания.
(function () {
  var box = document.getElementById('job'), log = document.getElementById('job-log');
  var title = document.getElementById('job-title'), prog = document.getElementById('job-progress');
  var timer = null, wasRunning = false;

  function show(j) {
    if (!j || !j.id) return;
    box.hidden = false;
    var running = j.status === 'running' || j.status === 'queued';
    title.textContent = running ? 'Идёт сбор' : 'Сбор закончен';
    prog.textContent = (j.progress || '') + ' · ' + j.seconds + ' с';
    var atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
    log.textContent = (j.log || []).join('\n');
    if (atBottom) log.scrollTop = log.scrollHeight;
    document.querySelectorAll('[data-run],[data-run-all]').forEach(function (b) { b.disabled = running; });
    if (running) { wasRunning = true; schedule(); }
    else if (wasRunning) { wasRunning = false; setTimeout(function () { location.reload(); }, 1200); }
  }
  function poll() { fetch('/job').then(function (r) { return r.json(); }).then(show).catch(schedule); }
  function schedule() { clearTimeout(timer); timer = setTimeout(poll, 1500); }

  function run(ids) {
    var fd = new FormData(); ids.forEach(function (id) { fd.append('id', id); });
    fetch('/run', { method: 'POST', body: fd }).then(function (r) { return r.json(); }).then(function (j) { box.classList.remove('min'); show(j); });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-run]'); if (b) { run([b.dataset.run]); return; }
    if (e.target.closest('[data-run-all]')) run([]);
  });
  document.getElementById('job-toggle').addEventListener('click', function () {
    box.classList.toggle('min'); this.textContent = box.classList.contains('min') ? 'развернуть' : 'свернуть';
  });
  if (window.JOB && (window.JOB.status === 'running' || window.JOB.status === 'queued')) show(window.JOB);
})();
