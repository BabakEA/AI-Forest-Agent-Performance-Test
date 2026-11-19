"""Assumption-based Kubernetes capacity forecast, report and manifest templates.

IMPORTANT: this is a planning model, not a performance test or production sizing guarantee.
"""
from __future__ import annotations
import json
import math
from dataclasses import dataclass, asdict, field
from pathlib import Path

@dataclass
class ServiceCapacity:
    name: str
    requests_per_workflow: float
    measured_or_assumed_rps_per_pod: float
    cpu_request_m: int
    memory_request_mib: int
    cpu_limit_m: int
    memory_limit_mib: int
    min_ha_replicas: int = 2
    max_replicas: int = 100
    target_utilization_fraction: float = .65
    hpa_cpu_target_pct: int = 65
    image: str = 'registry.example.invalid/REPLACE_ME:tag'
    container_port: int = 8080

@dataclass
class CapacityInputs:
    project: str = 'agent-platform'
    hostname: str = 'agents.example.invalid'
    gateway_class: str = 'REPLACE_WITH_INSTALLED_GATEWAY_CLASS'
    users: int = 1000
    active_fraction_at_peak: float = .10
    workflows_per_active_user_per_min: float = 2.0
    peak_multiplier: float = 1.5
    reserved_headroom: float = .30
    node_allocatable_cpu_m: int = 7500
    node_allocatable_memory_mib: int = 28000
    node_max_pod_count: int = 60
    llm_calls_per_workflow: float = 2.0
    llm_input_tokens_per_call: int = 1000
    llm_output_tokens_per_call: int = 250
    services: list[ServiceCapacity] = field(default_factory=lambda:[
        ServiceCapacity('api',1,60,250,256,1000,512),
        ServiceCapacity('mcp',2,35,350,384,1200,768),
        ServiceCapacity('agent',1,12,500,768,1500,1536),
        ServiceCapacity('llm-gateway',2,25,350,384,1200,768),
    ])

    @classmethod
    def from_dict(cls,d):
        fields=set(cls.__dataclass_fields__)
        kwargs={k:v for k,v in d.items() if k in fields and k!='services'}
        if 'services' in d:kwargs['services']=[ServiceCapacity(**x) for x in d['services']]
        obj=cls(**kwargs);obj.validate();return obj

    def validate(self):
        if self.users < 1 or self.active_fraction_at_peak <= 0 or self.active_fraction_at_peak>1:raise ValueError('Check users / active_fraction_at_peak')
        if self.workflows_per_active_user_per_min <=0 or self.peak_multiplier <1 or not 0<=self.reserved_headroom <1: raise ValueError('Check demand and headroom')
        if not self.services:raise ValueError('At least one service required')
        if self.node_allocatable_cpu_m<=0 or self.node_allocatable_memory_mib<=0 or self.node_max_pod_count<=0:raise ValueError('Node allocatable must be > 0')
        for s in self.services:
            if any(x<=0 for x in (s.measured_or_assumed_rps_per_pod,s.cpu_request_m,s.memory_request_mib,s.max_replicas,s.target_utilization_fraction)) or not 0<s.target_utilization_fraction<=1:raise ValueError('Invalid service capacity')
            if s.min_ha_replicas>s.max_replicas:raise ValueError('minimum replicas exceed max')
            if s.requests_per_workflow<0:raise ValueError('Negative fanout')


def forecast(config:CapacityInputs):
    config.validate()
    active=config.users*config.active_fraction_at_peak
    workflows=active*config.workflows_per_active_user_per_min/60*config.peak_multiplier
    services=[]
    for s in config.services:
        fanout=config.llm_calls_per_workflow if s.name=='llm-gateway' else s.requests_per_workflow
        rps=workflows*fanout
        sustainable=s.measured_or_assumed_rps_per_pod*s.target_utilization_fraction
        capacity= math.ceil((rps/max(.00001,sustainable))/(1-config.reserved_headroom)) if rps>0 else 0
        desired=max(s.min_ha_replicas,capacity)
        services.append({'name':s.name,'target_rps':round(rps,2),'pod_baseline_rps':s.measured_or_assumed_rps_per_pod,
                         'safe_per_pod_rps':round(sustainable,2),'estimated_replicas':desired,
                         'max_replicas':s.max_replicas,'over_max':desired>s.max_replicas,
                         'requested_cpu_m':desired*s.cpu_request_m,'requested_memory_mib':desired*s.memory_request_mib,
                         'request_cpu_m_per_pod':s.cpu_request_m,'request_memory_mib_per_pod':s.memory_request_mib})
    total_cpu=sum(x['requested_cpu_m'] for x in services)
    total_mem=sum(x['requested_memory_mib'] for x in services)
    total_pods=sum(x['estimated_replicas'] for x in services)
    cpu_nodes=math.ceil(total_cpu/config.node_allocatable_cpu_m)
    mem_nodes=math.ceil(total_mem/config.node_allocatable_memory_mib)
    pod_nodes=math.ceil(total_pods/config.node_max_pod_count)
    llm_rps=workflows*config.llm_calls_per_workflow
    return {'users':config.users,'active_users_peak':round(active,1),
            'workflows_tps_peak':round(workflows,2),'workflows_per_min_peak':round(workflows*60,2),
            'llm_calls_per_sec':round(llm_rps,2),
            'llm_input_tokens_per_min':round(llm_rps*config.llm_input_tokens_per_call*60),
            'llm_output_tokens_per_min':round(llm_rps*config.llm_output_tokens_per_call*60),
            'llm_total_tokens_per_min':round(llm_rps*(config.llm_input_tokens_per_call+config.llm_output_tokens_per_call)*60),
            'services':services,'total_requested_cpu_m':total_cpu,'total_requested_memory_mib':total_mem,
            'total_replicas':total_pods,'node_floor':max(cpu_nodes,mem_nodes,pod_nodes),
            'node_floor_components':{'cpu':cpu_nodes,'memory':mem_nodes,'pod_limit':pod_nodes}}


def scenario_table(config:CapacityInputs, users:list[int] | None=None):
    levels=users or sorted(set([100,1000,5000,10000,25000,50000,config.users]))
    out=[]
    for count in levels:
        c=CapacityInputs.from_dict({**asdict(config),'users':count})
        out.append(forecast(c))
    return out


def write_capacity_report(config:CapacityInputs,path:str|Path,levels=None):
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    results=scenario_table(config,levels)
    current=forecast(config)
    (path/'capacity_config.json').write_text(json.dumps(asdict(config),indent=2),encoding='utf-8')
    (path/'capacity_forecast.json').write_text(json.dumps({'current':current,'scenarios':results},indent=2),encoding='utf-8')
    lines=['# MCP / Agent / API / LLM Gateway — Kubernetes capacity forecast',
           '', '> **PLANNING ESTIMATE ONLY.** Every value is assumption-driven unless you replace the RPS-per-pod inputs with measured staging data. No cloud account, cluster, GPU or upstream LLM-provider quotas were tested.',
           '', '## Input assumptions','',
           f'- Users: **{config.users:,}**; peak-active fraction: **{100*config.active_fraction_at_peak:.0f}%**; workflows per active user per minute: **{config.workflows_per_active_user_per_min:g}**; burst multiplier: **{config.peak_multiplier:g}×**.',
           f'- Spare capacity margin: **{100*config.reserved_headroom:.0f}%**; per-pod target fraction of observed/assumed capacity is service-specific.',
           f'- Requested resources refer to application pods only. Estimate excludes node/system services, observability, control plane, databases, message queues and LB gateways. Node floor is not a recommended production cluster size.',
           '', '## Demand conversion','',
           'Peak workflow TPS = users × active_fraction × workflows_per_active_user_per_min ÷ 60 × peak_multiplier.',
           'Service RPS = peak workflow TPS × service calls per workflow.',
           'Pods = max(HA minimum, ceil(service RPS ÷ (per-pod tested/assumed RPS × target utilization) ÷ (1 − reserved headroom))).',
           '',f'At **{config.users:,} users**, estimated peak is **{current["workflows_tps_peak"]} workflow transactions/sec** and **{current["llm_calls_per_sec"]} LLM calls/sec**.',
           f'**Token quota estimate:** {current["llm_input_tokens_per_min"]:,} input + {current["llm_output_tokens_per_min"]:,} output tokens/min. This is NOT the network or CPU throughput of the LLM gateway. Check provider/model quotas and GPU serving capacity separately.',
           '', '## Per-service pod recommendation','',
           '| Service | Peak RPS | Assumed/tested max RPS/pod | Target safe RPS/pod | Estimated replicas | CPU requested | Memory requested |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for s in current['services']:
        lines.append(f'| {s["name"]} | {s["target_rps"]} | {s["pod_baseline_rps"]} | {s["safe_per_pod_rps"]} | {s["estimated_replicas"]}{" ⚠ ABOVE HPA MAX" if s["over_max"] else ""} | {s["requested_cpu_m"]}m | {s["requested_memory_mib"]}Mi |')
    lines.extend(['',f'**App pod total:** {current["total_replicas"]} replicas, {current["total_requested_cpu_m"]}m CPU, {current["total_requested_memory_mib"]}Mi memory.',
                  f'**Theoretical minimum application-only nodes:** {current["node_floor"]}, based on CPU, memory and pod density; real clusters need platform overhead, HA spread and node autoscaler capacity.',
                  '', '## User-growth scenarios','',
                  '| Users | Peak workflow TPS | MCP RPS | Agent RPS | API RPS | LLM calls/s | Total app pods | Node floor | LLM total tokens/min |',
                  '|---:|---:|---:|---:|---:|---:|---:|---:|---:|'])
    for r in results:
        s={x['name']:x for x in r['services']}
        lines.append(f'| {r["users"]:,} | {r["workflows_tps_peak"]} | {s.get("mcp",{}).get("target_rps","—")} | {s.get("agent",{}).get("target_rps","—")} | {s.get("api",{}).get("target_rps","—")} | {r["llm_calls_per_sec"]} | {r["total_replicas"]} | {r["node_floor"]} | {r["llm_total_tokens_per_min"]:,} |')
    lines.extend(['','## Load balancer and Kubernetes recommendations','',
                  '1. **Gateway API:** choose an installed GatewayClass/controller; TLS terminate at the Gateway, attach HTTPRoutes to ClusterIP Services, require authentication and tenant authorization within the service boundary. Replace placeholder host, images, class, TLS secret and other settings.',
                  '2. **MCP:** stateless protocol endpoints are easier to scale horizontally; legacy stateful MCP sessions require connection/session affinity or a distributed session store. Validate SSE/streaming idle timeouts with the specific gateway controller.',
                  '3. **HPA:** CPU-based scaling uses the included `autoscaling/v2` example; CPU may be a poor proxy for I/O-heavy MCP or LLM gateways. For mature deployment, choose a metric aligned with saturation (in-flight requests, successful RPS per pod, queue depth, CPU or provider throttling) and expose it via a supported metrics adapter/KEDA.',
                  '4. **KEDA / queue:** long-running agents should normally execute asynchronously via queues, with idempotency keys and cancellation. Scale workers against pending work and task age, not just HTTP QPS.',
                  '5. **LLM:** gateway pods only forward/model-route; model compute and provider token-per-minute limits are separate bottlenecks. Never infer GPU requirements from gateway pod count.',
                  '6. **Protection:** admission rate limits and per-tenant quotas, circuit breakers, connection and timeout budgets, retry-with-jitter, 429 propagation, pod readiness, PodDisruptionBudgets, topology spreading, and controlled scale-up.',
                  '7. **Metrics:** record p50/p95/p99 and error rates per operation, `successful TPS`, `LLM tokens/s`, queue backlog, HPA desired/current replicas, CPU and memory; load-test at every planned growth tier.',
                  '','## Configuration status', '',
                  '- Manifests in `k8s/` are **illustrative**, not guaranteed to deploy as-is. They contain replacement image names, GatewayClass, host and TLS secret; inspect and adapt before applying.',
                  '- Do **not** install both HPA and KEDA objects targeting the same Deployment; choose a single scaler owner for each workload.',
                  '- Never paste API keys into manifests or reports. Inject credentials via a managed Secret or workload identity.',
                  ''])
    (path/'CAPACITY_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    render_k8s(config,path/'k8s',current)
    chart_capacity(results,path)
    return current


def render_k8s(config:CapacityInputs,path:Path,current:dict):
    import yaml
    path.mkdir(parents=True,exist_ok=True)
    objects=[]
    for svc in config.services:
        rec=next(s for s in current['services'] if s['name']==svc.name)
        labels={'app':config.project+'-'+svc.name}
        objs=[
          {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':labels['app']},'spec':{
             'replicas':min(svc.max_replicas,max(svc.min_ha_replicas,rec['estimated_replicas'])),
             'selector':{'matchLabels':labels},'template':{'metadata':{'labels':labels},'spec':{
               'terminationGracePeriodSeconds':60,
               'containers':[{'name':svc.name,'image':svc.image,'ports':[{'containerPort':svc.container_port}],
                 'resources':{'requests':{'cpu':f'{svc.cpu_request_m}m','memory':f'{svc.memory_request_mib}Mi'},
                              'limits':{'cpu':f'{svc.cpu_limit_m}m','memory':f'{svc.memory_limit_mib}Mi'}},
                 'readinessProbe':{'httpGet':{'path':'/health','port':svc.container_port},'periodSeconds':5},
                 'livenessProbe':{'httpGet':{'path':'/health','port':svc.container_port},'periodSeconds':15},
                 'envFrom':[{'secretRef':{'name':'REPLACE_WITH_EXISTING_SERVICE_SECRET'}}]}]}}}},
          {'apiVersion':'v1','kind':'Service','metadata':{'name':labels['app']},'spec':{
             'selector':labels,'type':'ClusterIP','ports':[{'name':'http','port':80,'targetPort':svc.container_port}]}},
          {'apiVersion':'autoscaling/v2','kind':'HorizontalPodAutoscaler','metadata':{'name':labels['app']+'-hpa'},'spec':{
             'scaleTargetRef':{'apiVersion':'apps/v1','kind':'Deployment','name':labels['app']},
             'minReplicas':svc.min_ha_replicas,'maxReplicas':svc.max_replicas,
             'metrics':[{'type':'Resource','resource':{'name':'cpu','target':{
                        'type':'Utilization','averageUtilization':svc.hpa_cpu_target_pct}}}],
             'behavior':{'scaleUp':{'stabilizationWindowSeconds':0,'policies':[{'type':'Pods','value':4,'periodSeconds':60},
                            {'type':'Percent','value':100,'periodSeconds':60}],'selectPolicy':'Max'},
                         'scaleDown':{'stabilizationWindowSeconds':300,'policies':[{'type':'Percent','value':20,'periodSeconds':60}]}}}},
          {'apiVersion':'policy/v1','kind':'PodDisruptionBudget','metadata':{'name':labels['app']+'-pdb'},'spec':{
             'minAvailable':1,'selector':{'matchLabels':labels}}}
        ]
        objects.extend(objs)
    (path/'services-deployments-hpa.yaml').write_text(yaml.safe_dump_all(objects,sort_keys=False),encoding='utf-8')
    gateway={'apiVersion':'gateway.networking.k8s.io/v1','kind':'Gateway','metadata':{'name':config.project+'-gateway'},'spec':{
        'gatewayClassName':config.gateway_class,'listeners':[{'name':'https','hostname':config.hostname,
             'port':443,'protocol':'HTTPS','tls':{'mode':'Terminate','certificateRefs':[{'kind':'Secret','name':'REPLACE_WITH_TLS_SECRET'}]}}]}}
    paths={'api':'/api','mcp':'/mcp','agent':'/agent','llm-gateway':'/v1'}
    routes=[]
    for svc in config.services:
        if svc.name not in paths:continue
        routes.append({'apiVersion':'gateway.networking.k8s.io/v1','kind':'HTTPRoute','metadata':{'name':config.project+'-'+svc.name+'-route'},'spec':{
          'parentRefs':[{'name':config.project+'-gateway'}],'hostnames':[config.hostname],
          'rules':[{'matches':[{'path':{'type':'PathPrefix','value':paths[svc.name]}}],
                    'backendRefs':[{'name':config.project+'-'+svc.name,'port':80}]}]}})
    (path/'gateway-httproutes.yaml').write_text(yaml.safe_dump_all([gateway,*routes],sort_keys=False),encoding='utf-8')
    # Optional Prometheus/KEDA queue-based autoscaling alternative for agent workers.
    # Do NOT combine it with the CPU HPA above for the same Deployment.
    keda={'apiVersion':'keda.sh/v1alpha1','kind':'ScaledObject',
          'metadata':{'name':config.project+'-agent-queue-scaler'},
          'spec':{'scaleTargetRef':{'name':config.project+'-agent'},
                  'minReplicaCount':2,'maxReplicaCount':100,'pollingInterval':15,'cooldownPeriod':300,
                  'triggers':[{'type':'prometheus','metadata':{
                    'serverAddress':'http://REPLACE_WITH_PROMETHEUS:9090',
                    'metricName':'agent_queue_depth',
                    'query':'sum(agent_queue_depth{workload="REPLACE_ME"})',
                    'threshold':'10',
                    'activationThreshold':'1'}}]}}
    (path/'OPTIONAL-keda-agent-queue.yaml').write_text(yaml.safe_dump(keda,sort_keys=False),encoding='utf-8')
    # Optional per-workload RPS-based autoscaling via Prometheus; requires a
    # validated counter/labels and removal of the same workload's CPU HPA.
    rps_keda={'apiVersion':'keda.sh/v1alpha1','kind':'ScaledObject',
        'metadata':{'name':config.project+'-mcp-rps-scaler'},
        'spec':{'scaleTargetRef':{'name':config.project+'-mcp'},
           'minReplicaCount':2,'maxReplicaCount':100,'pollingInterval':15,
           'triggers':[{'type':'prometheus','metadata':{
             'serverAddress':'http://REPLACE_WITH_PROMETHEUS:9090',
             'metricName':'mcp_requests_per_second',
             'query':'sum(rate(http_requests_total{service="REPLACE_WITH_MCP_METRIC_LABEL"}[2m]))',
             'threshold':'15',
             'activationThreshold':'1'}}]}}
    (path/'OPTIONAL-keda-mcp-rps.yaml').write_text(yaml.safe_dump(rps_keda,sort_keys=False),encoding='utf-8')

    (path/'README.md').write_text('# Kubernetes starter manifests (not apply-ready)\n\nInstall a Gateway API controller and CRDs first. Replace image names, domain, GatewayClass, TLS secret, auth secret and health path. Replace HPA CPU targets with measured custom traffic or queue metrics if CPU does not track request saturation. Use only one autoscaler per deployment. All service URLs and images are illustrative. Test against a staging cluster before applying.\n',encoding='utf-8')


def chart_capacity(results:list[dict],path:Path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    users=[r['users'] for r in results]
    names=[s['name'] for s in results[0]['services']]
    fig,ax=plt.subplots(figsize=(10,5))
    for name in names:
        ax.plot(users,[next(x['estimated_replicas'] for x in r['services'] if x['name']==name) for r in results],label=name,marker='o')
    ax.set_xlabel('Total users');ax.set_ylabel('Estimated application replicas');ax.set_title('Capacity forecast — assumption-driven pod count')
    ax.legend();ax.grid(alpha=.2);fig.tight_layout();fig.savefig(path/'forecast_pods.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,5))
    ax.plot(users,[r['workflows_tps_peak'] for r in results],marker='o',label='Workflow TPS')
    ax.plot(users,[r['llm_calls_per_sec'] for r in results],marker='x',label='LLM calls/sec')
    ax.set_xlabel('Total users');ax.set_ylabel('TPS / calls per sec');ax.set_title('Forecast workload demand');ax.grid(alpha=.2);ax.legend()
    fig.tight_layout();fig.savefig(path/'forecast_tps.png',dpi=150);plt.close(fig)
