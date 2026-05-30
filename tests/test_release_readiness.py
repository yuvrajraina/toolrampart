from __future__ import annotations

import tomllib
from pathlib import Path

import toolrampart
from toolrampart.app import create_app


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_version_matches_project_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["name"] == "toolrampart"
    assert toolrampart.__version__ == project["project"]["version"]
    assert create_app().version == toolrampart.__version__


def test_alpha_release_docs_are_present_and_linked() -> None:
    required_docs = [
        "docs/RELEASE.md",
        "docs/THREAT_MODEL.md",
        "docs/PRODUCTION_CHECKLIST.md",
        "docs/SECURITY.md",
        "llms.txt",
        "AGENTS.md",
    ]
    for relative_path in required_docs:
        assert (ROOT / relative_path).is_file()

    nav = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "Release Process: RELEASE.md" in nav
    assert "Threat Model: THREAT_MODEL.md" in nav
    assert "Production Checklist: PRODUCTION_CHECKLIST.md" in nav

    llm_index = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "docs/RELEASE.md" in llm_index
    assert "docs/THREAT_MODEL.md" in llm_index
    assert "docs/PRODUCTION_CHECKLIST.md" in llm_index
