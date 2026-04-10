from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_MINUTES: int
    DB_NAME: str
    DB_USER: str
    CIPHER_KEY: str
    DB_PASSWORD: str
    DATABASE_URL: str
    STRIPE_WEBHOOK_SECRET: str
    SYNC_DATABASE_URL: str
    REDIS_URL: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    BUCKET: str
    Standard: str
    Premium: str
    Regular: str

    model_config = {"env_file": ".env"}


settings = Settings(**{})
