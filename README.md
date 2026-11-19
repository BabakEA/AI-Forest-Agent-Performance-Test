# AI Forest Agent Performance Test (AFPerf)

A local-first Python package and visual configuration studio for **MCP / REST API / Agent / LLM gateway** benchmarking and **assumption-based Kubernetes capacity forecasting**. Engineering prototype **v0.7.0**.

> **Safety:** The default project runs **mock tests only**. Live traffic requires approved endpoints and `--ack-live`. Do not publish the unauthenticated Streamlit dashboard to the internet. Keep `.env` secret.

## Installation

After the first approved PyPI release, install the published distribution with:

```bash
python -m pip install afperf
afperf init my-benchmarks
cd my-benchmarks
afperf start
```

**Note:** `pip install afperf` requires a successful, publicly available PyPI release. Before publishing, use the local wheel. The single-command install includes Streamlit.


### Local source installation (Windows Git Bash, macOS, Linux)

```bash
cd agent-performance-test
python -m pip install -e '.[dashboard,test]'
afperf --version
```

Both `afperf` and `aiforest-perf` run the same CLI. `agent-performance-test` remains available as a compatibility entrypoint. Unlike the old `apt` name, `afperf` does not shadow the Linux package manager.

### Install an offline-built wheel

```bash
python -m pip install ./dist/afperf-0.7.0-py3-none-any.whl
```

The wheel contains application code, dashboard and JSON templates, **not vendored Python dependencies**. Runtime dependencies still need to be installed from an approved package index or internal wheelhouse. The ZIP includes the wheel separately.

## Quick start

```bash
afperf init my-benchmarks
cd my-benchmarks
afperf start                  # local browser dashboard http://127.0.0.1:8501
```

The dashboard lets users design, validate and download benchmark and capacity JSON. It explains each chart, axis and metric; `1c`, `2c` and `4c` mean one, two or four **concurrent HTTP test workers**, not CPU cores or Kubernetes replicas.

### Benchmark and forecast

```bash
afperf performance benchmark.json --out results/benchmark
afperf forecast forecast.json --out results/forecast
```

`afperf benchmark benchmark.json` aliases `afperf performance`. `afperf forecast benchmark.json` also works when a sibling `forecast.json` exists: it explicitly prints that it is using the capacity profile. Benchmark results **do not automatically determine sustainable per-pod TPS**. Enter measured or assumed RPS-per-pod in `forecast.json`.

### Approved live testing only

Edit `benchmark.json` to switch `mode` to `live`; use *only* approved read-only operations with bounded load:

```bash
afperf performance benchmark.json --ack-live --out results/approved-live
```

Live traffic is rejected unless acknowledged. The current library additionally enforces conservative caps on rate, concurrency and test length. Synthetic payloads are preferable to confidential user data.

### Docker scaffolding

```bash
afperf docker
sh docker/start.sh build
sh docker/start.sh run
# Or: sh docker/start.sh compose
# Shutdown: sh docker/start.sh down
```

`afperf docker` **creates** `docker/Dockerfile`, `docker/src/`, `docker/config/`, `docker/docker-compose.yml`, `.dockerignore` and `docker/start.sh`. It does **not** build or run containers automatically. Source is bundled locally, so Docker does not depend on this package being published on PyPI. No `.env` or tokens are copied into the generated image. The Dockerfile still downloads Python dependencies when it builds. Use `host.docker.internal` rather than `127.0.0.1` for endpoints on the host under Docker Desktop.

Default Docker dashboard binds only to `127.0.0.1:8501`; it does not expose remote/public access. Authentication and access controls are not yet suitable for a multi-tenant enterprise SaaS.

## Project layout

```text
my-benchmarks/
  benchmark.json           # versioned MCP/API/agent/LLM tests
  forecast.json            # capacity assumptions and service profiles
  .env.example             # safe variable names only
  .env                     # optional local secrets: create yourself
  examples/                # AI Forest starter profiles
  results/                 # reports, raw CSV, charts and K8s templates
  docker/                  # generated offline source and Docker scaffold
```

## Why it exists

Performance benchmarking and Kubernetes capacity planning are frequently disconnected, especially for workflows composed of tools, memory, retrieval and model calls. AFPerf aims to bring representative synthetic tests, p20/p50/p95/p99 latency, errors, token usage and versioned capacity assumptions into one local-friendly workflow.

The **[white paper](WHITE_PAPER.md)** explains the approach, limitations, competitive positioning and roadmap. The original AFPerf code is published under **Apache License 2.0**, with AI Forest attribution in `NOTICE`. Third-party library licenses apply independently.

## Verification

The Python CLI, project initializer, mock benchmark, forecast, offline Docker generator, and existing unit tests can be tested without a network connection. The Streamlit UI and actual Docker image execution must be verified on a developer workstation / CI runner with those tools installed.

## CLI naming (v0.6.1)

The v0.6.0 `apt` executable was removed because Linux distributions use `apt` for package management. Use `afperf` (recommended) or `aiforest-perf`. The Python distribution is renamed to `afperf` starting with v0.7.0. The Python import path remains `agent_perf`. This package has not been published to PyPI in this release. A preliminary name search is not trademark clearance.

## Building and publishing the official package

See [RELEASING.md](RELEASING.md). `bash scripts/release.sh --version 0.7.0 --build-only` builds locally; `--publish` performs authenticated release actions after safety checks and legal license approval. **Never paste credentials into a command.**

## License

AFPerf is licensed under the Apache License, Version 2.0 (`Apache-2.0`). See [LICENSE](LICENSE), [NOTICE](NOTICE) and [LICENSING.md](LICENSING.md). AI Forest names and marks remain separate from the software license.
