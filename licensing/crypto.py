import base64
import json
from pathlib import Path
from typing import Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    value = (value or "").strip()
    pad = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + pad)


def load_public_key_from_b64(public_key_b64: str) -> Ed25519PublicKey:
    raw = base64.b64decode(public_key_b64.strip())
    if len(raw) != 32:
        raise ValueError("Public key must be 32 bytes (base64 of raw Ed25519 key).")
    return Ed25519PublicKey.from_public_bytes(raw)


def load_private_key_from_file(path: str) -> Ed25519PrivateKey:
    data = Path(path).read_bytes()

    # Raw 32-byte Ed25519 private key (binary file)
    if len(data) == 32:
        return Ed25519PrivateKey.from_private_bytes(data)

    # Base64 encoded raw 32-byte key
    try:
        raw = base64.b64decode(data.decode("utf-8").strip(), validate=True)
        if len(raw) == 32:
            return Ed25519PrivateKey.from_private_bytes(raw)
    except Exception:
        pass

    # PEM private key
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except Exception as exc:
        raise ValueError("Unsupported private key format.") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Private key is not Ed25519.")
    return key


def sign_payload_bytes(payload_bytes: bytes, private_key: Ed25519PrivateKey) -> bytes:
    return private_key.sign(payload_bytes)


def verify_signature_bytes(
    payload_bytes: bytes,
    signature: bytes,
    public_key: Ed25519PublicKey,
) -> bool:
    try:
        public_key.verify(signature, payload_bytes)
        return True
    except InvalidSignature:
        return False


def build_signed_license_document(payload: dict, private_key: Ed25519PrivateKey) -> dict:
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = sign_payload_bytes(payload_bytes, private_key)
    return {"payload": b64url_encode(payload_bytes), "sig": b64url_encode(signature)}


def extract_and_verify_document(
    document: dict,
    public_key: Ed25519PublicKey,
) -> Tuple[bool, bytes]:
    payload_b64 = document.get("payload")
    sig_b64 = document.get("sig")
    if not isinstance(payload_b64, str) or not isinstance(sig_b64, str):
        return False, b""

    try:
        payload_bytes = b64url_decode(payload_b64)
        signature = b64url_decode(sig_b64)
    except Exception:
        return False, b""

    is_valid = verify_signature_bytes(payload_bytes, signature, public_key)
    return is_valid, payload_bytes

