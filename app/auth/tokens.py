"""Stateless JWT access token issuance and verification.

Tokens are signed with the application SECRET_KEY using HS256. They carry only
an identity pointer (sub) plus timing claims (iat/exp); role and class are
always re-read from the database per request, so stale privilege claims can
never exist.
"""
from datetime import datetime, timedelta, timezone

import jwt

# Token type marker (single token kind for now; allows future refresh tokens).
TOKEN_TYPE_ACCESS = "access"


class TokenError(Exception):
    """Base error for any token that cannot be accepted."""


class TokenExpired(TokenError):
    """The token's exp claim is in the past."""


def issue_access_token(user, secret_key: str, ttl_minutes: int) -> tuple[str, int]:
    """Return (signed_token, expires_in_seconds) for the given user."""
    now = datetime.now(timezone.utc)
    expires_in = int(timedelta(minutes=ttl_minutes).total_seconds())
    payload = {
        "sub": str(user.id),
        "type": TOKEN_TYPE_ACCESS,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    return token, expires_in


def decode_token(token: str, secret_key: str) -> dict:
    """Validate signature/claims and return the payload.

    Raises TokenExpired for an expired token and TokenError for any other
    rejection (bad signature, malformed token, missing claims, alg confusion).
    Decoding is pinned to HS256 so an attacker cannot force "none"/RS256.
    """
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired("access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid access token") from exc

    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise TokenError("unexpected token type")
    return payload
