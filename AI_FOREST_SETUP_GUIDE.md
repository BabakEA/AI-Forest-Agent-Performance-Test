# AI Forest: configure LLM Gateway, Cipher, Redis Memory MCP, Home/Media/Audio MCP

**Version 0.4 — 19 Nov 2026**  
**Status:** example configuration and locally tested mock runner. **No AI Forest live endpoint has been contacted or validated.**

## Which JSON files do I edit?

There are **three primary AI Forest JSON profiles**:

| Input file | Run command | Targets |
|---|---|---|
| `examples/ai_forest_01_gateway_chat.json` | `benchmark` | LLM Gateway `4004`, Cipher health API `9102`, Cipher web UI `9101`, optional (disabled) `/agent` |
| `examples/ai_forest_02_memory_home_media_audio_mcps.json` | `benchmark` | Home MCP `9135`, Media MCP `9136`, Audio MCP `9137` discovery, optional Redis Memory MCP discovery/read (disabled until verified) |
| `examples/ai_forest_03_capacity_forecast.json` | `forecast` | Planning-only API, MCP, agent, gateway, Redis memory MCP and media/audio per-pod capacity estimates |

Only **one JSON is passed to any given CLI invocation**. `benchmark_suite.json`, `live_read_only_template.json`, and `capacity_template.json` are the original generic examples, not prerequisites.

The **optional fourth** `examples/ai_forest_web_ui_optional.json` is for Playwright **browser UI testing**, which is a different test driver from HTTP benchmarking.

## 0. Install and test locally

```powershell
cd Agent_Performance_Toolkit
python -m pip install -r requirements-test.txt
python -m pytest -q
python -m pip install -r requirements-dashboard.txt
python -m streamlit run dashboard.py
```

For the GUI open **Load JSON suite**, select the AI Forest JSON profile, review the enabled cases and rate cap, and explicitly approve live requests before clicking Run. For individual experiments choose **Single endpoint form** and change the endpoint, auth token, request payload and expected fields.

## 1. Gateway + Cipher chat/API smoke tests

**Check the real gateway model name and authorization first.** We cannot infer the LiteLLM routing alias from the model hosted in Ollama or vLLM. Do not use a plaintext token in the file.

```powershell
# Use the actual LiteLLM-visible model route name, not an assumed Ollama tag.
$env:LLM_MODEL = 'REPLACE_WITH_DEPLOYED_MODEL'
$env:LLM_GATEWAY_TOKEN = 'REPLACE_WITH_TOKEN_IF_REQUIRED'
$env:CIPHER_API_TOKEN = 'REPLACE_IF_REQUIRED'

python -m agent_perf benchmark `
  --config examples/ai_forest_01_gateway_chat.json `
  --ack-live --out results/ai-forest-gateway-smoke
```

- `4004/v1/chat/completions` tests a small, synthetic prompt in **non-streaming** and **streaming** modes. Streaming captures time to first content token (TTFT) when the provider returns SSE tokens. Usage token counts are shown only if the gateway returns them.
- `9102/api/status` is a **candidate path** from the historic Cipher setup, not confirmed in this session. If the actual health endpoint differs, edit `url` accordingly.
- `9101/` checks that the web UI returns HTTP 200, **not** whether its chat works. Use the optional browser smoke test for chat.
- `9102/agent` is a suggested **disabled** candidate; confirm the deployed route and payload contract before enabling it.
- If you want more than a single request per target, set `test_type` to `load` and `requests_per_case` to e.g. `20` — only after a smoke test succeeds. In `smoke` mode the current runner does **one request per enabled case**, regardless of `requests_per_case`.

### Model/connection verification (read-only)

```powershell
# Confirm listening ports without generating traffic:
Test-NetConnection 127.0.0.1 -Port 4004
Test-NetConnection 127.0.0.1 -Port 9102
Test-NetConnection 127.0.0.1 -Port 9101

# If your gateway supports this route and authentication:
# Invoke-RestMethod http://127.0.0.1:4004/v1/models -Headers @{ Authorization = "Bearer $env:LLM_GATEWAY_TOKEN" }
```

## 2. Home, media, audio MCP + Redis Memory MCP

```powershell
$env:AI_FOREST_MCP_TOKEN = 'REPLACE_IF_REQUIRED'
$env:REDIS_MEMORY_MCP_TOKEN = 'REPLACE_IF_REQUIRED'

python -m agent_perf benchmark `
  --config examples/ai_forest_02_memory_home_media_audio_mcps.json `
  --ack-live --out results/ai-forest-mcp-discovery
```

The initial enabled cases call **`tools/list` only** on three candidate Streamable HTTP URLs:
- `http://127.0.0.1:9135/mcp` — home
- `http://127.0.0.1:9136/mcp` — media
- `http://127.0.0.1:9137/mcp` — audio

**Do not assume `/mcp` is the actual route!** Check server logs, configuration, and your MCP client settings. Some older servers expose SSE/stdio instead. The runner supports **Streamable HTTP**, not legacy `/sse` dual-endpoint transport or stdio in this version. For old Streamable HTTP choose `2025-11-25`; for a modern 2026-07-28 server choose the newer protocol version. A protocol mismatch can fail initialization even if the port is open.

**Redis nuance:** the Redis database at port `7001` speaks Redis protocol, **not HTTP**. The Redis Memory **MCP adapter** must have its own independently identified HTTP URL/port. Both memory cases are disabled with placeholder URLs until you find it. Test in this order:
1. Find and verify the Memory MCP HTTP URL. Replace `REPLACE_REDIS_MCP_PORT` and set `enabled: true` only on the **discovery** case.
2. Run `tools/list`; inspect server-side tools or use an approved MCP inspector. Find a **read-only** retrieval tool name and its exact JSON schema.
3. On an isolated synthetic test key, update the disabled memory-read case to the approved real tool name and arguments; only then enable it. Avoid memory creation/deletion in performance suites.
4. If you need to prove persistence across chats, create a **separate, explicit integration test**: seed synthetic data in a test namespace, start a fresh chat, verify retrieval, and correlate with Redis/MCP traces. Never use real personal chats as load-test data.

### Interpreting result columns

- `c=1, c=2, c=4`: number of concurrent workers, *not* CPU cores or Kubernetes pods.
- **p20, p50, p95, p99 (ms)**: percentage of successful calls completed at or before that duration; failures counted separately. Reliable tail percentiles require much larger samples than a smoke test.
- **success_rps:** completed good HTTP calls/second. Gateway throughput does not equal LLM inference tokens/sec.
- **first_token_p50_ms:** streaming time to first content-bearing token, not raw TCP first byte.
- **observed_input_tokens/output_tokens:** reported upstream usage (may be zero if absent); not inferred from input text.

## 3. Capacity / TPS / Kubernetes forecast

```powershell
python -m agent_perf forecast `
  --config examples/ai_forest_03_capacity_forecast.json `
  --out results/ai-forest-capacity
```

The default v0.4 profile uses a **1,000 registered user, small pilot** scenario, with seven services and *unverified* throughput-per-pod assumptions. Edit active-user fraction, workflow rate, request fan-out, per-pod RPS, CPU/memory requests, node allocatable and per-model token usage as required. The returned HPA and Gateway API YAML **is not apply-ready**. Its controller, images, path routing, endpoints, secure secrets, TLS, anti-affinity and cloud resources require staging verification. Non-default service names such as `redis-memory-mcp`, `audio-mcp` and `media-mcp` have generated Services/Deployments but **do not automatically receive Gateway API HTTPRoutes**; explicitly design routing for their desired exposure rather than publishing private tools inadvertently.

## 4. Browser/web-chat end-to-end tests

The performance dashboard itself tests gateway or MCP endpoints via the single-target form, or via the JSON suite. This measures **HTTP services**, not actual browser rendering. To test an end user browsing Cipher:

```powershell
python -m pip install -r requirements-browser.txt
python -m playwright install chromium

# Edit examples/ai_forest_web_ui_optional.json with selectors from YOUR Cipher UI first.
python web_ui_smoke.py --config examples/ai_forest_web_ui_optional.json --check-config
python web_ui_smoke.py --config examples/ai_forest_web_ui_optional.json --ack-live
```

The browser smoke sends one synthetic prompt and verifies the text displayed in the assistant-response element. It records browser-visible response latency, which includes frontend, agent orchestration, gateway, and any memory retrieval. It does **not** attribute that latency to the underlying services — use distributed traces to allocate per-service time.

Optional `memory_test: true` checks a **synthetic nonce** after clicking a configured new-chat control. A success means the UI remembered that nonce in a new chat. It does **not** prove Redis specifically provided the memory or that data is durable across device restart. Verify with an authorized read-only Redis memory MCP call or backend traces. Never enable it with real customer content.

## 5. Licenses, skills, package ownership

- AI Forest's Python scripts and test definitions in this ZIP are **our project code**.
- `httpx`, `matplotlib`, `PyYAML`, `plotly`, `streamlit`, `pytest` and `playwright` are **external dependencies**, downloaded/installed using pip and governed by their own licenses. They are **not** the AI Forest project's copyrighted packages.
- The original toolkit did not grant a top-level open-source license. This update deliberately does not decide on a license for AI Forest code without your direction.
- Skills installed in your IDE/agent environment may be first-party or third-party. The toolkit ZIP does not contain a general skills registry or the installed skill source; check the source repository/publisher and license of each skill independently.
- See `DEPENDENCIES_AND_LICENSES.md` for a package-by-package overview.

## Troubleshooting

| Symptom | Likely reason | Safe first check |
|---|---|---|
| 401/403 | Token/permission problem | Check auth env variable, scopes and intended audience; don't print tokens |
| 404 | Candidate path wrong | Check server routes and MCP transport |
| Legacy MCP initialization error | Protocol/session mismatch or SSE-only server | Inspect MCP SDK/version, path and server log |
| LiteLLM `model_not_found` | Model alias in `LLM_MODEL` wrong | List routes through authorized `/v1/models` |
| Redis connection refused | Memory MCP adapter absent/incorrect port | Do not use Redis native 7001 as MCP HTTP URL |
| LLM token count zero | Provider didn't return usage metadata | Enable usage reporting where supported, don't infer token counts |
| UI test selector not found | CSS selector doesn't match your actual frontend | Use browser devtools, don't guess CSS |
| 1c, 2c, 4c | Concurrent workers | This is not CPU or thread count in K8s |
