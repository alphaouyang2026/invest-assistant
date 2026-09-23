"""Runtime settings, read from the environment."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jquants_api_key: str | None = None
    database_path: Path = Path("var/invest.db")
    timezone: str = "Asia/Tokyo"

    @property
    def tzinfo(self) -> ZoneInfo:
        """The zone every date in this system is read in."""
        return ZoneInfo(self.timezone)

    @property
    def database_url(self) -> str:
        """The SQLite URL for `database_path`.

        Absolute and POSIX-shaped, so the same URL reads the same file
        whether it is built on Windows or inside the container, and
        whichever directory the process happens to be started from.
        """
        return f"sqlite:///{self.database_path.resolve().as_posix()}"

    @property
    def runtime_dir(self) -> Path:
        """`var/`: the job lock and job log live beside the database."""
        return self.database_path.parent

    def require_jquants_api_key(self) -> str:
        """The key, or a failure that names the variable to set.

        Absence is not a start-up error: the service runs fine until
        something actually reaches for J-Quants, which is here.
        """
        if not self.jquants_api_key:
            raise RuntimeError(
                "要访问 J-Quants 需要 API key：请在 .env 里设置 JQUANTS_API_KEY"
            )
        return self.jquants_api_key
