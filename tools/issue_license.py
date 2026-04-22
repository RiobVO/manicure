"""
CLI выпуска лицензионного ключа — запускается автором.

Usage:
    python tools/issue_license.py <tenant_slug> <customer_name> <months>

Пример:
    python tools/issue_license.py nails-chilanzar "Салон Сабина" 12

Выводит в stdout строку лицензии (то что идёт в .env как LICENSE_KEY).
В stderr — человекочитаемое саммари для лога продаж.
"""
import argparse
import base64
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

PRIVATE_KEY_PATH = Path("license_private_key.pem")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Выпустить лицензионный ключ.")
    parser.add_argument("tenant_slug", help="Идентификатор салона (должен совпадать с TENANT_SLUG в .env).")
    parser.add_argument("customer_name", help="Имя клиента для логов — не показывается в боте.")
    parser.add_argument("months", type=int, help="Срок действия в месяцах (30-дневных).")
    parser.add_argument(
        "--expires-at",
        help="ISO8601 override expires_at (UTC). Используется только для тестов "
             "grace/restricted. Пример: 2026-04-19T03:45:00+00:00",
    )
    args = parser.parse_args()

    if not PRIVATE_KEY_PATH.exists():
        sys.stderr.write(
            f"Нет {PRIVATE_KEY_PATH}. Сгенерируй ключи: python tools/generate_keys.py\n"
        )
        sys.exit(1)

    # Warning если ключ лежит в директории проекта (значит есть риск утечки
    # через архив/git/облако). Правильное место — ~/.config/manicure/ или
    # password manager. В .gitignore он есть, но не защитит от `tar -czf`
    # или «скинь мне проект в Telegram» (аудит 2026-04-22).
    resolved = PRIVATE_KEY_PATH.resolve()
    try:
        resolved.relative_to(Path.cwd().resolve())
        sys.stderr.write(
            "⚠ ВНИМАНИЕ: приватный ключ лежит в директории проекта.\n"
            "  Рекомендуется перенести в ~/.config/manicure/license_private_key.pem\n"
            "  или password manager. Случайный tar/zip выгрузит ключ наружу.\n\n"
        )
    except ValueError:
        pass  # ключ снаружи проекта — то что нужно

    priv = load_pem_private_key(PRIVATE_KEY_PATH.read_bytes(), password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        sys.stderr.write("Приватный ключ не Ed25519 — использовал не тот генератор?\n")
        sys.exit(1)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    if args.expires_at:
        expires = datetime.fromisoformat(args.expires_at)
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    else:
        expires = now + timedelta(days=args.months * 30)

    payload = {
        "tenant_slug": args.tenant_slug,
        "customer_name": args.customer_name,
        "license_id": str(uuid.uuid4()),
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }
    # sort_keys — чтобы одна и та же payload сериализовалась байт-в-байт,
    # независимо от порядка ключей в python-словаре.
    payload_bytes = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    sig = priv.sign(payload_bytes)

    key = f"{b64url(payload_bytes)}.{b64url(sig)}"
    print(key)

    sys.stderr.write("\nВыписано:\n")
    sys.stderr.write(f"  салон:      {args.tenant_slug}\n")
    sys.stderr.write(f"  клиент:     {args.customer_name}\n")
    sys.stderr.write(f"  выдана:     {now.isoformat()}\n")
    sys.stderr.write(f"  истекает:   {expires.isoformat()}\n")
    sys.stderr.write(f"  license_id: {payload['license_id']}\n")


if __name__ == "__main__":
    main()
