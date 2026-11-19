"""AI Forest local dashboard — benchmarks, forecast and optional browser smoke tests."""
from __future__ import annotations
import asyncio
import json
from datetime import datetime
from pathlib import Path

import streamlit as st
from agent_perf.env import load_project_env
load_project_env()
from agent_perf.models import Suite, Case
from agent_perf.runner import run_suite
from agent_perf.report import save_benchmark
from agent_perf.capacity import CapacityInputs, write_capacity_report
from agent_perf.studio_ui import render_test_designer, render_capacity_designer

ROOT = Path.cwd() if (Path.cwd() / "benchmark.json").is_file() else Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'examples'
RESULTS = ROOT / 'results'
STAMPS = lambda: datetime.now().strftime('%Y%m%d-%H%M%S')

st.set_page_config(page_title='AI Forest Agent Performance Toolkit',page_icon='📊',layout='wide')
st.title('AI Forest — Agent Performance Test Studio v0.7')
st.caption('Design tests visually · Generate configuration JSON · Run approved benchmarks · Forecast Kubernetes capacity. Local mock by default.')
st.info('**Concurrency legend:** 1c / c=1 = one simultaneous HTTP request worker; 2c = two workers, 4c = four. This is not CPU-core count. Each percentile measures successful client-observed latency in milliseconds.')

CHARTS = [
  ('latency_percentiles.png', 'Latency percentiles', 'X: target service and number of concurrent workers. Y: successful request duration (milliseconds). p20/p50/p95/p99 mean 20%/50%/95%/99% of successful calls finish at or below this duration. Compare p95/p99 to your latency SLO. Failed calls are NOT included in percentiles.'),
  ('throughput.png', 'Success throughput', 'X: target service and concurrency. Y: successfully completed requests per second (RPS). A larger RPS is useful only while latency and errors remain acceptable; the configured RPS cap may limit observed throughput.'),
  ('failures.png', 'Request errors', 'X: target service and concurrency. Y: number of failed requests. Include authentication, timeouts, protocol/JSON mismatches and HTTP failures. Zero failures in a tiny test does not prove production reliability.'),
]

def show_benchmark(suite:Suite):
    suite.validate()
    with st.spinner('Running authorized workload; may consume gateway tokens...'):
        progress = st.progress(0)
        def notify(step,total,case,workers):progress.progress(min(1.0,step/max(1,total)),text=f'Finished {case} at {workers} concurrent workers')
        observations,summary=asyncio.run(run_suite(suite,progress=notify))
        output=RESULTS / ('ui-' + STAMPS())
        save_benchmark(output,observations,summary,suite)
    st.success(f'Results saved: {output.resolve()}')
    st.dataframe(summary,use_container_width=True,hide_index=True)
    st.caption('RPS means successful HTTP requests/second. For LLMs, model tokens/second and provider quotas are separate measurements. Null first-token latency means no streaming token was observed.')
    for png,heading,explanation in CHARTS:
        st.subheader(heading)
        st.image(str(output / png),use_container_width=True)
        st.caption(explanation)
    c1,c2=st.columns(2)
    c1.download_button('Download summary.json',data=(output/'summary.json').read_bytes(),file_name='summary.json')
    c2.download_button('Download requests.csv',data=(output/'requests.csv').read_bytes(),file_name='requests.csv')
    st.info(f'Open {output/"dashboard.html"} in your browser to zoom and filter interactive charts. The generated HTML contains a description under each chart.')


tab_studio,tab_capacity_designer,tab_tests,tab_forecast,tab_browser,tab_about=st.tabs(['🧩 Visual test designer','🏗️ Forecast JSON designer','🧪 Run & advanced JSON', '📈 Capacity quick forecast','🌐 Browser chat test', '📚 Metrics & licenses'])
with tab_studio:
    render_test_designer(st, ROOT, show_benchmark)
with tab_capacity_designer:
    render_capacity_designer(st, ROOT)
with tab_tests:
    st.subheader('Test your services')
    choice=st.radio('Select test configuration',['Load JSON suite','Single endpoint form'],horizontal=True)
    if choice=='Load JSON suite':
        preset_files=sorted(EXAMPLES.glob('ai_forest_0*.json')) + [EXAMPLES/'benchmark_suite.json',EXAMPLES/'live_read_only_template.json']
        # Only Suite JSON files; the capacity file is loaded in the forecast tab.
        preset_files=[x for x in preset_files if 'capacity' not in x.name]
        preset=st.selectbox('Prepared JSON workload',preset_files,format_func=lambda x:x.name)
        st.caption('Every field in this JSON is editable before running. `enabled: false` keeps unverified operations out of the test. Change URL paths and MCP protocol to match your actual services.')
        suite_text=st.text_area('Suite configuration JSON',value=preset.read_text(encoding='utf-8'),height=370,key='suite_'+preset.name)
        try:
            suite=Suite.from_dict(json.loads(suite_text))
            cols=st.columns(4)
            cols[0].metric('Traffic mode',suite.mode)
            cols[1].metric('Test type',suite.test_type)
            cols[2].metric('Enabled cases',sum(c.enabled for c in suite.cases))
            cols[3].metric('Workers',max(suite.concurrency_levels) if suite.test_type=='ramp' else suite.concurrency)
            st.dataframe([{'case':c.name,'kind':c.kind,'enabled':c.enabled,'endpoint':c.url,'MCP tool':c.mcp_tool or '(tools/list)' if c.kind=='mcp' else '—','token env':c.token_env} for c in suite.cases],use_container_width=True,hide_index=True)
        except (ValueError,TypeError) as ex:
            st.error(f'JSON parse error: {str(ex)[:160]}')
            suite=None
        ack=st.checkbox('I own/operate these services, authorize the configured limited live requests and understand model calls may cost money',value=False,key='suite_ack')
        if st.button('Run selected JSON suite',type='primary',disabled=suite is None):
            try:
                suite.ack_live=ack if suite.mode=='live' else False
                show_benchmark(suite)
            except Exception as ex:
                st.error(f'Benchmark failed: {type(ex).__name__}. Check URL, model, MCP handshake, authentication, JSON and live safety settings. Do not paste secrets into error reports.')
    else:
        a,b,c,d=st.columns(4)
        mode=a.selectbox('Traffic destination',['mock','live'])
        kind=b.selectbox('Target type',['mcp','api','agent','llm'])
        test_type=c.selectbox('Test mode',['smoke','load','ramp','soak'])
        name=d.text_input('Case name',value='my-'+kind)
        endpoint=st.text_input('HTTP endpoint (used for live tests)',value={'mcp':'http://127.0.0.1:9135/mcp','api':'http://127.0.0.1:9102/api/status','agent':'http://127.0.0.1:9102/agent','llm':'http://127.0.0.1:4004/v1/chat/completions'}[kind])
        st.caption('Never save API tokens in JSON. Use environment-variable names for CLI and the local UI; temporary bearer entry below is used for this run only.')
        col1,col2,col3=st.columns(3)
        token_env=col1.text_input('Token environment variable name',value='')
        auth_token=col2.text_input('Or temporary bearer token',type='password')
        method=col3.selectbox('HTTP method',['POST','GET','PUT','PATCH','DELETE']) if kind in ['api','agent'] else 'POST'
        example={'api':{'status':'check'},'agent':{'query':'Reply OK to this synthetic request.'},'llm':{'messages':[{'role':'user','content':'Reply OK.'}],'max_tokens':12,'temperature':0},'mcp':{}}[kind]
        payload_text=st.text_area('Request payload JSON',value=json.dumps(example,indent=2),height=140)
        head_text=st.text_input('Extra request headers JSON',value='{}')
        mcp_version='2025-11-25';mcp_tool='';mcp_args='{}';model='mock-model';stream=False;expected_path='';expected_value=None
        if kind=='mcp':
            u,v=st.columns(2)
            mcp_version=u.selectbox('MCP protocol version',['2025-11-25','2026-07-28'])
            mcp_tool=v.text_input('Read-only tool name (blank = tools/list)')
            mcp_args=st.text_area('MCP arguments JSON',value='{}',height=85)
        if kind=='llm':
            u,v=st.columns(2)
            model=u.text_input('LLM model name',value='REPLACE_WITH_DEPLOYED_MODEL')
            stream=v.checkbox('Streaming responses (records time to first content token)')
        if kind in ['api','agent']:
            expected_path=st.text_input('Optional response JSON field (example: status)',value='')
        v1,v2,v3,v4=st.columns(4)
        samples=v1.number_input('Requests/stage',min_value=1,max_value=1000,value=10)
        concurrency=v2.number_input('Concurrent workers',min_value=1,max_value=100,value=1)
        rps=v3.number_input('Request rate limit (new calls/sec; live: 0–10)',min_value=0.0,value=1.0,step=.5)
        timeout=v4.number_input('Timeout (seconds)',min_value=1,max_value=300,value=30)
        levels_text=st.text_input('Ramp concurrency levels',value='1,2,4,8') if test_type=='ramp' else '1'
        soak_seconds=st.number_input('Soak duration (seconds)',min_value=1,max_value=3600,value=30) if test_type=='soak' else 30
        ack=st.checkbox('I own these endpoints and authorize limited live traffic') if mode=='live' else False
        if st.button('Run single-target benchmark',type='primary'):
            try:
                payload=json.loads(payload_text);headers=json.loads(head_text);args=json.loads(mcp_args)
                case=Case(name=name,kind=kind,url=endpoint,method=method,payload=payload,headers=headers,token_env=token_env,auth_token=auth_token,model=model,stream=stream,mcp_version=mcp_version,mcp_tool=mcp_tool,mcp_tool_args=args,expected_json_path=expected_path)
                suite=Suite(mode=mode,test_type=test_type,requests_per_case=int(samples),concurrency=int(concurrency),concurrency_levels=[int(x.strip()) for x in levels_text.split(',')],rps_limit=float(rps),timeout_s=float(timeout),soak_seconds=float(soak_seconds),ack_live=ack,cases=[case])
                show_benchmark(suite)
            except Exception as ex:
                st.error(f'Test configuration/connection failed: {type(ex).__name__}. Verify auth, MCP URL, model, port and server availability.')

with tab_forecast:
    st.subheader('Forecast Kubernetes application capacity')
    st.warning('All per-pod throughput defaults are illustrative. A forecast is NOT a measured production SLO or a production-ready Kubernetes manifest.')
    conf_path=st.selectbox('Capacity profile',[EXAMPLES/'ai_forest_03_capacity_forecast.json',EXAMPLES/'capacity_template.json'],format_func=lambda x:x.name)
    config=json.loads(conf_path.read_text(encoding='utf-8'))
    c1,c2,c3=st.columns(3)
    config['users']=c1.number_input('Total registered users',min_value=1,value=int(config['users']),step=100)
    config['active_fraction_at_peak']=c2.slider('Peak active users / all users',min_value=.01,max_value=1.0,value=float(config['active_fraction_at_peak']),step=.01)
    config['workflows_per_active_user_per_min']=c3.number_input('Workflows / active user / minute',min_value=.01,value=float(config['workflows_per_active_user_per_min']),step=.1)
    c1,c2,c3=st.columns(3)
    config['peak_multiplier']=c1.number_input('Burst multiplier (×)',min_value=1.0,value=float(config['peak_multiplier']),step=.1)
    config['reserved_headroom']=c2.slider('Reserved capacity headroom',min_value=.0,max_value=.8,value=float(config['reserved_headroom']),step=.05)
    config['llm_calls_per_workflow']=c3.number_input('LLM calls per workflow',min_value=.0,value=float(config['llm_calls_per_workflow']),step=.5)
    c1,c2=st.columns(2)
    config['llm_input_tokens_per_call']=c1.number_input('Input tokens / LLM call',min_value=1,value=int(config['llm_input_tokens_per_call']),step=50)
    config['llm_output_tokens_per_call']=c2.number_input('Output tokens / LLM call',min_value=1,value=int(config['llm_output_tokens_per_call']),step=50)
    st.caption('Adjust every service’s per-pod RPS only after an appropriate staging load test. Services shown below are placeholders, not validated pod resource requirements.')
    st.dataframe(config['services'],use_container_width=True,hide_index=True)
    services_text=st.text_area('Editable service sizing JSON',value=json.dumps(config['services'],indent=2),height=210)
    with st.expander('Kubernetes deployment placeholders'):
        config['project']=st.text_input('Kubernetes resource prefix',value=config['project'])
        config['hostname']=st.text_input('Host (must replace .invalid)',value=config['hostname'])
        config['gateway_class']=st.text_input('Installed GatewayClass',value=config['gateway_class'])
    if st.button('Generate forecast and K8s example manifests',type='primary'):
        try:
            config['services']=json.loads(services_text)
            ci=CapacityInputs.from_dict(config)
            dest=RESULTS/('capacity-'+STAMPS())
            result=write_capacity_report(ci,dest)
            c1,c2,c3=st.columns(3)
            c1.metric('Peak workflows/sec (TPS)',result['workflows_tps_peak'])
            c2.metric('Estimated app pod replicas',result['total_replicas'])
            c3.metric('LLM input+output tokens/min',f"{result['llm_total_tokens_per_min']:,}")
            st.dataframe(result['services'],use_container_width=True,hide_index=True)
            st.subheader('Application replica demand by user count')
            st.image(str(dest/'forecast_pods.png'),use_container_width=True)
            st.caption('X: registered users (people). Y: estimated Kubernetes application replicas (pods), by service. Assumes the specified fraction of users are simultaneously active and that each pod sustains the configured requests/sec.')
            st.subheader('Workflow and LLM call demand')
            st.image(str(dest/'forecast_tps.png'),use_container_width=True)
            st.caption('X: registered users. Y: workflow transactions per second (TPS) and LLM calls per second. These values are request demand, NOT tokens/sec or actual GPU/model serving speed.')
            st.download_button('Download capacity report',data=(dest/'CAPACITY_REPORT.md').read_bytes(),file_name='CAPACITY_REPORT.md')
            st.download_button('Download HPA/Deployment example YAML',data=(dest/'k8s'/'services-deployments-hpa.yaml').read_bytes(),file_name='services-deployments-hpa.yaml')
            st.info(f'All forecasts and YAML saved in {dest.resolve()}')
        except Exception as ex:
            st.error(f'Capacity planning failed: {type(ex).__name__}. Check JSON and deployment placeholders.')

with tab_browser:
    st.subheader('Browser-based chat smoke test (optional)')
    st.caption('Use this when you want to evaluate what a user sees in Cipher’s web chat, beyond the latency of calling the gateway API directly. Browser E2E results reflect frontend, agent, gateway and any memory retrieval combined.')
    st.info('Requires optional Playwright + Chromium: `python -m pip install playwright` then `python -m playwright install chromium`. No browser test runs automatically.')
    st.code('python web_ui_smoke.py --config examples/ai_forest_web_ui_optional.json --ack-live',language='bash')
    st.warning('Edit the UI CSS selectors from your actual page. The browser test does not identify Redis as the memory backend by itself. To prove persistence, correlate with the Redis Memory MCP read-only tool or backend trace, ideally across a new chat session.')
    st.code((EXAMPLES/'ai_forest_web_ui_optional.json').read_text(encoding='utf-8'),language='json')
    st.caption('The bundled browser test uses harmless synthetic text. Enable the optional cross-session memory scenario only in your authorized test environment; it deliberately asks the assistant to remember a synthetic nonce.')

with tab_about:
    st.subheader('How to interpret the measurements')
    st.markdown('**p20 / p50 / p95 / p99:** fraction of successful requests that finish within the plotted duration; **RPS:** completed HTTP calls/second; **TPS:** business workflows/second; **TTFT:** time until first generated content token in an SSE stream; **LLM tokens/sec:** model output speed, not equivalent to RPS. **c=4:** four concurrent workers, not four CPU cores.')
    st.markdown('**For Redis memory:** MCP `tools/list` tests network/protocol and tool discovery, not memory correctness. Test a read-only memory lookup only after verifying tool contracts. To test durable memory, seed synthetic data in an isolated environment and confirm retrieval in a new conversation, correlated with backend metrics.')
    st.markdown('**Licenses:** The requirements install existing third-party packages (`httpx`, `matplotlib`, `PyYAML`, `plotly`, and optionally `streamlit`/`pytest`). They are not original AI Forest inventions. The v0.3 toolkit contained no top-level LICENSE grant; we have not assigned an open-source license to your AI Forest code. See `DEPENDENCIES_AND_LICENSES.md`.')
