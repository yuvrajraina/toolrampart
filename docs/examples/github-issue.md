# GitHub Issue Creator

Use this pattern for external API actions.

Source: `examples/github_issue_tool.py`

```python
from toolrampart import rate_limit, redact, scope, side_effects, tool

@tool
@scope("github.issue.create")
@redact(["token"])
@rate_limit("30/hour/user")
@side_effects(external_network=True, writes_data=True, idempotent=False)
def create_github_issue(repo: str, title: str, body: str, token: str | None = None) -> dict:
    ...
```

Use a GitHub token with the narrowest possible repository permissions.

For retries, pass an idempotency key from the caller so ToolRampart can replay the completed result instead of creating duplicate issues.
