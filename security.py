import os
import sys
import hmac
import hashlib
from cryptography.fernet import Fernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

is_debug = os.getenv('FLASK_ENV', 'production').lower() == 'development'

_ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '')
_HASH_SALT      = os.getenv('HASH_SALT', '')


def _validate_crypto_secrets():
    if is_debug:
        return
    missing = [n for n, v in [('ENCRYPTION_KEY', _ENCRYPTION_KEY), ('HASH_SALT', _HASH_SALT)] if not v]
    if missing:
        sys.exit(f"[FATAL] Missing secrets: {missing}")

_validate_crypto_secrets()


class EncryptionHandler:
    def __init__(self):
        self._fernet = None

    def _get_fernet(self):
        if self._fernet is None:
            key = os.getenv('ENCRYPTION_KEY', '')
            if not key:
                return None
            self._fernet = Fernet(key.encode())
        return self._fernet

    def encrypt(self, value):
        if value is None:
            return None
        f = self._get_fernet()
        if f is None:
            return value
        return f.encrypt(value.encode()).decode()

    def decrypt(self, value):
        if value is None:
            return None
        f = self._get_fernet()
        if f is None:
            return value
        try:
            return f.decrypt(value.encode()).decode()
        except Exception:
            return value


encryption_handler = EncryptionHandler()


class EncryptedField(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encryption_handler.encrypt(value)

    def process_result_value(self, value, dialect):
        return encryption_handler.decrypt(value)


def blind_index(value):
    salt = os.getenv('HASH_SALT', 'dev_salt')
    return hmac.new(
        salt.encode(),
        value.strip().lower().encode(),
        hashlib.sha256
    ).hexdigest()
