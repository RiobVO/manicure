"""
Одноразовая утилита: генерирует Ed25519 keypair для подписи лицензий.

Запускать у автора ровно ОДИН раз, в начале продаж. Результат:
  • license_private_key.pem — хранится локально у автора. НЕ коммитить.
  • PUBLIC_KEY_PEM — строка PEM, которую нужно вставить в utils/license.py.

Повторный запуск сломает все ранее выпущенные лицензии (другая подпись).
"""
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

PRIVATE_PATH = Path("license_private_key.pem")


def main() -> None:
    if PRIVATE_PATH.exists():
        print(
            f"{PRIVATE_PATH} уже существует. Если перегенерируешь — все ранее "
            "выпущенные лицензии станут невалидными. Удали файл вручную если уверен.",
            file=sys.stderr,
        )
        sys.exit(1)

    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()

    priv_pem = priv.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    )

    PRIVATE_PATH.write_bytes(priv_pem)

    print(f"Приватный ключ записан в {PRIVATE_PATH}")
    print("  ⚠ ХРАНИ ЛИЧНО. Не коммитить. Терять нельзя — перевыпустить лицензии без него невозможно.")
    print()
    print("Публичный ключ ↓↓↓ — скопируй в utils/license.py::PUBLIC_KEY_PEM и закоммить:")
    print()
    print(pub_pem.decode("ascii"))


if __name__ == "__main__":
    main()
