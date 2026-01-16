import os
from dataclasses import dataclass


@dataclass
class Config:
    # Telegram
    telegram_bot_token: str

    # OpenAI (for Whisper)
    openai_api_key: str

    # Anthropic (for parsing)
    anthropic_api_key: str

    # Database
    database_url: str

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        return cls(
            telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
            openai_api_key=os.environ["OPENAI_API_KEY"],
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            database_url=os.environ["DATABASE_URL"],
        )


def get_config() -> Config:
    """Get configuration singleton."""
    return Config.from_env()
