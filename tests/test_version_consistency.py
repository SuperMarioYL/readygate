"""Version lockstep: every live surface carries the same version.

Frozen recorded artifacts (docs/demo-results.json pins its source revision,
assets/demo.gif is the v0.1.0 vhs capture) stay at their recorded content
and are allow-listed; CHANGELOG history lines are history.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from readygate import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "0.2.0"


def test_pyproject_version_matches():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == EXPECTED_VERSION


def test_dunder_version_matches():
    assert __version__ == EXPECTED_VERSION


def test_uv_lock_pins_project_version():
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    m = lock.find('name = "readygate"')
    assert m != -1
    project_block = lock[m : m + 200]
    assert f'version = "{EXPECTED_VERSION}"' in project_block


def test_site_json_content_version_matches():
    site = json.loads((REPO_ROOT / "web" / "site.json").read_text(encoding="utf-8"))
    assert site["meta"]["content_version"] == EXPECTED_VERSION


def test_changelog_documents_both_releases():
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.1.0] - 2026-08-21" in text
    assert f"## [{EXPECTED_VERSION}] - 2026-09-13" in text


@pytest.mark.skipif(shutil.which("readygate") is None, reason="readygate console script not installed")
def test_cli_version_output_matches():
    proc = subprocess.run(["readygate", "--version"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert EXPECTED_VERSION in proc.stdout


def test_no_stray_old_version_references_in_live_sources():
    # package sources and the two config surfaces must carry no stale version
    offenders = []
    for path in sorted((REPO_ROOT / "readygate").rglob("*.py")):
        if "0.1.0" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    for name in ("pyproject.toml", "web/site.json"):
        if "0.1.0" in (REPO_ROOT / name).read_text(encoding="utf-8"):
            offenders.append(name)
    assert offenders == []
