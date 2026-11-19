# MCP / Agent / API / LLM — reusable deployment capacity report template

> Template only; replace estimates with measured staging data. For repeatable calculations, edit `examples/capacity_template.json` and run `python -m agent_perf forecast`.

## 1. Workload definition

| Input | Value | How to measure / choose |
|---|---|---|
| Total registered users | `[users]` | Product adoption forecast |
| Peak active users | `[users × active_ratio]` | Concurrent activity instrumentation |
| Workflows/active user/min | `[workflows]` | Product usage logs |
| Burst multiplier | `[1.5]` | Marketing launches / time-of-day traffic |
| MCP calls/workflow | `[2]` | Distributed agent traces |
| Agent runs/workflow | `[1]` | Workflow definition |
| API calls/workflow | `[1]` | Gateway access logs |
| LLM calls/workflow | `[2]` | LLM telemetry |
| Mean input/output tokens | `[1000/250]` | Provider usage logs |
| Target p95 end-to-end latency | `[SLO]` | Product requirements |
| Target error rate | `[e.g. <1%]` | Product SLO |

## 2. Demand model

- `peak_workflow_tps = users × active_ratio × workflows_per_user_per_min × burst_factor / 60`
- `service_rps = peak_workflow_tps × calls_per_workflow`
- `safe_pod_rps = measured_pod_rps_at_p95_and_error_SLO × target_utilization`
- `replicas = max(min_HA, ceil(service_rps / safe_pod_rps / (1 − reserved_headroom)))`
- `cpu_request_total = replicas × cpu_request_per_pod`; likewise for memory
- `inference_tokens_per_min = llm_calls_per_second × 60 × average_tokens_per_call`

Do not conflate **workflow transactions/sec** with **LLM generated tokens/sec**. Do not estimate inference GPUs from HTTP gateway RPS alone.

## 3. Load balancer configuration decisions

| Setting | Starting proposal | Production verification |
|---|---|---|
| External entry | Managed L7 LB + supported Gateway API controller | GatewayClass installed, DNS, certificate, WAF policies |
| TLS | Terminate HTTPS at edge; re-encrypt internally if required | PKI and threat model |
| Routing | `/api`, `/mcp`, `/agent`, `/v1` to separate ClusterIP Services | Versioned API paths and access policies |
| Session handling | Stateless MCP preferred | Legacy MCP SSE/session affinity or shared state |
| Max concurrent requests | Based on bounded agent/tool/model capacity | Staging stress test |
| Retry policy | Idempotent operations only, exponential backoff + jitter | Prevent retry storms |
| Request timeout | By operation and streaming semantics | Match gateway implementation and agent deadlines |
| Rate limits | Per user/tenant/tool/model, reject overload with 429 | Provider quota and auth integration |
| Circuit breaker | Trip on known upstream failures; cap queues | Trace error budget |
| Canary | Weighted rollout / staged traffic split | Controller-specific support |

## 4. Kubernetes deployment configuration

For each workload, record: `image`, `replica min/max`, `CPU and memory requests/limits`, `HPA CPU target` *or* `KEDA custom/queue target`, probes, `PDB`, topology spreading, storage/network dependencies, metrics adapter and cluster autoscaler settings. See generated YAML.

Do **not** enable both KEDA and an independent HPA for the same Deployment. Use CPU HPA only if CPU is correlated with saturation; often for agent workflows, backlog/queue-age is more appropriate.

## 5. Acceptance criteria before production

- Correctness checks and auth/tenant isolation pass.
- Per-target p95 and p99 are measured with enough samples, at designed load and peak bursts.
- Error budgets, 429s, retries and upstream throttling observed.
- Node and pod resource utilization, HPA behavior and scale-up time tested.
- Failover during AZ/node/pod termination tested.
- Model serving/provider throughput and token quota confirmed separately.
- Autoscaling and load-balancer configuration reviewed against current cluster controller and installed CRDs.

## 6. Planning caveats

The generated node floor is **not** production node count. Platform services, HA zones, rollouts, observability, databases, model runtimes, queues and monitoring need additional budget. Forecasts are only as good as the per-pod benchmark data and traffic mix used to calculate them.
