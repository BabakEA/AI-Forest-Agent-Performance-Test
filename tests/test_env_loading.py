import os
from pathlib import Path
from agent_perf.env import load_project_env


def test_env_file_loads_without_overriding_existing(tmp_path, monkeypatch):
    f = tmp_path / "local.env"
    f.write_text("LLM_GATEWAY_TOKEN=example_only\n", encoding="utf8")
    monkeypatch.setenv("AI_FOREST_ENV_FILE", str(f))
    monkeypatch.delenv("LLM_GATEWAY_TOKEN", raising=False)
    assert load_project_env()
    assert os.environ["LLM_GATEWAY_TOKEN"] == "example_only"
    monkeypatch.setenv("LLM_GATEWAY_TOKEN", "preexisting")
    assert load_project_env()
    assert os.environ["LLM_GATEWAY_TOKEN"] == "preexisting"
