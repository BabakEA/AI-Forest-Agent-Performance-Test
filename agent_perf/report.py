"""Privacy-conscious benchmark reports and offline charts."""
from __future__ import annotations
import csv
import json
import math
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from typing import Iterable
from .models import Observation, Suite


def percentile(values: list[float], p: int) -> float | None:
    if not values: return None
    a=sorted(values)
    pos=(len(a)-1)*p/100
    lo=math.floor(pos);hi=math.ceil(pos)
    return round(a[lo]+(a[hi]-a[lo])*(pos-lo),3)


def summarize(obs: list[Observation], elapsed: float, case: str, kind: str, concurrency: int) -> dict:
    completed=[o for o in obs if o.ok]
    lats=[o.latency_ms for o in completed]
    first_tokens=[o.first_token_ms for o in completed if o.first_token_ms is not None]
    duration=max(.001,elapsed)
    return {'case':case, 'kind':kind,'concurrency':concurrency,
            'attempted':len(obs),'success':len(completed),'errors':len(obs)-len(completed),
            'success_pct':round(100*len(completed)/max(1,len(obs)),2),
            'duration_s':round(duration,3),'success_rps':round(len(completed)/duration,3),
            'attempt_rps':round(len(obs)/duration,3),
            'p20_ms':percentile(lats,20),'p50_ms':percentile(lats,50),
            'p95_ms':percentile(lats,95),'p99_ms':percentile(lats,99),
            'first_token_p50_ms':percentile(first_tokens,50),
            'transfer_mbps':round(8*sum(x.request_bytes+x.response_bytes for x in obs)/duration/1e6,5),
            'observed_input_tokens':sum(x.input_tokens or 0 for x in completed),
            'observed_output_tokens':sum(x.output_tokens or 0 for x in completed),
            'token_usage_reported_count':sum(x.input_tokens is not None or x.output_tokens is not None for x in completed)}


def save_benchmark(path: str | Path, obs: list[Observation], summary: list[dict], suite: Suite):
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    fields=list(Observation.__dataclass_fields__)
    with (path/'requests.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader(); writer.writerows(asdict(x) for x in obs)
    (path/'summary.json').write_text(json.dumps({'test_config':suite.public(),'summary':summary},indent=2),encoding='utf-8')
    header='| Case | Kind | Workers | N | Success | p20 ms | p50 ms | p95 ms | p99 ms | Success RPS |\n|---|---|---:|---:|---:|---:|---:|---:|---:|---:|'
    rows=[]
    for r in summary:
        v=[r['case'],r['kind'],r['concurrency'],r['attempted'],f"{r['success_pct']}%",r['p20_ms'],r['p50_ms'],r['p95_ms'],r['p99_ms'],r['success_rps']]
        rows.append('| '+' | '.join(str(x) if x is not None else 'n/a' for x in v)+' |')
    (path/'REPORT.md').write_text('# Performance benchmark results\n\n**Measurements:** client-observed, not server CPU or hardware capacity. Failed requests are excluded from successful latency percentiles and separately counted. Payload byte counts omit headers and TLS overhead. Token usage is only counted when returned by the server.\n\n'+header+'\n'+'\n'.join(rows)+'\n\n**Live results:** only if explicitly enabled; mock results are synthetic and cannot be used as production capacity evidence.\n',encoding='utf-8')
    make_charts(path,obs,summary)
    return path


def make_charts(path:Path,obs:list[Observation],summary:list[dict]):
    '''Save readable static PNGs and a self-contained, captioned HTML dashboard.'''
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels=[f"{r['case']}\n{r['concurrency']} concurrent workers" for r in summary]
    x=list(range(len(labels)))
    notes={
      'latency': 'X = target service + concurrent request workers; Y = successful call latency in milliseconds. p20, p50, p95 and p99 represent completion thresholds for 20%, 50%, 95% and 99% of successful requests. Failed calls are tracked separately.',
      'throughput': 'X = target service + concurrent workers; Y = successful HTTP responses per second (RPS). High throughput only helps while tail latency and error rate meet your objectives. RPS differs from LLM output tokens per second.',
      'failures': 'X = target service + concurrent workers; Y = count of unsuccessful requests. Includes HTTP and protocol errors, timeouts and failed JSON assertions; inspect request counts before interpreting rates.',
      'timeline': 'X = seconds since test-stage origin; Y = client-observed latency (milliseconds) of each successful request. Look for latency spikes as concurrency and request volume change. This is not CPU utilization.',
    }
    (path/'CHART_GUIDE.md').write_text('''# Understanding the performance graphs

**1c / c=1** = one concurrent request worker; **2c** = two; **4c** = four. They are not CPU cores.

''' + '\n\n'.join(f'## {k.title()}\n\n{v}' for k,v in notes.items()) + '\n\nLatency quantiles exclude failed calls. A small sample does not provide reliable p99 estimates.\n',encoding='utf-8')

    def save_static(kind,filename):
        fig,ax=plt.subplots(figsize=(max(10,len(labels)*2.1),5.5))
        if kind=='latency':
            for name in ('p20_ms','p50_ms','p95_ms','p99_ms'):
                ax.plot(x,[r[name] if r[name] is not None else float('nan') for r in summary],marker='o',label=name.removesuffix('_ms'))
            ax.set_title('Successful request latency — percentile thresholds')
            ax.set_ylabel('Latency (milliseconds, ms)')
            ax.legend(title='Percentile')
        elif kind=='throughput':
            ax.bar(x,[r['success_rps'] for r in summary])
            ax.set_title('Successfully completed requests per second')
            ax.set_ylabel('Success throughput (requests/second, RPS)')
        else:
            ax.bar(x,[r['errors'] for r in summary])
            ax.set_title('Failed HTTP requests by target')
            ax.set_ylabel('Failed request count (requests)')
        ax.set_xticks(x,labels,rotation=15,ha='right')
        ax.set_xlabel('Target service and concurrency (simultaneous workers)')
        ax.grid(axis='y',alpha=.2)
        fig.text(.02,.015,notes[kind],fontsize=8,wrap=True,ha='left',va='bottom')
        fig.tight_layout(rect=(0,.085,1,1))
        fig.savefig(path/filename,dpi=150,bbox_inches='tight')
        plt.close(fig)
    save_static('latency','latency_percentiles.png')
    save_static('throughput','throughput.png')
    save_static('failures','failures.png')

    try:
        import html
        import plotly.graph_objects as go
        import plotly.io as pio
        figures=[]
        f=go.Figure()
        for name in ('p20_ms','p50_ms','p95_ms','p99_ms'):
            f.add_trace(go.Scatter(x=labels,y=[r[name] for r in summary],name=name.removesuffix('_ms'),mode='lines+markers'))
        f.update_layout(title='Latency percentiles by service and concurrency',xaxis_title='Target service / concurrent workers',yaxis_title='Successful call latency (ms)',height=490)
        figures.append(('Latency percentile thresholds',f,notes['latency']))
        f=go.Figure(go.Bar(x=labels,y=[r['success_rps'] for r in summary],name='Successful RPS'))
        f.update_layout(title='Success throughput',xaxis_title='Target service / concurrent workers',yaxis_title='Requests per second (RPS)',height=460)
        figures.append(('Throughput',f,notes['throughput']))
        f=go.Figure(go.Bar(x=labels,y=[r['errors'] for r in summary],name='Failed requests'))
        f.update_layout(title='Request failures',xaxis_title='Target service / concurrent workers',yaxis_title='Failed requests (count)',height=460)
        figures.append(('Failed calls',f,notes['failures']))
        f=go.Figure()
        for group in sorted({x.case for x in obs}):
            items=[x for x in obs if x.case==group and x.ok]
            f.add_trace(go.Scatter(x=[o.start_s for o in items],y=[o.latency_ms for o in items],mode='markers',name=group,marker={'size':5,'opacity':.5}))
        f.update_layout(title='Request-level latency over time',xaxis_title='Seconds from test origin (s)',yaxis_title='Successful call latency (ms)',height=490)
        figures.append(('Latency timeline',f,notes['timeline']))
        blocks=[]
        for i,(title,fig,note) in enumerate(figures):
            fragment=pio.to_html(fig,full_html=False,include_plotlyjs=True if i==0 else False,config={'responsive':True,'displaylogo':False})
            blocks.append(f'<section><h2>{html.escape(title)}</h2>{fragment}<p class="explain">{html.escape(note)}</p></section>')
        page='''<!doctype html><html><head><meta charset="utf-8"><title>AI Forest Performance Charts</title><style>body{font-family:system-ui,-apple-system,Segoe UI,Arial;max-width:1280px;margin:24px auto;padding:0 16px;color:#202936;background:#f6f8fc}header,section{background:#fff;border:1px solid #e5eaf0;border-radius:14px;padding:20px;margin-bottom:24px;box-shadow:0 2px 6px #0001}h1{margin-top:0}.explain{font-size:14px;color:#475569;line-height:1.7;border-top:1px solid #e5eaf0;padding-top:10px}code{background:#eff2f7;padding:2px 5px;border-radius:3px}</style></head><body><header><h1>AI Forest MCP / API / Agent / LLM Benchmarks</h1><p>Client-observed HTTP metrics. <b>1c = one concurrent worker, 2c = two, 4c = four</b>, not CPU cores. Results from mock runs are synthetic and cannot establish production capacity.</p></header>''' + ''.join(blocks) + '</body></html>'
        (path/'dashboard.html').write_text(page,encoding='utf-8')
    except ImportError:
        pass
