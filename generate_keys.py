# generate_keys.py
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

priv = Ed25519PrivateKey.generate()
pub = priv.public_key()

# Приватный в PEM (для генератора лицензий, хранить только у себя)
pem = priv.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
with open("private.key", "wb") as f:
    f.write(pem)

# Публичный в base64 raw 32 bytes (вставляется в main.py)
pub_raw = pub.public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
pub_b64 = base64.b64encode(pub_raw).decode("ascii")
print("APP_PUBLIC_KEY_B64 =", pub_b64)
