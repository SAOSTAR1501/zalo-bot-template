import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Zalo Bot Credentials
    ZALO_BOT_TOKEN: str = ""
    ZALO_WEBHOOK_SECRET: str = ""
    WEBHOOK_URL: str = ""

    # AI Provider
    AI_PROVIDER: str = "ollama"  # ollama | gemini | openai | deepseek | echo

    # Ollama
    OLLAMA_BASE_URL: str = "https://ollama.com"
    OLLAMA_API_KEY: str = ""
    OLLAMA_MODEL: str = "gemma4:31b"

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # OpenAI / DeepSeek / Custom
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Memory & Context
    MAX_CONTEXT_HOURS: int = 12
    MAX_CONTEXT_TURNS: int = 20
    DB_PATH: str = "data/zalo_bot.db"

    # Access Control
    ADMIN_USER_IDS: str = ""
    ALLOWED_GROUP_IDS: str = ""

    # Server
    PORT: int = 8080
    HOST: str = "0.0.0.0"

    @property
    def admin_ids(self) -> List[str]:
        if not self.ADMIN_USER_IDS:
            return []
        return [uid.strip() for uid in self.ADMIN_USER_IDS.split(",") if uid.strip()]

    @property
    def allowed_groups(self) -> List[str]:
        if not self.ALLOWED_GROUP_IDS:
            return []
        return [gid.strip() for gid in self.ALLOWED_GROUP_IDS.split(",") if gid.strip()]


settings = Settings()
