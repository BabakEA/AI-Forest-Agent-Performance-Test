"""Streamlit visual JSON builder for the AI Forest testing and capacity toolkit.

Isolated from the backend so CLI users do not need to install Streamlit.
"""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import asdict
from pathlib import Path

from .capacity import CapacityInputs, write_capacity_report
from .designer import (
    default_suite, make_benchmark_config, make_capacity_config, make_bundle,
    safe_json, sanitized_env_example, synthetic_words, template_case,
    validate_url_and_secret_mode,
)
from .models import Suite


def _uid():
    return uuid.uuid4().hex[:12]


def _case_label(obj: dict) -> str:
    return f"{obj.get('name','unnamed')} · {obj.get('kind','api').upper()}" + ('' if obj.get('enabled', True) else ' · disabled')


def _init(st, root: Path):
    if 'studio_cases' not in st.session_state:
        initial = default_suite()
        st.session_state.studio_cases = [{**c, '_id':_uid()} for c in initial['cases']]
        st.session_state.studio_settings = {k:v for k,v in initial.items() if k != 'cases'}
    if 'studio_revision' not in st.session_state:
        st.session_state.studio_revision = 0
    if 'studio_secrets' not in st.session_state:
        st.session_state.studio_secrets = {}
    if 'studio_capacity' not in st.session_state:
        p = root / 'examples' / 'ai_forest_03_capacity_forecast.json'
        st.session_state.studio_capacity = json.loads(p.read_text(encoding='utf-8')) if p.exists() else asdict(CapacityInputs())


def _import_suite(st, obj: dict):
    if not isinstance(obj, dict) or not isinstance(obj.get('cases'), list):
        raise ValueError('This is not a benchmark suite JSON: missing cases array.')
    cfg = make_benchmark_config(obj, obj['cases'])
    st.session_state.studio_cases = [{**c, '_id':_uid()} for c in cfg['cases']]
    st.session_state.studio_settings = {k:v for k,v in cfg.items() if k!='cases'}
    st.session_state.studio_secrets = {}
    st.session_state.studio_revision += 1


def _parse_object(text: str, label: str):
    try:
        val = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f'{label}: invalid JSON at line {exc.lineno}, column {exc.colno}.') from None
    if not isinstance(val, dict):
        raise ValueError(f'{label}: expected a JSON object with {{...}}.')
    return val


def _current_suite(st):
    cfg = st.session_state.studio_settings
    cases = [{k:v for k,v in c.items() if not k.startswith('_')} for c in st.session_state.studio_cases]
    return make_benchmark_config(cfg, cases)


def _load_button(st, source_obj, label):
    if st.button(label, use_container_width=True):
        try:
            _import_suite(st, source_obj)
            st.rerun()
        except Exception as ex:
            st.error(str(ex))


def render_test_designer(st, root: Path, run_callback):
    _init(st, root)
    st.subheader('Visual test designer')
    st.caption('Build real CLI-compatible benchmark JSON without editing files. Define a workload, add target endpoints, then download or run it.')
    st.info('**Four steps:** ① Import a template or start fresh → ② Set test traffic → ③ Add/edit endpoint rules → ④ Validate, download JSON or run. Every live test requires explicit approval.')

    # 1. Source / import
    with st.expander('① Start from a template or import a JSON suite', expanded=False):
        presets = [x for x in (root/'examples').glob('*.json')
                   if 'capacity' not in x.name and 'web_ui' not in x.name]
        c1, c2 = st.columns(2)
        with c1:
            preset = st.selectbox('Available benchmark presets', presets, format_func=lambda x:x.name,
                                  key='studio_preset_select', help='Loads the entire suite, including all cases and traffic settings.')
            if st.button('Load selected preset', key='studio_load_preset'):
                try:
                    _import_suite(st, json.loads(preset.read_text(encoding='utf-8')))
                    st.rerun()
                except Exception as ex: st.error(f'Cannot import: {ex}')
            if st.button('Reset to safe example (mock only)', key='studio_reset'):
                _import_suite(st, default_suite())
                st.rerun()
        with c2:
            up = st.file_uploader('Import a benchmark JSON file', type=['json'], key='studio_upload')
            if up is not None and st.button('Import uploaded file', key='studio_import_uploaded'):
                try:
                    _import_suite(st, json.loads(up.getvalue().decode('utf-8-sig')))
                    st.rerun()
                except Exception as ex: st.error(f'Import rejected: {ex}')
            st.caption('Existing cases are replaced only when you click Import. Session-only secrets are cleared when importing.')

    # 2. Suite level
    settings = st.session_state.studio_settings
    rev = st.session_state.studio_revision
    with st.expander('② Traffic and test settings', expanded=True):
        with st.form(f'studio_traffic_{rev}'):
            a,b,c,d = st.columns(4)
            mode = a.selectbox('Target environment', ['mock','live'], index=['mock','live'].index(settings.get('mode','mock')),
                               help='Mock uses a local simulated server. Live sends real HTTP requests to configured URLs.')
            typ = b.selectbox('Test strategy', ['smoke','load','ramp','soak'], index=['smoke','load','ramp','soak'].index(settings.get('test_type','smoke')),
                              help='Smoke: 1 request/case. Load: fixed concurrency. Ramp: concurrency stages. Soak: bounded sustained load.')
            samples = c.number_input('Requests / case / stage', min_value=1, max_value=50000,
                                     value=int(settings.get('requests_per_case',10)), step=1,
                                     help='For smoke tests this is ignored: exactly one measured request per enabled case.')
            concurrency = d.number_input('Concurrent request workers', min_value=1, max_value=100,
                                         value=int(settings.get('concurrency',1)),
                                         help='1c = one simultaneous client request, not CPU cores or Kubernetes pods.')
            a,b,c,d = st.columns(4)
            levels = a.text_input('Ramp worker levels', value=','.join(map(str,settings.get('concurrency_levels',[1,2,4,8]))),
                                   help='Use values like 1,2,4,8. Each stage runs the configured number of requests per case.')
            rps = b.number_input('New requests / second (cap)', min_value=0.0,
                                 value=float(settings.get('rps_limit',1.0)), step=0.5,
                                 help='Global start-rate cap per case/stage; live requires >0 and ≤10. It can limit throughput regardless of worker count.')
            timeout = c.number_input('Timeout per HTTP call (seconds)', min_value=1, max_value=300,
                                      value=int(settings.get('timeout_s',30)))
            warmup = d.number_input('Warmup requests / case', min_value=0, max_value=1000,
                                     value=int(settings.get('warmup',0)), help='Executed before measured calls; not included in latency percentiles.')
            soak = st.number_input('Soak-test maximum duration (seconds)', min_value=1, max_value=3600,
                                    value=int(settings.get('soak_seconds',30)),
                                    help='Soak is bounded by this duration and the request count. Live soak is capped at 120 seconds.')
            st.caption('Live safety limits: ≤8 client workers, ≤10 new requests/sec, ≤1,000 requests per case/stage; soak ≤120 sec.')
            if st.form_submit_button('Save traffic settings', use_container_width=True):
                try:
                    seq = [int(x.strip()) for x in levels.split(',') if x.strip()]
                    if not seq: raise ValueError('Provide at least one ramp concurrency level.')
                    draft = dict(settings, mode=mode, test_type=typ, requests_per_case=int(samples),
                                 concurrency=int(concurrency), concurrency_levels=seq,
                                 rps_limit=float(rps), timeout_s=float(timeout), warmup=int(warmup),
                                 soak_seconds=float(soak))
                    _ = make_benchmark_config(draft, [c for c in st.session_state.studio_cases])
                    st.session_state.studio_settings = draft
                    st.success('Traffic settings validated and saved.')
                except Exception as ex: st.error(f'Traffic settings not saved: {ex}')

    # 3. Targets and test rules
    st.markdown('#### ③ Endpoint rules / test cases')
    st.caption('Each row is an independent case. A single suite can combine LLM gateways, REST APIs, agents and MCP servers. Disable routes that are not yet verified.')
    cases = st.session_state.studio_cases
    if cases:
        st.dataframe([{'Enabled': 'Yes' if c.get('enabled',True) else 'No',
                       'Case':c.get('name',''), 'Target':str(c.get('kind','')).upper(),
                       'Method':c.get('method','POST'), 'URL':c.get('url',''),
                       'Auth':('env: '+c.get('token_env')) if c.get('token_env') else ('session-only' if c['_id'] in st.session_state.studio_secrets else 'none'),
                       'Model / MCP tool':c.get('model','') if c.get('kind')=='llm' else c.get('mcp_tool','')}
                      for c in cases],hide_index=True,use_container_width=True)

    opts = ['+ Add a new case'] + [c['_id'] for c in cases]
    picker = st.selectbox('Choose a case to edit, or add a new one', opts,
        format_func=lambda x:'➕ Add a new endpoint rule' if x.startswith('+') else _case_label(next(c for c in cases if c['_id']==x)),
        key='studio_case_picker')
    is_new = picker.startswith('+')
    if is_new:
        chosen_kind = st.selectbox('Type of new endpoint', ['llm','mcp','api','agent'], key='studio_new_type',
                                    help='Selecting MCP adds protocol/tool controls; LLM adds model, streaming and token controls.')
        original = template_case(chosen_kind, name=f'my-{chosen_kind}-{len(cases)+1}')
    else:
        original = next(c for c in cases if c['_id']==picker)
        chosen_kind = original.get('kind','api')
    # Controls affecting the form layout must be outside the form, because
    # Streamlit does not rerender a form until submission.
    if is_new:
        rule_kind = chosen_kind
    else:
        rule_kind = st.selectbox('Target type for selected rule', ['llm','mcp','api','agent'],
                                 index=['llm','mcp','api','agent'].index(chosen_kind),
                                 key=f'studio_kind_{picker}_{rev}',
                                 help='Changing type reveals the corresponding model, MCP or payload fields.')
    secret_key = original.get('_id','')
    old_secret = st.session_state.studio_secrets.get(secret_key,'')
    old_auth = 'Session-only token' if old_secret else ('Environment variable (.env)' if original.get('token_env') else 'None')
    auth_mode = st.selectbox('Credential source', ['Environment variable (.env)','Session-only token','None'],
                             index=['Environment variable (.env)','Session-only token','None'].index(old_auth),
                             key=f'studio_auth_{picker}_{rev}',
                             help='Recommended: enter only your .env variable name. Actual tokens are masked and never exported.')
    # A form avoids saving a half-typed case after every keystroke.
    with st.form(f'studio_rule_{picker}_{rule_kind}_{rev}'):
        c1,c2 = st.columns([2,1])
        name = c1.text_input('Case name', value=original.get('name',''),
                             help='Unique identifier for this test in CSV and charts.')
        enabled = c2.checkbox('Enable this test', value=bool(original.get('enabled',True)),
                              help='Disabled cases remain in the JSON but generate no requests.')
        kind = rule_kind
        endpoint = st.text_input('Full HTTP(S) endpoint URL', value=original.get('url',''),
                                help='E.g. http://127.0.0.1:4004/v1/chat/completions or http://127.0.0.1:9135/mcp. No query-string secrets.')
        c1,c2,c3 = st.columns(3)
        method = c1.selectbox('HTTP method', ['POST','GET','PUT','PATCH','DELETE'],
                              index=['POST','GET','PUT','PATCH','DELETE'].index(original.get('method','POST').upper())
                              if original.get('method','POST').upper() in ['POST','GET','PUT','PATCH','DELETE'] else 0,
                              disabled=kind in ('llm','mcp'),help='MCP and OpenAI-compatible LLM requests use POST.')
        statuses = c2.text_input('Expected HTTP status codes', value=','.join(map(str,original.get('expected_status',[200]))),
                                 help='Usually 200. Enter 200,202 to accept multiple codes.')
        expected_path = c3.text_input('Required JSON response field (optional)',value=original.get('expected_json_path',''),
                                      help='For API/agent only, e.g. status or $.result.answer. Blank disables body field checking.')
        expected_val = st.text_input('Expected field value (JSON, optional)',
                                      value='null' if original.get('expected_value') is None else json.dumps(original.get('expected_value')),
                                      help='Use null to check only that the field exists and is non-null. Use "completed" to check an exact string.')
        c1,c2 = st.columns([1,2])
        c1.caption('Selected auth: ' + auth_mode)
        token_env = c2.text_input('Environment variable name (not its secret value)',
                                   value=original.get('token_env','') or ('LLM_GATEWAY_TOKEN' if kind=='llm' else ''),
                                   disabled=auth_mode!='Environment variable (.env)',
                                   help='For example LLM_GATEWAY_TOKEN. The app reads its value from your local .env.')
        secret = st.text_input('Actual bearer token — RUN ONLY; never exported',
                               value=old_secret, type='password', disabled=auth_mode!='Session-only token',
                               help='Stored only in this Streamlit session memory; not written to generated JSON, .env.example or report files.')
        hdrs = st.text_area('Custom headers (JSON object)',value=json.dumps(original.get('headers',{}),indent=2),height=80,
                            help='Use for non-secret headers such as X-Tenant-ID. Authorization/X-API-Key headers are blocked; use the credential field above.')

        payload = copy.deepcopy(original.get('payload'))
        model, model_env, stream = original.get('model','gemma4:26b'),original.get('model_env',''),bool(original.get('stream',False))
        mcp_version=original.get('mcp_version','2025-11-25')
        mcp_tool=original.get('mcp_tool','')
        mcp_expected_tool=original.get('mcp_expected_tool','')
        mcp_args=original.get('mcp_tool_args',{})
        requested_words=0; text_field='query'
        if kind == 'llm':
            st.markdown('**LLM gateway settings**')
            c1,c2,c3 = st.columns(3)
            model=c1.text_input('Model name sent to gateway',value=model,help='Exact LiteLLM alias, e.g. gemma4:26b or gpt-luna-fast.')
            model_env=c2.text_input('Optional model_env variable name',value=model_env,
                                     help='Leave blank to always use Model name. If set, an environment variable overrides the name.')
            stream=c3.checkbox('Streaming / first-token timing',value=stream,
                                 help='Streams SSE chunks and measures first content-bearing token time when available.')
            c1,c2,c3 = st.columns(3)
            max_tokens=c1.number_input('Maximum output tokens',min_value=1,max_value=16384,
                                         value=int((payload or {}).get('max_tokens',32)),
                                         help='Token budget sent to model; actual tokens may be fewer.')
            temperature=c2.number_input('Sampling temperature',min_value=0.,max_value=2.,
                                          value=float((payload or {}).get('temperature',0)),step=.1)
            requested_words=c3.number_input('Synthetic input words (0 = keep JSON)', min_value=0,max_value=3000,value=0,
                                             help='Creates a harmless prompt containing exactly this number of words; not a tokenizer-accurate token count.')
            st.caption('**Input words ≠ input tokens.** For exact token counts, use gateway usage metadata/tokenizer. This controls synthetic prompt size, not output length.')
        elif kind == 'mcp':
            st.markdown('**MCP tool / protocol settings**')
            c1,c2 = st.columns(2)
            versions=['2025-11-25','2026-07-28']
            mcp_version=c1.selectbox('MCP protocol version',versions,index=versions.index(mcp_version) if mcp_version in versions else 0,
                                      help='Choose the protocol your server actually implements. Older servers need initialization; new stateless servers use method headers.')
            mcp_tool=c2.text_input('Read-only tool name (blank = tools/list)',value=mcp_tool,
                                   help='Discovery is safest. Tool execution needs verified arguments and non-mutating behavior.')
            mcp_expected_tool=st.text_input('Tool expected in tools/list (optional)',value=mcp_expected_tool,
                                            help='Fail discovery if this tool is absent. Leave blank to just test successful discovery.')
            mcp_arg_text=st.text_area('Tool arguments JSON',value=json.dumps(mcp_args,indent=2),height=110,
                                     help='Only used when a tool name is supplied. Never benchmark memory writes or physical device actions without an isolated test environment.')
        elif kind in ('agent','api'):
            st.markdown('**API / agent test input**')
            c1,c2 = st.columns(2)
            requested_words = c1.number_input('Synthetic input words (0 = keep JSON)',min_value=0,max_value=3000,value=0,
                                               help='Generate harmless test text to exercise payload size. The field below receives this text.')
            text_field = c2.text_input('JSON text field for generated words', value='query' if kind=='agent' else 'text',
                                        help='Top-level JSON property, for example query, prompt or text. Ensure your real endpoint supports it.')
        payload_text = st.text_area('Request payload JSON', value=json.dumps(payload,indent=2) if payload is not None else '{}',
                                     height=175, help='Advanced payload editor. For API/agent specify the exact request shape. LLM payload uses messages, max_tokens and temperature. MCP calls generate JSON-RPC automatically.')
        st.caption('MCP tool calls may have side effects even when names sound read-only. Use tools/list first. Avoid real user data and mutating agent commands in load tests.')
        submit=st.form_submit_button('Save / add endpoint rule',type='primary',use_container_width=True)
    if submit:
        try:
            if not name.strip(): raise ValueError('Case name is required.')
            if any(c['_id']!=original.get('_id') and c.get('name')==name for c in cases):
                raise ValueError('Case names must be unique.')
            validate_url_and_secret_mode(endpoint,token_env if auth_mode=='Environment variable (.env)' else '')
            if enabled and not endpoint.startswith(('http://','https://')):
                raise ValueError('Provide a complete HTTP or HTTPS endpoint URL for an enabled test.')
            body=_parse_object(payload_text,'Request payload')
            head=_parse_object(hdrs,'Custom headers')
            margs=_parse_object(mcp_arg_text,'MCP tool arguments') if kind=='mcp' else {}
            status_list=[int(n.strip()) for n in statuses.split(',') if n.strip()]
            if not status_list or any(n<100 or n>599 for n in status_list):raise ValueError('Expected status must contain HTTP status codes, e.g. 200,202.')
            ev=json.loads(expected_val) if expected_val.strip() else None
            if requested_words:
                words=synthetic_words(int(requested_words))
                if kind=='llm':
                    ms=body.setdefault('messages',[])
                    if not isinstance(ms,list):raise ValueError('LLM messages must be an array.')
                    users=[x for x in ms if isinstance(x,dict) and x.get('role')=='user']
                    if users:users[-1]['content']=words
                    else:ms.append({'role':'user','content':words})
                elif kind in ('agent','api'):
                    if not text_field or not text_field.isidentifier():raise ValueError('Generated text field must be a simple JSON property name, e.g. query.')
                    body[text_field]=words
            if kind=='llm':
                body['max_tokens']=int(max_tokens);body['temperature']=float(temperature)
            new=dict(original)
            new.update(name=name.strip(),kind=kind,enabled=bool(enabled),url=endpoint.strip(),method=method,
                       headers=head,token_env=token_env.strip() if auth_mode=='Environment variable (.env)' else '',
                       expected_status=status_list,expected_json_path=expected_path.strip(),expected_value=ev,
                       payload=body,model=model,model_env=model_env.strip(),stream=bool(stream),
                       mcp_version=mcp_version,mcp_tool=mcp_tool.strip(),mcp_expected_tool=mcp_expected_tool.strip(),
                       mcp_tool_args=margs)
            new.pop('auth_token',None)
            new['_id']=original.get('_id') or _uid()
            from .designer import _safe_case
            _safe_case(new)
            if kind=='mcp' and mcp_tool and any(x in mcp_tool.lower().split('_') for x in ('create','delete','remove','write','send','update','push','publish')):
                raise ValueError('Mutating tool names are blocked in performance tests.')
            if auth_mode=='Session-only token' and secret:
                st.session_state.studio_secrets[new['_id']]=secret
            else:st.session_state.studio_secrets.pop(new['_id'],None)
            if is_new:cases.append(new)
            else:cases[cases.index(original)]=new
            st.session_state.studio_revision += 1
            st.success('Case saved. Review JSON preview below, or add another case.')
            st.rerun()
        except Exception as ex:
            st.error(f'Could not save case: {ex}')
    if not is_new:
        a,b = st.columns(2)
        if a.button('Duplicate selected case',key='studio_duplicate'):
            dup=copy.deepcopy(original);dup['_id']=_uid();dup['name']=dup.get('name','case')+'-copy';cases.append(dup)
            st.session_state.studio_revision+=1;st.rerun()
        if b.button('Delete selected case',key='studio_delete'):
            cases.remove(original);st.session_state.studio_secrets.pop(original['_id'],None)
            st.session_state.studio_revision+=1;st.rerun()

    # 4. JSON export + controlled test execution
    st.markdown('#### ④ Validate, export and optionally run')
    try:
        config = _current_suite(st)
    except Exception as ex:
        st.error(f'Configuration must be corrected before export: {ex}')
        return
    active=sum(c.get('enabled',True) for c in config['cases'])
    mode=config['mode'];strategy=config['test_type']
    stages=len(config['concurrency_levels']) if strategy=='ramp' else 1
    measured=active*stages*(1 if strategy=='smoke' else config['requests_per_case'])
    a,b,c,d=st.columns(4)
    a.metric('Enabled endpoint rules',active)
    b.metric('Estimated measured calls',measured)
    c.metric('Max client workers',max(config['concurrency_levels']) if strategy=='ramp' else config['concurrency'])
    d.metric('Target',mode.upper())
    if strategy=='soak':st.caption('Soak stops at the duration or request-count bound, whichever is first; measured request estimate is an upper bound.')
    st.caption('The request count excludes warmups and MCP initialization requests. Live tests cost real tokens/API quota and can influence service availability.')
    safe_text=safe_json(config)
    with st.expander('Preview performance_test.json',expanded=False):
        st.code(safe_text,language='json')
        st.caption('The exported file includes complete payloads and endpoint URLs. Review them before sharing; no actual bearer token is exported.')
    c1,c2=st.columns(2)
    c1.download_button('⬇️ Download performance_test.json',safe_text,'performance_test.json','application/json',use_container_width=True)
    c2.download_button('⬇️ Download safe .env.example',sanitized_env_example(config),'.env.example','text/plain',use_container_width=True)
    st.code('python -m agent_perf benchmark --config examples/performance_test.json --out results/my-benchmark' +
            (' --ack-live' if mode=='live' else ''),language='bash')
    if any(c['_id'] in st.session_state.studio_secrets for c in cases):
        st.info('Some cases use temporary masked tokens. These work for **Run from dashboard** only; exported files require `.env` variable names to use credentials from the CLI.')
    ack=st.checkbox('I own these endpoints and explicitly authorize this limited live workload (including possible API costs)',value=False,key='studio_live_ack') if mode=='live' else True
    if st.button('▶️ Run designed benchmark',type='primary',disabled=mode=='live' and not ack,use_container_width=True):
        try:
            suite=Suite.from_dict(config)
            suite.ack_live=bool(ack) if mode=='live' else False
            for c,raw in zip(suite.cases,cases):
                if raw['_id'] in st.session_state.studio_secrets:
                    c.auth_token=st.session_state.studio_secrets[raw['_id']]
            suite.validate()
            run_callback(suite)
        except Exception as ex:
            st.error(f'Benchmark did not run: {type(ex).__name__}: {str(ex)[:180]}')
    st.caption('Your existing Run & results tab still supports hand-authored JSON files and advanced troubleshooting.')


def render_capacity_designer(st, root:Path):
    _init(st,root)
    st.subheader('Visual Kubernetes capacity and cost-demand designer')
    st.caption('Configure expected users, activity, token demand and per-service pod capacity. Download a valid forecast JSON and generate a scenario report without writing JSON by hand.')
    st.warning('Forecast values are illustrative until calibrated against load-test measurements. API/MCP request TPS, workflow TPS, and model tokens/sec are different units.')
    with st.expander('How sizing works — four simple quantities',expanded=False):
        st.markdown('**Peak workflow TPS** = registered users × active fraction × workflows per active user per minute ÷ 60 × peak multiplier.\n\n'
                    '**Service RPS** = workflow TPS × calls per workflow.\n\n'
                    '**Replicas** depend on service RPS, per-pod sustainable RPS, target utilization and reserve headroom, plus min/max replicas.\n\n'
                    '**LLM token demand** = workflow TPS × LLM calls/workflow × (input + output tokens/call). This is upstream serving demand, not the capability of gateway pods.')
    with st.expander('Import an existing capacity JSON',expanded=False):
        file = st.file_uploader('Forecast JSON',type=['json'],key='capacity_upload')
        if file is not None and st.button('Load forecast from upload',key='capacity_import'):
            try:
                conf=make_capacity_config(json.loads(file.getvalue().decode('utf-8-sig')))
                st.session_state.studio_capacity=conf;st.session_state.studio_revision+=1;st.rerun()
            except Exception as ex:st.error(f'Capacity import rejected: {ex}')
        if st.button('Reset to AI Forest seven-service defaults',key='capacity_reset'):
            path=root/'examples'/'ai_forest_03_capacity_forecast.json'
            st.session_state.studio_capacity=json.loads(path.read_text(encoding='utf-8'))
            st.session_state.studio_revision+=1;st.rerun()
    config=copy.deepcopy(st.session_state.studio_capacity)
    advanced_table = st.checkbox('Show advanced service sizing fields',value=False,
                                  key='studio_capacity_advanced',
                                  help='Enable image, container port and scaling controls in addition to the simple demand/resource fields.')
    with st.form(f'capacity_designer_{st.session_state.studio_revision}'):
        st.markdown('#### ① Who is using your product?')
        c1,c2,c3=st.columns(3)
        users=c1.number_input('Registered users',min_value=1,max_value=100000000,
                                value=int(config['users']),step=100,
                                help='Total registered accounts. Not the number of simultaneous users.')
        pct=c2.number_input('Active at peak (%)',min_value=.1,max_value=100.,
                              value=float(config['active_fraction_at_peak'])*100.,step=1.,
                              help='Percent of registered users active during the busiest period.')
        freq=c3.number_input('Workflows per active user / minute',min_value=.001,max_value=100.,
                               value=float(config['workflows_per_active_user_per_min']),step=.1,
                               help='A workflow is one end-user task, possibly containing multiple MCP/API/LLM calls.')
        c1,c2,c3=st.columns(3)
        burst=c1.number_input('Peak burst multiplier',min_value=1.,max_value=100.,value=float(config['peak_multiplier']),step=.1,
                               help='1.5 means 50% extra demand during a burst.')
        reserve=c2.number_input('Reserved headroom (%)',min_value=0.,max_value=90.,value=float(config['reserved_headroom'])*100.,step=5.,
                                 help='Additional spare application capacity, separate from autoscaling utilization targets.')
        calls=c3.number_input('LLM calls per workflow',min_value=0.,max_value=100.,value=float(config['llm_calls_per_workflow']),step=.5)
        c1,c2=st.columns(2)
        input_tokens=c1.number_input('Average LLM input tokens / call',min_value=0,max_value=1000000,value=int(config['llm_input_tokens_per_call']),step=100,
                                     help='This is an estimate across prompts, RAG context and conversation history.')
        output_tokens=c2.number_input('Average LLM output tokens / call',min_value=0,max_value=1000000,value=int(config['llm_output_tokens_per_call']),step=50)
        st.markdown('#### ② Capacity of each service')
        st.caption('Add or delete service rows in the table. RPS/pod should eventually come from an approved staging load test at your p95/error target, not guesswork.')
        import streamlit as stmod
        if advanced_table:
            edit_cols=list(config['services'][0].keys())
        else:
            edit_cols=['name','requests_per_workflow','measured_or_assumed_rps_per_pod',
                       'cpu_request_m','memory_request_mib','min_ha_replicas','max_replicas']
        ed_data=[{k:v for k,v in row.items() if k in edit_cols} for row in config['services']]
        edited=st.data_editor(ed_data,num_rows='dynamic',hide_index=True,use_container_width=True,
                               column_config={
                                   'name':stmod.column_config.TextColumn('Service ID',help='Unique Kubernetes-safe name, e.g. redis-memory-mcp'),
                                   'requests_per_workflow':stmod.column_config.NumberColumn('Calls / workflow',help='Average times one user task hits this service',min_value=0.,format='%.2f'),
                                   'measured_or_assumed_rps_per_pod':stmod.column_config.NumberColumn('Sustainable RPS / pod',help='Measured or assumed per-pod throughput at target SLO',min_value=.01,format='%.2f'),
                                   'cpu_request_m':stmod.column_config.NumberColumn('CPU request (mCPU)',help='1000 mCPU = 1 vCPU',min_value=1),
                                   'memory_request_mib':stmod.column_config.NumberColumn('RAM request (MiB)',min_value=1),
                                   'min_ha_replicas':stmod.column_config.NumberColumn('Minimum pods',min_value=0),
                                   'max_replicas':stmod.column_config.NumberColumn('Max pods',min_value=1),
                               })
        st.caption('Example: 2 calls/workflow × 1 workflow/sec = 2 HTTP requests/sec. CPU request uses millicores; memory uses MiB.')
        st.markdown('#### ③ Node sizes and deployment placeholders')
        c1,c2,c3=st.columns(3)
        cpu=c1.number_input('Node allocatable CPU (mCPU)',min_value=1,value=int(config['node_allocatable_cpu_m']))
        ram=c2.number_input('Node allocatable RAM (MiB)',min_value=1,value=int(config['node_allocatable_memory_mib']))
        pods=c3.number_input('Maximum pods per node',min_value=1,value=int(config['node_max_pod_count']))
        c1,c2,c3=st.columns(3)
        prefix=c1.text_input('K8s resource prefix',value=config['project'],help='Lowercase DNS-style name, e.g. ai-forest')
        hostname=c2.text_input('Ingress/Gateway hostname',value=config['hostname'],help='Placeholder .invalid is okay for generating example YAML; replace before deployment.')
        klass=c3.text_input('GatewayClass name',value=config['gateway_class'],help='Must match a controller installed in your Kubernetes cluster.')
        saved=st.form_submit_button('Validate and update forecast JSON',type='primary',use_container_width=True)
    if saved:
        try:
            if hasattr(edited,'to_dict'): rows=edited.to_dict(orient='records')
            else: rows=list(edited)
            orig={s['name']:s for s in config['services']}
            combined=[]
            for row in rows:
                if not row.get('name'):raise ValueError('Each service row needs a name. Remove incomplete rows.')
                prev=orig.get(str(row['name']),copy.deepcopy(config['services'][0]))
                prev['name']=str(row['name'])
                for key,value in row.items():
                    if value is None or (isinstance(value,float) and __import__('math').isnan(value)):
                        raise ValueError(f'Missing value for service {prev["name"]}, field {key}')
                    prev[key]=value
                combined.append(prev)
            if not combined:raise ValueError('Keep at least one service.')
            if len({s['name'] for s in combined}) != len(combined):raise ValueError('Service names must be unique.')
            proposal=dict(config,users=int(users),active_fraction_at_peak=float(pct)/100.,
                          workflows_per_active_user_per_min=float(freq),peak_multiplier=float(burst),
                          reserved_headroom=float(reserve)/100.,llm_calls_per_workflow=float(calls),
                          llm_input_tokens_per_call=int(input_tokens),llm_output_tokens_per_call=int(output_tokens),
                          node_allocatable_cpu_m=int(cpu),node_allocatable_memory_mib=int(ram),node_max_pod_count=int(pods),
                          project=prefix.strip(),hostname=hostname.strip(),gateway_class=klass.strip(),services=combined)
            clean=make_capacity_config(proposal)
            st.session_state.studio_capacity=clean
            st.success('Forecast inputs validated. Download the JSON below or generate a capacity report.')
            st.rerun()
        except Exception as ex:
            st.error(f'Forecast configuration not saved: {ex}')
    # Export CURRENT SAVED configuration, not unsubmitted widget values.
    try:
        capacity=make_capacity_config(st.session_state.studio_capacity)
        from .capacity import forecast
        result=forecast(CapacityInputs.from_dict(capacity))
        a,b,c,d=st.columns(4)
        a.metric('Workflow TPS at peak',f"{result['workflows_tps_peak']:.3f}")
        b.metric('Application replicas',result['total_replicas'])
        c.metric('LLM calls/sec',f"{result['llm_calls_per_sec']:.3f}")
        d.metric('LLM tokens/min',f"{result['llm_total_tokens_per_min']:,.0f}")
    except Exception as ex:
        st.error(f'Capacity calculation needs correction: {ex}');return
    payload=safe_json(capacity)
    with st.expander('Preview capacity_forecast.json'):
        st.code(payload,language='json')
    st.download_button('⬇️ Download capacity_forecast.json',payload,'capacity_forecast.json','application/json',use_container_width=True)
    st.code('python -m agent_perf forecast --config examples/capacity_forecast.json --out results/capacity',language='bash')
    if st.button('📈 Generate forecast report and graphs',type='primary',use_container_width=True):
        try:
            import datetime
            target=root/'results'/('studio-capacity-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            report=write_capacity_report(CapacityInputs.from_dict(capacity),target)
            st.success(f"Scenario generated: {target}")
            st.dataframe(report['services'],use_container_width=True,hide_index=True)
            st.image(str(target/'forecast_pods.png'),use_container_width=True)
            st.caption('X = registered users (accounts); Y = estimated application replicas (Kubernetes pods) under the current assumptions.')
            st.image(str(target/'forecast_tps.png'),use_container_width=True)
            st.caption('X = registered users (accounts); Y = peak workflows/sec and LLM calls/sec. Token throughput is a separate metric.')
            st.download_button('Download generated capacity report', (target/'CAPACITY_REPORT.md').read_bytes(),file_name='CAPACITY_REPORT.md')
            st.info('Generated Kubernetes YAML files are **examples only**. They require validated pod throughput, images, TLS, GatewayClass, secret references, and environment-specific checks.')
        except Exception as ex:st.error(f'Forecast generation failed: {ex}')

    st.markdown('#### Export both JSON configurations together')
    try:
        bench = _current_suite(st)
        bundle=make_bundle(bench,capacity)
        st.download_button('📦 Download performance + capacity + safe .env example',bundle,
                           file_name='AI_Forest_generated_configs.zip',mime='application/zip',use_container_width=True)
        st.caption('The ZIP includes performance_test.json, capacity_forecast.json, .env.example and a setup guide—never raw credentials.')
    except Exception as ex:st.info(f'Fix the benchmark designer to enable the combined download: {ex}')
