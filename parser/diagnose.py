"""Почему сайт не собирается. Парсер останавливается и пишет причину человеческим языком, вместо того чтобы молча вернуть пустой Excel."""
import re

import requests


class Stop(Exception):
    """Сбор остановлен: дальше пытаться бессмысленно. В args[0] причина для человека."""

    @property
    def reason(self):
        return self.args[0] if self.args else 'причина не определена'


BLOCK_MARKERS = [
    (r'BlockedRegion|blocked.?region|доступ.{0,20}(из вашей страны|из вашего региона)|not available in your (country|region)',
     'Сайт закрыт для посетителей из России: региональная блокировка. Нужен файл или фид от поставщика либо сбор с прокси нужной страны.'),
    (r'cf-chl|challenge-platform|Just a moment\.\.\.|Checking your browser|Attention Required! \| Cloudflare|cf-turnstile',
     'Сайт защищён Cloudflare: вместо страниц отдаётся проверка «вы не робот». Автоматический сбор невозможен, нужен файл или фид от поставщика.'),
    (r'(?s)(?:g-recaptcha|recaptcha|hcaptcha|smartcaptcha|captcha).{0,4000}(?:не робот|not a robot|are you human|verify you are|подтвердите|проверка безопасности)'
     r'|(?:не робот|not a robot|are you human).{0,4000}(?:captcha|recaptcha)',
     'Сайт требует пройти капчу («я не робот»). Автоматический сбор невозможен, нужен файл или фид от поставщика.'),
    (r'One moment, please|Please wait while your request is being verified|DDoS-Guard|ddos-guard',
     'Сайт включил защиту от ботов (проверка перед открытием страницы). Автоматический сбор блокируется.'),
]


def access_problem(fx, url):
    """Причина, по которой сайт нельзя открыть, или None, если открывается."""
    html = fx.get(url, quiet=True, retries=1)
    body = html if html else (getattr(fx, 'last_headers', '') + '\n' + (fx.last_body or ''))
    for pat, reason in BLOCK_MARKERS:
        # защита видна по коду страницы, если на ней почти нет обычного текста
        if re.search(pat, body or '', re.I) and (not html or _text_len(html) < 700):
            return reason
    if html:
        return None
    st, exc = fx.last_status, fx.last_exc
    if st == 404:
        return f'Адрес не существует (ошибка 404): {url}. Проверьте ссылку.'
    if st in (401, 403):
        return f'Сайт запрещает доступ (ошибка {st}). Скорее всего, сбор с этого сайта заблокирован.'
    if st == 429:
        return 'Сайт отвечает «слишком много запросов» (ошибка 429) и не пускает парсер. Попробуйте позже или запросите файл у поставщика.'
    if st and st >= 500:
        return f'На сайте ошибка сервера ({st}). Попробуйте позже.'
    if isinstance(exc, requests.exceptions.Timeout):
        return 'Сайт не отвечает: время ожидания истекло. Попробуйте позже.'
    if isinstance(exc, requests.exceptions.SSLError):
        return 'У сайта неисправный сертификат безопасности (https), соединение не устанавливается.'
    if isinstance(exc, requests.exceptions.ConnectionError):
        return 'Сайт не найден или не принимает соединения. Проверьте адрес.'
    return 'Сайт не открылся по неизвестной причине.'


def _text_len(html):
    t = re.sub(r'(?is)<(script|style|noscript)[^>]*>.*?</\1>', ' ', html or '')
    t = re.sub(r'<[^>]+>', ' ', t)
    return len(re.sub(r'\s+', ' ', t).strip())


def empty_reason(state, kw='', search='', is_search=False):
    """Причина, почему товары не собраны, по проверенным страницам (state['samples']: [(адрес, html, запись или None)])."""
    samples = state.get('samples') or []
    n_cands = state.get('candidates', 0)
    is_search = is_search or bool(search)
    if n_cands == 0:
        if is_search:
            return f'Поиск на сайте по «{search or kw}» не дал ссылок на товары: либо таких товаров нет, либо результаты поиска строятся скриптом.'
        return 'На сайте не найдено ссылок на карточки товаров: ни в карте сайта, ни на главной, ни в меню каталога.'
    htmls = ' '.join(h for _, h, _ in samples if h)
    if re.search(r'<iframe[^>]+(3d|viewer|visore|sketchfab|360|configurator)', htmls, re.I):
        return ('Фото товаров показаны в 3D-просмотрщике во встроенном окне, обычных фото на страницах нет. '
                'Скопировать фото невозможно: возьмите их у дилера или запросите у поставщика.')
    named = [it for _, _, it in samples if it and it.get('name')]
    if named and not any(it.get('images') for it in named):
        return ('Карточки товаров находятся, но фото на них нет: сайт подгружает фото особым способом, их не видно даже в браузере. '
                'Возьмите фото у дилера или у поставщика.')
    if re.search(r'href="[^"]+\.pdf"', htmls, re.I) and not named:
        return 'Отдельных карточек товаров на сайте нет: каталог выложен в PDF. Нужен файл или фид от поставщика.'
    if samples and all(_text_len(h) < 400 for _, h, _ in samples if h):
        return 'Страницы сайта строятся скриптом и почти пустые даже в браузере. Сбор со страниц невозможен, нужен фид или файл.'
    if kw and named:
        return f'Карточки на сайте есть, но ни одна не подходит под отбор «{kw}». Проверьте слово отбора.'
    if is_search:
        return (f'Поиск на сайте по «{search or kw}» выдаёт не карточки товаров (статьи, разделы или страницы без названия, цены и фото). '
                'Вставьте адрес раздела каталога с нужными товарами.')
    return ('На проверенных страницах не нашлось карточек товаров: нет названия, цены или фото товара. '
            'Если товары на сайте есть, вставьте адрес раздела каталога вместо главной.')


def warnings_for(models):
    """Замечания к собранному: чего не хватает у всех товаров."""
    vs = [v for m in models for v in m['variants']]
    out = []
    if vs and not any(v.get('price') for v in vs):
        out.append('цен на сайте нет (возможно, это каталог производителя): возьмите цены из прайса поставщика')
    if vs and not any(v.get('local_images') for v in vs):
        out.append('фото не скачались ни для одного товара')
    if models and not any(m.get('category') for m in models):
        out.append('раздел товара на сайте не указан')
    return out
