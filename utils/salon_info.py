"""
Данные о салоне (контакт, будущие общесалонные поля) — хранятся
в таблице settings, редактируются админом.
"""
from __future__ import annotations

from db.settings import get_setting


async def get_salon_contact() -> str | None:
    """
    Контакт салона (@handle / телефон / ссылка). None если не задан.
    Редактируется админом в ⚙ Настройках → «Контакт для клиентов».
    """
    v = await get_setting("salon_contact", "")
    v = (v or "").strip()
    return v or None


async def refund_contact_line() -> str:
    """
    Строка-подсказка клиенту, куда обращаться по вопросу возврата.
    Если контакт задан — показываем его. Если нет — нейтральный текст,
    чтобы не давать ложных обещаний.
    """
    contact = await get_salon_contact()
    if contact:
        return f"📞 по вопросу возврата оплаты — {contact}"
    return "📞 свяжись с салоном по вопросу возврата оплаты"
