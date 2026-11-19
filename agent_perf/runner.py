"""Safe, opt-in async HTTP performance measurements for API, agent, MCP and LLM.

No secrets or response bodies are written to results. MCP initialization and warmups
are excluded from request timing. A mock fixture is used unless live is approved.
"""
from __future__ import annotations
import asyncio
import json
import os
import random
import threading
import time
import uuid
from dataclasses import asdict
from http.server import ThreadingHTTPServer
from typing import Any

import httpx
from .models import Case, Suite, Observation
from .legacy_lab import LocalMockHandler, parse_jsonrpc_or_sse

class ToolkitMockHandler(LocalMockHandler):
    def do_GET(self):
        if self.path.startswith('/api/') or self.path=='/health':
            self._response(200, {'ok':True,'status':'ok','kind':'api', 'message':'mock response'})
        else:
            self._response(404, {'error':'not found'})

    def do_POST(self):
        if self.path.startswith('/api/') or self.path.startswith('/agent'):
            try:
                request = json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
            except (ValueError,TypeError):
                self._response(400,{'error':'invalid JSON'});return
            delay = max(0.004, random.lognormvariate(-3.5,0.50))
            if random.random()<.05: delay += random.uniform(.075,.18)
            time.sleep(delay)
            if request.get('simulate_error'):
                self._response(503,{'error':'mock injected error'});return
            if self.path.startswith('/agent'):
                self._response(200,{'status':'completed','answer':'Synthetic agent result','steps':3,'ok':True})
            else:
                self._response(200,{'status':'ok','ok':True,'kind':'api','echo':request})
        else:
            super().do_POST()

def start_fixture():
    srv=ThreadingHTTPServer(('127.0.0.1',0),ToolkitMockHandler)
    threading.Thread(target=srv.serve_forever,daemon=True).start()
    return srv,f'http://127.0.0.1:{srv.server_port}'

def get_path(obj:Any,path:str):
    if not path:return None
    cur=obj
    for key in path.removeprefix('$.').removeprefix('$').split('.'):
        if not key: continue
        if isinstance(cur,list): cur=cur[int(key)]
        elif isinstance(cur,dict):cur=cur[key]
        else:raise KeyError(key)
    return cur

class Pacer:
    def __init__(self,rps:float):
        self.rps=rps
        self.lock=asyncio.Lock()
        self.next_tick=0.0
    async def wait(self):
        if self.rps<=0:return
        loop=asyncio.get_running_loop()
        async with self.lock:
            now=loop.time()
            at=max(now,self.next_tick)
            self.next_tick=at+1/self.rps
        await asyncio.sleep(max(0,at-loop.time()))

async def setup_mcp(client:httpx.AsyncClient,case:Case,headers:dict[str,str]):
    if case.mcp_version=='2026-07-28':return
    req={'jsonrpc':'2.0','id':0,'method':'initialize',
         'params':{'protocolVersion':case.mcp_version,'capabilities':{},
                   'clientInfo':{'name':'agent-performance-toolkit','version':'0.2'}}}
    resp=await client.post(case.url,json=req,headers=headers)
    resp.raise_for_status()
    result=parse_jsonrpc_or_sse(resp.content,resp.headers.get('content-type',''),0)
    if not isinstance(result,dict) or 'result' not in result:
        raise RuntimeError('MCP initialization returned no result')
    headers['MCP-Protocol-Version']=result['result'].get('protocolVersion',case.mcp_version)
    if session:=resp.headers.get('mcp-session-id'):
        headers['Mcp-Session-Id']=session
    note={'jsonrpc':'2.0','method':'notifications/initialized'}
    resp=await client.post(case.url,json=note,headers=headers)
    if resp.status_code not in (200,202,204):
        raise RuntimeError(f'Initialized notification returned HTTP {resp.status_code}')

async def send_once(client:httpx.AsyncClient,case:Case,headers:dict[str,str],
                    sequence:int,concurrency:int,base_time:float) -> Observation:
    method=case.method.upper() if case.kind not in ('mcp','llm') else 'POST'
    headers=dict(headers)
    data=case.payload
    if case.kind=='mcp':
        operation='tools/call' if case.mcp_tool else 'tools/list'
        params=({'name':case.mcp_tool,'arguments':case.mcp_tool_args} if case.mcp_tool else {})
        if case.mcp_version=='2026-07-28':
            params['_meta']={
               'io.modelcontextprotocol/protocolVersion':case.mcp_version,
               'io.modelcontextprotocol/clientInfo':{'name':'agent-performance-toolkit','version':'0.2'},
               'io.modelcontextprotocol/clientCapabilities':{}}
            headers['Mcp-Method']=operation
            if case.mcp_tool:headers['Mcp-Name']=case.mcp_tool
        data={'jsonrpc':'2.0','id':sequence,'method':operation,'params':params}
    elif case.kind=='llm':
        data=dict(data or {'messages':[{'role':'user','content':'Reply OK only.'}]})
        data.setdefault('model',os.environ.get(case.model_env, case.model) if case.model_env else case.model)
        data['stream']=case.stream
        data.setdefault('max_tokens',12)
    bodybytes=len(json.dumps(data).encode('utf-8')) if data is not None else 0
    if method=='GET':bodybytes=0
    first_byte=None
    first_token=None
    status=None
    total_bytes=0
    received=bytearray()
    start=time.perf_counter()
    try:
        req_args={'headers':headers}
        if data is not None:
            if method=='GET':req_args['params']=data
            else:req_args['json']=data
        async with client.stream(method,case.url,**req_args) as response:
            status=response.status_code
            ctype=response.headers.get('content-type','')
            pending=''
            async for chunk in response.aiter_bytes():
                if not chunk:continue
                if first_byte is None:first_byte=1000*(time.perf_counter()-start)
                total_bytes+=len(chunk)
                received.extend(chunk)
                if case.kind=='llm' and case.stream and first_token is None:
                    # Incremental SSE parsing, content-bearing delta only.
                    pending+=chunk.decode('utf-8',errors='replace')
                    lines=pending.split('\n')
                    pending=lines.pop()
                    for line in lines:
                        if not line.startswith('data:'):continue
                        try: event=json.loads(line[5:].strip())
                        except (ValueError,TypeError):continue
                        if any(x.get('delta',{}).get('content') for x in event.get('choices',[])):
                            first_token=1000*(time.perf_counter()-start)
                            break
        duration=1000*(time.perf_counter()-start)
        if status not in case.expected_status:
            raise ValueError('unexpected_http_status')
        usage={}
        if case.kind=='mcp':
            obj=parse_jsonrpc_or_sse(bytes(received),ctype,sequence)
            if 'error' in obj or 'result' not in obj or obj.get('result',{}).get('isError'):
                raise ValueError('mcp_rpc_or_tool_error')
            if not case.mcp_tool and case.mcp_expected_tool:
                tools = obj['result'].get('tools',[])
                if not any(t.get('name') == case.mcp_expected_tool for t in tools):
                    raise ValueError('expected_mcp_tool_missing')
        elif case.kind=='llm':
            if case.stream:
                if b'data: [DONE]' not in received:raise ValueError('incomplete_sse_response')
                for line in bytes(received).decode('utf-8',errors='replace').splitlines():
                    if line.startswith('data:'):
                        try:
                            event=json.loads(line[5:].strip())
                            if isinstance(event.get('usage'),dict):usage=event['usage']
                        except (ValueError,AttributeError):pass
            else:
                obj=json.loads(received)
                if not obj.get('choices'):raise ValueError('missing_choices')
                usage=obj.get('usage') or {}
        elif case.expected_json_path:
            obj=json.loads(received)
            actual=get_path(obj,case.expected_json_path)
            if case.expected_value is not None and actual != case.expected_value:
                raise ValueError('json_expectation_failed')
            if case.expected_value is None and actual is None:
                raise ValueError('expected_path_is_null')
        return Observation(case.name,case.kind,concurrency,sequence,start-base_time,
            round(duration,3),True,status,_r(first_byte),_r(first_token),bodybytes,total_bytes,
            usage.get('prompt_tokens'),usage.get('completion_tokens'))
    except (httpx.HTTPError,ValueError,KeyError,TypeError,UnicodeError,IndexError) as exc:
        duration=1000*(time.perf_counter()-start)
        # Only error category, NEVER server response bodies or user secrets.
        error= str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        return Observation(case.name,case.kind,concurrency,sequence,start-base_time,
            round(duration,3),False,status,_r(first_byte),_r(first_token),bodybytes,total_bytes,
            error_type=error[:60])

def _r(x):return round(x,3) if x is not None else None

async def run_stage(case:Case,suite:Suite,concurrency:int,token:str):
    pacer=Pacer(suite.rps_limit)
    lock=asyncio.Lock()
    index=0
    task_begin=time.perf_counter()
    # Number of requests is per stage. Soak is bound by both duration and count.
    n=1 if suite.test_type=='smoke' else suite.requests_per_case
    deadline=(task_begin+suite.soak_seconds) if suite.test_type=='soak' else None
    async def next_index():
        nonlocal index
        async with lock:
            if index >= n or (deadline is not None and time.perf_counter()>=deadline):return None
            index+=1
            return index
    async def worker():
        headers={'Accept':'application/json, text/event-stream' if case.kind=='mcp' else 'application/json'}
        headers.update(case.headers)
        if token:headers['Authorization']=f'Bearer {token}'
        if case.kind=='mcp':headers['MCP-Protocol-Version']=case.mcp_version
        async with httpx.AsyncClient(timeout=httpx.Timeout(suite.timeout_s),follow_redirects=False) as client:
            if case.kind=='mcp':await setup_mcp(client,case,headers)
            for i in range(suite.warmup):
                await send_once(client,case,headers,-i-1,concurrency,task_begin)
            output=[]
            while True:
                no=await next_index()
                if no is None:break
                await pacer.wait()
                output.append(await send_once(client,case,headers,no,concurrency,task_begin))
            return output
    started=time.perf_counter()
    parts=await asyncio.gather(*(worker() for _ in range(concurrency)))
    elapsed=time.perf_counter()-started
    samples=sorted((s for batch in parts for s in batch),key=lambda s:s.start_s)
    if samples:
        elapsed=max(0.001,max(x.start_s+x.latency_ms/1000 for x in samples)-min(x.start_s for x in samples))
    return samples,elapsed

async def run_suite(suite:Suite,progress=None):
    suite.validate()
    server=None
    if suite.mode=='mock':
        server,root=start_fixture()
        for case in suite.cases:
            if not case.enabled:continue
            case.url=root + {'mcp':'/mcp','llm':'/v1/chat/completions',
                             'agent':'/agent','api':'/api/echo'}[case.kind]
            if case.kind=='llm' and case.model=='':case.model='mock-model'
    try:
        all_items=[]
        summaries=[]
        levels=(suite.concurrency_levels if suite.test_type=='ramp' else [suite.concurrency])
        active_cases=[case for case in suite.cases if case.enabled]
        steps=len(active_cases)*len(levels)
        i=0
        from .report import summarize
        for case in active_cases:
            token=case.auth_token or (os.environ.get(case.token_env,'') if case.token_env else '')
            for concurrency in levels:
                obs,elapsed=await run_stage(case,suite,int(concurrency),token)
                all_items.extend(obs)
                summaries.append(summarize(obs,elapsed,case.name,case.kind,int(concurrency)))
                i+=1
                if progress:progress(i,steps,case.name,concurrency)
        return all_items,summaries
    finally:
        if server:
            server.shutdown();server.server_close()
