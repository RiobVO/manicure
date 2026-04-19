from aiogram.fsm.state import State, StatesGroup


class BookingStates(StatesGroup):
    choose_category = State()  # 1-й шаг: ручки/ножки
    choose_service = State()   # 2-й шаг: конкретная услуга с ценой
    choose_addons = State()   # выбор доп. опций (если есть)
    choose_master = State()   # выбор мастера
    choose_date = State()
    choose_time = State()
    confirm_profile = State()  # подтверждение сохранённого профиля
    get_name = State()
    get_phone = State()
    confirm = State()


class ReviewStates(StatesGroup):
    enter_comment = State()  # ожидание текстового комментария после выбора рейтинга


class AdminStates(StatesGroup):
    # Поиск клиента
    client_search = State()

    # Редактирование услуги
    service_edit_name = State()
    service_edit_price = State()
    service_edit_duration = State()
    service_edit_description = State()

    # Добавление услуги
    service_add_name = State()
    service_add_category = State()  # ручки/ножки
    service_add_price = State()
    service_add_duration = State()

    # Перенос записи
    reschedule_pick_date = State()
    reschedule_pick_time = State()

    # Настройки
    settings_edit_slot_step = State()

    # Гибкий график (салонно-глобальный)
    schedule_edit_start = State()
    schedule_edit_end = State()

    # Гибкий график per-master (админ редактирует расписание конкретного мастера)
    master_schedule_edit_start = State()
    master_schedule_edit_end = State()

    # Блокировка времени
    block_pick_date = State()
    block_pick_type = State()
    block_pick_time_start = State()
    block_pick_time_end = State()

    # Доп. опции (аддоны)
    addon_add_name = State()
    addon_add_price = State()

    # Мастера
    master_add_name = State()
    master_add_user_id = State()
    master_add_bio = State()
    master_edit_name = State()
    master_edit_user_id = State()
    master_edit_bio = State()

    # Выбор мастера при создании блокировки
    block_pick_master = State()
