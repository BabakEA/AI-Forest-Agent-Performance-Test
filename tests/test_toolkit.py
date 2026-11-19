import asyncio
import json
from pathlib import Path
import pytest
from agent_perf.models import Case, Suite
from agent_perf.runner import run_suite
from agent_perf.report import percentile,save_benchmark
from agent_perf.capacity import CapacityInputs,forecast,write_capacity_report


def test_percentiles():
    assert percentile([10,20,30,40,50],20)==18
    assert percentile([10,20,30,40,50],50)==30
    assert percentile([10,20,30,40,50],99)==49.6
    assert percentile([],95) is None


def test_capacity_demand_and_manifests(tmp_path):
    cfg=CapacityInputs(users=10000)
    r=forecast(cfg)
    assert r['workflows_tps_peak']==50
    assert r['llm_calls_per_sec']==100
    assert r['llm_total_tokens_per_min']==7_500_000
    assert r['total_replicas']==28
    assert write_capacity_report(cfg,tmp_path)['total_replicas']==28
    assert (tmp_path/'CAPACITY_REPORT.md').exists()
    assert (tmp_path/'forecast_pods.png').exists()
    text=(tmp_path/'k8s'/'services-deployments-hpa.yaml').read_text()
    assert 'HorizontalPodAutoscaler' in text and 'apiVersion: apps/v1' in text
    assert 'secretRef' in text


def test_live_rejected_by_default():
    with pytest.raises(ValueError):
        Suite(mode='live',cases=[Case(name='live',kind='api',url='https://example.com')]).validate()


def test_mock_suite_all_kinds(tmp_path):
    cases=[Case('read-github','mcp'),Case('read-github-tool','mcp',mcp_tool='get_file_contents'),
           Case('api','api',method='POST',payload={'x':1},expected_json_path='status',expected_value='ok'),
           Case('agent','agent',payload={'query':'OK'},expected_json_path='status',expected_value='completed'),
           Case('llm','llm',model='mock-model',stream=True)]
    suite=Suite(mode='mock',test_type='smoke',requests_per_case=1,concurrency=1,cases=cases)
    observations,summaries=asyncio.run(run_suite(suite))
    assert len(observations)==5
    assert all(o.ok for o in observations),[(o.case,o.error_type) for o in observations]
    save_benchmark(tmp_path,observations,summaries,suite)
    assert (tmp_path/'dashboard.html').exists()
    assert (tmp_path/'latency_percentiles.png').exists()
    assert (tmp_path/'summary.json').exists()


def test_mcp_modern_mock():
    suite=Suite(mode='mock',test_type='smoke',requests_per_case=1,concurrency=1,
        cases=[Case(name='newer',kind='mcp',mcp_version='2026-07-28')])
    obs,_=asyncio.run(run_suite(suite))
    assert obs[0].ok


def test_ai_forest_profiles_valid_and_memory_disabled():
    from pathlib import Path
    import json
    folder=Path(__file__).parents[1] / 'examples'
    gateway=Suite.from_dict(json.loads((folder/'ai_forest_01_gateway_chat.json').read_text()))
    mcps=Suite.from_dict(json.loads((folder/'ai_forest_02_memory_home_media_audio_mcps.json').read_text()))
    assert gateway.mode == 'live' and gateway.test_type == 'smoke'
    assert any(c.kind == 'llm' and c.model_env == 'LLM_MODEL' for c in gateway.cases)
    assert sum(c.enabled for c in gateway.cases) == 4
    assert sum(c.enabled for c in mcps.cases) == 3
    assert all(not c.enabled for c in mcps.cases if 'redis' in c.name)
    assert all(c.mcp_version == '2025-11-25' for c in mcps.cases if c.kind=='mcp')
    assert len(CapacityInputs.from_dict(json.loads((folder/'ai_forest_03_capacity_forecast.json').read_text())).services)==7


def test_ai_forest_gateway_mock_charts_have_axis_labels(tmp_path):
    from pathlib import Path
    import json
    cfg=json.loads((Path(__file__).parents[1]/'examples'/'ai_forest_01_gateway_chat.json').read_text())
    s=Suite.from_dict(cfg)
    s.mode='mock';s.rps_limit=0
    obs,summaries=asyncio.run(run_suite(s))
    assert all(o.ok for o in obs)
    assert len(obs) == 4
    save_benchmark(tmp_path,obs,summaries,s)
    html=(tmp_path/'dashboard.html').read_text(encoding='utf-8')
    assert 'concurrent workers' in html
    assert 'Latency percentile thresholds' in html
    assert 'Requests per second (RPS)' in html
    assert (tmp_path/'CHART_GUIDE.md').exists()


def test_web_ui_optional_requires_real_selectors():
    from pathlib import Path
    import json
    from web_ui_smoke import validate_config
    conf=json.loads((Path(__file__).parents[1]/'examples'/'ai_forest_web_ui_optional.json').read_text())
    with pytest.raises(ValueError,match='selector'):
        validate_config(conf)
    conf['input_selector']='#chat'
    conf['assistant_message_selector']='.assistant-response'
    validate_config(conf)
    conf['memory_test']=True
    with pytest.raises(ValueError,match='new_chat_selector'):
        validate_config(conf)
