from __future__ import annotations

import json
import os
import urllib.request

from toolrampart import rate_limit, redact, scope, side_effects, tool


@tool
@scope("github.issue.create")
@redact(["token"])
@rate_limit("30/hour/user")
@side_effects(external_network=True, writes_data=True, idempotent=False)
def create_github_issue(repo: str, title: str, body: str, token: str | None = None) -> dict:
    github_token = token or os.environ["GITHUB_TOKEN"]
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ToolRampart-example",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))
    return {"number": data["number"], "url": data["html_url"], "title": data["title"]}
