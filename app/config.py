from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_mode: Literal["demo", "live"] = "demo"
    movie_source: Literal["imdb", "sample"] = "imdb"
    llm_provider: Literal["openai", "azure"] = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    aoai_endpoint: str = ""
    aoai_api_key: str = ""
    aoai_deploy_gpt41_mini: str = ""
    aoai_deploy_embed_3_small: str = ""
    azure_api_version: str = "2024-10-21"
    react_max_rounds: int = 6
    rag_pool_size: int = 60
    data_dir: str = "runtime"
