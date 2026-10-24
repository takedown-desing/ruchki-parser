#!/bin/bash
# Двойной щелчок в Finder: ставит всё нужное при первом запуске и открывает админку парсера в браузере.
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Нужен Python 3: установите с https://www.python.org/downloads/ и запустите снова."; read -r; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Первый запуск: готовлю окружение, это займёт минуту…"
  python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt || { echo "Не удалось установить библиотеки"; read -r; exit 1; }
fi
git pull -q 2>/dev/null
echo "Админка парсера: http://127.0.0.1:8765  (окно не закрывайте, пока работаете)"
.venv/bin/python app.py
