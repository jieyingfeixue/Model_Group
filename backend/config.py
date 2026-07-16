from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    image_storage_mode: str = "local"
    image_local_root: Path = Path("./demo_assets/images")
    metadata_root: Path = Path("./demo_data/metadata")
    datasets_path: Path = Path("./demo_data/datasets.json")
    api_prefix: str = "/api"


settings = Settings()
