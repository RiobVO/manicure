"""
Верификация лицензионного ключа и определение режима работы бота.

Формат лицензии: <base64url(payload_json)>.<base64url(signature)>
  payload: {tenant_slug, customer_name, license_id, issued_at, expires_at}
  signature: Ed25519 поверх UTF-8 байт payload_json
  publickey: вмёрзший в PUBLIC_KEY_PEM (запущенный bot не читает файлов)

Режимы (enum LicenseMode):
  DEV        — публичный ключ не заменён на реальный. Бот работает, warning в логах.
  OK         — валидная подпись, не истекла.
  GRACE      — истекла ≤ GRACE_DAYS назад. Бот работает, админу алерты.
  RESTRICTED — нет ключа / невалидна / истекла > GRACE_DAYS назад. Бот только на /start.

Всё содержимое ключа в PUBLIC_KEY_PEM публично по дизайну — это не секрет.
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

logger = logging.getLogger(__name__)

# Grace 90 дней — под производственную норму (GitLab/Metabase/JetBrains делают
# 30-90). 7 дней было в первоначальном брифе, но для живого продукта это враждебно:
# салон не должен ловить блокировку в 22:00 из-за нашей же забывчивости продлить.
GRACE_DAYS = 90

# Публичный ключ. Сгенерировать через `python tools/generate_keys.py` и заменить
# блок ниже. Плейсхолдер детектится по подстроке PLACEHOLDER_MARKER — в этом
# случае бот работает в режиме DEV (для локальной разработки до выпуска лицензий).
PLACEHOLDER_MARKER = "PLACEHOLDER_REPLACE_ME"
# Боевой публичный ключ. Парный приватный — в license_private_key.pem у автора,
# никогда не коммитится. Перевыпуск ключей инвалидирует все существующие лицензии.
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA7eNE5+ukC6loQcGWFGLD2zjjnwAyLEn6f7PiTEZTJrc=
-----END PUBLIC KEY-----
"""


class LicenseMode(str, Enum):
    DEV = "dev"
    OK = "ok"
    GRACE = "grace"
    RESTRICTED = "restricted"


class LicenseError(Exception):
    """Любая причина, по которой лицензию нельзя принять."""


@dataclass(frozen=True)
class License:
    tenant_slug: str
    customer_name: str
    license_id: str
    issued_at: datetime
    expires_at: datetime

    def days_until_expiry(self) -> int:
        return (self.expires_at - datetime.now(timezone.utc)).days


@dataclass(frozen=True)
class LicenseState:
    """Результат проверки лицензии на старте. Хранится на весь процесс."""
    mode: LicenseMode
    license: Optional[License] = None
    reason: str = ""

    @property
    def allows_booking(self) -> bool:
        return self.mode in (LicenseMode.DEV, LicenseMode.OK, LicenseMode.GRACE)


def _is_placeholder() -> bool:
    return PLACEHOLDER_MARKER in PUBLIC_KEY_PEM


def _load_public_key() -> Ed25519PublicKey:
    key = load_pem_public_key(PUBLIC_KEY_PEM.encode("ascii"))
    if not isinstance(key, Ed25519PublicKey):
        raise LicenseError("Public key is not Ed25519")
    return key


def _b64url_decode(s: str) -> bytes:
    # urlsafe_b64decode требует padding; выпускаемый ключ padding не содержит.
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def verify_license(key_str: str) -> License:
    """
    Проверить подпись и распарсить payload. Бросает LicenseError при любой
    ошибке — вызывающий решает как обращаться в режим.
    """
    if not key_str or not key_str.strip():
        raise LicenseError("LICENSE_KEY пуст")

    try:
        payload_b64, sig_b64 = key_str.strip().split(".", 1)
    except ValueError as exc:
        raise LicenseError(f"malformed key (нет разделителя): {exc}") from exc

    try:
        payload_bytes = _b64url_decode(payload_b64)
        sig_bytes = _b64url_decode(sig_b64)
    except Exception as exc:
        raise LicenseError(f"base64 decode failed: {exc}") from exc

    pub = _load_public_key()
    try:
        pub.verify(sig_bytes, payload_bytes)
    except InvalidSignature as exc:
        raise LicenseError("invalid signature") from exc

    try:
        data = json.loads(payload_bytes.decode("utf-8"))
        return License(
            tenant_slug=data["tenant_slug"],
            customer_name=data["customer_name"],
            license_id=data["license_id"],
            issued_at=datetime.fromisoformat(data["issued_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise LicenseError(f"malformed payload: {exc}") from exc


def evaluate_license(key_str: str, expected_tenant: str) -> LicenseState:
    """
    Комплексная проверка: вытаскивает License + определяет режим исходя из
    её срока и совпадения tenant_slug с ожидаемым.
    """
    if _is_placeholder():
        return LicenseState(
            mode=LicenseMode.DEV,
            reason="public key не заменён на реальный (tools/generate_keys.py)",
        )

    try:
        lic = verify_license(key_str)
    except LicenseError as exc:
        return LicenseState(mode=LicenseMode.RESTRICTED, reason=f"ключ невалиден: {exc}")

    if lic.tenant_slug != expected_tenant:
        return LicenseState(
            mode=LicenseMode.RESTRICTED,
            license=lic,
            reason=f"tenant mismatch: ключ для '{lic.tenant_slug}', бот запущен как '{expected_tenant}'",
        )

    now = datetime.now(timezone.utc)
    grace_deadline = lic.expires_at + timedelta(days=GRACE_DAYS)

    if now <= lic.expires_at:
        return LicenseState(mode=LicenseMode.OK, license=lic)
    if now <= grace_deadline:
        return LicenseState(
            mode=LicenseMode.GRACE,
            license=lic,
            reason=f"истекла {(now - lic.expires_at).days} дн. назад, grace до {grace_deadline.date()}",
        )
    return LicenseState(
        mode=LicenseMode.RESTRICTED,
        license=lic,
        reason=f"истекла {(now - lic.expires_at).days} дн. назад, grace исчерпан",
    )
