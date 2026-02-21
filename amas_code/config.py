"""Config loader — YAML config with sane defaults + API key management."""
import os
from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "model": "gemini/gemini-3-flash-preview",
    "auto_accept": False,
    "max_context_tokens": 2000000,
    "checkpoint_on_edit": True,
    "stream": True,
    "ignore": ["node_modules", "__pycache__", ".git", "*.pyc", "dist", "build"],
}

# Provider → env var name mapping (litellm also reads these automatically)
PROVIDER_ENV_VARS = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "zhipuai": "ZHIPU_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# Common model shortcuts for autocomplete
KNOWN_MODELS = [
    # Gemini
    "gemini/gemini-3-pro-preview",
    "gemini/gemini-3-flash-preview",
    "gemini/gemini-2.0-flash",
    # Claude
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
    # OpenAI
    "gpt-4o",
    "gpt-4o-mini",
    "o3-mini",
    # DeepSeek
    "deepseek/deepseek-chat",
    "deepseek/deepseek-reasoner",
    # Ollama (local)
    "ollama/llama3",
    "ollama/codellama",
    "ollama/mistral",
    "ollama/qwen2.5-coder",
    # GLM
    "glm-4",
    "glm-4-flash",
]


def load(path: str = ".amas/config.yaml") -> dict:
    """Load config from YAML, merging with defaults."""
    p = Path(path)
    if p.exists():
        user = yaml.safe_load(p.read_text()) or {}
        return {**DEFAULT_CONFIG, **user}
    return DEFAULT_CONFIG.copy()


def save(config: dict, path: str = ".amas/config.yaml") -> None:
    """Save config to YAML file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.dump(config, default_flow_style=False))


def resolve_api_key(config: dict) -> str | None:
    """Resolve API key: config api_keys → env var → None (litellm fallback)."""
    model = config.get("model", "")
    provider = model.split("/")[0] if "/" in model else _guess_provider(model)

    # 1. Check config api_keys dict
    keys = config.get("api_keys", {})
    if provider in keys and keys[provider]:
        return keys[provider]

    # 2. Check environment variable
    env_var = PROVIDER_ENV_VARS.get(provider, "")
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]

    # 3. Return None — litellm will try its own env var lookup
    return None


def _guess_provider(model: str) -> str:
    """Guess provider from model name when no prefix like 'gemini/' is used."""
    model_lower = model.lower()
    if "claude" in model_lower:
        return "anthropic"
    if "gpt" in model_lower or "o1" in model_lower:
        return "openai"
    if "glm" in model_lower:
        return "zhipuai"
    if "deepseek" in model_lower:
        return "deepseek"
    return ""


def set_api_key(provider: str, key: str, path: str = ".amas/config.yaml") -> None:
    """Set an API key for a provider and save to config."""
    config = load(path)
    if "api_keys" not in config:
        config["api_keys"] = {}
    config["api_keys"][provider] = key

    # Also set the env var for the current session so litellm picks it up
    env_var = PROVIDER_ENV_VARS.get(provider, "")
    if env_var:
        os.environ[env_var] = key

    save(config, path)


def set_model(model: str, path: str = ".amas/config.yaml") -> None:
    """Set the default model and save to config."""
    config = load(path)
    config["model"] = model
    save(config, path)
