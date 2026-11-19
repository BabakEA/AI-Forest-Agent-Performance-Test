# AFPerf v0.6.1 — Three-minute product walkthrough storyboard

**Title:** Test your AI agents, MCP tools and LLM gateways — then forecast Kubernetes capacity.

**0:00–0:20: The problem.** On screen: Agent -> multiple MCP calls -> LLM gateway -> Redis -> HTTP API -> K8s. Voiceover: "A single user request triggers many operations. How do you know if the system can handle the next 10,000 users?"

**0:20–0:45: Installation.** In Windows Git Bash: `python -m pip install -e '.[dashboard,test]'`, `afperf init my-demo`, `cd my-demo`, `afperf start`. Show terminal output and local browser. Hide any `.env` file or token.

**0:45–1:30: Visual workload builder.** Add an MCP discovery case and LLM gateway case using a synthetic, clearly labeled mock server; adjust request count and concurrency from 1c through 8c. Export `benchmark.json`. Explain that `c` denotes concurrent HTTP workers, not CPU cores.

**1:30–2:05: Run and interpret.** Execute `afperf performance benchmark.json`. Open HTML report; highlight p50/p95/p99 latency, successful RPS, failures and first-token latency when streaming. Never present mock measurements as actual model inference.

**2:05–2:35: Forecast.** Edit projected user count in dashboard, export `forecast.json`, then run `afperf forecast forecast.json`. Show planned pods, token-per-minute requirements, Gateway API and HPA examples. Explain that sizing is an assumption-based hypothesis until calibrated against real staging throughput.

**2:35–2:50: Deployment convenience.** Run `afperf docker`. Show generated Dockerfile, `src/`, `docker-compose.yml`, and `start.sh` plus commands `sh docker/start.sh build` and `compose` as commands only. Don't depict real Docker success without running it.

**2:50–3:00: Closing.** "AI Forest Agent Performance Test: design, benchmark, forecast, and package—in one workflow." Show the AI Forest attribution and a notice: *prototype; licensing terms under review*.

**Recording safety:** use synthetic fixture data only; obscure OS usernames, tokens, internal domains and enterprise materials. Obtain any necessary third-party logo/trademark permissions. Do not claim this prototype is enterprise-certified or commercially licensed before release review.
