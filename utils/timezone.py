"""Работа с таймзонами проекта."""
from zoneinfo import ZoneInfo
from datetime import datetime, date

from config import TIMEZONE

_tz = ZoneInfo(TIMEZONE)


def now_local() -> datetime:
    """Текущее время в локальной таймзоне проекта."""
    return datetime.now(_tz)


def today_local() -> date:
    """Текущая дата в локальной таймзоне проекта."""
    return now_local().date()


def get_tz() -> ZoneInfo:
    """Возвращает объект таймзоны проекта."""
    return _tz
