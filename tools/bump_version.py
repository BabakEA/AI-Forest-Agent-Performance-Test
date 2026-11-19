#!/usr/bin/env python3
"""Update AFPerf packaging and runtime version in one safe, dependency-free step."""
from __future__ import annotations
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
VERSION_FILE = ROOT / "agent_perf" / "_version.py"


def update_version(version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", version):
        raise ValueError("Version must be PEP 440 style: 0.7.1, 0.8.0rc1, etc.")
    data = PYPROJECT.read_text(encoding="utf-8")
    before, count = re.subn(r'(?m)^version = "[^"]+"\s*$', f'version = "{version}"', data, count=1)
    if count != 1:
        raise RuntimeError("Cannot find exactly one [project] version in pyproject.toml")
    PYPROJECT.write_text(before, encoding="utf-8")
    VERSION_FILE.write_text('"""AFPerf version (kept in sync with pyproject.toml)."""\n__version__ = "' + version + '"\n',encoding="utf-8")
    print(f"Updated AFPerf version to {version}: {PYPROJECT.name}, {VERSION_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Synchronize AFPerf package version")
    ap.add_argument("version")
    args = ap.parse_args()
    update_version(args.version)
