"""Фото: скачать, проверить, привести к квадрату 800×800 на белом фоне (как на сайте) и сохранить в папку сайта."""
import hashlib
import io
import os

from PIL import Image

SIZE = 800
MIN_SIDE = 250


def save_image(fx, url, folder, base_name):
    """Путь к сохранённому файлу (относительно folder) или None, если картинка не скачалась или слишком мелкая."""
    raw = fx.get(url, binary=True, quiet=True)
    if not raw:
        return None
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        return None
    if min(im.size) < MIN_SIDE:
        return None
    if im.mode in ('RGBA', 'LA', 'P'):
        im = im.convert('RGBA')
        bg = Image.new('RGB', im.size, 'white')
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert('RGB')
    im.thumbnail((SIZE - 40, SIZE - 40), Image.LANCZOS) if max(im.size) > SIZE - 40 else None
    canvas = Image.new('RGB', (SIZE, SIZE), 'white')
    canvas.paste(im, ((SIZE - im.width) // 2, (SIZE - im.height) // 2))
    os.makedirs(folder, exist_ok=True)
    name = f'{base_name}-{hashlib.sha1(url.encode()).hexdigest()[:6]}.jpg'
    canvas.save(os.path.join(folder, name), 'JPEG', quality=84, optimize=True, progressive=True)
    return name
