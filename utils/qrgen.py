"""
Генерация QR-картинок для печати на ресепшене (Phase 2 v.4).

Требование из спеки: A5, читается с ~1 метра на трёх разных телефонах.
Достигается error_correction=H (30% избыточности) + box_size=10.

Макет плаката:
    [salon_name — мелко, если задан]
    [source_label — крупно]
       ▓▓▓▓▓▓▓▓▓▓▓▓▓
       ▓    QR     ▓
       ▓▓▓▓▓▓▓▓▓▓▓▓▓
    [отсканируй — запишись]

Возвращаем PNG-bytes через BytesIO — хендлер оборачивает в BufferedInputFile
без записи на диск.
"""
from __future__ import annotations

from io import BytesIO

# Цвета: высокий контраст под плохое освещение кафе/салона.
_FG = (17, 17, 17)
_BG = (255, 255, 255)

# Макетные константы (в пикселях).
_PADDING = 40
_SALON_NAME_H = 40      # мелкая строка сверху (убирается если salon_name пуст)
_SOURCE_LABEL_H = 70    # крупная строка — label источника
_BOTTOM_CAPTION_H = 70  # «отсканируй — запишись»


def _load_font(size: int):
    """
    Пробуем DejaVu (добавлен в Dockerfile пакетом fonts-dejavu-core),
    откатываемся на default. Default ImageFont у Pillow — только
    латиница, кириллица рендерится квадратиками.
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


def generate_qr(
    url: str,
    source_label: str,
    salon_name: str | None = None,
    bottom_caption: str = "отсканируй — запишись",
) -> bytes:
    """
    Отрисовать QR-плакат.

    Args:
        url: deep-link для кодирования (t.me/<bot>?start=<code>).
        source_label: крупный заголовок над QR — label источника
            («Зеркало», «Instagram bio»). Печатается на плакате, чтобы
            владелец не запутался где какой QR висит.
        salon_name: мелкая строка над source_label. None → не рисуем.
        bottom_caption: инструкция под QR. По умолчанию — как в спеке.

    Returns:
        PNG в bytes. Вызывающий оборачивает в BufferedInputFile.
    """
    # Lazy-импорт: qrcode/PIL — внешние зависимости, нужны только на
    # рендеринге. Модуль должен грузиться даже когда пакет не установлен.
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

    show_salon = bool(salon_name and salon_name.strip())
    top_total_h = (_SALON_NAME_H if show_salon else 0) + _SOURCE_LABEL_H

    canvas_w = qr_w + _PADDING * 2
    canvas_h = _PADDING + top_total_h + qr_h + _BOTTOM_CAPTION_H + _PADDING
    canvas = Image.new("RGB", (canvas_w, canvas_h), _BG)

    # Вклеиваем QR по центру.
    qr_x = (canvas_w - qr_w) // 2
    qr_y = _PADDING + top_total_h
    canvas.paste(qr_img, (qr_x, qr_y))

    draw = ImageDraw.Draw(canvas)
    font_salon = _load_font(22)
    font_label = _load_font(44)
    font_caption = _load_font(26)

    y_cursor = _PADDING
    if show_salon:
        _draw_centered_text(draw, salon_name.strip(), font_salon, canvas_w, y_cursor)
        y_cursor += _SALON_NAME_H
    _draw_centered_text(draw, source_label, font_label, canvas_w, y_cursor + 5)

    _draw_centered_text(
        draw, bottom_caption, font_caption, canvas_w,
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
