"""Безопасный парсинг callback data."""
import logging

logger = logging.getLogger(__name__)


def parse_callback(data: str | None, prefix: str, expected_parts: int) -> tuple | None:
    """Безопасный парсинг callback data.

    Убирает prefix_ из начала, разбивает остаток по '_', проверяет количество частей.
    Возвращает tuple частей или None если формат не совпал.

    Пример: parse_callback("service_15", "service", 1) → ("15",)
    Пример: parse_callback("appt_status_3_completed", "appt_status", 2) → ("3", "completed")
    Пример: parse_callback("cal_day_2025_04_15", "cal_day", 3) → ("2025", "04", "15")
    """
    if data is None:
        return None

    full_prefix = f"{prefix}_"
    if not data.startswith(full_prefix):
        return None

    remainder = data[len(full_prefix):]
    # maxsplit чтобы последняя часть захватывала всё (напр. "no_show" не разбивалось)
    parts = remainder.split("_", expected_parts - 1) if expected_parts > 1 else [remainder]

    if len(parts) != expected_parts:
        return None

    return tuple(parts)
