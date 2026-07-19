import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

_ph = PasswordHasher()


def _validate_pin(pin: str) -> None:
    if not isinstance(pin, str) or len(pin) != 6 or not pin.isascii() or not pin.isdigit():
        raise ValueError("PIN must be exactly six ASCII digits")


def hash_pin(pin: str) -> str:
    _validate_pin(pin)
    return _ph.hash(pin)


def verify_pin(pin: str, hashed: str) -> bool:
    try:
        _validate_pin(pin)
        return _ph.verify(hashed, pin)
    except (ValueError, VerificationError):
        return False


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
