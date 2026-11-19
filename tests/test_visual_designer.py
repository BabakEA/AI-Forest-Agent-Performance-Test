"""Security, compatibility and serialization tests for the visual designer."""
import io
import json
import zipfile

import pytest

from agent_perf.capacity import CapacityInputs, forecast
from agent_perf.designer import (
    default_suite, make_benchmark_config, make_capacity_config,
    make_bundle, sanitized_env_example, synthetic_words, template_case,
    validate_url_and_secret_mode,
)
from agent_perf.models import Suite


def test_default_benchmark_export_roundtrips_and_runs_mock():
    defaults=default_suite()
    export=make_benchmark_config(defaults,defaults['cases'])
    suite=Suite.from_dict(export)
    suite.validate()
    assert suite.mode == 'mock'
    assert {c.kind for c in suite.cases} == {'mcp','llm','api'}
    assert 'auth_token' not in json.dumps(export)


def test_all_case_fields_survive_export():
    case=template_case('mcp')
    case.update(mcp_expected_tool='get_status',mcp_tool='get_status',
                mcp_tool_args={'synthetic_id':'x'},headers={'X-Correlation-ID':'synthetic'},
                expected_status=[200,202])
    cfg=make_benchmark_config(default_suite(),[case])
    restored=Suite.from_dict(json.loads(json.dumps(cfg))).cases[0]
    assert restored.mcp_tool_args=={'synthetic_id':'x'}
    assert restored.expected_status==[200,202]
    assert restored.headers['X-Correlation-ID']=='synthetic'


def test_no_raw_token_in_export_bundle():
    conf=default_suite()
    conf['cases'][0]['token_env']='LLM_GATEWAY_TOKEN'
    cap = make_capacity_config(__import__('dataclasses').asdict(CapacityInputs()))
    zipbytes=make_bundle(conf,cap)
    z=zipfile.ZipFile(io.BytesIO(zipbytes))
    assert set(z.namelist()) == {'performance_test.json','capacity_forecast.json','.env.example','README_SETUP.txt'}
    contents=''.join(z.read(p).decode() for p in z.namelist())
    assert 'LLM_GATEWAY_TOKEN="REPLACE_ME"' in contents
    assert 'auth_token' not in z.read('performance_test.json').decode()
    assert 'password123' not in contents


def test_prevent_tokens_embedded_in_headers_or_suite():
    config=default_suite()
    config['cases'][0]['headers']={'Authorization':'Bearer password123'}
    with pytest.raises(ValueError,match='credentials in headers'):
        make_benchmark_config(config,config['cases'])
    config=default_suite()
    config['cases'][0]['auth_token']='password123'
    with pytest.raises(ValueError,match='never allowed inside exported JSON'):
        make_benchmark_config(config,config['cases'])
    with pytest.raises(ValueError,match='credentials or query tokens'):
        validate_url_and_secret_mode('https://example.org/path?token=password123')


def test_duplicate_cases_blocked():
    cfg=default_suite()
    c=template_case('api',name='same')
    with pytest.raises(ValueError,match='unique'):
        make_benchmark_config(cfg,[c,c.copy()])


def test_synthetic_words_are_deterministic_and_exact():
    assert synthetic_words(0)==''
    text=synthetic_words(125)
    assert len(text.split())==125
    assert text==synthetic_words(125)
    with pytest.raises(ValueError):synthetic_words(3001)


def test_capacity_forecast_export_roundtrip():
    cap=make_capacity_config(__import__('dataclasses').asdict(CapacityInputs(users=4000)))
    assert CapacityInputs.from_dict(cap).users==4000
    assert forecast(CapacityInputs.from_dict(cap))['total_replicas']>=8


def test_capacity_service_duplicates_and_bad_limits_blocked():
    cap=__import__('dataclasses').asdict(CapacityInputs())
    cap['services'].append(dict(cap['services'][0]))
    with pytest.raises(ValueError,match='unique'):
        make_capacity_config(cap)
    cap=__import__('dataclasses').asdict(CapacityInputs())
    cap['services'][0]['cpu_limit_m']=5
    with pytest.raises(ValueError,match='limits must be'):
        make_capacity_config(cap)
