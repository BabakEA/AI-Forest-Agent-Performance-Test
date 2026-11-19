# Execute from inside the extracted toolkit folder.
python -m pip install -r requirements-test.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python -m agent_perf benchmark --config examples/benchmark_suite.json --out results/my-test
python -m agent_perf forecast --config examples/capacity_template.json --out results/my-forecast
Write-Host 'Open results/my-test/dashboard.html and results/my-forecast/CAPACITY_REPORT.md'
