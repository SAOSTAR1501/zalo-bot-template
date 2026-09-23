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

    # Ollama / Cloud LLM Endpoints
    OLLAMA_BASE_URL: str = "https://ollama.com"
    OLLAMA_API_KEY: str = ""
    OLLAMA_MODEL: str = "deepseek-v4-pro:0813"
    VISION_MODEL: str = "kimi-k2.7-code"
    FALLBACK_MODELS: str = "glm-5.3-flash,glm-5.2,glm-5.1"
    VISION_FALLBACK_MODELS: str = "kimi-k3,glm-5.3-flash"

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # OpenAI / DeepSeek / Custom
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Memory & Context Optimization (Episodic Summary Memory)
    MAX_CONTEXT_HOURS: int = 12
    RECENT_MESSAGES_COUNT: int = 4        # Raw recent turns to retain
    AUTO_SUMMARIZE_THRESHOLD: int = 6     # Unsummarized turns before updating rolling summary
    DB_PATH: str = "data/zalo_bot.db"

    # Message Debouncing & Aggregation
    DEBOUNCE_WAIT_SECONDS: float = 2.5            # Seconds to wait for consecutive messages before batch LLM call

    ADMIN_USER_IDS: str = "3f6de3efa9a340fd19b2"  # Mai Công Sao
    ALLOWED_GROUP_IDS: str = ""
    FREE_MESSAGE_QUOTA: int = 10                  # Free 1-1 messages for new users
    MAX_SPAM_WARNINGS: int = 3                    # Replies before silent drop

    # Stickers
    STICKER_CATALOG_JSON: str = ""          # Optional JSON override of the sticker catalog
    STICKER_EXTRA_URLS: str = ""            # Extra sticker URLs: "laugh: url1, url2 | cry: url3"
    STICKER_AUTO_SEND: bool = True          # Allow bot to auto-send a matching sticker with replies

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
