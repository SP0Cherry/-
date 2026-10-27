"""Password hashing helpers.

Passwords are ONLY ever stored as salted hashes (pbkdf2:sha256, random salt).
Plaintext passwords must never be persisted or logged.
"""
from werkzeug.security import check_password_hash, generate_password_hash

HASH_METHOD = "pbkdf2:sha256"
SALT_LENGTH = 16


def hash_password(plaintext: str) -> str:
    return generate_password_hash(
        plaintext, method=HASH_METHOD, salt_length=SALT_LENGTH
    )


def verify_password(password_hash: str, plaintext: str) -> bool:
    return check_password_hash(password_hash, plaintext)
