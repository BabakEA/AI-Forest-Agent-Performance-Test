"""Regression checks that distribution and CLI versions stay aligned."""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # Python 3.10; declared in the test extra

from agent_perf import __version__

ROOT=Path(__file__).resolve().parents[1]

def test_pypi_distribution_name_and_version():
    p=tomllib.loads((ROOT/'pyproject.toml').read_text('utf-8'))['project']
    assert p['name']=='afperf'
    assert p['version']==__version__
    assert any('streamlit' in x for x in p['dependencies'])

def test_cli_module_version():
    r=subprocess.run([sys.executable,'-m','agent_perf.afperf_cli','--version'],cwd=ROOT,capture_output=True,text=True)
    assert r.returncode==0
    assert __version__ in r.stdout

def test_release_script_has_no_implicit_upload():
    script=(ROOT/'scripts/release.sh').read_text('utf-8')
    assert 'MODE="build"' in script
    assert 'MODE="publish"' in script
    assert '[[ -s "LICENSE" ]]' in script
    assert 'gh release create' in script
    assert 'twine upload' in script


def test_apache_20_license_distribution():
    p=tomllib.loads((ROOT/'pyproject.toml').read_text('utf-8'))['project']
    assert p['license']=='Apache-2.0'
    assert set(p['license-files'])=={'LICENSE','NOTICE'}
    text=(ROOT/'LICENSE').read_text('utf-8')
    assert 'Apache License' in text and 'Version 2.0' in text
    notice=(ROOT/'NOTICE').read_text('utf-8')
    assert 'AI Forest Inc.' in notice
    script=(ROOT/'scripts/release.sh').read_text('utf-8')
    assert 'BabakEA/AI-Forest-Agent-Performance-Test' in script
