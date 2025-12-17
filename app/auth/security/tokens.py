from datetime import datetime, timedelta
import jwt
from cryptography.fernet import Fernet

from fastapi import HTTPException
from starlette import status

from app.core.config import SECRET_KEY, ALGORITHM, REFRESH_TOKEN_EXPIRE_DAYS, ACCESS_TOKEN_EXPIRE_MINUTES

cipher_suite = Fernet(b'7UyZJViX2HMoM5OqZN0iOhYtM7xMmzhXgPFMhTtOK+o=')


def encrypt_phone_number(phone_number: str) -> str:
    return cipher_suite.encrypt(phone_number.encode()).decode()


def decrypt_phone_number(encrypted_phone_number: str) -> str:
    return cipher_suite.decrypt(encrypted_phone_number.encode()).decode()


def create_access_token(data: dict):
    phone_number = data.get("sub")
    encrypted_phone_number = encrypt_phone_number(phone_number)
    to_encode = {"sub": encrypted_phone_number, "token_type": "access"}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict):
    phone_number = data.get("sub")
    encrypted_phone_number = encrypt_phone_number(phone_number)
    to_encode = {"sub": encrypted_phone_number, "token_type": "refresh"}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str, expected_token_type: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
        token_type = payload.get("token_type")
        if expected_token_type != "any" and token_type != expected_token_type:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Invalid token type: expected {expected_token_type}, got {token_type}")
        encrypted_phone_number = payload.get("sub")
        phone_number = decrypt_phone_number(encrypted_phone_number)
        payload["sub"] = phone_number
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Could not validate credentials")