"""
Безопасность: JWT, хеширование паролей, шифрование
"""
from datetime import datetime, timedelta
from typing import Any, Optional

import bcrypt
from cryptography.fernet import Fernet
from jose import JWTError, jwt

from app.config import settings

# Шифрование для API ключей
_cipher_suite: Optional[Fernet] = None

# bcrypt ограничен 72 байтами
BCRYPT_MAX_BYTES = 72


def get_cipher() -> Fernet:
    """Получение cipher suite для шифрования"""
    global _cipher_suite
    if _cipher_suite is None:
        _cipher_suite = Fernet(settings.ENCRYPTION_KEY.encode())
    return _cipher_suite


def _to_bcrypt_bytes(password: str) -> bytes:
    """Преобразование пароля в bytes с обрезкой до 72 байт."""
    encoded = password.encode("utf-8")
    return encoded[:BCRYPT_MAX_BYTES] if len(encoded) > BCRYPT_MAX_BYTES else encoded


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Проверка пароля

    Args:
        plain_password: Пароль в открытом виде
        hashed_password: Хешированный пароль (bcrypt)

    Returns:
        bool: True если пароль совпадает
    """
    try:
        return bcrypt.checkpw(
            _to_bcrypt_bytes(plain_password),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        return False


def get_password_hash(password: str) -> str:
    """
    Хеширование пароля (bcrypt).

    Args:
        password: Пароль в открытом виде

    Returns:
        str: Хешированный пароль
    """
    hashed = bcrypt.hashpw(
        _to_bcrypt_bytes(password),
        bcrypt.gensalt(),
    )
    return hashed.decode("utf-8")


def create_access_token(
    subject: str | Any,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Создание JWT access токена
    
    Args:
        subject: Subject (обычно user_id)
        expires_delta: Время жизни токена
        
    Returns:
        str: JWT токен
    """
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode = {"exp": expire, "sub": str(subject), "type": "access"}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(subject: str | Any) -> str:
    """
    Создание JWT refresh токена
    
    Args:
        subject: Subject (обычно user_id)
        
    Returns:
        str: JWT токен
    """
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh"}
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict[str, Any]]:
    """
    Декодирование JWT токена
    
    Args:
        token: JWT токен
        
    Returns:
        Optional[dict]: Payload токена или None при ошибке
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None


def encrypt_api_key(api_key: str) -> str:
    """
    Шифрование API ключа маркетплейса
    
    Args:
        api_key: API ключ в открытом виде
        
    Returns:
        str: Зашифрованный API ключ (base64)
    """
    cipher = get_cipher()
    encrypted = cipher.encrypt(api_key.encode())
    return encrypted.decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Расшифровка API ключа маркетплейса
    
    Args:
        encrypted_key: Зашифрованный API ключ (base64)
        
    Returns:
        str: API ключ в открытом виде
    """
    cipher = get_cipher()
    decrypted = cipher.decrypt(encrypted_key.encode())
    return decrypted.decode()


def generate_encryption_key() -> str:
    """
    Генерация ключа шифрования для .env файла
    
    Returns:
        str: Fernet key
    """
    return Fernet.generate_key().decode()
