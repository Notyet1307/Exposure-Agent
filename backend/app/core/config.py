import secrets
import warnings
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AnyUrl, BeforeValidator, EmailStr, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_DEFAULT_VALUES = {
    "SECRET_KEY": frozenset({"changethis", "not-for-production-issue4-secret"}),
    "POSTGRES_PASSWORD": frozenset(
        {"changethis", "not-for-production-issue4-postgres"}
    ),
    "FIRST_SUPERUSER": frozenset({"admin@example.com"}),
    "FIRST_SUPERUSER_PASSWORD": frozenset(
        {"changethis", "not-for-production-issue4-admin"}
    ),
}


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # 60 minutes * 24 hours * 8 days = 8 days
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str
    ARTIFACT_ROOT: Path = Path("/app/artifacts")
    OCTOBUS_URL: str = "http://octobus:9000"
    OCTOBUS_TIMEOUT_SECONDS: float = 15.0
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value in REPOSITORY_DEFAULT_VALUES.get(var_name, frozenset()):
            message = (
                f"The value of {var_name} is a repository default, "
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    def _enforce_non_default_secrets(self) -> None:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret("FIRST_SUPERUSER", self.FIRST_SUPERUSER)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )


settings = Settings()  # type: ignore
settings._enforce_non_default_secrets()
