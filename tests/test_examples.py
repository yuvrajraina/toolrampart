from __future__ import annotations

import importlib


def test_example_modules_import():
    modules = [
        "examples.refund_tool",
        "examples.read_only_sql_tool",
        "examples.crm_update_tool",
        "examples.github_issue_tool",
        "examples.isolated_long_job",
        "examples.destructive_admin_tool",
        "examples.mcp_client_usage",
    ]

    for module in modules:
        importlib.import_module(module)
