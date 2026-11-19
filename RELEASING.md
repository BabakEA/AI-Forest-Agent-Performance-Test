# AFPerf — release and publishing guide

**Distribution:** `afperf` (PyPI) · **Python import:** `agent_perf` · **CLI:** `afperf` / `aiforest-perf` · **First intended version:** `0.7.0`.

The release script performs **no external action by default**. A release is only uploaded when an authorized maintainer explicitly uses `--publish` in a Git checkout that already has a GitHub remote.

## 1. Requirements (Windows Git Bash, macOS, Linux)

```bash
python --version                # 3.10 or later
git --version
gh --version                     # GitHub CLI: https://cli.github.com
python -m pip install --upgrade build twine pytest tomli
```

Sign in to GitHub separately: `gh auth login`. Do **not** store a personal access token in the source repository.

AFPerf's repository is `https://github.com/BabakEA/AI-Forest-Agent-Performance-Test`.
Clone that repository first, or use your existing local checkout. Copy the prepared release files into that repository while preserving your existing work. Do not initialize a new repository.

From the extracted release-source folder, you can safely sync the files into a clean clone (without committing or publishing):

```bash
git clone https://github.com/BabakEA/AI-Forest-Agent-Performance-Test.git
bash scripts/install_into_repo.sh ./AI-Forest-Agent-Performance-Test
cd ./AI-Forest-Agent-Performance-Test
git diff -- LICENSE
git status --short
```

The existing GitHub repository currently contains an MIT LICENSE and README. Syncing the release candidate replaces them with Apache-2.0 LICENSE and the full AFPerf README. Git history retains the earlier MIT state; the permissions granted to previously distributed MIT copies continue. Review the changes before committing.

## 2. License and copyright

AFPerf core is licensed under **Apache License 2.0**. If GitHub already contains an MIT `LICENSE` file, commit this release candidate's `LICENSE` and `NOTICE` instead, but keep any attribution required by earlier releases or contributions. Existing MIT grants on previously distributed copies are not revoked; see `LICENSING.md`. The repository must contain the official full text in `LICENSE`, `NOTICE` attribution, and `pyproject.toml` SPDX metadata (`license = "Apache-2.0"`). There is no registration step for this software license. AI Forest brand and marks are not licensed by Apache-2.0. Verify third-party asset/license provenance and copyright ownership before public publication.

## 3. Local release validation (no upload)

```bash
bash scripts/release.sh --version 0.7.0 --build-only
```

Runs unit tests, creates `dist/afperf-0.7.0-py3-none-any.whl` and `dist/afperf-0.7.0.tar.gz`, verifies metadata and bundled dashboard/example configurations, and writes `dist/SHA256SUMS.txt`.

You can also install the built wheel offline if its dependencies are already present:

```bash
python -m pip install dist/afperf-0.7.0-py3-none-any.whl
python -m pip show afperf
afperf --version
```

The local validation step is repeatable and **does not create tags, releases or PyPI versions**.

## 4. Publish both PyPI and GitHub release (explicit operation)

Before the first publish, verify that the distribution name `afperf` can be claimed on PyPI and that you have an API token with upload permissions. Project-scoped tokens are recommended **after** the project exists; first publication may require an account-scoped token or preconfigured Trusted Publishing. The script does not reserve the name or authenticate with PyPI until upload.

Commit all intended source, the Apache-2.0 LICENSE, and changes to the changelog first:

```bash
git status --short
git add .
git commit -m 'Prepare AFPerf v0.7.0 release'  # if there are changes
git push
```

Then:

```bash
bash scripts/release.sh --version 0.7.0 --publish --repo BabakEA/AI-Forest-Agent-Performance-Test
```

The script:

1. Checks for a real LICENSE, clean Git worktree, authenticated GitHub access, source and dependency prerequisites, tracked secrets, and a nonduplicate PyPI version.
2. Synchronizes `pyproject.toml` and `agent_perf/_version.py` when `--version` differs from the currently committed version.
3. Runs tests and builds/checks `.whl` + `.tar.gz` and SHA256 checksums.
4. Commits the version bump if needed; creates/pushes Git tag `v0.7.0` to the configured `origin`.
5. Creates a **draft** GitHub release carrying the wheel, sdist and checksums.
6. Prompts for a PyPI API token without echoing it (or uses existing `TWINE_PASSWORD`); uploads the Python distributions via Twine.
7. Publishes the GitHub release draft only after the PyPI upload succeeds.

PyPI releases cannot be overwritten. If publishing partially fails, inspect GitHub draft and PyPI status before any retry; then use `--publish --resume` for the same version. `--resume` assumes the Git tag points at HEAD and GitHub draft already exists. It is intended for the same maintainer; do not blindly resume a release from an untrusted repository or project.

**Security note:** avoid storing `TWINE_PASSWORD` in `.env` or shell history. The script securely prompts if missing. For longer-term unattended CI publishing, prefer GitHub Actions **Trusted Publishing** with OIDC rather than a long-lived token. This kit intentionally includes CI for testing and builds but **does not enable automatic PyPI publishing**.

## 5. After successful publication

```bash
python -m pip install --upgrade afperf
afperf --version
afperf init example-project
cd example-project
afperf start
```

Check the authenticated release through your PyPI project page and GitHub Releases. If the project name is unavailable or owned by someone else, choose a new distribution name in `pyproject.toml`, revise release script URLs and distribution checks, then rebuild rather than trying to upload to a project you do not own.

## 6. No assumptions about product readiness

This release script does not perform live load tests against customer agents or verify public SaaS security. The Streamlit dashboard is local-first and should not be publicly hosted without authentication and authorization controls. Real Docker image runtime and browser UI acceptance remain part of the release checklist.

## GitHub access and ownership

If GitHub returns 404 through an app connection, authorize the repository for that GitHub App, or release from a local clone using `gh auth login`. A 404 does **not** prove the repository does not exist. PyPI distribution ownership is separately enforced by PyPI.
