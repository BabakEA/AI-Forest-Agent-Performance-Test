#!/usr/bin/env bash
# AI Forest AFPerf guarded release pipeline — Git Bash / Linux / macOS.
# No network publishing happens unless --publish is explicitly supplied.
set -Eeuo pipefail
IFS=$'\n\t'

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="build"
VERSION=""
RESUME="false"
REPOSITORY=""
PYTHON="${PYTHON:-python}"

usage() {
  cat <<'EOF'
AI Forest AFPerf release — Build, check, publish to PyPI, create GitHub release

Usage:
  bash scripts/release.sh [--version 0.7.0] [--build-only]
  bash scripts/release.sh --version 0.7.0 --publish [--repo OWNER/REPO]
  bash scripts/release.sh --version 0.7.0 --publish --resume [--repo OWNER/REPO]

Default is BUILD ONLY: no git commits/tags, no publication, no credentials.
--publish is an explicit opt-in that commits/pushes a version tag, creates a
DRAFT GitHub release, uploads the wheel+sdist to PyPI and publishes that draft.
--resume is for continuing a previously prepared same-version draft release.

Requirements:
  python -m pip install --upgrade build twine pytest tomli
  git and GitHub CLI (gh), with gh auth login (publish only)
  An approved LICENSE file in the repository (publish only)
  TWINE_PASSWORD (authorized PyPI API token) or interactive secret entry.
  Default repository: BabakEA/AI-Forest-Agent-Performance-Test

The GitHub repository must already exist and contain this source. The script
cannot assert that PyPI project name 'afperf' belongs to you until PyPI accepts
and authenticates the first upload.
EOF
}

while (($#)); do
  case "$1" in
    --build-only) MODE="build" ;;
    --publish) MODE="publish" ;;
    --resume) RESUME="true" ;;
    --version)
      (($# >= 2)) || { echo 'ERROR: --version requires an argument' >&2; exit 2; }
      VERSION="$2"; shift ;;
    --repo)
      (($# >= 2)) || { echo 'ERROR: --repo requires OWNER/REPO' >&2; exit 2; }
      REPOSITORY="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "$MODE" != "publish" && "$RESUME" == "true" ]]; then
  echo 'ERROR: --resume requires --publish' >&2; exit 2
fi

command -v "$PYTHON" >/dev/null || { echo "ERROR: Python not found: $PYTHON" >&2; exit 2; }
"$PYTHON" - <<'PY'
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # Python 3.10 release tool
from pathlib import Path
p=tomllib.loads(Path('pyproject.toml').read_text('utf-8'))
assert p['project']['name']=='afperf', 'The PyPI distribution must be named afperf'
assert any('streamlit' in r.lower() for r in p['project']['dependencies']), 'pip install afperf should include dashboard support'
print('Verified distribution name:',p['project']['name'])
PY

CURRENT_VERSION="$("$PYTHON" - <<'PY'
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # Python 3.10 release tool
from pathlib import Path
print(tomllib.loads(Path('pyproject.toml').read_text('utf-8'))['project']['version'])
PY
)"
VERSION="${VERSION:-$CURRENT_VERSION}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?$ ]] || {
  echo "ERROR: Invalid version '$VERSION'" >&2; exit 2;
}
TAG="v$VERSION"
echo "AFPerf release: distribution=afperf, version=$VERSION, mode=$MODE, tag=$TAG"

# Install these release tools in your isolated packaging environment first.
for mod in pytest build twine; do
  "$PYTHON" -c "import $mod" >/dev/null 2>&1 || {
    echo "ERROR: Missing '$mod'. Run: $PYTHON -m pip install --upgrade build twine pytest" >&2; exit 2;
  }
done

# Public release gates must complete BEFORE mutating the repository or uploading.
if [[ "$MODE" == "publish" ]]; then
  [[ -s "LICENSE" ]] || {
    echo 'STOP: LICENSE is missing. The release requires Apache License 2.0.' >&2
    echo 'AI_FOREST_LICENSE_PROPOSAL_DRAFT.md is NOT an effective LICENSE.' >&2
    exit 2
  }
  if ! grep -q 'Apache License' LICENSE || ! grep -q 'Version 2.0' LICENSE; then
    echo 'STOP: LICENSE does not appear to be the official Apache License 2.0 text.' >&2; exit 2
  fi
  [[ -s 'NOTICE' ]] || { echo 'STOP: NOTICE is missing.' >&2; exit 2; }
  if grep -Eiq 'not effective|proposal only|discussion draft only' LICENSE; then
    echo 'STOP: LICENSE still appears to be a draft. Finalize it before publishing.' >&2; exit 2
  fi
  for binary in git gh curl; do
    command -v "$binary" >/dev/null || { echo "ERROR: '$binary' is required for --publish" >&2; exit 2; }
  done
  git rev-parse --show-toplevel >/dev/null 2>&1 || {
    echo 'ERROR: initialize/clone a Git repository before publishing.' >&2; exit 2;
  }
  [[ "$(cd "$(git rev-parse --show-toplevel)" && pwd)" == "$ROOT" ]] || {
    echo 'ERROR: run release.sh in the root of its own Git repository, not a nested repository.' >&2; exit 2;
  }
  # Reject tracked credentials even if the ignore file is present.
  while IFS= read -r path; do
    case "$path" in
      .env|*/.env|.env.*|*/.env.*) [[ "$path" == '.env.example' ]] || { echo "ERROR: tracked env file: $path" >&2; exit 2; } ;;
      *.pem|*.key|*.p12|*.pfx) echo "ERROR: tracked secret-like file: $path" >&2; exit 2 ;;
    esac
  done < <(git ls-files)
  [[ "$RESUME" == "true" || -z "$(git status --porcelain --untracked-files=normal)" ]] || {
    echo 'ERROR: working tree must be clean for a new public release. Commit your changes first.' >&2; exit 2;
  }
  gh auth status >/dev/null || { echo 'ERROR: GitHub CLI not authenticated. Run gh auth login.' >&2; exit 2; }
  REPOSITORY="${REPOSITORY:-${GH_REPO:-BabakEA/AI-Forest-Agent-Performance-Test}}"
  if [[ -z "$REPOSITORY" ]]; then
    REPOSITORY="$(gh repo view --json nameWithOwner --jq .nameWithOwner)" || {
      echo 'ERROR: no GitHub repository found. Set --repo OWNER/REPO or GH_REPO.' >&2; exit 2;
    }
  fi
  [[ "$REPOSITORY" =~ ^[^/[:space:]]+/[^/[:space:]]+$ ]] || { echo 'ERROR: --repo must be OWNER/REPO' >&2; exit 2; }
  gh repo view "$REPOSITORY" --json nameWithOwner --jq .nameWithOwner >/dev/null || {
    echo "ERROR: GitHub repository not accessible: $REPOSITORY" >&2; exit 2;
  }
  origin="$(git remote get-url origin)" || { echo 'ERROR: Git origin remote not configured.' >&2; exit 2; }
  # Prevent --repo from pointing at one repository while git push origin targets another.
  case "$origin" in
    "https://github.com/$REPOSITORY"|"https://github.com/$REPOSITORY.git"|"git@github.com:$REPOSITORY"|"git@github.com:$REPOSITORY.git") ;;
    *) echo "ERROR: git origin '$origin' does not match release repo '$REPOSITORY'." >&2; exit 2 ;;
  esac
  # Fail closed on connectivity and exact version conflicts. PyPI also validates project ownership during upload.
  status="$(curl --silent --show-error --location --max-time 20 --output /dev/null --write-out '%{http_code}' "https://pypi.org/pypi/afperf/${VERSION}/json")" || {
    echo 'ERROR: cannot verify the target PyPI version (network problem).' >&2; exit 2;
  }
  if [[ "$RESUME" == "false" ]]; then
    [[ "$status" == '404' ]] || { echo "ERROR: PyPI version $VERSION check returned $status (must be 404)." >&2; exit 2; }
  else
    [[ "$status" == '404' || "$status" == '200' ]] || { echo "ERROR: unexpected PyPI status $status" >&2; exit 2; }
  fi
  echo "Authenticated GitHub repo: $REPOSITORY; PyPI version lookup: $status"
fi

# Do not mutate source for a local build with an alternate --version.
if [[ "$MODE" == "build" && "$VERSION" != "$CURRENT_VERSION" ]]; then
  echo "ERROR: local build-only uses current version $CURRENT_VERSION. To change version, run python tools/bump_version.py $VERSION first." >&2
  exit 2
fi

if [[ "$MODE" == "publish" ]]; then
  if [[ "$RESUME" == "true" ]]; then
    [[ "$VERSION" == "$CURRENT_VERSION" ]] || { echo "ERROR: --resume needs current version $CURRENT_VERSION" >&2; exit 2; }
    [[ "$(git rev-parse "$TAG^{commit}" 2>/dev/null)" == "$(git rev-parse HEAD)" ]] || {
      echo "ERROR: --resume requires existing $TAG to point at HEAD." >&2; exit 2;
    }
  elif [[ "$VERSION" != "$CURRENT_VERSION" ]]; then
    "$PYTHON" tools/bump_version.py "$VERSION"
  fi
fi

echo 'Running automated tests...'
"$PYTHON" -m pytest -q

echo 'Building wheel + source distribution...'
rm -rf dist build
"$PYTHON" -m build --wheel --sdist --outdir dist
"$PYTHON" -m twine check dist/*.whl dist/*.tar.gz

# Validate published command entrypoint and required package data without installing or contacting network.
"$PYTHON" - <<'PY'
import pathlib, zipfile
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
p=tomllib.loads(pathlib.Path('pyproject.toml').read_text('utf-8'))
v=p['project']['version']
files=list(pathlib.Path('dist').glob('afperf-*.whl'))
assert len(files)==1, f'Expected one wheel: {files}'
with zipfile.ZipFile(files[0]) as wh:
    names=wh.namelist()
    metadata=[x for x in names if x.endswith('.dist-info/METADATA')]
    assert len(metadata)==1
    meta=wh.read(metadata[0]).decode()
    assert 'Name: afperf' in meta
    assert f'Version: {v}' in meta
    assert any(x.endswith('agent_perf/ui/dashboard.py') for x in names), 'Dashboard must be included'
    assert any('agent_perf/templates/examples/' in x and x.endswith('.json') for x in names), 'Starter configs missing'
    assert any(x.endswith('agent_perf/_version.py') for x in names), 'Version file missing'
    assert 'License-Expression: Apache-2.0' in meta, 'Apache-2.0 metadata missing'
    assert any(x.endswith('/LICENSE') or '/licenses/LICENSE' in x for x in names), 'LICENSE must ship in wheel'
    assert any(x.endswith('/NOTICE') or '/licenses/NOTICE' in x for x in names), 'NOTICE must ship in wheel'
    assert not any('/.env' in x and not x.endswith('.env.example') for x in names), 'Secret env accidentally packaged'
print('Wheel validated:', files[0].name)
PY

"$PYTHON" - <<'PY'
import hashlib,pathlib
out=pathlib.Path('dist'); files=sorted([*out.glob('*.whl'),*out.glob('*.tar.gz')]); assert len(files)==2
(out/'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in files))
for f in files: print(f'Built: {f.name} ({f.stat().st_size} bytes)')
PY

if [[ "$MODE" == "build" ]]; then
  echo 'BUILD-ONLY complete. No GitHub release or PyPI upload occurred.'
  echo 'Artifacts: dist/*.whl dist/*.tar.gz dist/SHA256SUMS.txt'
  exit 0
fi

# A publish operation is intentionally irreversible (PyPI forbids replacing a release).
# First create a DRAFT GitHub release so users do not see a GitHub release before PyPI succeeds.
if [[ "$RESUME" == "false" ]]; then
  git add pyproject.toml agent_perf/_version.py
  # Version-only release commit; all other source changes must have been committed earlier.
  if ! git diff --cached --quiet; then
    git commit -m "release: AFPerf $VERSION"
  fi
  if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    echo "ERROR: Git tag $TAG already exists. Stop and inspect; use --resume only for a partial published release." >&2; exit 2
  fi
  git tag -a "$TAG" -m "AFPerf $VERSION"
  git push origin HEAD
  git push origin "$TAG"
  gh release create "$TAG" dist/*.whl dist/*.tar.gz dist/SHA256SUMS.txt \
    --repo "$REPOSITORY" --verify-tag --draft --title "AFPerf $VERSION" --generate-notes
else
  gh release view "$TAG" --repo "$REPOSITORY" >/dev/null || {
    echo "ERROR: GitHub release draft $TAG not found. Create/repair it manually first." >&2; exit 2;
  }
fi

status="$(curl --silent --show-error --location --max-time 20 --output /dev/null --write-out '%{http_code}' "https://pypi.org/pypi/afperf/${VERSION}/json")" || {
  echo 'ERROR: could not recheck PyPI; GitHub draft remains unpublished.' >&2; exit 2;
}
if [[ "$status" == '404' ]]; then
  if [[ -z "${TWINE_PASSWORD:-}" ]]; then
    [[ -t 0 ]] || { echo 'ERROR: TWINE_PASSWORD missing and no interactive terminal for PyPI token prompt.' >&2; exit 2; }
    echo 'Enter your PyPI project-scoped API token; it will not be echoed or saved to disk.'
    read -r -s -p 'PyPI token: ' TWINE_PASSWORD
    printf '\n'
    export TWINE_PASSWORD
  fi
  export TWINE_USERNAME='__token__'
  "$PYTHON" -m twine upload --non-interactive --repository-url https://upload.pypi.org/legacy/ dist/*.whl dist/*.tar.gz
  unset TWINE_PASSWORD
elif [[ "$status" == '200' && "$RESUME" == 'true' ]]; then
  echo "PyPI afperf $VERSION already exists; skipping re-upload during resume. Verify ownership manually."
else
  echo "ERROR: Unexpected PyPI response $status. Draft release remains." >&2; exit 2
fi

gh release edit "$TAG" --repo "$REPOSITORY" --draft=false
printf '\nSUCCESS: PyPI https://pypi.org/project/afperf/%s/\nGitHub repo: %s\nRelease tag: %s\n' "$VERSION" "$REPOSITORY" "$TAG"
