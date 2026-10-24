"""Единая запись товара (одно покрытие одной модели) и помощники для текста, цен и цветов."""
import html as htmllib
import re

FIELDS = ['url', 'name', 'brand', 'sku', 'finish', 'price', 'currency', 'in_stock', 'category',
          'description', 'specs', 'images', 'group', 'source']


def new_item(source):
    return {'url': '', 'name': '', 'brand': '', 'sku': '', 'finish': '', 'price': None, 'currency': 'RUB',
            'in_stock': None, 'category': [], 'description': '', 'specs': {}, 'images': [], 'group': '', 'source': source}


def clean_text(s, html=False):
    """Текст без тегов, лишних пробелов и html-сущностей."""
    if s is None:
        return ''
    s = str(s)
    if html or '<' in s:
        s = re.sub(r'(?i)<br\s*/?>|</p>|</li>|</h\d>', '\n', s)
        s = re.sub(r'<[^>]+>', ' ', s)
    s = htmllib.unescape(s).replace('\xa0', ' ')
    if re.search(r'â€|Ã[\x80-\xbf]|Ð[\x80-\xbf]', s):
        # текст в UTF-8, прочитанный как latin-1/cp1252: «â€“» → «–»
        for enc in ('cp1252', 'latin-1'):
            try:
                s = s.encode(enc).decode('utf-8'); break
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
    s = re.sub(r'[ \t\r\f\v]+', ' ', s)
    s = re.sub(r'\s*\n\s*', '\n', s)
    return s.strip()


def to_price(v):
    """Число из строки цены: «5 490 руб.», «5490.00 RUB», «от 1 200 ₽». None, если цены нет."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = str(v).replace('\xa0', ' ')
    m = re.search(r'\d[\d\s]*(?:[.,]\d{1,2})?', s)
    if not m:
        return None
    num = m.group(0).replace(' ', '').replace(',', '.')
    try:
        val = float(num)
    except ValueError:
        return None
    return val if val > 0 else None


# названия покрытий: по ним из названия товара выделяется цвет и «модель без цвета»
COLOR_PHRASES = [
    'матовый чёрный', 'матовый черный', 'чёрный матовый', 'черный матовый', 'полированный хром', 'матовый хром', 'хром матовый',
    'хром полированный', 'сатинированный хром', 'хром сатин', 'матовое золото', 'золото матовое', 'полированное золото',
    'матовый никель', 'никель матовый', 'сатинированный никель', 'никель сатин', 'античная бронза', 'бронза античная',
    'античная латунь', 'латунь античная', 'полированная латунь', 'матовая латунь', 'натуральная латунь', 'матовый графит',
    'графит матовый', 'белый матовый', 'матовый белый', 'чёрный', 'черный', 'хром', 'никель', 'бронза', 'латунь', 'золото',
    'графит', 'медь', 'серебро', 'белый', 'шампань', 'титан', 'нержавеющая сталь', 'сталь',
    'matt black', 'black', 'polished chrome', 'satin chrome', 'chrome', 'satin nickel', 'nickel', 'brass', 'bronze', 'gold',
    'graphite', 'copper', 'white', 'antique brass', 'satin brass']
_COLOR_RE = re.compile(r'(?i)(?:,\s*|\s+)(?:цвет[а-я]*\s*[:\-]?\s*|покрытие\s*[:\-]?\s*)?(' +
                       '|'.join(sorted((re.escape(c) for c in COLOR_PHRASES), key=len, reverse=True)) + r')(?:\s+pvd)?\s*$')
_COLOR_WORD_RE = re.compile(r'(?i)\s*(?:,\s*)?\bцвет[а-я]*\b\s*[:\-]?\s*(.+)$')


def split_color(name):
    """«Ручка X на розетке цвет бронза» → («Ручка X на розетке», «бронза»). Если цвета не видно, цвет пустой."""
    n = (name or '').strip()
    m = _COLOR_WORD_RE.search(n)
    if m and len(m.group(1)) <= 40:
        return n[:m.start()].rstrip(' ,-–'), m.group(1).strip(' .,')
    m = _COLOR_RE.search(n)
    if m:
        return n[:m.start()].rstrip(' ,-–'), m.group(1).strip()
    return n, ''


def slug(s, maxlen=80):
    tr = dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',
                  ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't', 'u', 'f',
                   'h', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'yu', 'ya']))
    s = ''.join(tr.get(c, c) for c in (s or '').lower())
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    return s[:maxlen].rstrip('-') or 'item'
