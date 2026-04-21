"""
Генерация QR-картинок для печати на ресепшене (Phase 2 v.4).

Требование из спеки: A5, читается с ~1 метра на трёх разных телефонах.
Достигается error_correction=H (30% избыточности) + box_size=10 и рамкой
из салонного названия и подписи под QR.

Возвращаем PNG-bytes через BytesIO — хендлер оборачивает в BufferedInputFile
без записи на диск.
"""
from __future__ import annotations

from io import BytesIO

# Цвета: высокий контраст под плохое освещение кафе/салона.
_FG = (17, 17, 17)
_BG = (255, 255, 255)

# Высота подписей под QR (в пикселях). Итоговая картинка — QR + top_label + bottom_label.
_LABEL_TOP_H = 70
_LABEL_BOTTOM_H = 90
_PADDING = 40


def _load_font(size: int):
    """
    Пробуем DejaVu (есть в python:slim docker-образе), откатываемся на default.
    Default ImageFont у Pillow очень мелкий — поэтому DejaVu желателен,
    но не блокер.
    """
    from PIL import ImageFont
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def generate_qr(url: str, salon_name: str, bottom_caption: str = "отсканируй — запишись") -> bytes:
    """
    Отрисовать QR + два текста (сверху salon_name, снизу инструкция).

    Args:
        url: полный deep-link, который закодируется (t.me/<bot>?start=<code>).
        salon_name: заголовок над QR (обычно название салона).
        bottom_caption: инструкция под QR. По умолчанию — как в спеке.

    Returns:
        PNG в bytes. Вызывающий оборачивает в BufferedInputFile.
    """
    # Lazy-импорт: qrcode/PIL — внешние зависимости, нужны только на
    # рендеринге. Модуль должен грузиться даже когда пакет не установлен
    # (например в тестовом .venv без pip install). Админ увидит понятную
    # ошибку только при нажатии «QR», бот не падает.
    import qrcode
    from PIL import Image, ImageDraw
    from qrcode.constants import ERROR_CORRECT_H

    qr = qrcode.QRCode(
        version=None,  # auto: выбирает минимальную версию под длину url
        error_correction=ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=_FG, back_color=_BG).convert("RGB")
    qr_w, qr_h = qr_img.size

    # Итоговый холст: вертикальный sandwich с подписями.
    canvas_w = qr_w + _PADDING * 2
    canvas_h = _LABEL_TOP_H + qr_h + _LABEL_BOTTOM_H + _PADDING * 2
    canvas = Image.new("RGB", (canvas_w, canvas_h), _BG)

    # Вклеиваем QR по центру.
    qr_x = (canvas_w - qr_w) // 2
    qr_y = _PADDING + _LABEL_TOP_H
    canvas.paste(qr_img, (qr_x, qr_y))

    draw = ImageDraw.Draw(canvas)
    font_top = _load_font(36)
    font_bottom = _load_font(24)

    _draw_centered_text(draw, salon_name, font_top, canvas_w, _PADDING + 10)
    _draw_centered_text(
        draw, bottom_caption, font_bottom, canvas_w,
        qr_y + qr_h + 20,
    )

    buf = BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _draw_centered_text(
    draw,
    text: str,
    font,
    canvas_w: int,
    y: int,
) -> None:
    """Отрисовать текст по центру по горизонтали на заданной строке."""
    try:
        # Pillow ≥9: textbbox возвращает (x0, y0, x1, y1).
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
    except AttributeError:
        # Старый Pillow fallback.
        text_w, _ = draw.textsize(text, font=font)  # type: ignore[attr-defined]
    draw.text(((canvas_w - text_w) // 2, y), text, font=font, fill=_FG)
