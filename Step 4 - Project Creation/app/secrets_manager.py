from cryptography.fernet import Fernet, InvalidToken
from app.config import ENCRYPTION_KEY
import logging

logger = logging.getLogger("sqh.secrets")

_fernet = None


def _get_fernet() -> Fernet | None:
    global _fernet
    if _fernet is not None:
        return _fernet
    if not ENCRYPTION_KEY:
        logger.warning("SQH_ENCRYPTION_KEY not set — secrets stored without Fernet layer")
        return None
    try:
        _fernet = Fernet(ENCRYPTION_KEY.encode())
        return _fernet
    except Exception:
        logger.error("Invalid SQH_ENCRYPTION_KEY — cannot initialise Fernet")
        return None


def encrypt(plaintext: str) -> str:
    f = _get_fernet()
    if f is None:
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    f = _get_fernet()
    if f is None:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.error("Fernet decryption failed — token invalid or key mismatch")
        return ""
