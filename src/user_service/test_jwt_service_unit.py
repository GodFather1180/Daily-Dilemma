from datetime import datetime, timedelta
import time

import pytest

from user_service.jwt_service import JWTService


def _future_expiry(hours: int = 1) -> str:
    # Return a formatted datetime string HOURS in the future.
    return (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def test_get_public_key_pem_returns_pem():
    service = JWTService()
    pem = service._get_public_key_pem()
    # Hits the public key PEM generation
    assert "BEGIN PUBLIC KEY" in pem
    assert "END PUBLIC KEY" in pem


def test_parse_expiry_invalid_format_raises_value_error():
    service = JWTService()
    # Hits the ValueError branch in _parse_expiry
    with pytest.raises(ValueError):
        service._parse_expiry("not-a-date")


def test_issue_token_invalid_expiry_raises_value_error():
    service = JWTService()
    # Hits the ValueError branch in issue_token
    with pytest.raises(ValueError):
        service.issue_token(user_id=1, expiry_str="not-a-date")


def test_validate_token_rejects_obviously_invalid_token():
    service = JWTService()
    # "not-a-jwt" will trigger InvalidTokenError in jwt.decode
    assert service.validate_token("not-a-jwt") is None


def test_validate_token_rejects_token_older_than_last_issued():
    service = JWTService()
    expiry = _future_expiry(hours=1)

    # Issue one token and manually move last_issued_at forward
    old_token = service.issue_token(user_id=1, expiry_str=expiry)

    # Pretend we later issued a newer token: bump last issued-at
    now = int(time.time())
    service.user_last_issued_at["1"] = now + 10

    # Branch where payload iat < last_iat should return None
    assert service.validate_token(old_token) is None


def test_expire_token_marks_token_and_prevents_future_validation():
    service = JWTService()
    expiry = _future_expiry(hours=1)
    token = service.issue_token(user_id=1, expiry_str=expiry)

    # First time: token is valid, expire_token returns True and stores it
    assert service.expire_token(token) is True
    assert token in service.expired_tokens

    # After that, validate_token should treat it as expired
    assert service.validate_token(token) is None

    # Second call: validate_token returns None, so expire_token returns False
    assert service.expire_token(token) is False
