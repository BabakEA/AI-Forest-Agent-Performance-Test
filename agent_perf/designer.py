"""Pure functions for the AI Forest visual configuration studio.

These helpers never import Streamlit and never write authentication tokens to JSON.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import asdict, fields
from typing import Any
from urllib.parse import urlsplit

from .capacity import CapacityInputs
from .models import Case, Suite

ENV_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
SECRET_HEADER_NAMES = {'authorization', 'proxy-authorization', 'x-api-key', 'api-key', 'x-auth-token', 'cookie', 'set-cookie'}


def synthetic_words(count: int) -> str:
    """Return a repeatable, benign payload of exactly ``count`` whitespace-separated words."""
    if not isinstance(count, int) or not 0 <= count <= 3000:
        raise ValueError('Synthetic word count must be between 0 and 3,000.')
    words = ('synthetic benchmark payload for safe repeatable testing without customer records '
             'measure latency throughput and response quality only ').split()
    return ' '.join(words[i % len(words)] for i in range(count))


def template_case(kind: str, *, name: str = '') -> dict[str, Any]:
    """A complete Case-compatible example with no credentials and no side effects."""
    if kind not in {'mcp', 'api', 'agent', 'llm'}:
        raise ValueError('Choose MCP, API, agent or LLM.')
    defaults = {
        'mcp': ('home-mcp-discovery', 'http://127.0.0.1:9135/mcp', 'POST', {}),
        'api': ('cipher-web-health', 'http://127.0.0.1:9101/', 'GET', None),
        'agent': ('cipher-agent-verify-route', 'http://127.0.0.1:9102/agent', 'POST', {'query': 'Reply OK. Do not write memory.'}),
        'llm': ('gemma4-26b', 'http://127.0.0.1:4004/v1/chat/completions', 'POST', {
            'messages': [{'role': 'system', 'content': 'Synthetic test only. Reply OK.'},
                         {'role': 'user', 'content': 'Reply OK.'}],
            'max_tokens': 32, 'temperature': 0,
        }),
    }
    label, url, method, payload = defaults[kind]
    value = asdict(Case(name=name or label, kind=kind, url=url, method=method, payload=payload))
    value.pop('auth_token', None)
    if kind == 'agent':
        value['enabled'] = False  # User must verify correct route and payload contract.
    if kind == 'llm':
        value['token_env'] = 'LLM_GATEWAY_TOKEN'
        value['model'] = 'gemma4:26b'
    return value


def default_suite() -> dict[str, Any]:
    suite = asdict(Suite(mode='mock', test_type='smoke', requests_per_case=10,
                          concurrency=1, concurrency_levels=[1, 2, 4, 8], rps_limit=1,
                          timeout_s=30, warmup=0, soak_seconds=30))
    suite['cases'] = [template_case('llm'), template_case('mcp'), template_case('api')]
    suite.pop('ack_live', None)
    return suite


def _safe_case(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError('Each test case must be a JSON object.')
    case = Case.from_dict(raw)
    if case.token_env and not ENV_PATTERN.fullmatch(case.token_env):
        raise ValueError(f'{case.name}: token_env must be an environment variable name (e.g. LLM_GATEWAY_TOKEN).')
    if case.model_env and not ENV_PATTERN.fullmatch(case.model_env):
        raise ValueError(f'{case.name}: model_env must be an environment variable name (e.g. LLM_MODEL).')
    if not isinstance(case.headers, dict):
        raise ValueError(f'{case.name}: headers must be a JSON object.')
    if any(str(k).lower() in SECRET_HEADER_NAMES for k in case.headers):
        raise ValueError(f'{case.name}: do not place credentials in headers JSON. Use the masked token input or token_env.')
    if 'auth_token' in raw and raw['auth_token']:
        raise ValueError(f'{case.name}: actual tokens are never allowed inside exported JSON.')
    # Export only the fields consumed by Case.from_dict, including complete payloads.
    out = asdict(case)
    out.pop('auth_token', None)
    return out


def make_benchmark_config(settings: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    allowed = {f.name for f in fields(Suite)} - {'cases', 'ack_live'}
    cfg = {k: v for k, v in settings.items() if k in allowed}
    cfg['cases'] = [_safe_case(c) for c in cases]
    case_names = [c['name'] for c in cfg['cases']]
    if len(case_names) != len(set(case_names)):
        raise ValueError('Test case names must be unique so reports can identify each result.')
    suite = Suite.from_dict(cfg)
    # Validate the active cases without requiring live approval for a JSON export.
    if suite.mode == 'live':
        suite.ack_live = True
    suite.validate()
    return cfg


def make_capacity_config(raw: dict[str, Any]) -> dict[str, Any]:
    # Preserve exact native schema, don't export keys the forecast CLI will ignore.
    obj = CapacityInputs.from_dict(raw)
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', obj.project):
        raise ValueError('Kubernetes project prefix must be lowercase letters, digits and hyphens.')
    if len({x.name for x in obj.services}) != len(obj.services):
        raise ValueError('Service names must be unique.')
    for svc in obj.services:
        if svc.cpu_limit_m < svc.cpu_request_m or svc.memory_limit_mib < svc.memory_request_mib:
            raise ValueError(f'{svc.name}: Kubernetes resource limits must be >= requests.')
        if svc.min_ha_replicas < 0 or svc.max_replicas < 1:
            raise ValueError(f'{svc.name}: replicas must have min >= 0 and max >= 1.')
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', svc.name):
            raise ValueError(f'Invalid Kubernetes service name: {svc.name!r}')
    return asdict(obj)


def sanitized_env_example(config: dict[str, Any]) -> str:
    names = sorted({c.get('token_env', '') for c in config.get('cases', []) if c.get('token_env')})
    names += sorted({c.get('model_env', '') for c in config.get('cases', []) if c.get('model_env') and c.get('model_env') not in names})
    lines = ['# AI Forest benchmark secrets / model overrides',
             '# Local only. Never commit a real .env to a repository.',
             '# Fill these placeholders in a local .env file.', '']
    lines.extend(f'{name}="REPLACE_ME"' for name in names)
    return '\n'.join(lines) + '\n'


def make_bundle(config: dict[str, Any], capacity: dict[str, Any]) -> bytes:
    bench = make_benchmark_config(config, config.get('cases', []))
    cap = make_capacity_config(capacity)
    guide = ("AI FOREST CONFIGURATION STUDIO — EXPORT\n\n"
             "1. Extract performance_test.json and capacity_forecast.json into toolkit/examples/.\n"
             "2. Copy .env.example into the toolkit root as .env and replace the placeholders.\n"
             "3. Never commit or share .env. Raw tokens are never exported in this bundle.\n"
             "4. Mock: python -m agent_perf benchmark --config examples/performance_test.json --out results/mock\n"
             "5. Live: verify targets, rate caps and authorization; run with --ack-live.\n"
             "6. Forecast: python -m agent_perf forecast --config examples/capacity_forecast.json --out results/capacity\n"
             "7. Forecasts are assumption based, not production capacity certifications.\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('performance_test.json', json.dumps(bench, indent=2) + '\n')
        z.writestr('capacity_forecast.json', json.dumps(cap, indent=2) + '\n')
        z.writestr('.env.example', sanitized_env_example(bench))
        z.writestr('README_SETUP.txt', guide)
    return buf.getvalue()


def safe_json(raw: dict[str, Any]) -> str:
    return json.dumps(raw, indent=2, ensure_ascii=False) + '\n'


def validate_url_and_secret_mode(url: str, token_env: str = '') -> None:
    parts = urlsplit(url)
    if parts.username or parts.password or parts.query:
        raise ValueError('Do not include credentials or query tokens in URL. Use token_env / the session-only password field.')
    if token_env and not ENV_PATTERN.fullmatch(token_env):
        raise ValueError('Environment variable name must contain only letters, digits and underscores, starting with a letter or underscore.')
