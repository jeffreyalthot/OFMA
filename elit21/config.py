from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SECRET = "elit21-secret"
PRODUCTION_ENV_NAMES = {"prod", "production", "live"}


@dataclass(frozen=True)
class AppConfig:
    environment: str
    secret_key: str
    session_cookie_secure: bool
    force_https: bool
    hsts_enabled: bool


def is_production_environment(environment: str | None = None) -> bool:
    env = (environment or os.getenv("ELIT21_ENV") or os.getenv("FLASK_ENV") or "development")
    return env.strip().lower() in PRODUCTION_ENV_NAMES


def load_app_config() -> AppConfig:
    environment = (os.getenv("ELIT21_ENV") or os.getenv("FLASK_ENV") or "development").strip().lower()
    secret_key = os.getenv("ELIT21_SECRET", DEFAULT_SECRET).strip()
    production = is_production_environment(environment)
    if production and secret_key == DEFAULT_SECRET:
        raise RuntimeError(
            "ELIT21_SECRET doit être configuré avec une valeur non défaut en production."
        )
    force_https = production or os.getenv("ELIT21_FORCE_HTTPS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return AppConfig(
        environment=environment,
        secret_key=secret_key,
        session_cookie_secure=production,
        force_https=force_https,
        hsts_enabled=production,
    )
