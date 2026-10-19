from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = 'Orovalle Platform API'
    app_version: str = '0.1.0'
    log_level: str = 'INFO'
    cors_allow_origins: str = 'http://localhost:5173,http://localhost:8080,http://partes_operaciones.lan.orvana.com.bo,https://partes_operaciones.lan.orvana.com.bo'
    mongo_uri: str
    operaciones_database: str = 'Operaciones'
    gravimetria_database: str = 'griphonv2'
    gravimetria_collection: str = 'datacollector'

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(',') if origin.strip()]

    @property
    def mongodb_database(self) -> str:
        return self.mongo_uri.rsplit('/', maxsplit=1)[-1].split('?', maxsplit=1)[0] or 'orovalle_platform'


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()