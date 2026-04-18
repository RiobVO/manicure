"""
Генерация свободных слотов записи.

Чистая функция: получает занятые интервалы + диапазоны блокировок + рабочие
часы, возвращает список строк "HH:MM". Для сегодняшней даты учитывает
MIN_BOOKING_ADVANCE_HOURS (время на подготовку мастера).

Вынесено из handlers/client.py, чтобы логику можно было переиспользовать
и тестировать без зависимости от Telegram-слоя.
"""
from datetime import datetime, timedelta

from constants import MIN_BOOKING_ADVANCE_HOURS
from utils.timezone import now_local


def generate_free_slots(
    booked: list,
    duration: int,
    date_str: str,
    work_start: int,
    work_end: int,
    slot_step: int,
    blocked_ranges: list | None = None,
) -> list:
    slots = []
    current = datetime.strptime(f"{date_str} {work_start}:00", "%Y-%m-%d %H:%M")
    end_of_day = datetime.strptime(f"{date_str} {work_end}:00", "%Y-%m-%d %H:%M")

    now = now_local().replace(tzinfo=None)
    if date_str == now.strftime("%Y-%m-%d"):
        current = max(current, now + timedelta(hours=MIN_BOOKING_ADVANCE_HOURS))
        minutes = current.minute
        if minutes % slot_step != 0:
            current += timedelta(minutes=slot_step - (minutes % slot_step))
        current = current.replace(second=0, microsecond=0)

    while current + timedelta(minutes=duration) <= end_of_day:
        slot_start = current
        slot_end = current + timedelta(minutes=duration)
        is_free = True

        for booked_time, booked_duration in booked:
            b_start = datetime.strptime(f"{date_str} {booked_time}", "%Y-%m-%d %H:%M")
            b_end = b_start + timedelta(minutes=booked_duration)
            if not (slot_end <= b_start or slot_start >= b_end):
                is_free = False
                break

        if is_free and blocked_ranges:
            for bl_start_str, bl_end_str in blocked_ranges:
                bl_start = datetime.strptime(f"{date_str} {bl_start_str}", "%Y-%m-%d %H:%M")
                bl_end = datetime.strptime(f"{date_str} {bl_end_str}", "%Y-%m-%d %H:%M")
                if not (slot_end <= bl_start or slot_start >= bl_end):
                    is_free = False
                    break

        if is_free:
            slots.append(current.strftime("%H:%M"))

        current += timedelta(minutes=slot_step)

    return slots
