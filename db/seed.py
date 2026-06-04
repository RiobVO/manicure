"""
Seed-данные для первого запуска.

Используется только в init_db(), когда таблица services пуста. После первого
старта таблица заполняется из БД — этот модуль больше не читается.
Вынесен из корневого services.py, чтобы не конфликтовать по имени
с пакетом db/services (CRUD).

Категории (см. constants.CATEGORY_KEYS):
  hands     — маникюр
  feet      — педикюр
  face      — лицо (брови, усики, подбородок, щёки, полностью)
  depil     — депиляция (воск/шугаринг по зонам)
  skincare  — уход за лицом (УЗ-чистка, механическая чистка)
  dental    — стоматология (отбеливание зубов)

Шаблон записи: {id, name, price, duration, category, is_active?}.
is_active=0 → услуга в каталоге, но клиенту не показывается. Используется
для новых категорий (face/depil/skincare/dental) — Сабина проставит цены
и активирует через админку. Услуги с явно проставленной ценой 0 — плейсхолдер.
"""
SERVICES = [
    # ─── Маникюр (исторический seed v.0) ─────────────────────────────────────
    {"id": 1, "name": "Маникюр без покрытия",   "price": 150000, "duration": 45,  "category": "hands"},
    {"id": 2, "name": "Маникюр с лаком",         "price": 180000, "duration": 60,  "category": "hands"},
    {"id": 3, "name": "Маникюр с гель-лаком",    "price": 250000, "duration": 120, "category": "hands"},
    {"id": 4, "name": "Маникюр с наращиванием",  "price": 350000, "duration": 150, "category": "hands"},
    # ─── Педикюр ─────────────────────────────────────────────────────────────
    {"id": 5, "name": "Педикюр без покрытия",    "price": 180000, "duration": 60,  "category": "feet"},
    {"id": 6, "name": "Педикюр с гель-лаком",    "price": 280000, "duration": 120, "category": "feet"},

    # ─── Лицо (face) — is_active=0, цены проставит салон ─────────────────────
    {"id": 7,  "name": "Лицо полностью", "price": 0, "duration": 30, "category": "face",     "is_active": 0},
    {"id": 8,  "name": "Брови",          "price": 0, "duration": 30, "category": "face",     "is_active": 0},
    {"id": 9,  "name": "Усики",          "price": 0, "duration": 30, "category": "face",     "is_active": 0},
    {"id": 10, "name": "Подбородок",     "price": 0, "duration": 30, "category": "face",     "is_active": 0},
    {"id": 11, "name": "Щёки",           "price": 0, "duration": 30, "category": "face",     "is_active": 0},

    # ─── Уход за лицом (skincare) ────────────────────────────────────────────
    {"id": 12, "name": "Ультразвуковая чистка", "price": 0, "duration": 30, "category": "skincare", "is_active": 0},
    {"id": 13, "name": "Механическая чистка",   "price": 0, "duration": 30, "category": "skincare", "is_active": 0},

    # ─── Стоматология (dental) ───────────────────────────────────────────────
    # ⚠ юридический риск: отбеливание зубов = медицинская услуга. Активировать
    # ТОЛЬКО если у салона партнёр-стоматолог с лицензией. Иначе оставить
    # is_active=0 или удалить из каталога через админку.
    {"id": 14, "name": "Отбеливание зубов", "price": 0, "duration": 30, "category": "dental", "is_active": 0},

    # ─── Депиляция (depil) — двумерная: метод × зона ─────────────────────────
    # Воск × 9 зон
    {"id": 15, "name": "Воск — руки полностью",        "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 16, "name": "Воск — руки до локтя",         "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 17, "name": "Воск — руки с захватом локтя", "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 18, "name": "Воск — ноги полностью",        "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 19, "name": "Воск — ноги до колена",        "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 20, "name": "Воск — ноги с захватом колена","price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 21, "name": "Воск — бикини глубокое",       "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 22, "name": "Воск — бикини классическое",   "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 23, "name": "Воск — подмышки",              "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    # Шугаринг × 9 зон
    {"id": 24, "name": "Шугаринг — руки полностью",        "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 25, "name": "Шугаринг — руки до локтя",         "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 26, "name": "Шугаринг — руки с захватом локтя", "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 27, "name": "Шугаринг — ноги полностью",        "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 28, "name": "Шугаринг — ноги до колена",        "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 29, "name": "Шугаринг — ноги с захватом колена","price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 30, "name": "Шугаринг — бикини глубокое",       "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 31, "name": "Шугаринг — бикини классическое",   "price": 0, "duration": 30, "category": "depil", "is_active": 0},
    {"id": 32, "name": "Шугаринг — подмышки",              "price": 0, "duration": 30, "category": "depil", "is_active": 0},
]
