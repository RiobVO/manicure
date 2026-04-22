"""
Пакет db — публичный API для работы с базой данных.

Все модули проекта импортируют функции из этого пакета:
    from db import get_services, init_db, ...
"""

# --- connection ---
from db.connection import get_db, close_db, init_db, _dict_rows, _dict_row, backup_db

# --- helpers ---
from db.helpers import _price_fmt

# --- appointments ---
from db.appointments import (
    get_booked_times,
    create_appointment,
    get_appointments_by_date_full,
    get_appointment_by_id,
    update_appointment_status,
    reschedule_appointment,
    get_appointments_by_phone,
    get_upcoming_appointments,
    get_client_appointments,
    cancel_appointment_by_client,
    get_all_future_appointments,
    get_stats,
    get_stats_by_master,
    get_appointments_for_export,
    get_user_appointments_page,
    get_user_appointments_full,
    count_user_appointments,
    save_appointment_addons,
)

# --- services ---
from db.services import (
    get_services,
    get_service_by_id,
    update_service_name,
    update_service_price,
    update_service_duration,
    update_service_description,
    toggle_service_active,
    delete_service,
    add_service,
    update_service_category,
    get_addons_for_service,
    get_addon_by_id,
    add_addon,
    delete_addon,
    toggle_addon_active,
    service_has_future_appointments,
)

# --- masters ---
from db.masters import (
    get_active_masters,
    get_all_masters,
    get_master,
    get_master_by_user_id,
    get_active_masters_with_user_id,
    get_master_appointments_today,
    get_master_appointments_upcoming,
    create_master,
    update_master,
    toggle_master_active,
    delete_master,
    seed_master_schedule,
    get_master_schedule,
    get_day_schedule_for_master,
    get_day_off_weekdays_for_master,
    update_master_weekday,
    get_time_blocks_for_master,
    add_master_day_off,
    delete_master_day_off,
    get_future_master_day_offs,
    count_master_scheduled_on_date,
)

# --- clients ---
from db.clients import (
    get_client_profile,
    save_client_profile,
    get_recent_clients,
    search_clients,
    get_dormant_clients,
    get_client_card,
    get_user_lang,
    set_user_lang,
)

# --- settings ---
from db.settings import (
    get_setting,
    set_setting,
    get_all_settings,
    get_weekly_schedule,
    get_day_schedule,
    update_weekday_schedule,
    is_day_off,
    get_time_blocks,
    get_future_blocks,
    add_day_off,
    add_time_block,
    delete_blocked_slot,
)

# --- reminders ---
from db.reminders import was_reminder_sent, mark_reminder_sent

# --- reviews ---
from db.reviews import save_review, get_review_by_appointment, get_reviews_stats, get_all_masters_ratings

# --- admin ---
from db.admin import (
    log_admin_action,
    get_admin_logs,
    add_admin,
    remove_admin,
    get_db_admins,
    is_db_admin,
)
