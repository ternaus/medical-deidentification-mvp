"""Application settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime paths and local processing limits."""

    model_config = SettingsConfigDict(env_prefix="MEDICAL_DEID_", frozen=True)

    data_dir: Path = Path("local-data")
    max_upload_bytes: int = 25 * 1024 * 1024
    processing_enabled: bool = True

    @property
    def database_path(self) -> Path:
        """Return the SQLite database path."""
        return self.data_dir / "sessions.sqlite3"

    @property
    def sessions_dir(self) -> Path:
        """Return the per-session artifact directory."""
        return self.data_dir / "sessions"
