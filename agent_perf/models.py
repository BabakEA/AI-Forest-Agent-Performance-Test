"""Validated, serializable workload configuration and per-call observations."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
from urllib.parse import urlsplit, urlunsplit

KINDS = {'mcp', 'api', 'agent', 'llm'}
TESTS = {'smoke', 'load', 'ramp', 'soak'}
MCP_VERSIONS = {'2025-11-25', '2026-07-28'}

@dataclass
class Case:
    name: str
    kind: str
    enabled: bool = True  # off by default for unverified/private-memory operations
    url: str = ''
    method: str = 'POST'
    payload: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)
    token_env: str = ''
    auth_token: str = field(default='', repr=False)  # memory only, never serialize
    expected_status: list[int] = field(default_factory=lambda: [200])
    expected_json_path: str = ''  # e.g. response.status, $.result.answer
    expected_value: Any = None
    model: str = 'mock-model'
    model_env: str = ''  # optional deployed model override from environment
    stream: bool = False
    mcp_version: str = '2025-11-25'
    mcp_tool: str = ''
    mcp_expected_tool: str = ''  # tools/list must advertise this name, if set
    mcp_tool_args: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> 'Case':
        allowed = {x.name for x in cls.__dataclass_fields__.values()}
        return cls(**{k:v for k,v in obj.items() if k in allowed and k!='auth_token'})

    def validate(self, live: bool) -> None:
        if not self.enabled:return  # disabled templates may contain non-routable placeholders
        if self.kind not in KINDS: raise ValueError(f'Unsupported target kind: {self.kind}')
        if not self.name.strip(): raise ValueError('Case name is required')
        if self.kind == 'mcp' and self.mcp_version not in MCP_VERSIONS: raise ValueError('Bad MCP version')
        if self.payload is not None and not isinstance(self.payload, dict): raise ValueError('Payload must be a JSON object')
        if self.kind == 'mcp' and not isinstance(self.mcp_tool_args, dict): raise ValueError('MCP tool arguments must be a JSON object')
        if self.kind == 'mcp' and self.mcp_tool:
            bad = ('create','delete','remove','update','write','merge','push','send','approve','submit','close','revoke','transfer','publish')
            tool_name = self.mcp_tool.lower()
            if any(token in tool_name.split('_') for token in bad):
                raise ValueError(f'Refusing potentially mutating MCP tool {self.mcp_tool!r}. Use a read-only tool for benchmarks.')
        if live:
            u = urlsplit(self.url)
            if u.scheme not in ('http','https') or not u.hostname:
                raise ValueError(f'Case {self.name}: supply a full http(s) URL')
            if u.username or u.password: raise ValueError('No secrets in URLs; use token environment variable instead')
            if u.query: raise ValueError('Do not put access tokens or query parameters in benchmark URLs')

    def public(self) -> dict[str, Any]:
        """Only safe metadata for results, NOT raw payload or auth headers."""
        u = urlsplit(self.url)
        safe_url = urlunsplit((u.scheme,u.netloc,u.path,'','')) if u.scheme else ''
        return {'name':self.name,'kind':self.kind,'enabled':self.enabled,'url':safe_url,
                'method':self.method.upper(),'expected_status':self.expected_status,
                'mcp_version':self.mcp_version if self.kind=='mcp' else None,
                'mcp_tool':self.mcp_tool if self.kind=='mcp' else None,
                'mcp_expected_tool':self.mcp_expected_tool if self.kind=='mcp' else None,
                'model_env':self.model_env if self.kind=='llm' else None,
                'stream':self.stream if self.kind=='llm' else None,
                'payload_bytes':len(__import__('json').dumps(self.payload).encode()) if self.payload else 0}

@dataclass
class Suite:
    mode: str = 'mock'
    test_type: str = 'load'
    requests_per_case: int = 60
    concurrency: int = 4
    concurrency_levels: list[int] = field(default_factory=lambda: [1,2,4,8])
    rps_limit: float = 0
    timeout_s: float = 20
    warmup: int = 1
    soak_seconds: float = 30
    ack_live: bool = False
    cases: list[Case] = field(default_factory=list)

    @classmethod
    def from_dict(cls, obj: dict[str,Any]) -> 'Suite':
        known = {x.name for x in cls.__dataclass_fields__.values()}
        kwargs = {k:v for k,v in obj.items() if k in known and k!='cases'}
        return cls(**kwargs, cases=[Case.from_dict(c) for c in obj.get('cases',[])])

    def validate(self) -> None:
        if self.mode not in {'mock','live'}: raise ValueError('mode must be mock or live')
        if self.test_type not in TESTS: raise ValueError('Unknown test type')
        if not self.cases or not any(c.enabled for c in self.cases): raise ValueError('At least one enabled case is required')
        if not 1 <= self.requests_per_case <= 50000: raise ValueError('requests_per_case must be 1–50,000')
        if not 1 <= self.concurrency <= 100: raise ValueError('concurrency must be 1–100')
        if not self.concurrency_levels or any(not 1 <= int(x) <= 100 for x in self.concurrency_levels):
            raise ValueError('concurrency_levels must be 1–100')
        if not 0 < self.timeout_s <= 300 or self.warmup < 0 or self.rps_limit < 0:
            raise ValueError('Invalid timeout, warmup or rate limit')
        if self.mode=='live':
            if not self.ack_live: raise ValueError('Live traffic requires explicit --ack-live / dashboard approval')
            if self.requests_per_case > 1000: raise ValueError('Live tests capped at 1,000 requests per case/level')
            if self.concurrency > 8 or max(self.concurrency_levels)>8:
                raise ValueError('Live concurrency capped at 8 for protection')
            if self.rps_limit <= 0 or self.rps_limit > 10:
                raise ValueError('Live tests require 0 < rps_limit <= 10')
            if self.test_type == 'soak' and self.soak_seconds > 120:
                raise ValueError('Live soak is limited to 120 seconds')
        for c in self.cases: c.validate(self.mode=='live')

    def public(self) -> dict[str,Any]:
        return {k:v for k,v in asdict(self).items() if k not in ('cases','ack_live')} | {'cases':[c.public() for c in self.cases]}

@dataclass
class Observation:
    case: str
    kind: str
    concurrency: int
    index: int
    start_s: float
    latency_ms: float
    ok: bool
    status: int | None
    first_byte_ms: float | None = None
    first_token_ms: float | None = None
    request_bytes: int = 0
    response_bytes: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    error_type: str = ''
