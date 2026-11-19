# AFPerf v0.6.1 — CLI rename

**Product:** AI Forest Agent Performance Test (AFPerf)
**Distribution:** `agent-performance-test` (unchanged)
**Preferred executable:** `afperf`
**Long executable:** `aiforest-perf`
**Compatibility executable:** `agent-performance-test`
**Removed executable:** `apt` (conflicts with Linux package manager)

Install locally:

```bash
python -m pip install -U -e '.[dashboard,test]'
afperf --version
afperf init my-project
cd my-project
afperf start
```

Existing benchmark.json, forecast.json and .env files require no change. A previous v0.6.0 `apt` launcher may linger in some Python environments; do not use it. The Docker generator now uses `afperf` internally, too. Docker runtime has not been verified in this environment.
