#!/usr/bin/env python3
"""MCP + OpenAI-compatible LLM latency benchmark, with a localhost-only mock.

Dependencies: httpx >= 0.27. No external calls occur unless --mode live and
--ack-load are both supplied. Not a security or model quality evaluation.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import statistics
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

VERSION_2025 = '2025-11-25'
VERSION_2026 = '2026-07-28'


class LocalMockHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'LocalBenchmarkFixture/1.0'

    def log_message(self, *_args: Any) -> None:
        pass

    def _response(self, code: int, value: dict[str, Any] | None,
                  extra_headers: dict[str, str] | None = None) -> None:
        body = b'' if value is None else json.dumps(value).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_POST(self) -> None:
        try:
            data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            req = json.loads(data)
        except (ValueError, json.JSONDecodeError):
            self._response(400, {'error': 'invalid json'})
            return
        if self.path.rstrip('/') == '/mcp':
            self._mcp(req)
        elif self.path.rstrip('/') == '/v1/chat/completions':
            self._llm(req)
        else:
            self._response(404, {'error': 'not found'})

    def _mcp(self, req: dict[str, Any]) -> None:
        method = req.get('method', '')
        version = self.headers.get('MCP-Protocol-Version', VERSION_2025)
        if version == VERSION_2026:
            meta = req.get('params', {}).get('_meta', {})
            if (meta.get('io.modelcontextprotocol/protocolVersion') != version
                    or self.headers.get('Mcp-Method') != method
                    or (method == 'tools/call' and
                        self.headers.get('Mcp-Name') != req.get('params', {}).get('name'))):
                self._response(400, {'jsonrpc':'2.0','id':req.get('id'),
                                      'error': {'code': -32020, 'message': 'HeaderMismatch'}})
                return
        if method == 'initialize':
            self._response(200, {'jsonrpc':'2.0','id':req.get('id'),
                'result': {'protocolVersion': VERSION_2025, 'capabilities':{'tools':{}},
                           'serverInfo':{'name':'safe-mock-github','version':'1.0'}}},
                {'Mcp-Session-Id': str(uuid.uuid4())})
            return
        if method == 'notifications/initialized':
            self._response(202, None)
            return
        # Heavy-tailed response distribution with occasional 200-400ms spikes.
        r = random.random()
        delay = max(0.005, random.lognormvariate(-3.35, 0.50))
        if r < 0.04:
            delay += random.uniform(0.11, 0.23)
        elif r < 0.06:
            delay += random.uniform(0.05, 0.1)
        time.sleep(delay)
        if method == 'tools/list':
            result = {'tools': [{'name':'get_file_contents',
                'description':'Mock read-only repository content',
                'inputSchema':{'type':'object','properties':{'path':{'type':'string'}}}}]}
        elif method == 'tools/call' and req.get('params', {}).get('name') == 'get_file_contents':
            result = {'content':[{'type':'text','text':'# Mock README\nThis is a local fixture.'}],
                      'isError':False}
        else:
            self._response(200, {'jsonrpc':'2.0','id':req.get('id'),
                    'error': {'code':-32601, 'message': 'Unknown mock method or tool'}})
            return
        self._response(200, {'jsonrpc':'2.0','id':req.get('id'),'result':result})

    def _llm(self, req: dict[str, Any]) -> None:
        if not req.get('model') or not req.get('messages'):
            self._response(400, {'error':'model and messages required'})
            return
        r = random.random()
        wait = max(0.018, random.lognormvariate(-2.55, 0.42))
        if r < 0.045:
            wait += random.uniform(0.25, 0.5)
        time.sleep(wait)
        if req.get('stream', False):
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream; charset=utf-8')
            self.send_header('Cache-Control','no-cache')
            self.send_header('Connection','close')
            self.end_headers()
            chunks = ['Mock ', 'LLM ', 'reply ', 'for ', 'performance ', 'testing.']
            for chunk in chunks:
                event = {'id':'chatcmpl-mock','object':'chat.completion.chunk',
                         'choices':[{'index':0,'delta':{'content':chunk},'finish_reason':None}]}
                self.wfile.write(f'data: {json.dumps(event)}\n\n'.encode())
                self.wfile.flush()
                time.sleep(0.010)
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
            self.close_connection = True
            return
        self._response(200, {'id':'chatcmpl-mock','object':'chat.completion',
             'choices':[{'index':0,'finish_reason':'stop',
                         'message':{'role':'assistant','content':'Mock answer. Not a real model.'}}],
             'usage':{'prompt_tokens':20,'completion_tokens':8,'total_tokens':28}})


def start_mock() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(('127.0.0.1', 0), LocalMockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_port}'


@dataclass
class Sample:
    workload: str
    ok: bool
    latency_ms: float
    first_byte_ms: float | None
    first_token_ms: float | None
    http_status: int | None
    request_bytes: int
    response_bytes: int
    error: str


class Pacer:
    def __init__(self, rps: float):
        self.rps = rps
        self.lock = asyncio.Lock()
        self.next_at = 0.0

    async def wait(self) -> None:
        if self.rps <= 0:
            return
        loop = asyncio.get_running_loop()
        async with self.lock:
            now = loop.time()
            when = max(now, self.next_at)
            self.next_at = when + 1.0 / self.rps
        delay = when - loop.time()
        if delay > 0:
            await asyncio.sleep(delay)


def parse_jsonrpc_or_sse(data: bytes, content_type: str, request_id: int) -> dict[str, Any]:
    if 'text/event-stream' not in content_type:
        parsed = json.loads(data.decode('utf-8'))
        if not isinstance(parsed, dict):
            raise ValueError('JSON-RPC response was not an object')
        return parsed
    for line in data.decode('utf-8', errors='replace').splitlines():
        if line.startswith('data:'):
            value = line[5:].strip()
            if not value or value == '[DONE]':
                continue
            event = json.loads(value)
            if isinstance(event, dict) and event.get('id') == request_id:
                return event
    raise ValueError('No matching JSON-RPC response in SSE stream')


async def send_request(client: httpx.AsyncClient, target_url: str,
                       payload: dict[str, Any], headers: dict[str, str],
                       workload: str, stream_tokens: bool = False) -> Sample:
    request_bytes = len(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    started = time.perf_counter()
    first_byte: float | None = None
    first_token: float | None = None
    response_bytes = 0
    code = None
    received = bytearray()
    error = ''
    try:
        async with client.stream('POST', target_url, json=payload, headers=headers) as response:
            code = response.status_code
            content_type = response.headers.get('content-type', '')
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                if first_byte is None:
                    first_byte = (time.perf_counter() - started) * 1000
                response_bytes += len(chunk)
                received.extend(chunk)
                if stream_tokens and first_token is None:
                    # Detect first content-bearing SSE delta (may differ from first byte).
                    for line in received.decode('utf-8',errors='replace').splitlines():
                        if line.startswith('data:') and line[5:].strip() not in ('', '[DONE]'):
                            try:
                                obj = json.loads(line[5:].strip())
                                if any(c.get('delta',{}).get('content') for c in obj.get('choices', [])):
                                    first_token = (time.perf_counter() - started) * 1000
                                    break
                            except json.JSONDecodeError:
                                pass
        duration = (time.perf_counter() - started) * 1000
        if not (200 <= (code or 0) < 300):
            raise ValueError(f'HTTP {code}: {bytes(received)[:160]!r}')
        if workload == 'mcp':
            rpc = parse_jsonrpc_or_sse(bytes(received), content_type, int(payload['id']))
            if 'error' in rpc:
                raise ValueError(f'MCP JSON-RPC error: {rpc["error"]}')
            if rpc.get('result',{}).get('isError'):
                raise ValueError('MCP tool returned isError=true')
            if 'result' not in rpc:
                raise ValueError('MCP response missing result')
        else:
            if stream_tokens:
                if b'data: [DONE]' not in received:
                    raise ValueError('Incomplete LLM SSE stream')
            else:
                llm = json.loads(received)
                if not llm.get('choices'):
                    raise ValueError('LLM response missing choices')
        return Sample(workload, True, duration, first_byte, first_token, code,
                      request_bytes, response_bytes, '')
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        duration = (time.perf_counter() - started) * 1000
        error = (str(exc) or type(exc).__name__)[:180]
        return Sample(workload, False, duration, first_byte, first_token, code,
                      request_bytes, response_bytes, error)


class MCPClient:
    def __init__(self, url: str, token: str | None, version: str, tool: str | None,
                 tool_args: dict[str, Any]):
        self.url, self.version = url, version
        self.tool, self.tool_args = tool, tool_args
        self.headers: dict[str,str] = {
            'Content-Type':'application/json',
            'Accept':'application/json, text/event-stream',
            'MCP-Protocol-Version':version,
        }
        if token:
            self.headers['Authorization'] = f'Bearer {token}'
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=False)
        self.counter = 0

    async def initialize(self) -> None:
        if self.version == VERSION_2026:
            return
        payload = {'jsonrpc':'2.0','id':0,'method':'initialize',
          'params':{'protocolVersion':VERSION_2025,'capabilities':{},
                    'clientInfo':{'name':'benchmark-lab','version':'1.0'}}}
        result = await self.client.post(self.url, json=payload, headers=self.headers)
        if result.status_code != 200:
            raise RuntimeError(f'MCP initialization failed: HTTP {result.status_code}: {result.text[:160]}')
        parsed = parse_jsonrpc_or_sse(result.content, result.headers.get('content-type',''), 0)
        if 'result' not in parsed:
            raise RuntimeError(f'MCP initialization error: {parsed}')
        self.headers['MCP-Protocol-Version'] = parsed['result'].get('protocolVersion', VERSION_2025)
        session = result.headers.get('mcp-session-id')
        if session:
            self.headers['Mcp-Session-Id'] = session
        note = {'jsonrpc':'2.0', 'method':'notifications/initialized'}
        ack = await self.client.post(self.url, json=note, headers=self.headers)
        if ack.status_code not in (200, 202, 204):
            raise RuntimeError(f'MCP initialized notification failed: HTTP {ack.status_code}')

    async def invoke(self) -> Sample:
        self.counter += 1
        method = 'tools/call' if self.tool else 'tools/list'
        params: dict[str,Any] = ({'name':self.tool,'arguments':self.tool_args}
                                 if self.tool else {})
        headers = dict(self.headers)
        if self.version == VERSION_2026:
            params['_meta'] = {
              'io.modelcontextprotocol/protocolVersion': VERSION_2026,
              'io.modelcontextprotocol/clientInfo': {'name':'benchmark-lab','version':'1.0'},
              'io.modelcontextprotocol/clientCapabilities': {}}
            headers['Mcp-Method'] = method
            if self.tool:
                headers['Mcp-Name'] = self.tool
        payload = {'jsonrpc':'2.0','id':self.counter,'method':method,'params':params}
        return await send_request(self.client, self.url, payload, headers, 'mcp')

    async def close(self) -> None:
        await self.client.aclose()


class LLMClient:
    def __init__(self, url: str, token: str | None, model: str, stream: bool):
        self.url, self.model, self.stream = url, model, stream
        self.headers = {'Content-Type':'application/json'}
        if token:
            self.headers['Authorization'] = f'Bearer {token}'
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(30.0), follow_redirects=False)

    async def invoke(self) -> Sample:
        payload = {
            'model': self.model,
            'messages': [{'role':'user', 'content': 'Reply with the word OK only.'}],
            'temperature': 0,
            'max_tokens': 12,
            'stream': self.stream,
        }
        return await send_request(self.client, self.url, payload, self.headers, 'llm', self.stream)

    async def close(self) -> None:
        await self.client.aclose()


def percentile(numbers: list[float], percentile_value: float) -> float | None:
    if not numbers:
        return None
    values = sorted(numbers)
    pos = (len(values) - 1) * percentile_value / 100
    low, high = int(pos), min(int(pos) + 1, len(values) - 1)
    fraction = pos - low
    return values[low] * (1 - fraction) + values[high] * fraction


def summarize(samples: list[Sample], elapsed_s: float) -> dict[str, Any]:
    ok = [x for x in samples if x.ok]
    latencies = [x.latency_ms for x in ok]
    ttfb = [x.first_byte_ms for x in ok if x.first_byte_ms is not None]
    first_token = [x.first_token_ms for x in ok if x.first_token_ms is not None]
    fmt = lambda x: None if x is None else round(x, 2)
    bytes_total = sum(x.request_bytes + x.response_bytes for x in samples)
    return {
        'requests':len(samples), 'success':len(ok), 'failures':len(samples)-len(ok),
        'success_rate_pct':fmt(100 * len(ok)/len(samples)) if samples else 0,
        'elapsed_s':fmt(elapsed_s),
        'completed_rps':fmt(len(ok)/elapsed_s) if elapsed_s else None,
        'observed_payload_mbps':fmt(8 * bytes_total/elapsed_s/1e6) if elapsed_s else None,
        'mean_ms':fmt(statistics.mean(latencies)) if latencies else None,
        'p20_ms':fmt(percentile(latencies,20)),
        'p50_ms':fmt(percentile(latencies,50)),
        'p95_ms':fmt(percentile(latencies,95)),
        'p99_ms':fmt(percentile(latencies,99)),
        'first_byte_p50_ms':fmt(percentile(ttfb,50)),
        'first_token_p50_ms':fmt(percentile(first_token,50)),
        'errors':list(dict.fromkeys(x.error for x in samples if x.error))[:12],
    }


async def run_workload(kind: str, cfg: argparse.Namespace, target_url: str,
                       token: str | None) -> tuple[list[Sample], dict[str,Any]]:
    limiter = Pacer(cfg.rps)
    total = cfg.samples
    workers = min(cfg.concurrency, total)
    ready = asyncio.Event()
    all_ready = asyncio.Event()
    ready_lock = asyncio.Lock()
    ready_workers = 0
    async def worker(worker_id: int) -> list[Sample]:
        nonlocal ready_workers
        if kind == 'mcp':
            obj = MCPClient(target_url, token, cfg.mcp_version, cfg.mcp_tool,
                            json.loads(cfg.mcp_tool_args))
        else:
            obj = LLMClient(target_url, token, cfg.llm_model, cfg.llm_stream)
        try:
            if kind == 'mcp':
                await obj.initialize()
            # Warmup is deliberately outside the reported test window.
            for _ in range(cfg.warmup):
                await obj.invoke()
            async with ready_lock:
                ready_workers += 1
                if ready_workers == workers:
                    all_ready.set()
            await ready.wait()
            out: list[Sample] = []
            for _ in range(total // workers + (worker_id < total % workers)):
                await limiter.wait()
                out.append(await obj.invoke())
            return out
        except Exception:
            # Release the coordinator if a live endpoint rejects initialization.
            all_ready.set()
            raise
        finally:
            await obj.close()
    tasks = [asyncio.create_task(worker(i)) for i in range(workers)]
    # Wait until *all* workers finish initialization and warmup before timing.
    # A failed worker must not leave the other workers waiting indefinitely.
    await all_ready.wait()
    failed = [t for t in tasks if t.done() and not t.cancelled() and t.exception()]
    if failed:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise RuntimeError(f'Cannot begin benchmark: {failed[0].exception()}')
    started = time.perf_counter()
    ready.set()
    results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - started
    flat = [sample for group in results for sample in group]
    return flat, summarize(flat, elapsed)


def write_reports(all_samples: list[Sample], summaries: dict[str, Any], out_dir: Path,
                  mode: str, cfg: argparse.Namespace) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir/'requests.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(Sample.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(x) for x in all_samples)
    with (out_dir/'summary.json').open('w', encoding='utf-8') as f:
        json.dump({'run_at_utc':datetime.now(timezone.utc).isoformat(),
                   'mode':mode, 'test_parameters':{
                       'samples_per_workload':cfg.samples,'concurrency':cfg.concurrency,
                       'rps_limit':cfg.rps,'warmup_per_worker':cfg.warmup,
                       'mcp_version':cfg.mcp_version,
                       'llm_stream':cfg.llm_stream},
                   'results':summaries},f,indent=2)
    lines = [f'# Benchmark results — {mode.upper()} mode','',
             '**These data measure HTTP request latency, not model correctness or agent outcome quality.**',
             '',f'- Samples per workload: {cfg.samples}',
             f'- Concurrency: {cfg.concurrency}; requested start RPS cap: {cfg.rps or "unlimited"}',
             f'- MCP protocol: {cfg.mcp_version}; LLM streaming: {cfg.llm_stream}',
             '- Percentiles: linear interpolation over successful request durations.',
             '- p99 is noisy with small samples. Use 1,000+ representative requests for a more useful tail estimate.',
             '- Throughput and Mbps are observed rates, not maximum achievable capacity.',
             '- Payload Mbps excludes TLS/IP/HTTP headers and external downstream traffic.',
             '', '| Workload | Success | RPS | p20 (ms) | p50 (ms) | p95 (ms) | p99 (ms) | Avg (ms) | Payload Mbps |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key, val in summaries.items():
        lines.append(f'| {key} | {val["success"]}/{val["requests"]} | {val["completed_rps"]} | '
          f'{val["p20_ms"]} | {val["p50_ms"]} | {val["p95_ms"]} | {val["p99_ms"]} | '
          f'{val["mean_ms"]} | {val["observed_payload_mbps"]} |')
        if val['errors']:
            lines.extend(['',f'{key} errors:', *[f'- {x}' for x in val['errors']]])
    lines.extend(['', 'TTFB = first response byte; LLM first-token latency is measured separately for streaming runs.',
                  'Do not confuse tools/list benchmark with a tool execution or an end-to-end agent workflow.', ''])
    (out_dir/'RESULTS.md').write_text('\n'.join(lines), encoding='utf-8')


def get_args() -> argparse.Namespace:
    parser=argparse.ArgumentParser(description='Safe GitHub MCP and LLM gateway benchmark lab')
    parser.add_argument('--mode',choices=['mock','live'],default='mock')
    parser.add_argument('--target',choices=['both','mcp','llm'],default='both')
    parser.add_argument('--samples',type=int,default=300)
    parser.add_argument('--concurrency',type=int,default=8)
    parser.add_argument('--rps',type=float,default=0,
                        help='Max per-workload request start rate. Live defaults to 2.')
    parser.add_argument('--warmup',type=int,default=2)
    parser.add_argument('--mcp-version',choices=[VERSION_2025,VERSION_2026],default=VERSION_2025)
    parser.add_argument('--mcp-tool',default='',help='Optional MCP tool name. Choose read-only tools only.')
    parser.add_argument('--mcp-tool-args',default='{}',help='Tool arguments JSON')
    parser.add_argument('--mcp-url',default=os.environ.get('MCP_URL',''))
    parser.add_argument('--llm-url',default=os.environ.get('LLM_URL',''))
    parser.add_argument('--llm-model',default=os.environ.get('LLM_MODEL','mock-model'))
    parser.add_argument('--llm-stream',action='store_true')
    parser.add_argument('--ack-load',action='store_true',help='Required to send live traffic')
    parser.add_argument('--out',default='results')
    args=parser.parse_args()
    if not 1 <= args.samples <= 100000:
        parser.error('--samples must be between 1 and 100000')
    if not 1 <= args.concurrency <= 200:
        parser.error('--concurrency must be between 1 and 200')
    if args.warmup < 0 or args.rps < 0:
        parser.error('--warmup and --rps cannot be negative')
    try:
        if not isinstance(json.loads(args.mcp_tool_args),dict):
            raise ValueError()
    except (ValueError,json.JSONDecodeError):
        parser.error('--mcp-tool-args must be a JSON object')
    if args.mode == 'live':
        if not args.ack_load:
            parser.error('Live HTTP traffic requires --ack-load, after confirming permission.')
        if args.rps == 0:
            args.rps = 2.0
        if args.concurrency > 4:
            parser.error('For live testing start with <=4 concurrent workers.')
        if args.target in ('both','mcp') and not args.mcp_url:
            parser.error('Live MCP test requires MCP_URL or --mcp-url (full endpoint URL).')
        if args.target in ('both','llm') and not args.llm_url:
            parser.error('Live LLM test requires LLM_URL or --llm-url (full chat completions URL).')
        if args.llm_model == 'mock-model' and args.target in ('both','llm'):
            parser.error('Set --llm-model to a model actually deployed at the gateway.')
        for url in [u for u in [args.mcp_url if args.target!='llm' else '',
                                 args.llm_url if args.target!='mcp' else ''] if u]:
            if not (url.startswith('http://') or url.startswith('https://')):
                parser.error('Live URLs must be full http(s) URLs')
    return args


async def run(cfg: argparse.Namespace) -> None:
    server = None
    if cfg.mode == 'mock':
        server, root = start_mock()
        print(f'Local fixture running on {root} (127.0.0.1 only)')
        cfg.mcp_url = root+'/mcp'
        cfg.llm_url = root+'/v1/chat/completions'
    try:
        chosen = ['mcp','llm'] if cfg.target == 'both' else [cfg.target]
        all_samples: list[Sample] = []
        summaries: dict[str,Any] = {}
        for kind in chosen:
            url = cfg.mcp_url if kind == 'mcp' else cfg.llm_url
            token = os.environ.get('MCP_TOKEN' if kind == 'mcp' else 'LLM_TOKEN')
            print(f'Running {kind.upper()}: {cfg.samples} requests, {cfg.concurrency} workers, '
                  f'RPS cap {cfg.rps or "none"}; no secret values printed')
            samples, summary = await run_workload(kind, cfg, url, token)
            all_samples.extend(samples)
            summaries[kind] = summary
            print(json.dumps(summary, indent=2))
        write_reports(all_samples,summaries,Path(cfg.out),cfg.mode,cfg)
        print(f'Wrote {Path(cfg.out).resolve() / "RESULTS.md"} and requests.csv / summary.json')
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    asyncio.run(run(get_args()))
