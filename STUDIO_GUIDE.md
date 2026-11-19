# AI Forest Performance & Capacity Studio v0.5 — User Guide

**Purpose:** create and run MCP, REST API, AI-agent and LLM-gateway performance tests without manually writing JSON; generate a separate Kubernetes capacity forecast with explainable assumptions. The original CLI, batch runner, browser UI test and charts are still available.

## Launch from Windows Git Bash

```bash
cd /path/to/Agent_Performance_Toolkit
python -m pip install -e '.[dashboard,test,browser]'
cp .env.example .env
notepad.exe .env
python -m streamlit run dashboard.py
```

No per-project `.venv` is created or bundled. Use your existing Python/Conda environment.

## Visual workflow: create performance_test.json

1. Open **Visual test designer**. Use the safe mock example, select a prepared AI Forest suite, or import your existing JSON file.
2. In **Traffic settings**, choose `mock` or `live`, `smoke` / `load` / `ramp` / `soak`, requests per stage, concurrency (`1c`, `2c`, `4c`, `8c`), RPS rate cap, warmup and timeout. Save these settings. `smoke` always sends **one measured request per enabled case**, regardless of the requests-per-stage input.
3. In **Endpoint rules**, choose **Add a new endpoint rule**. Select `MCP`, `API`, `agent` or `LLM`, then supply a test name, full URL, method where applicable, expected status, optional JSON response assertion, and payload.
4. For **LLM**, select model (`gemma4:26b`, `gpt-luna-fast`, etc.), streaming, maximum output tokens, temperature and optional synthetic input word count. Synthetic word count adds harmless, deterministic words to the user message. **Words are not tokens**; use actual provider usage metadata for token accounting.
5. For **MCP**, select the server protocol version, then run `tools/list` first (blank tool name). Only select a verified **read-only** tool for `tools/call`. Never load-test memory writes or physical device actions from these examples.
6. Choose the token mode: `.env` variable name (recommended), a masked **session-only** token for a dashboard run, or no authentication. Actual token values are not exported to JSON or bundles. If you choose session-only mode, the downloaded JSON cannot reproduce auth in the CLI; switch to an `.env` variable name for reusable configurations.
7. Save the endpoint. Repeat to add more cases. Duplicate, edit, disable or delete cases from the list.
8. Preview and **Download performance_test.json**. Place it in the `examples/` folder and run it with the original CLI, or authorize a **Run designed benchmark** in the dashboard.

**Safe example:**

```bash
python -m agent_perf benchmark --config examples/performance_test.json --out results/mock
```

**Authorized live test:**

```bash
python -m agent_perf benchmark --config examples/performance_test.json --ack-live --out results/live
```

Live runs are capped by the toolkit: 8 concurrent client workers, 10 new requests/sec, 1000 measured calls per case/stage, and 120 seconds for soak. A preset does **not** imply permission to stress someone else's service.

## Visual workflow: create capacity_forecast.json

1. Open **Forecast JSON designer** and set registered users, active fraction at peak, workflows per active user per minute, burst multiplier, and reserve headroom.
2. Enter average LLM calls per workflow plus estimated input/output tokens per model call.
3. Use the **service sizing table** to add, edit or delete services. For each service, specify requests per workflow, sustainable requests/second per Kubernetes pod, CPU/memory requests, and replica min/max. Toggle **Show advanced service sizing fields** to edit image, port, utilization and resource limits.
4. Fill node allocatable CPU, memory and max pods/node, plus Kubernetes resource prefix, hostname and installed GatewayClass (or leave clearly labeled placeholders for demonstration reports).
5. Save, preview and **Download capacity_forecast.json**. Optionally choose **Generate forecast report and graphs**. The combined export includes both JSONs and a sanitized `.env.example`.

```bash
python -m agent_perf forecast --config examples/capacity_forecast.json --out results/capacity
```

**Forecast is a scenario, not a capacity certification.** Replace assumed RPS/pod with measured sustainable values at your p95/error SLO. Gateway pod counts do not size local GPU inference or guarantee provider token quotas. `TPS` for workflows and `tokens/second` for model output are separate units.

## Simple field dictionary

| Label | Meaning |
| --- | --- |
| Case | One independent endpoint operation or model variant, with its own payload/expected response |
| Mock / live | Simulated local traffic / actual HTTP requests to the endpoint |
| Smoke | Connectivity and basic correctness, exactly one timed request per case |
| Load | Fixed concurrency and number of requests |
| Ramp | Several stages of increasing client concurrency, e.g. 1,2,4,8 |
| Soak | Bounded sustained request traffic |
| `1c`, `2c`, `4c`, `8c` | Concurrent client HTTP request workers, **not** CPU cores, pods, or model inference workers |
| `requests_per_case` | Timed requests for one case at each stage, except smoke |
| `rps_limit` | Max new calls per second at a test stage; can be the bottleneck |
| `token_env` | **Name** of secret-bearing environment variable, e.g. `LLM_GATEWAY_TOKEN`; not the value |
| Session token | Actual API key entered into a masked widget and used only in this local session |
| `model` / `model_env` | Explicit gateway model alias / optional env-variable name that overrides it |
| Input words | Approximate text size via an exact count of harmless space-delimited words |
| Output tokens | `max_tokens` request budget; actual use depends on model/provider |
| p20/p50/p95/p99 | Successful client-observed latency quantiles in milliseconds |
| Workflow TPS | End-user tasks per second, not the number of MCP/LLM calls |
| Safe RPS/pod | Service pod throughput compatible with the acceptable p95/error rate |
| CPU request (mCPU) | Kubernetes CPU reservation, where 1000 mCPU equals one vCPU |
| Memory request (MiB) | Kubernetes memory reservation, not total host memory |

## Secrets and safety

- Use `.env` for local secrets; do not commit it or put secrets into URLs, headers JSON, or test payloads. The visual designer rejects common raw authorization header names.
- A `.env.example` is deliberately only a template of variable names and `REPLACE_ME` placeholders.
- Session-only token mode does not persist passwords to generated JSON. It is meant for local, temporary runs, not sharing or team automation.
- Protect the Streamlit host with network controls; this is a **local development dashboard**, not a multi-user production RBAC service. Adding login/roles, server-side secret storage, tenant isolation, task queues, audit logs, and a secure agent runner are separate hardening milestones before SaaS deployment.
- Request payloads are included in exported benchmark JSON. Use only synthetic or approved test data. Review files before distributing them.
- The report generator writes Kubernetes examples, not ready-to-apply manifests; inspect image, namespace, secrets, TLS, GatewayClass, scaling, affinity and probe paths.

## Testing and packaging

```bash
python -m pytest -q
```

The visual builder uses the actual `Suite` and `CapacityInputs` classes; exports are validated with the same contracts as the CLI. The UI code is in `agent_perf/studio_ui.py`, with testable serializing logic in `agent_perf/designer.py`.
