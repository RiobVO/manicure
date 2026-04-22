import logging

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from db import save_review, get_review_by_appointment, get_user_lang, get_appointment_by_id
from keyboards.inline import review_comment_keyboard
from states import ReviewStates
from utils.callbacks import parse_callback
from utils.i18n import t

logger = logging.getLogger(__name__)
router = Router()

_RATING_LABEL = {1: "😞", 2: "😐", 3: "🙂", 4: "😊", 5: "🤩"}


async def _can_review(appt_id: int, user_id: int) -> bool:
    """
    Ownership + state guard: отзыв разрешён только автору записи и только
    на завершённый визит. Без этого любой мог перебрать AUTOINCREMENT id
    и поставить 1 звезду чужому мастеру (IDOR) — аудит от 2026-04-22.
    """
    appt = await get_appointment_by_id(appt_id)
    if not appt:
        return False
    if appt.get("user_id") != user_id:
        logger.warning(
            "review ownership violation: user=%s попытался отзыв на чужую appt=%s (владелец user=%s)",
            user_id, appt_id, appt.get("user_id"),
        )
        return False
    if appt.get("status") != "completed":
        logger.warning(
            "review на незавершённую запись: user=%s appt=%s status=%s",
            user_id, appt_id, appt.get("status"),
        )
        return False
    return True


@router.callback_query(F.data.regexp(r"^rev_rate_(\d+)_([1-5])$"))
async def cb_review_rating(callback: CallbackQuery, state: FSMContext):
    """Клиент выбрал рейтинг — сохраняем, предлагаем комментарий."""
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "rev_rate", 2)
    if not parts:
        logger.warning("Некорректный callback: %s", callback.data)
        await callback.answer()
        return
    appt_id = int(parts[0])
    rating = int(parts[1])

    if not await _can_review(appt_id, callback.from_user.id):
        denied = "Fikr qoldirib bo'lmaydi." if lang == "uz" else "Отзыв недоступен."
        await callback.answer(denied, show_alert=True)
        return

    existing = await get_review_by_appointment(appt_id)
    if existing:
        already = "Fikr allaqachon saqlangan, rahmat!" if lang == "uz" else "Отзыв уже сохранён, спасибо!"
        await callback.answer(already, show_alert=False)
        return

    await save_review(appt_id, callback.from_user.id, rating)

    emoji = _RATING_LABEL.get(rating, "⭐")
    if lang == "uz":
        head = f"{emoji} Baho {rating}/5 — rahmat!\n\n{t('review_comment_prompt', lang)}"
    else:
        head = f"{emoji} Оценка {rating}/5 — спасибо!\n\n{t('review_comment_prompt', lang)}"
    try:
        await callback.message.edit_text(
            head,
            reply_markup=review_comment_keyboard(appt_id, lang),
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        pass
    await callback.answer()


def _rebook_kb(appt_id: int, lang: str) -> InlineKeyboardMarkup:
    label = "🔁 Qayta yozilish" if lang == "uz" else "🔁 Записаться снова"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=f"quick_rebook_{appt_id}"),
    ]])


@router.callback_query(F.data.regexp(r"^rev_skip_(\d+)$"))
async def cb_review_skip(callback: CallbackQuery, state: FSMContext):
    """Клиент пропустил комментарий."""
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "rev_skip", 1)
    if not parts:
        await callback.answer()
        return
    appt_id = int(parts[0])
    await state.clear()
    thanks = "Fikr uchun rahmat! 🙏" if lang == "uz" else "Спасибо за отзыв! 🙏"
    try:
        await callback.message.edit_text(thanks, reply_markup=_rebook_kb(appt_id, lang))
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.callback_query(F.data.regexp(r"^rev_comment_(\d+)$"))
async def cb_review_comment(callback: CallbackQuery, state: FSMContext):
    """Клиент хочет написать комментарий — переходим в FSM."""
    lang = await get_user_lang(callback.from_user.id)
    parts = parse_callback(callback.data, "rev_comment", 1)
    if not parts:
        await callback.answer()
        return
    appt_id = int(parts[0])
    if not await _can_review(appt_id, callback.from_user.id):
        denied = "Fikr qoldirib bo'lmaydi." if lang == "uz" else "Отзыв недоступен."
        await callback.answer(denied, show_alert=True)
        return
    await state.set_state(ReviewStates.enter_comment)
    await state.update_data(review_appt_id=appt_id)
    prompt = "Fikringizni yozing:" if lang == "uz" else "Напишите ваш комментарий:"
    try:
        await callback.message.edit_text(prompt)
    except TelegramBadRequest:
        pass
    await callback.answer()


@router.message(ReviewStates.enter_comment)
async def review_comment_text(message: Message, state: FSMContext):
    """Клиент ввёл текст комментария."""
    lang = await get_user_lang(message.from_user.id)
    data = await state.get_data()
    appt_id = data.get("review_appt_id")
    comment = message.text.strip() if message.text else ""

    # Defence-in-depth: state мог быть поставлен до нашего ownership-guard
    # (например, старая версия бота). Проверяем ещё раз перед записью.
    if appt_id and comment and await _can_review(appt_id, message.from_user.id):
        existing = await get_review_by_appointment(appt_id)
        if existing:
            await save_review(appt_id, message.from_user.id, existing["rating"], comment)

    await state.clear()
    thanks = "Fikr uchun rahmat! 🙏" if lang == "uz" else "Спасибо за отзыв! 🙏"
    await message.answer(
        thanks,
        reply_markup=_rebook_kb(appt_id, lang) if appt_id else None,
    )
