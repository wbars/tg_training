import os
from pathlib import Path
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
    db_path: Path

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        base_dir = Path(__file__).parent.parent

        return cls(
            telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
            openai_api_key=os.environ["OPENAI_API_KEY"],
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            db_path=Path(os.environ.get("DB_PATH", base_dir / "data" / "gym.db")),
        )


def get_config() -> Config:
    """Get configuration singleton."""
    return Config.from_env()
