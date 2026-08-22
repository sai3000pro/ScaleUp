from __future__ import annotations

from app.core.security import (
    create_opaque_token,
    hash_opaque_token,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_opaque_tokens_are_high_entropy_and_stored_as_hashes() -> None:
    first = create_opaque_token()
    second = create_opaque_token()

    assert first != second
    assert len(first) >= 40
    assert hash_opaque_token(first) != first
    assert hash_opaque_token(first) != hash_opaque_token(second)


def test_password_hashes_verify_without_exposing_plaintext() -> None:
    plain = "hunter22-long-enough"
    hashed = hash_password(plain)

    assert hashed != plain
    assert "$argon2id$" in hashed
    assert "$m=32768,t=3,p=1$" in hashed
    assert verify_password(plain, hashed)
    assert not verify_password("wrong-password", hashed)
    assert not needs_rehash(hashed)
