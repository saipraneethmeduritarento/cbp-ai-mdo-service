from enum import Enum
from typing import Union
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class EnvironmentOption(str, Enum):
    LOCAL = "local"
    STAGING = "staging"
    PRODUCTION = "production"

class Settings(BaseSettings):
    """
    Application settings loaded from environment variables or a .env file.
    """
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: EnvironmentOption = EnvironmentOption.LOCAL
    LOG_LEVEL: str = "INFO"

    APP_NAME: str = "MDO Approval System"
    APP_DESC: str = "API for managing MDO approval requests"
    APP_VERSION: str = "1.0.0"
    APP_ROOT_PATH: str = "/mdo-tpc-ai"

    REQUIRED_ROLE: str = "PUBLIC" # set "cbp_creator" for production

    CBP_API_KEY: bool = False  # set True in .env to skip the real CBP API call

    DATABASE_URL: str

# Create a settings instance that can be imported by other modules
settings = Settings()