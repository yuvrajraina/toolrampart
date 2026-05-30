from __future__ import annotations

import sys

from toolrampart.core import default_rampart
from toolrampart.discovery import load_target


def test_load_target_imports_module_from_current_working_directory(tmp_path, monkeypatch) -> None:
    (tmp_path / "tools.py").write_text(
        "from toolrampart import tool\n\n"
        "@tool\n"
        "def smoke_ping() -> dict:\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "path",
        [entry for entry in sys.path if entry not in {"", str(tmp_path)}],
    )
    default_rampart._tools.clear()  # noqa: SLF001

    try:
        shield = load_target("tools")
        assert shield.get_tool("smoke_ping").name == "smoke_ping"
    finally:
        default_rampart._tools.clear()  # noqa: SLF001
