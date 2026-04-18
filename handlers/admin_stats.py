import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from utils.admin import is_admin_callback, deny_access, IsAdminFilter

from db import get_stats, get_reviews_stats, _price_fmt

logger = logging.getLogger(__name__)
router = Router()
router.message.filter(IsAdminFilter())
router.callback_query.filter(IsAdminFilter())


@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    stats = await get_stats()
    reviews = await get_reviews_stats()

    conversion_str = f"{stats['conversion']:.0f}%" if stats['conversion'] > 0 else "—"
    avg_check_str = f"{_price_fmt(int(stats['avg_check']))} сум" if stats['avg_check'] > 0 else "—"
    rating_str = f"{reviews['avg_rating']} ⭐ ({reviews['total']} отзывов)" if reviews['total'] > 0 else "—"

    text = (
        "📊 <b>Статистика</b>\n\n"
        f"📅 <b>Сегодня:</b> {stats['today_count']} записей\n"
        f"📆 <b>Эта неделя:</b> {stats['week_count']} записей\n"
        f"🗓 <b>Этот месяц:</b> {stats['month_count']} записей\n\n"
        f"💰 <b>Выручка:</b> {_price_fmt(stats['total_revenue'])} сум\n"
        f"🧾 <b>Средний чек:</b> {avg_check_str}\n"
        f"📈 <b>Конверсия (месяц):</b> {conversion_str}\n"
        f"🔄 <b>Возвраты клиентов:</b> {stats['returning_clients']}\n"
        f"⭐ <b>Рейтинг:</b> {rating_str}\n\n"
        f"✅ Выполнено: {stats['completed_count']}\n"
        f"❌ Отменено: {stats['cancelled_count']}\n"
        f"💅 Популярная: {stats['top_service_name']} ({stats['top_service_count']} визитов)"
    )

    export_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍🎨 По мастерам", callback_data="stats_by_master")],
        [InlineKeyboardButton(text="📥 Экспорт в Excel", callback_data="admin_export")],
    ])

    try:
        await callback.message.edit_text(text, reply_markup=export_kb, parse_mode="HTML")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data == "stats_by_master")
async def cb_stats_by_master(callback: CallbackQuery):
    if not is_admin_callback(callback):
        await deny_access(callback)
        return

    from db import get_stats_by_master, _price_fmt
    stats = await get_stats_by_master()

    if not stats:
        try:
            await callback.message.edit_text("Нет данных по мастерам.")
        except TelegramBadRequest:
            pass
        await callback.answer()
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
