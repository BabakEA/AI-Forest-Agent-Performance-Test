# AI Forest Toolkit — code ownership, third-party libraries and licenses

This note reflects the *actual package manifest* (`pyproject.toml` and `requirements*.txt`). It is not a legal audit or a claim of ownership of upstream software.

## Our toolkit versus the packages it uses

- **AI Forest toolkit source:** `agent_perf/*.py`, `dashboard.py`, `web_ui_smoke.py`, `examples/*.json`, `tests/` and the authored documentation in this archive. This is the project's own integration/application code.
- **Third-party dependencies:** when you run `pip install -r requirements*.txt`, pip downloads existing maintained packages from their upstream publishers. **Those libraries are not AI Forest inventions** and their licenses continue to govern their code.
- **External frameworks, Skills and MCP servers:** any skills, tool integrations or servers installed separately from this ZIP remain separate packages/projects with their own owners, terms and licenses. This archive does not bundle the full upstream source or transfer ownership.
- **AFPerf original core:** this release candidate is licensed under the Apache License, Version 2.0 (`Apache-2.0`). Read the root `LICENSE` and `NOTICE`. Earlier prototype archives were not necessarily licensed on identical terms; third-party libraries retain their own licenses. Confirm the authority to license all included original source and third-party contributions before publishing.

## Declared upstream dependencies and typical upstream licenses

| Package | Why used | Upstream licensing family* |
|---|---|---|
| `httpx` | Async HTTP requests for API/MCP/LLM tests | BSD-3-Clause |
| `matplotlib` | Static PNG graphs | Matplotlib license (PSF-derived) |
| `PyYAML` | Kubernetes YAML templates | MIT |
| `plotly` | Offline interactive HTML charts | MIT |
| `streamlit` *(optional)* | Local dashboard UI | Apache-2.0 |
| `pytest` *(optional)* | Automated tests | MIT |
| `playwright` *(optional)* | Browser/UI test script | Apache-2.0 |
| `setuptools`/`wheel` | Python package building | Upstream distribution terms vary |

*These are commonly published license identifications, not a legal guarantee for every future version of dependency. Verify the licenses and notices of the **exact resolved versions** in your deployment using `pip show PACKAGE` and upstream `LICENSE`/`NOTICE` documents. Review transitive dependencies too. The package currently specifies minimum versions, not pinned lockfile versions.

## Project privacy and security expectations

The benchmarking tool must not distribute secrets, private user chats, embeddings, or captured production requests. Use environment variables or an approved secrets manager. Never place credentials into committed JSON test presets. All sample payloads are synthetic.
