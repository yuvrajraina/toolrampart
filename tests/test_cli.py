from __future__ import annotations

import pytest
import typer

from toolrampart.cli import _load_arguments


def test_load_arguments_from_json_string() -> None:
    assert _load_arguments('{"amount": 100}', None) == {"amount": 100}


def test_load_arguments_from_file(tmp_path) -> None:
    args_path = tmp_path / "args.json"
    args_path.write_text('{"user_id": "u_1"}', encoding="utf-8")

    assert _load_arguments("{}", args_path) == {"user_id": "u_1"}
    assert _load_arguments(f"@{args_path}", None) == {"user_id": "u_1"}


def test_load_arguments_from_utf8_bom_file(tmp_path) -> None:
    args_path = tmp_path / "args.json"
    args_path.write_text('{"user_id": "u_1"}', encoding="utf-8-sig")

    assert _load_arguments("{}", args_path) == {"user_id": "u_1"}


def test_load_arguments_requires_json_object() -> None:
    with pytest.raises(typer.BadParameter):
        _load_arguments("[1, 2, 3]", None)
