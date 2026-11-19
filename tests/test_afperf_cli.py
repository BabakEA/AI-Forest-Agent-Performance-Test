import json
from pathlib import Path
from unittest.mock import patch

import pytest
from agent_perf import afperf_cli


def test_apt_init_produces_valid_configs(tmp_path):
    assert afperf_cli.main(['init',str(tmp_path/'client')]) == 0
    p = tmp_path / 'client'
    from agent_perf.models import Suite
    from agent_perf.capacity import CapacityInputs
    suite = Suite.from_dict(json.loads((p/'benchmark.json').read_text()))
    suite.validate()
    assert suite.mode == 'mock'
    CapacityInputs.from_dict(json.loads((p/'forecast.json').read_text()))
    assert (p/'.env.example').exists() and not (p/'.env').exists()
    assert (p/'examples'/'ai_forest_01_gateway_chat.json').exists()


def test_apt_does_not_overwrite_existing_secrets_or_configs(tmp_path):
    assert afperf_cli.main(['init',str(tmp_path)]) == 0
    (tmp_path/'.env').write_text('LLM_GATEWAY_TOKEN=LOCAL_SECRET')
    (tmp_path/'benchmark.json').write_text('DO_NOT_OVERWRITE')
    assert afperf_cli.main(['init',str(tmp_path)]) == 0
    assert (tmp_path/'benchmark.json').read_text() == 'DO_NOT_OVERWRITE'
    assert afperf_cli.main(['init',str(tmp_path),'--force']) == 0
    assert (tmp_path/'.env').read_text() == 'LLM_GATEWAY_TOKEN=LOCAL_SECRET'
    assert json.loads((tmp_path/'benchmark.json').read_text())['mode'] == 'mock'


def test_apt_docker_generates_buildable_source_scaffold_without_secrets(tmp_path, monkeypatch):
    assert afperf_cli.main(['init',str(tmp_path)]) == 0
    (tmp_path/'.env').write_text('LLM_GATEWAY_TOKEN=SUPER_PRIVATE_TOKEN')
    monkeypatch.chdir(tmp_path)
    assert afperf_cli.main(['docker']) == 0
    docker = tmp_path/'docker'
    assert (docker/'src'/'pyproject.toml').exists()
    assert (docker/'src'/'agent_perf'/'ui'/'dashboard.py').exists()
    assert (docker/'Dockerfile').exists()
    assert (docker/'docker-compose.yml').exists()
    assert (docker/'start.sh').exists()
    assert (docker/'config'/'benchmark.json').exists()
    assert not (docker/'config'/'.env').exists()
    assert not any(p.name == '.env' for p in docker.rglob('*'))
    assert 'SUPER_PRIVATE_TOKEN' not in '\n'.join(f.read_text(errors='ignore') for f in docker.rglob('*') if f.is_file())
    assert afperf_cli.main(['docker']) == 2  # fail rather than silently overwrite
    assert afperf_cli.main(['docker','--force']) == 0


def test_docker_rejects_raw_authorization_header(tmp_path, monkeypatch):
    assert afperf_cli.main(['init',str(tmp_path)]) == 0
    bench = json.loads((tmp_path/'benchmark.json').read_text())
    bench['cases'][0]['headers']['Authorization']='Bearer THIS_IS_A_SECRET'
    (tmp_path/'benchmark.json').write_text(json.dumps(bench))
    monkeypatch.chdir(tmp_path)
    assert afperf_cli.main(['docker']) == 2
    assert not (tmp_path/'docker'/'config'/'benchmark.json').exists()


def test_cli_start_invokes_installed_streamlit(monkeypatch):
    commands=[]
    monkeypatch.setattr(afperf_cli.subprocess,'call',lambda c:commands.append(c) or 0)
    assert afperf_cli.main(['start','--headless','--port','8527']) == 0
    args=commands[0]
    assert args[1:4]==['-m','streamlit','run']
    assert args[-1]=='true' and '8527' in args


def test_forecast_accepts_sibling_benchmark_config(tmp_path, monkeypatch):
    assert afperf_cli.main(['init',str(tmp_path)]) == 0
    monkeypatch.chdir(tmp_path)
    assert afperf_cli.main(['forecast','benchmark.json','--out','results/x']) == 0
    assert (tmp_path/'results/x/CAPACITY_REPORT.md').exists()


def test_rename_removes_os_package_manager_entrypoint_and_updates_docker(tmp_path, monkeypatch):
    import agent_perf
    root = Path(agent_perf.__file__).parent.parent
    project_metadata = (root / 'pyproject.toml').read_text(encoding='utf-8')
    assert '\nafp erf =' not in project_metadata
    assert '\napt =' not in project_metadata
    assert '\nafperf = "agent_perf.afperf_cli:main"' in project_metadata
    assert '\naiforest-perf = "agent_perf.afperf_cli:main"' in project_metadata
    assert afperf_cli.main(['init', str(tmp_path)]) == 0
    monkeypatch.chdir(tmp_path)
    assert afperf_cli.main(['docker']) == 0
    generated = (tmp_path/'docker'/'Dockerfile').read_text()
    compose = (tmp_path/'docker'/'docker-compose.yml').read_text()
    assert 'CMD ["afperf", "start"' in generated
    assert 'afperf-dashboard:' in compose
    assert 'CMD ["apt"' not in generated
