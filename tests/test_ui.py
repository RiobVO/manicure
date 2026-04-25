"""Тесты UI-форматтеров (utils.ui)."""
from utils.ui import (
    price,
    duration,
    date_soft,
    date_tiny,
    days_ago_phrase,
    rating_line,
    greeting_new,
    greeting_returning,
    STATUS_MARK,
    FLOWER,
)


def test_price_formats_thousands_separator():
    s = price(250000)
    assert "250" in s
    assert "сум" in s


def test_duration_under_hour():
    assert duration(45) == "45 мин"


def test_duration_exact_hour():
    assert duration(60) == "1 ч"


def test_duration_mixed():
    assert duration(90) == "1 ч 30 мин"


def test_date_soft_format():
    # 2026-04-18 — суббота
    assert date_soft("2026-04-18") == "суббота, 18 апреля"


def test_date_tiny_format():
    # 2026-04-18 — суббота. Формат '<день> <мес> · <день_недели>'
    # month_short = MONTHS_RU[3][:3] = 'апр' (MONTHS_RU = ['января','февраля','марта','апреля',...])
    assert date_tiny("2026-04-18") == "18 апр · сб"


def test_days_ago_phrase_today():
    assert days_ago_phrase(0) == "сегодня"


def test_days_ago_phrase_yesterday():
    assert days_ago_phrase(1) == "вчера"


def test_days_ago_phrase_days():
    assert days_ago_phrase(3) == "прошло 3 дня"


def test_days_ago_phrase_weeks():
    # 14 дней → 2 недели
    assert days_ago_phrase(14) == "прошло 2 недели"


def test_greeting_new_contains_accent():
    # После UI-рефактора в B-стиль greeting начинается с 💅 и названия салона.
    s = greeting_new()
    assert "💅" in s
    assert "nail studio demo" in s.lower()


def test_greeting_returning_has_name_and_master():
    s = greeting_returning(
        name="Анна", days_ago=3,
        service="маникюр классический", master="ольга",
    )
    assert "Анна" in s
    # .title() — как делает функция
    assert "Ольга" in s


def test_rating_line_empty_when_no_reviews():
    assert rating_line(0, 0) == ""
    assert rating_line(None, 0) == ""
    assert rating_line(4.5, 0) == ""


def test_status_marks_set():
    assert STATUS_MARK["completed"] == "✓"
    assert STATUS_MARK["scheduled"] == "●"
    assert STATUS_MARK["cancelled"] == "✕"
    assert STATUS_MARK["no_show"] == "—"
