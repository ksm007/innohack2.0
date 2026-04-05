from functools import lru_cache
from pathlib import Path
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = None
    openai_model: str = "gpt-5.1-mini"
    openai_base_url: str | None = None

    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"

    pageindex_root: str | None = None
    pageindex_python: str | None = None
    pageindex_warmup_on_startup: bool = False

    anton_rx_docs_dir: str = "docs"
    anton_rx_storage_dir: str = "storage"

    @property
    def docs_dir(self) -> Path:
        return ROOT_DIR / self.anton_rx_docs_dir

    @property
    def storage_dir(self) -> Path:
        return ROOT_DIR / self.anton_rx_storage_dir

    @property
    def cache_dir(self) -> Path:
        return self.storage_dir / "cache"

    @property
    def extraction_dir(self) -> Path:
        return self.storage_dir / "extractions"

    @property
    def pageindex_dir(self) -> Path:
        return self.storage_dir / "pageindex"

    @property
    def sqlite_path(self) -> Path:
        return self.storage_dir / "anton_rx_track.db"

    @property
    def prompts_dir(self) -> Path:
        return ROOT_DIR / "prompts"

    @property
    def pageindex_root_path(self) -> Path | None:
        return Path(self.pageindex_root).expanduser().resolve() if self.pageindex_root else None

    @property
    def pageindex_python_path(self) -> str:
        if not self.pageindex_python or self.pageindex_python in {"python", "python3"}:
            return sys.executable
        return self.pageindex_python

    @property
    def neo4j_enabled(self) -> bool:
        return bool(self.neo4j_uri and self.neo4j_username and self.neo4j_password)

    def ensure_directories(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.extraction_dir.mkdir(parents=True, exist_ok=True)
        self.pageindex_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
