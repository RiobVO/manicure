"""Валидаторы пользовательского ввода."""
from datetime import time


def validate_time(text: str) -> time | None:
    """Парсит строку HH:MM в объект time.

    Возвращает None если формат невалидный (часы 0-23, минуты 0-59).
    """
    if not text or ":" not in text:
        return None

    parts = text.strip().split(":")
    if len(parts) != 2:
        return None

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        return None

    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None

    return time(hours, minutes)
