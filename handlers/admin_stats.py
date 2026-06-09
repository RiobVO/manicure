"""
Экран «📊 Статистика» с дельтами к предыдущему периоду.

Что показываем:
  • Записи: выполнено (с трендом ↑/↓), отмены и no-show с цветовыми маркерами
    🟢/🟡/🔴 (правила в _color_for_rate).
  • Деньги: выручка и средний чек с трендом.
  • Клиенты: новые vs вернувшиеся.
  • Топ-3 мастера по выручке + рейтинг.
  • Хит периода — самая частая услуга.

Период переключается inline-кнопками [Неделя] [Месяц] [3 мес] внутри экрана.
Это НЕ глобальное inline-меню (от него отказались) — это локальный
переключатель внутри одного экрана, как уже сделано в admin_settings для
slot_step и в других местах. Кнопка [👨‍🎨 По мастерам] и [📥 Экспорт] —
без изменений.
"""
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import _price_fmt, get_reviews_stats
from db.stats import (
    DEFAULT_PERIOD, PERIOD_DAYS, PERIOD_LABEL,
    get_stats_with_trend,
)
from utils.admin import IsAdminFilter, deny_access, is_admin_callback

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


# ─── рендер ─────────────────────────────────────────────────────────────────

def _delta_arrow(cur: float, prev: float) -> str:
    """
    Стрелка с процентом: '↑ 12%', '↓ 3%' или '' (пусто) если изменение
    меньше 1% или предыдущий период пустой. Меньше 1% не показываем —
    шум, отвлекает.
    """
    if not prev or prev <= 0:
        return ""
    pct = (cur - prev) / prev * 100
    if abs(pct) < 1:
        return ""
    arrow = "↑" if pct > 0 else "↓"
    return f"  {arrow} {abs(pct):.0f}%"


def _color_for_rate(rate_pct: float, green_below: float, yellow_below: float) -> str:
    """
    Цветовой маркер по простым правилам:
      rate < green → 🟢
      rate < yellow → 🟡
      rate >= yellow → 🔴
    Используется для отмен и no-show — в обоих случаях «меньше = лучше».
    """
    if rate_pct < green_below:
        return "🟢"
    if rate_pct < yellow_below:
        return "🟡"
    return "🔴"


def _stats_keyboard(period: str) -> InlineKeyboardMarkup:
    """Клавиатура экрана статистики: переключатель периода + дополнительные
    разделы. Текущий период помечен галочкой, чтобы было видно с одного взгляда."""
    def _period_btn(p: str, label: str) -> InlineKeyboardButton:
        marker = " ✓" if p == period else ""
        return InlineKeyboardButton(
            text=f"{label}{marker}",
            callback_data=f"stats_period_{p}",
        )

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _period_btn("week", "Неделя"),
            _period_btn("month", "Месяц"),
            _period_btn("quarter", "3 мес"),
        ],
        [InlineKeyboardButton(text="👨‍🎨 По мастерам", callback_data="stats_by_master")],
        [InlineKeyboardButton(text="📥 Экспорт в Excel", callback_data="admin_export")],
    ])


def _render_stats_text(data: dict, reviews_total: int, reviews_avg: float) -> str:
    """
    Собирает HTML-текст экрана статистики. reviews_* приходят из общего
    get_reviews_stats — рейтинг считаем за всю жизнь, не за окно (отзыв
    оставляется после завершения, не привязывается к текущему периоду).
    """
    period = data["period"]
    label = PERIOD_LABEL[period]
    cur = data["current"]
    prev = data["previous"]

    completed = cur["completed"]
    cancelled = cur["cancelled"]
    no_show = cur["no_show"]
    total = cur["total"]
    revenue = cur["revenue"]
    avg_check = cur["avg_check"]

    cancel_rate = (cancelled / total * 100) if total else 0.0
    no_show_rate = (no_show / total * 100) if total else 0.0

    cancel_color = _color_for_rate(cancel_rate, 5, 10)
    no_show_color = _color_for_rate(no_show_rate, 3, 7)

    completed_d = _delta_arrow(completed, prev["completed"])
    revenue_d   = _delta_arrow(revenue, prev["revenue"])
    avg_d       = _delta_arrow(avg_check, prev["avg_check"])

    # Если в окне ничего не было — показываем мягкую заглушку, без сухих нулей.
    if total == 0:
        return (
            f"📊 <b>Статистика · {label}</b>\n\n"
            f"За этот период записей пока нет.\n"
            f"Попробуй другой период ниже или дождись первых клиентов."
        )

    lines: list[str] = []
    lines.append(f"📊 <b>Статистика · {label}</b>")
    lines.append("")

    # Записи
    lines.append("📈 <b>Записи</b>")
    lines.append(f"   ✅ Выполнено: <b>{completed}</b>{completed_d}")
    lines.append(f"   ❌ Отмен: {cancelled} ({cancel_rate:.0f}%)  {cancel_color}")
    lines.append(f"   💔 Не пришли: {no_show} ({no_show_rate:.0f}%)  {no_show_color}")
    lines.append("")

    # Деньги
    lines.append("💰 <b>Деньги</b>")
    lines.append(f"   Выручка: <b>{_price_fmt(revenue)}</b> сум{revenue_d}")
    if completed:
        lines.append(f"   Средний чек: {_price_fmt(int(avg_check))} сум{avg_d}")
    lines.append("")

    # Клиенты
    lines.append("👥 <b>Клиенты</b>")
    lines.append(
        f"   Новых: {data['new_clients']}   Вернулись: {data['returning_clients']}"
    )

    # Топ мастера
    if data["top_masters"]:
        lines.append("")
        lines.append("👨‍🎨 <b>Топ мастера</b>")
        for i, m in enumerate(data["top_masters"], 1):
            rating = m.get("avg_rating")
            rating_part = f" · ⭐ {rating}" if rating else ""
            lines.append(
                f"   {i}. {m['name']} — {_price_fmt(int(m['revenue']))} сум{rating_part}"
            )

    # Хит периода
    top = data.get("top_service")
    if top:
        lines.append("")
        lines.append(
            f"💅 <b>Хит периода:</b> {top['service_name']} · {top['cnt']} раз"
        )

    # Общий рейтинг (за всю жизнь, не за окно)
    if reviews_total:
        lines.append("")
        lines.append(
            f"⭐ <b>Общий рейтинг:</b> {reviews_avg} ({reviews_total} отзывов)"
        )

    return "\n".join(lines)


async def build_stats_payload(period: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """
    Собирает (текст, клавиатура) для экрана статистики. Используется и из
    callback (cb_admin_stats), и из reply-кнопки (msg_stats в admin.py).

    period None или невалидный → DEFAULT_PERIOD (month).
    """
    if period not in PERIOD_DAYS:
        period = DEFAULT_PERIOD
    data = await get_stats_with_trend(period)
    reviews = await get_reviews_stats()
    text = _render_stats_text(
        data,
        reviews_total=reviews.get("total", 0),
        reviews_avg=reviews.get("avg_rating", 0.0),
    )
    return text, _stats_keyboard(period)


# ─── handlers ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    """Открыть экран статистики (приходит с reply-«📊 Статистика» через msg_stats
    или с любой inline-кнопки 'admin_stats' в подэкранах). Период по умолчанию."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass

    text, kb = await build_stats_payload(DEFAULT_PERIOD)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        # Сообщение не редактируется (старое/удалено) — ack без edit.
        pass


@router.callback_query(F.data.startswith("stats_period_"))
async def cb_stats_period(callback: CallbackQuery):
    """Переключение периода: stats_period_week | stats_period_month | stats_period_quarter."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    try:
        # Подтверждаем нажатие до DB+TG-вызовов: иначе крутилка висит весь RTT.
        # Текст в alert НЕ показываем — данные уже на экране.
        await callback.answer()
    except TelegramBadRequest:
        pass
    period = callback.data.removeprefix("stats_period_")
    text, kb = await build_stats_payload(period)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "stats_by_master")
async def cb_stats_by_master(callback: CallbackQuery):
    """Раздел «По мастерам» — отдельный экран со сводкой по каждому. Период
    тут не учитывается, цифры за всю жизнь — это OK для quick overview."""
    if not is_admin_callback(callback):
        await deny_access(callback)
        return
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass

    from db import get_stats_by_master  # локальный импорт — функция не нужна выше
    stats = await get_stats_by_master()

    if not stats:
        try:
            await callback.message.edit_text("Нет данных по мастерам.")
        except TelegramBadRequest:
            pass
        return

    lines = ["📊 <b>Статистика по мастерам</b>\n"]
    for s in stats:
        rating_str = f"{s['avg_rating']} ⭐ ({s['reviews_count']})" if s["avg_rating"] else "—"
        lines.append(
            f"\n👨‍🎨 <b>{s['name']}</b>\n"
            f"   ✅ {s['completed']} выполнено · 🕐 {s['scheduled']} ожидает · ❌ {s['cancelled']} отмен\n"
            f"   💰 {_price_fmt(s['revenue'])} сум · ⭐ {rating_str}"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="← Общая статистика", callback_data="admin_stats"),
    ]])

    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()
