import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from db import save_review, get_review_by_appointment
from keyboards.inline import review_comment_keyboard
from states import ReviewStates
from utils.callbacks import parse_callback

logger = logging.getLogger(__name__)
router = Router()

_RATING_LABEL = {1: "😞", 2: "😐", 3: "🙂", 4: "😊", 5: "🤩"}


@router.callback_query(F.data.regexp(r"^rev_rate_(\d+)_([1-5])$"))
async def cb_review_rating(callback: CallbackQuery, state: FSMContext):
    """Клиент выбрал рейтинг — сохраняем, предлагаем комментарий."""
    parts = parse_callback(callback.data, "rev_rate", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    rating = int(parts[1])

    # Проверяем, не оставлен ли уже отзыв (двойной тап)
    existing = await get_review_by_appointment(appt_id)
    if existing:
        await callback.answer("Отзыв уже сохранён, спасибо!", show_alert=False)
        return

    await save_review(appt_id, callback.from_user.id, rating)

    emoji = _RATING_LABEL.get(rating, "⭐")
    try:
        await callback.message.edit_text(
            f"{emoji} Оценка {rating}/5 — спасибо!\n\nХотите добавить комментарий?",
            reply_markup=review_comment_keyboard(appt_id),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.regexp(r"^rev_skip_(\d+)$"))
async def cb_review_skip(callback: CallbackQuery, state: FSMContext):
    """Клиент пропустил комментарий."""
    parts = parse_callback(callback.data, "rev_skip", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    await state.clear()
    try:
        await callback.message.edit_text(
            "Спасибо за отзыв! 🙏",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🔁 Записаться снова",
                    callback_data=f"quick_rebook_{appt_id}",
                ),
            ]]),
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.regexp(r"^rev_comment_(\d+)$"))
async def cb_review_comment(callback: CallbackQuery, state: FSMContext):
    """Клиент хочет написать комментарий — переходим в FSM."""
    parts = parse_callback(callback.data, "rev_comment", 1)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    await state.set_state(ReviewStates.enter_comment)
    await state.update_data(review_appt_id=appt_id)
    try:
        await callback.message.edit_text("Напишите ваш комментарий:")
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.message(ReviewStates.enter_comment)
async def review_comment_text(message: Message, state: FSMContext):
    """Клиент ввёл текст комментария."""
    data = await state.get_data()
    appt_id = data.get("review_appt_id")
    comment = message.text.strip() if message.text else ""

    if appt_id and comment:
        existing = await get_review_by_appointment(appt_id)
        if existing:
            await save_review(appt_id, message.from_user.id, existing["rating"], comment)

    await state.clear()
    await message.answer(
        "Спасибо за отзыв! 🙏",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text="🔁 Записаться снова",
                callback_data=f"quick_rebook_{appt_id}",
            ),
        ]]) if appt_id else None,
    )
