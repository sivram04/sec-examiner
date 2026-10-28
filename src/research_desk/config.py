from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sec_user_agent: str = "ai-research-desk contact@example.com"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    fred_api_key: str = ""

    postgres_url: str = "postgresql://desk:desk@localhost:5432/desk"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    # false: embedded Qdrant on disk under data/qdrant (no Docker needed)
    use_qdrant_server: bool = False
    neo4j_url: str = "bolt://localhost:7687"
    kafka_bootstrap: str = "localhost:19092"


settings = Settings()
