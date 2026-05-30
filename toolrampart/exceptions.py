class ToolRampartError(Exception):
    """Base exception for ToolRampart."""


class ToolNotFoundError(ToolRampartError):
    """Raised when a tool name is not registered."""


class ToolRegistrationError(ToolRampartError):
    """Raised when a function cannot be registered as a tool."""


class SubprocessExecutionError(ToolRampartError):
    """Raised when isolated subprocess execution fails."""


class SubprocessTimeoutError(TimeoutError, SubprocessExecutionError):
    """Raised when an isolated subprocess exceeds its timeout."""
