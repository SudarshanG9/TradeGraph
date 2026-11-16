"""Account records commit together; database identities are provisioned separately."""
import re
import bcrypt
from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_email(value: str) -> str:
    value = value.strip(' ').lower()
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`|~-]+@[a-z0-9.-]+\.[a-z]{2,}", value, re.ASCII):
        raise ValueError('A valid ASCII email address is required')
    return value


class Registration(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    full_name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=12, max_length=72)

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        return normalize_email(value)

    @field_validator('full_name')
    @classmethod
    def name_valid(cls, value):
        value = value.strip()
        if len(value)<2 or any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError('A full name without control characters is required')
        return value

    @field_validator('password')
    @classmethod
    def password_valid(cls, value):
        if len(value.encode('utf-8'))>72 or '\x00' in value or not value.strip():
            raise ValueError('Password must be 12..72 characters and at most 72 UTF-8 bytes')
        return value


def register_account(database, body: Registration):
    hashed = bcrypt.hashpw(body.password.encode('utf-8'), bcrypt.gensalt()).decode('ascii')
    settings = database.settings
    with database._connect_as(settings.postgres_auth_user, settings.postgres_auth_password) as conn:
        result = conn.execute('SELECT * FROM public.register_trader(%s,%s,%s)', (body.email, hashed, body.full_name)).fetchone()
    return result  # COMMIT before returning the receipt
