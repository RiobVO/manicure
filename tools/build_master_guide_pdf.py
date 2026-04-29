"""Сборка PDF-инструкции для мастера салона.

Источник текста — docs/MASTER_GUIDE.md, но содержимое здесь хардкодом
адаптировано под печать A4: укрупнённые шапки, упрощённые блоки кода,
без bash-разметки, без MD-таблиц.

Запуск:
    python tools/build_master_guide_pdf.py

Результат: docs/MASTER_GUIDE.pdf
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "MASTER_GUIDE.pdf"

# Кириллические шрифты с Windows. Если этого скрипта вызывают на Linux/Mac —
# нужно подменить пути или поставить пакет fonts-dejavu-core (как в Dockerfile).
FONT_REGULAR = Path("C:/Windows/Fonts/arial.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")
FONT_MONO = Path("C:/Windows/Fonts/consola.ttf")


def _register_fonts() -> None:
    """Регистрируем кириллические TTF-шрифты в reportlab.
    Дефолтные Helvetica/Times — без кириллицы, на печати будут пустые рамки."""
    if not FONT_REGULAR.exists():
        logger.error("Не найден шрифт %s. Поставь arial.ttf / dejavu-sans.", FONT_REGULAR)
        sys.exit(1)
    pdfmetrics.registerFont(TTFont("Body", str(FONT_REGULAR)))
    pdfmetrics.registerFont(TTFont("Body-Bold", str(FONT_BOLD)))
    if FONT_MONO.exists():
        pdfmetrics.registerFont(TTFont("Mono", str(FONT_MONO)))


def _make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "Title": ParagraphStyle(
            "Title", parent=base, fontName="Body-Bold", fontSize=22,
            leading=26, spaceAfter=6, textColor=colors.HexColor("#1a1a1a"),
        ),
        "Subtitle": ParagraphStyle(
            "Subtitle", parent=base, fontName="Body", fontSize=11,
            leading=14, spaceAfter=18, textColor=colors.HexColor("#666666"),
        ),
        "H1": ParagraphStyle(
            "H1", parent=base, fontName="Body-Bold", fontSize=16,
            leading=20, spaceBefore=18, spaceAfter=8,
            textColor=colors.HexColor("#1a1a1a"),
        ),
        "H2": ParagraphStyle(
            "H2", parent=base, fontName="Body-Bold", fontSize=12,
            leading=15, spaceBefore=12, spaceAfter=4,
            textColor=colors.HexColor("#333333"),
        ),
        "Body": ParagraphStyle(
            "Body", parent=base, fontName="Body", fontSize=10.5,
            leading=15, spaceAfter=6, textColor=colors.HexColor("#222222"),
        ),
        "Bullet": ParagraphStyle(
            "Bullet", parent=base, fontName="Body", fontSize=10.5,
            leading=15, spaceAfter=4, leftIndent=14, bulletIndent=2,
            textColor=colors.HexColor("#222222"),
        ),
        "Code": ParagraphStyle(
            "Code", parent=base,
            fontName="Mono" if FONT_MONO.exists() else "Body",
            fontSize=9.5, leading=13, spaceAfter=6,
            leftIndent=10, rightIndent=10, backColor=colors.HexColor("#f4f4f4"),
            borderPadding=6, textColor=colors.HexColor("#222222"),
        ),
        "Note": ParagraphStyle(
            "Note", parent=base, fontName="Body", fontSize=10,
            leading=14, spaceAfter=8, leftIndent=10, rightIndent=10,
            borderPadding=8, backColor=colors.HexColor("#fff8e0"),
            textColor=colors.HexColor("#444444"),
        ),
        "Footer": ParagraphStyle(
            "Footer", parent=base, fontName="Body", fontSize=9,
            leading=12, alignment=1, textColor=colors.HexColor("#888888"),
        ),
    }


def _bullet(text: str, styles: dict) -> Paragraph:
    return Paragraph(f"•&nbsp;&nbsp;{text}", styles["Bullet"])


def _build_story(styles: dict) -> list:
    s = styles
    story: list = []

    # ---------- Шапка ----------
    story.append(Paragraph("Инструкция мастера", s["Title"]))
    story.append(Paragraph(
        "Бот для записи клиентов — твой кабинет. Прочитай один раз, держи под рукой.",
        s["Subtitle"],
    ))

    # ---------- Подключение ----------
    story.append(Paragraph("1. Как подключиться", s["H1"]))
    story.append(Paragraph(
        "<b>Один раз</b> в самом начале — администратор привяжет тебя к боту:",
        s["Body"],
    ))
    story.append(_bullet(
        "Открой в Telegram бота <b>@userinfobot</b>, напиши ему любое слово — он "
        "пришлёт твой числовой Telegram ID (например, <i>123456789</i>).", s,
    ))
    story.append(_bullet(
        "Перешли этот ID администратору салона.", s,
    ))
    story.append(_bullet(
        "После того как администратор привяжет тебя — открой бота салона и нажми "
        "<b>/start</b>. Увидишь приветствие <i>«Кабинет мастера»</i> и три кнопки внизу.",
        s,
    ))
    story.append(Paragraph(
        "<b>Если после /start видишь «Выбери услугу» как обычный клиент</b> — значит "
        "привязка ещё не сработала. Напиши администратору.",
        s["Note"],
    ))

    # ---------- Что видишь ----------
    story.append(Paragraph("2. Что у тебя на экране", s["H1"]))
    story.append(Paragraph(
        "Внизу — постоянная клавиатура с тремя кнопками. Они открывают одно и "
        "то же «живое» сообщение, которое обновляется при каждом нажатии. "
        "Старые сообщения бот сам прибирает — чат не захламляется.",
        s["Body"],
    ))

    btn_table = Table(
        [[
            Paragraph("<b>📋 Сегодня</b><br/>записи на сегодня", s["Body"]),
            Paragraph("<b>📅 Мои записи</b><br/>ближайшие, до 30 шт.", s["Body"]),
            Paragraph("<b>📆 Моё расписание</b><br/>часы и отгулы", s["Body"]),
        ]],
        colWidths=[5.6 * cm, 5.6 * cm, 5.6 * cm],
    )
    btn_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fafafa")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(btn_table)
    story.append(Spacer(1, 8))

    # ---------- Сегодня ----------
    story.append(Paragraph("3. 📋 Сегодня — твой рабочий день", s["H1"]))
    story.append(Paragraph(
        "Все записи на сегодня: ожидающие (🕐), выполненные (✅), не пришёл (🚫). "
        "Отменённые сюда не попадают.",
        s["Body"],
    ))
    story.append(Paragraph("Каждая запись кликабельна — открывается карточка:", s["Body"]))
    story.append(Paragraph(
        "📋 Запись #42<br/>"
        "🕐 14:30 · 20 апреля, пн<br/>"
        "👤 Айгуль Назарова<br/>"
        "📞 +998 90 123-45-67<br/>"
        "💅 маникюр с гель-лаком (1ч 30м)<br/>"
        "📌 🕐 Ожидает",
        s["Code"],
    ))

    story.append(Paragraph("Что можно сделать с записью:", s["H2"]))
    story.append(_bullet(
        "<b>✅ Выполнено</b> — клиент пришёл, всё сделали.", s,
    ))
    story.append(_bullet(
        "<b>🚫 Не пришёл</b> — клиент не явился. Запись не пропадает: можно "
        "позже перенести или отменить.", s,
    ))
    story.append(_bullet(
        "<b>❌ Отменить</b> — запись аннулируется, клиент получает сообщение "
        "«мастер отменил запись».", s,
    ))
    story.append(_bullet(
        "<b>↔ Перенести</b> — открывается календарь на 7 дней вперёд, потом "
        "свободные слоты. Клиент получает уведомление автоматически.", s,
    ))
    story.append(Paragraph(
        "<b>Финальные статусы (✅/❌) кнопок больше не показывают.</b> "
        "Если ошибся — попроси администратора, он вернёт обратно через свою панель.",
        s["Note"],
    ))

    # ---------- Мои записи ----------
    story.append(Paragraph("4. 📅 Мои записи — что впереди", s["H1"]))
    story.append(Paragraph(
        "Ближайшие ожидающие записи — сегодня и вперёд, до 30 штук, "
        "сгруппированы по датам:",
        s["Body"],
    ))
    story.append(Paragraph(
        "📅 Твои ближайшие записи<br/><br/>"
        "—— 20 апреля, пн ——<br/>"
        "🕐 14:30 — Айгуль · маникюр с гель-лаком<br/><br/>"
        "—— 21 апреля, вт ——<br/>"
        "🕐 10:00 — Мадина · педикюр<br/>"
        "🕐 12:30 — Зухра · маникюр",
        s["Code"],
    ))
    story.append(Paragraph(
        "Клик на запись → та же карточка, те же действия, что в «📋 Сегодня».",
        s["Body"],
    ))

    story.append(PageBreak())

    # ---------- Расписание ----------
    story.append(Paragraph("5. 📆 Моё расписание", s["H1"]))
    story.append(Paragraph("Недельные часы работы (меняет администратор):", s["H2"]))
    story.append(Paragraph(
        "📆 Твоё расписание<br/><br/>"
        "Понедельник&nbsp;&nbsp;&nbsp;09:00 – 19:00<br/>"
        "Вторник&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;10:00 – 18:00<br/>"
        "Среда&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;— выходной<br/>"
        "Четверг&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;09:00 – 19:00<br/>"
        "Пятница&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;09:00 – 19:00<br/>"
        "Суббота&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;10:00 – 16:00<br/>"
        "Воскресенье&nbsp;— выходной",
        s["Code"],
    ))
    story.append(Paragraph(
        "<b>Часы меняет только администратор.</b> Это намеренно — иначе можно "
        "случайно создать рассинхрон с записями клиентов.",
        s["Body"],
    ))

    story.append(Paragraph("Отгулы — это ты делаешь сам:", s["H2"]))
    story.append(_bullet(
        "<b>🌙 Поставить отгул</b> — открывается календарь на 14 дней вперёд, "
        "выбираешь день. Если на этот день нет твоих записей — отгул сохраняется, "
        "администратор получает уведомление. Если записи есть — бот покажет сколько "
        "и попросит сначала их перенести через администратора.", s,
    ))
    story.append(_bullet(
        "<b>☀ Убрать отгул</b> — список будущих отгулов, выбираешь какой снять. "
        "Администратор получает уведомление.", s,
    ))
    story.append(Paragraph(
        "<b>Повторно поставить отгул на ту же дату не получится</b> — бот скажет "
        "«на эту дату уже стоит отгул».",
        s["Note"],
    ))

    # ---------- Что приходит само ----------
    story.append(Paragraph("6. Что приходит от бота само", s["H1"]))
    story.append(_bullet(
        "<b>Новая запись</b> — push-уведомление, как только клиент подтвердил бронь "
        "на тебя. Кнопка <i>«✅ Принято»</i> — убрать уведомление из чата.", s,
    ))
    story.append(_bullet(
        "<b>Перенос администратором</b> — сообщение «админ перенёс запись X с "
        "старой даты/времени на новую». Запись в твоих списках обновится сама.", s,
    ))
    story.append(_bullet(
        "<b>Отмена администратором</b> — push с записью, которую отменил админ.", s,
    ))
    story.append(Paragraph(
        "<b>Напоминания за 24 часа и 2 часа приходят клиентам, не тебе.</b> "
        "У тебя есть «📋 Сегодня» — это и есть твоё напоминание.",
        s["Note"],
    ))

    # ---------- Сценарии ----------
    story.append(Paragraph("7. Типовые ситуации", s["H1"]))

    story.append(Paragraph("Клиент не пришёл к назначенному времени.", s["H2"]))
    story.append(Paragraph(
        "Открой <b>«📋 Сегодня»</b> → клик на запись → <b>🚫 Не пришёл</b>. "
        "Если он позвонил и попросил перенести — на той же карточке "
        "<b>↔ Перенести</b> и выбери новую дату/время.",
        s["Body"],
    ))

    story.append(Paragraph("Хочу выходной на следующий четверг.", s["H2"]))
    story.append(Paragraph(
        "<b>«📆 Моё расписание»</b> → <b>🌙 Поставить отгул</b> → выбери дату. "
        "Если на этот день есть записи — бот покажет сколько, попроси "
        "администратора их перенести, потом возвращайся и ставь отгул повторно.",
        s["Body"],
    ))

    story.append(Paragraph("Клиент позвонил, хочет перенести запись на завтра.", s["H2"]))
    story.append(Paragraph(
        "<b>«📅 Мои записи»</b> → найди запись → клик → <b>↔ Перенести</b> → "
        "выбери дату → выбери свободный слот. Клиент получит уведомление "
        "автоматически.",
        s["Body"],
    ))

    story.append(Paragraph("Я по ошибке нажал «✅ Выполнено», а клиент ещё не пришёл.", s["H2"]))
    story.append(Paragraph(
        "Эту запись сам уже не вернёшь в <b>🕐 Ожидает</b> — напиши "
        "администратору, он сделает это через свою панель.",
        s["Body"],
    ))

    story.append(Paragraph("Я не вижу новой записи, хотя клиент говорит что записался.", s["H2"]))
    story.append(Paragraph(
        "Проверь <b>«📋 Сегодня»</b> — возможно запись на другой день, смотри "
        "<b>«📅 Мои записи»</b>. Если всё равно не находишь — попроси "
        "администратора проверить, на какого мастера записался клиент. Бывает, "
        "что клиент случайно выбрал другого мастера.",
        s["Body"],
    ))

    # ---------- Памятка ----------
    story.append(Paragraph("8. Короткая памятка", s["H1"]))
    cheatsheet = Table(
        [
            ["Что хочу сделать", "Куда нажимаю"],
            ["Посмотреть кто сегодня", "📋 Сегодня"],
            ["Посмотреть на завтра / послезавтра", "📅 Мои записи"],
            ["Отметить «клиент пришёл»", "📋 Сегодня → запись → ✅ Выполнено"],
            ["Отметить «не пришёл»", "📋 Сегодня → запись → 🚫 Не пришёл"],
            ["Перенести запись клиента", "запись → ↔ Перенести"],
            ["Поставить выходной", "📆 Моё расписание → 🌙 Поставить отгул"],
            ["Убрать выходной", "📆 Моё расписание → ☀ Убрать отгул"],
            ["Поменять часы работы по дням", "попроси администратора"],
            ["Вернуть случайно проставленный статус", "попроси администратора"],
        ],
        colWidths=[8.5 * cm, 8.5 * cm],
    )
    cheatsheet.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Body-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 1), (-1, -1), "Body"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f7f7f7")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dddddd")),
    ]))
    story.append(cheatsheet)
    story.append(Spacer(1, 18))

    # ---------- Footer ----------
    story.append(Paragraph(
        "Возникли вопросы — пиши администратору салона. "
        "Бот не отвечает — администратор разберётся.",
        s["Footer"],
    ))

    return story


def main() -> None:
    _register_fonts()
    styles = _make_styles()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title="Инструкция мастера",
        author="Manicure Bot",
    )
    story = _build_story(styles)
    doc.build(story)

    size_kb = OUTPUT.stat().st_size / 1024
    logger.info("PDF собран: %s (%.1f КБ)", OUTPUT, size_kb)


if __name__ == "__main__":
    main()
