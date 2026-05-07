from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


PACKAGE_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ModelConfig:
    config_name: str
    model_id: str
    display_name: str
    provider_id: str
    provider_name: str
    base_url: str
    api_key_env: Optional[str]
    api_key: Optional[str]
    rate_limit_rpm: int
    timeout_seconds: int
    extra_body: dict[str, object]

    def get_api_key(self) -> str | None:
        if self.api_key_env:
            value = os.environ.get(self.api_key_env) or load_dotenv_value(self.api_key_env)
            if value:
                return value
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            raise ValueError(f"Missing API key environment variable: {self.api_key_env}")
        return None


def load_model_config(model_name: str | None = None, model_file: str | None = None) -> ModelConfig:
    if model_file:
        path = Path(model_file).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Model config file not found: {path}")
        if model_name is None:
            model_name = path.stem
    else:
        path = Path.cwd() / "models" / f"{model_name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Model config not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    provider_id, provider_config, resolved_name, model_config = find_model(raw.get("provider", {}), model_name, path)
    options = provider_config.get("options", {})
    base_url = options.get("baseURL")
    if not base_url:
        raise ValueError(f"Model config {path} is missing provider.options.baseURL")

    return ModelConfig(
        config_name=resolved_name,
        model_id=model_config.get("model", resolved_name),
        display_name=model_config.get("name", resolved_name),
        provider_id=provider_id,
        provider_name=provider_config.get("name", provider_id),
        base_url=base_url.rstrip("/"),
        api_key_env=options.get("apiKeyEnv"),
        api_key=options.get("apiKey") or options.get("api_key"),
        rate_limit_rpm=int(model_config.get("rate_limit_rpm", 50)),
        timeout_seconds=int(model_config.get("timeout_seconds", model_config.get("timeout", 120))),
        extra_body=dict(model_config.get("extra_body", {})),
    )


def find_model(providers: dict, model_name: str | None, path: Path):
    for provider_id, provider_config in providers.items():
        models = provider_config.get("models", {})
        if model_name in models:
            return provider_id, provider_config, model_name, models[model_name]

    all_models = [
        (provider_id, provider_config, fallback_name, model_config)
        for provider_id, provider_config in providers.items()
        for fallback_name, model_config in provider_config.get("models", {}).items()
    ]
    if len(all_models) == 1:
        return all_models[0]
    raise ValueError(f"Model {model_name!r} was not found inside {path}")


def load_dotenv_value(key: str) -> str | None:
    for env_path in (Path.cwd() / ".env.local", Path.cwd() / ".env", PACKAGE_ROOT / ".env"):
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        prefix = f"{key}="
        for line in lines:
            line = line.strip()
            if line.startswith(prefix):
                value = line[len(prefix):].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    return value[1:-1]
                return value
    return None
