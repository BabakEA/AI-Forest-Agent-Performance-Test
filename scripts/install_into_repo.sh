#!/usr/bin/env bash
# Copy the prepared AFPerf source into an existing verified local Git checkout.
# No git commit, tag, push or PyPI publish is performed by this script.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-}"
if [[ -z "$DEST" ]]; then
  echo 'Usage: bash scripts/install_into_repo.sh /path/to/AI-Forest-Agent-Performance-Test' >&2
  exit 2
fi
command -v git >/dev/null || { echo 'git is required' >&2; exit 2; }
command -v python >/dev/null || { echo 'python is required' >&2; exit 2; }
DEST="$(cd -- "$DEST" && pwd)"
[[ "$DEST" != "$ROOT" ]] || { echo 'Destination is the release source itself; choose your cloned GitHub repo.' >&2; exit 2; }
[[ -d "$DEST/.git" ]] || { echo 'Target must be the root of an existing git clone.' >&2; exit 2; }
ORIGIN="$(git -C "$DEST" remote get-url origin)"
case "$ORIGIN" in
  https://github.com/BabakEA/AI-Forest-Agent-Performance-Test|https://github.com/BabakEA/AI-Forest-Agent-Performance-Test.git|git@github.com:BabakEA/AI-Forest-Agent-Performance-Test|git@github.com:BabakEA/AI-Forest-Agent-Performance-Test.git) ;;
  *) echo "Unexpected destination git origin: $ORIGIN" >&2; exit 2 ;;
esac
if [[ -n "$(git -C "$DEST" status --porcelain --untracked-files=normal)" ]]; then
  echo 'Target Git checkout has local modifications or untracked files. Commit/stash/remove them first.' >&2
  exit 2
fi
python - "$ROOT" "$DEST" <<'PY'
from pathlib import Path
import shutil, sys
source, destination = map(Path, sys.argv[1:3])
skip_dirs={'.git','.venv','__pycache__','.pytest_cache','.mypy_cache','build','dist','results','.ruff_cache'}
skip_suffixes={'.pyc','.pyo','.whl','.tar.gz'}
files=[]
for path in source.rglob('*'):
    if not path.is_file() or any(p in skip_dirs for p in path.relative_to(source).parts): continue
    if path.name in {'.env','TWINE_PASSWORD'} or (path.name.startswith('.env.') and path.name!='.env.example'): continue
    if path.suffix in skip_suffixes or path.name.endswith('.egg-info'): continue
    if any(part.endswith('.egg-info') for part in path.relative_to(source).parts): continue
    relative=path.relative_to(source)
    target=destination/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,target)
    files.append(str(relative))
print(f'Copied {len(files)} AFPerf source files into {destination}')
print('Included Apache-2.0 LICENSE, NOTICE and release tooling.')
print('Review: git status --short ; git diff -- LICENSE')
print('No commits, network pushes, tags or external publication occurred.')
PY
