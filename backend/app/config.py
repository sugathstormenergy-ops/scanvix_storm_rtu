"""
Storm Energy RTU Platform — Central Configuration
All operational parameters are loaded from environment variables.
Never hardcode connection strings, credentials, or ports.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Every value can be overridden by an environment variable of the same name
    (uppercase). Ansible injects these via the .env file it writes to the
    deployment target.  Sensitive values are stored in Ansible Vault and are
    never committed to source control.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "staging", "production"] = "production"
    APP_NAME: str = "Storm Energy RTU Platform"
    APP_VERSION: str = "1.0.0"
    LOG_LEVEL: str = "INFO"

    # ── API server ────────────────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_SECRET_KEY: str = Field(..., description="JWT signing secret — set in Ansible Vault")
    API_TOKEN_EXPIRE_MINUTES: int = 60

    # ── SQL Server ────────────────────────────────────────────────────────────
    SQL_SERVER: str = Field(..., description="SQL Server hostname or IP")
    SQL_PORT: int = 1433
    SQL_DATABASE: str = "STORM_ENERGY_RTU"
    # Leave both empty to use Windows Integrated Authentication (Trusted_Connection=yes).
    # The NSSM service must run as a Windows account with SQL Server access.
    # Supply non-empty values only when SQL Server authentication is explicitly required.
    SQL_USERNAME: str = Field(default="", description="SQL Server login — leave empty for Windows Integrated Authentication")
    SQL_PASSWORD: str = Field(default="", description="SQL Server password — leave empty for Windows Integrated Authentication")
    SQL_DRIVER: str = "ODBC Driver 17 for SQL Server"
    SQL_POOL_SIZE: int = 10
    SQL_MAX_OVERFLOW: int = 20
    SQL_POOL_RECYCLE: int = 1800  # seconds

    @property
    def database_url(self) -> str:
        """SQLAlchemy connection URL for pyodbc/MSSQL.

        Selects authentication mode based on SQL_USERNAME / SQL_PASSWORD:
          - Both non-empty  → SQL Server authentication (UID/PWD)
          - Either empty    → Windows Integrated Authentication (Trusted_Connection=yes)
                             Requires the Windows service account to have SQL Server access.
        """
        import urllib.parse
        base = (
            f"DRIVER={{{self.SQL_DRIVER}}};"
            f"SERVER={self.SQL_SERVER},{self.SQL_PORT};"
            f"DATABASE={self.SQL_DATABASE};"
        )
        if self.SQL_USERNAME and self.SQL_PASSWORD:
            # SQL Server authentication
            params = base + f"UID={self.SQL_USERNAME};PWD={self.SQL_PASSWORD};TrustServerCertificate=yes;"
        else:
            # Windows Integrated Authentication
            params = base + "Trusted_Connection=yes;TrustServerCertificate=yes;"
        return f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(params)}"

    # ── MQTT broker ───────────────────────────────────────────────────────────
    MQTT_HOST: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_TLS_PORT: int = 8883
    MQTT_TLS_ENABLED: bool = False
    # Windows deployment (scanvix109): app-side TLS material lives under
    # E:\StormEnergyRTU\certs, a sibling of app/config/logs/scripts managed
    # by the Ansible "directories" role (see roles/directories/tasks/main.yml
    # and inventory/group_vars/all.yml: scanvix_certs_dir). These are DEFAULT
    # fallback values only -- the deployed .env always sets the real values
    # via Ansible (env.j2: MQTT_CA_CERT / MQTT_CLIENT_CERT / MQTT_CLIENT_KEY).
    # No certificate files exist at these paths yet; TLS remains disabled
    # (MQTT_TLS_ENABLED defaults to False) until they are provisioned.
    MQTT_CA_CERT: str = r"E:\StormEnergyRTU\certs\ca.crt"
    MQTT_CLIENT_CERT: str = r"E:\StormEnergyRTU\certs\client.crt"   # optional -- only used for mutual TLS
    MQTT_CLIENT_KEY: str = r"E:\StormEnergyRTU\certs\client.key"    # optional -- only used for mutual TLS
    MQTT_USERNAME: str = Field(default="", description="Broker username")
    MQTT_PASSWORD: str = Field(default="", description="Broker password — set in Ansible Vault")
    MQTT_CLIENT_ID: str = "storm-rtu-consumer"
    MQTT_KEEPALIVE: int = 60
    MQTT_QOS: int = 1
    MQTT_RECONNECT_DELAY: int = 5   # seconds between reconnect attempts
    MQTT_MAX_RECONNECT_DELAY: int = 120

    # ── TCP listener ──────────────────────────────────────────────────────────
    TCP_HOST: str = "0.0.0.0"
    TCP_PORT: int = 8100
    TCP_TIMEOUT: int = 300          # seconds of inactivity before disconnect
    TCP_MAX_CONNECTIONS: int = 512
    TCP_BUFFER_SIZE: int = 4096

    # ── Telemetry pipeline ────────────────────────────────────────────────────
    DEDUP_WINDOW_SECONDS: int = 30  # identical device+timestamp within this window = duplicate
    HISTORICAL_THRESHOLD_SECONDS: int = 300  # if RTU ts is older than 5 min, treat as historical

    # ── Modbus / RS485 (server-side representation) ──────────────────────────
    # Actual register mapping is provided by Storm and stored in DeviceConfiguration.
    # These are defaults only.
    MODBUS_DEFAULT_BAUD_RATE: int = 9600
    MODBUS_DEFAULT_SLAVE_ID: int = 1

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return upper


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton settings instance."""
    return Settings()
