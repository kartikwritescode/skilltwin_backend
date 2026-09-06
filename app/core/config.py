from typing import List, Union, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    # Application
    APP_NAME: str = "SkillTwin Backend"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    API_V1_STR: str = "/api/v1"

    # Supabase / Postgres
    SUPABASE_URL: str = Field(default="https://placeholder.supabase.co", description="Supabase project URL")
    SUPABASE_SERVICE_ROLE_KEY: str = Field(default="placeholder-service-role-key", description="Supabase service role secret key")
    SUPABASE_ANON_KEY: str = Field(default="placeholder-anon-key", description="Supabase anonymous client key")
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./skilltwin.db",
        description="Database connection URL"
    )

    # AI / LLM Configuration
    LLM_PROVIDER: str = Field(default="gemini", description="Selected LLM provider (mock, openai, gemini, ollama)")
    LLM_API_KEY: str = Field(default="placeholder-api-key", description="API key for active LLM provider")
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Gemini API key alias")
    LLM_MODEL: str = Field(default="gemini-3.6-flash", description="Model identifier for generative tasks")
    GEMINI_MODEL: Optional[str] = Field(default=None, description="Gemini model alias")
    EMBEDDING_MODEL: str = Field(default="text-embedding-004", description="Model identifier for vector embeddings")

    @property
    def effective_api_key(self) -> str:
        if self.LLM_API_KEY and self.LLM_API_KEY != "placeholder-api-key":
            return self.LLM_API_KEY
        if self.GEMINI_API_KEY and self.GEMINI_API_KEY != "placeholder-api-key":
            return self.GEMINI_API_KEY
        return self.LLM_API_KEY

    @property
    def effective_model(self) -> str:
        if self.GEMINI_MODEL:
            return self.GEMINI_MODEL
        return self.LLM_MODEL

    # Security & CORS
    ALLOWED_ORIGINS: List[str] = ["*"]
    SUPABASE_JWT_SECRET: str = Field(
        default="skilltwin-supabase-jwt-secret-key-development-mode-2026",
        description="JWT secret used to sign and verify Supabase user tokens"
    )
    JWT_SECRET_KEY: str = "skilltwin-development-secret-key"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v_str = v.strip()
            if v_str.startswith("[") and v_str.endswith("]"):
                try:
                    import json
                    parsed = json.loads(v_str)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [i.strip() for i in v_str.split(",") if i.strip()]
        elif isinstance(v, list):
            return [str(i).strip() for i in v if str(i).strip()]
        raise ValueError(v)


settings = Settings()
