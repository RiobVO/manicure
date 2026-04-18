"""
Бизнес-операции бронирования.

Тонкая прослойка над db/*: агрегирует запросы, считает деривативные значения,
валидирует состояние. Не знает про Telegram.
"""
from dataclasses import dataclass
from typing import Any

from db import (
    get_all_settings,
    get_booked_times,
    get_day_schedule,
    get_day_schedule_for_master,
    get_master,
    get_time_blocks,
    get_time_blocks_for_master,
)
from utils.slots import generate_free_slots


# ─── Цены ───────────────────────────────────────────────────────────────────

def calculate_total_price(
    base_price: int,
    selected_addon_ids: list[int] | set[int],
    all_addons: list[dict[str, Any]],
) -> int:
    """
    Итоговая цена услуги с выбранными аддонами.

    all_addons — полный список аддонов услуги (из get_addons_for_service),
    selected_addon_ids — подмножество выбранных пользователем.
    """
    selected = set(selected_addon_ids)
    return base_price + sum(a["price"] for a in all_addons if a["id"] in selected)


def addon_names_for(
    selected_addon_ids: list[int] | set[int],
    all_addons: list[dict[str, Any]],
) -> list[str]:
    """Названия выбранных аддонов в порядке их появления в all_addons."""
    selected = set(selected_addon_ids)
    return [a["name"] for a in all_addons if a["id"] in selected]


# ─── Мастера ────────────────────────────────────────────────────────────────

async def resolve_active_master(master_id: int | None) -> dict[str, Any] | None:
    """
    Возвращает активного мастера по id или None, если мастер удалён/деактивирован.
    master_id=None → None (вызывающий сам решает что делать).
    """
    if master_id is None:
        return None
    master = await get_master(master_id)
    if not master or not master.get("is_active"):
        return None
    return master


# ─── Контекст дня для генерации слотов ──────────────────────────────────────

@dataclass(frozen=True)
class DayContext:
    """
    Всё, что нужно для построения свободных слотов на дату: рабочие часы,
    блокировки и шаг сетки. is_day_off=True означает, что работать нельзя
    (work_start/work_end/blocked_ranges невалидны).
    """
    is_day_off: bool
    work_start: int
    work_end: int
    blocked_ranges: list[tuple[str, str]]
    slot_step: int


async def fetch_day_context(master_id: int | None, date_str: str) -> DayContext:
    """
    Собирает расписание + блокировки + slot_step в один объект.
    master_id=None — глобальный график (без мастеров или legacy-режим).
    """
    if master_id is not None:
        day_schedule = await get_day_schedule_for_master(master_id, date_str)
        blocked_ranges = await get_time_blocks_for_master(master_id, date_str)
    else:
        day_schedule = await get_day_schedule(date_str)
        blocked_ranges = await get_time_blocks(date_str)

    slot_step = int((await get_all_settings()).get("slot_step", 30))

    if day_schedule is None:
        return DayContext(
            is_day_off=True,
            work_start=0, work_end=0,
            blocked_ranges=[],
            slot_step=slot_step,
        )

    work_start, work_end = day_schedule
    return DayContext(
        is_day_off=False,
        work_start=work_start,
        work_end=work_end,
        blocked_ranges=blocked_ranges,
        slot_step=slot_step,
    )


async def compute_free_slots(
    master_id: int | None,
    date_str: str,
    duration: int,
) -> tuple[DayContext, list[str]]:
    """
    Удобный агрегат: получить контекст дня и уже готовый список слотов.
    Если день выходной — slots будет пустым, is_day_off=True.
    """
    ctx = await fetch_day_context(master_id, date_str)
    if ctx.is_day_off:
        return ctx, []

    booked = await get_booked_times(date_str, master_id)
    slots = generate_free_slots(
        booked, duration, date_str,
        ctx.work_start, ctx.work_end, ctx.slot_step,
        ctx.blocked_ranges,
    )
    return ctx, slots
