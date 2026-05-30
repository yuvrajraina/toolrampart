from __future__ import annotations

import asyncio
import inspect
import multiprocessing
from multiprocessing.connection import Connection
from typing import Any, Callable

from .exceptions import SubprocessExecutionError, SubprocessTimeoutError


def run_in_subprocess(
    func: Callable[..., Any],
    arguments: dict[str, Any],
    *,
    timeout_seconds: float | None,
) -> Any:
    """Run an importable tool function in a child process.

    The function and its return value must be pickleable. This is deliberately
    opt-in because closures, local functions, open sockets, and database clients
    do not cross a process boundary safely.
    """

    context = multiprocessing.get_context("spawn")
    parent_conn, child_conn = context.Pipe(duplex=False)
    process = context.Process(
        target=_subprocess_worker,
        args=(func, arguments, child_conn),
    )
    process.start()
    child_conn.close()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(2)
        if process.is_alive():  # pragma: no cover - platform dependent
            process.kill()
            process.join(2)
        parent_conn.close()
        raise SubprocessTimeoutError(f"tool subprocess timed out after {timeout_seconds} seconds")

    if not parent_conn.poll():
        parent_conn.close()
        if process.exitcode == 0:
            raise SubprocessExecutionError("tool subprocess exited without a result")
        raise SubprocessExecutionError(f"tool subprocess exited with code {process.exitcode}")

    status, payload = parent_conn.recv()
    parent_conn.close()
    if status == "success":
        return payload
    error_type, message = payload
    raise SubprocessExecutionError(f"{error_type}: {message}")


def _subprocess_worker(
    func: Callable[..., Any],
    arguments: dict[str, Any],
    conn: Connection,
) -> None:
    try:
        result = func(**arguments)
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        conn.send(("success", result))
    except Exception as exc:
        try:
            conn.send(("error", (type(exc).__name__, str(exc))))
        except Exception:
            pass
    finally:
        conn.close()
