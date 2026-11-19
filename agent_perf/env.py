"""Read AI Forest local secrets without printing or exporting them.

A .env file is optional. Real environment variables always take precedence.
No .env values are copied into benchmark artifacts or serialized configs.
"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv


def load_project_env() -> bool:
    """Load the toolkit-root .env, or an explicit AI_FOREST_ENV_FILE path."""
    configured = os.environ.get("AI_FOREST_ENV_FILE", "").strip()
    env_path = (Path(configured).expanduser() if configured else ((Path.cwd() / ".env") if (Path.cwd() / ".env").is_file() else Path(__file__).resolve().parent.parent / ".env"))
    return bool(load_dotenv(dotenv_path=env_path, override=False)) if env_path.is_file() else False
