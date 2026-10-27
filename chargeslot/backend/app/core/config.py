from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "ChargeSlot API"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "temporary_development_secret_key_chargeslot_change_in_production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30       # Short-lived access token (CS19-004)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7           # Long-lived refresh token (CS19-004)
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5          # Lockout after 5 attempts (CS19-005)
    LOGIN_LOCKOUT_MINUTES: int = 15             # 15 minutes lockout duration (CS19-005)
    PASSWORD_RESET_EXPIRE_MINUTES: int = 15     # 15 minutes reset code expiry (CS19-006)
    DATABASE_URL: str = "sqlite:///./chargeslot.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
