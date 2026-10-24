"""Сохранение результатов в репозиторий: коммит данных и отправка в GitHub после каждого сбора."""
import subprocess

from .store import ROOT


def _git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=600)


def save(message, log=print):
    _git('add', 'data', 'output')
    if not _git('diff', '--cached', '--quiet').returncode:
        log('В репозитории без изменений')
        return False
    r = _git('commit', '-m', message)
    if r.returncode:
        log('Коммит не удался: ' + (r.stderr or r.stdout).strip()[:300])
        return False
    log('Сохранено в репозиторий')
    if not _git('remote').stdout.strip():
        log('Удалённого репозитория нет, отправка в GitHub пропущена')
        return True
    _git('pull', '--rebase', '--autostash', '-q')
    p = _git('push', '-q')
    log('Отправлено в GitHub' if p.returncode == 0 else 'Отправить в GitHub не удалось: ' + p.stderr.strip()[:300])
    return p.returncode == 0


def status():
    last = _git('log', '-1', '--format=%h %ad %s', '--date=format:%d.%m %H:%M').stdout.strip()
    remote = _git('remote', 'get-url', 'origin').stdout.strip()
    return {'last_commit': last, 'remote': remote}
