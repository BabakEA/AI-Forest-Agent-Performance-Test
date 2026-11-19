# AFPerf v0.7.0 — PyPI distribution & release tooling

- PyPI project/distribution renamed to `afperf`; command remains `afperf`.
- Dashboard dependency included in base install (`pip install afperf`).
- Added guarded Bash release pipeline, source distribution, wheel and GitHub Release generation.
- Added version synchronization and release instructions.
- PyPI and GitHub publishing are **not completed** by this source archive.

## v0.6.1 — AFPerf CLI naming refresh (19 November 2026)
- Replace ambiguous `apt` entrypoint with `afperf` and descriptive `aiforest-perf`; retain `agent-performance-test` for compatibility.
- Update Python module execution, Dockerfile, Compose service, bootstrap output, white paper and documentation.
- Keep distribution name and JSON schemas unchanged; no user secrets or existing configuration migration required.
- Naming is a proposal for distribution, not trademark clearance or PyPI publication.

## v0.5.0 — Visual Configuration Studio
- Guided Streamlit editors for test suites and Kubernetes forecasts, with validations and explanations.
- Add/duplicate/edit/delete endpoint rules, multi-service forecasts, and test settings.
- Generate CLI-compatible performance_test.json and capacity_forecast.json.
- Optional synthetic input word counts, separate output-token budget, and explicit model aliases.
- Environment-variable secrets or session-only masked token input; no raw secrets in exports.
- One-click combined ZIP export with both configs, safe .env.example, and setup notes.
- Added tests for JSON roundtrips, duplicate names, secure headers and bundle safety.
- Older benchmarking, charting, optional browser chat test, and forecast run features remain.

# Changelog

## v0.4.1 — 19 November 2026

- Load `.env` automatically for CLI benchmarks and Streamlit dashboard (python-dotenv, no shell `export`).
- Add `.env.example` and `.gitignore` to prevent publishing local secrets.
- Include a two-model LiteLLM gateway benchmark suite (`gemma4:26b`, `gpt-luna-fast`) and concise `ENV_SETUP.md`.
- Existing environment variables take precedence; live-run consent and safe traffic limits unchanged.


## v0.4.0 — 19 November 2026

- Added three **AI Forest-specific** editable JSON inputs for gateway/chat tests, Home/Media/Audio + Redis Memory MCP discovery, and Kubernetes capacity forecasting.
- Added optional Playwright configuration/script to smoke-test the Cipher web UI with synthetic prompts (memory test off by default).
- Added disabled-case support so provisional API routes and Redis Memory MCP tools are not contacted before verification.
- Added environment-based LLM model override (`model_env`) and optional expected MCP tool name (`mcp_expected_tool`).
- Improved Streamlit UI to import a full suite JSON, preview target cases, display results, and explain concurrency, graphs and license ownership.
- Labeled X/Y axes and metrics in generated static and offline interactive plots; explanations now appear beneath each chart. Added `CHART_GUIDE.md` to reports.
- Added `AI_FOREST_SETUP_GUIDE.md` and `DEPENDENCIES_AND_LICENSES.md`. Did not add an open-source license grant to the author's code.
- Safety defaults remain: localhost mock by default for generic benchmark examples, explicit opt-in for live traffic, strict live rate/concurrency limits, read-only MCP discovery first and no memory-write benchmark by default.

## v0.3.0 — 18 November 2026

- MCP, REST API, agent and LLM gateway HTTP benchmark runner; latency charts and Kubernetes capacity planning/report templates.
