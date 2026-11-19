# Secret loading — v0.4.1

The toolkit now automatically loads a local `.env` file before CLI benchmarks and on launch of `dashboard.py`.

## Windows Git Bash (no PowerShell, no export)

```bash
cd /path/to/Agent_Performance_Toolkit
python -m pip install -e ".[dashboard,test,browser]"
cp .env.example .env
notepad.exe .env
python -m streamlit run dashboard.py
```

Change the placeholder in `.env` to your actual LiteLLM token. Keep the key **only** in the local `.env` file and exclude it from Git/backups/shared ZIPs.

### Run both models without re-exporting a token

```bash
python -m agent_perf benchmark \
  --config examples/ai_forest_01_gateway_chat_two_models.json \
  --ack-live --out results/gateway-comparison
```

The two-model JSON has `model: gemma4:26b` and `model: gpt-luna-fast` explicitly, with no `model_env`, so each is benchmarked independently. Set other optional service keys in `.env` only if required.

### How it works

- `token_env: LLM_GATEWAY_TOKEN` tells the suite to read the `LLM_GATEWAY_TOKEN` environment variable loaded from `.env`.
- `model_env: LLM_MODEL` (if present) is an optional model override variable; remove it when comparing multiple explicit model names.
- Existing environment variables override `.env` values (`override=False`).
- By default the toolkit reads `.env` beside `dashboard.py`; use `AI_FOREST_ENV_FILE` if you need a different file.
- `.env.example` contains placeholders only. No real keys are bundled.
- `.bashrc` is an alternative, but not needed. Never put secrets in JSON, screenshots, Git or benchmark output.

### Confirm loading without printing your secret

```bash
python -c 'from agent_perf.env import load_project_env; import os; load_project_env(); print("Gateway token configured:", bool(os.getenv("LLM_GATEWAY_TOKEN")))'
```

If this prints False, verify `.env` location and the variable name. If your key was ever shared, rotate it.
