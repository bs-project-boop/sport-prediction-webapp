from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "sport_prediction"
    db_user: str = "sportapp"
    db_password: str = ""
    sport_prediction_pin_hash: str = ""
    session_ttl_seconds: int = 3600
    rate_limit_max_failures: int = 5
    rate_limit_window_seconds: int = 300
    rate_limit_lockout_seconds: int = 300
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    @property
    def database_url(self) -> str:
        return f"postgresql+psycopg2://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
