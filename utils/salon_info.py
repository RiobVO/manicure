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


async def get_salon_name() -> str | None:
    """
    Название салона для QR-плакатов. None если не задано.
    Редактируется админом в ⚙ Настройках → «Название салона».
    """
    v = await get_setting("salon_name", "")
    v = (v or "").strip()
    return v or None


async def refund_contact_line(lang: str = "ru") -> str:
    """
    Строка-подсказка клиенту, куда обращаться по вопросу возврата.
    Если контакт задан — показываем его. Если нет — нейтральный текст.
    """
    from utils.i18n import t
    contact = await get_salon_contact()
    if contact:
        return t("refund_contact_known", lang, contact=contact)
    return t("refund_contact_unknown", lang)
