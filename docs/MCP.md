# MCP Support

ToolRampart exposes a stdio MCP server through the official MCP Python SDK.

Install:

```bash
pip install toolrampart[mcp]
```

Run:

```bash
TOOLRAMPART_MCP_ACTOR=mcp-client TOOLRAMPART_MCP_SCOPES=billing.refund toolrampart mcp tools
```

Approval-gated calls return a ToolRampart result with `status = "requires_approval"` and an `approval_id`. After a human approves the request, retry the tool call with `_toolrampart_approval_id` in the MCP tool arguments.

For write tools, include `_toolrampart_idempotency_key` in the MCP arguments to deduplicate retries.

ToolRampart advertises both reserved fields in the MCP input schema so validating MCP clients can pass them safely.

ToolRampart exports MCP annotations from side-effect metadata:

- `readOnlyHint`
- `destructiveHint`
- `idempotentHint`
- `openWorldHint`

The MCP path still executes through ToolRampart's normal validation, policy, approval, rate-limit, timeout, retry, output validation, and audit pipeline.

Local test coverage validates the low-level MCP handler when `toolrampart[mcp]` is installed. The CI optional-extras job installs the local package with all extras and exercises MCP, Postgres, and Redis integration paths.
