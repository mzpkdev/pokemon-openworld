"""Deterministic, test-only interruption points for the content port pipeline."""

from __future__ import annotations

import os
import signal
from pathlib import Path


FAULT_ENV = "CONTENT_PORT_FAULT_AT"
FAULT_ACTION_ENV = "CONTENT_PORT_FAULT_ACTION"
FAULT_LOG_ENV = "CONTENT_PORT_FAULT_LOG"


def checkpoint(name: str) -> None:
    """Record *name* and inject the explicitly requested test fault, if any.

    Fault injection is inert unless ``CONTENT_PORT_FAULT_AT`` names this exact
    checkpoint.  Tests use SIGTERM to exercise the same recovery path as an
    externally interrupted process; ``raise`` is useful for in-process tests.
    """

    log = os.environ.get(FAULT_LOG_ENV)
    if log:
        path = Path(log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"{name}\n")
            stream.flush()
            os.fsync(stream.fileno())

    if os.environ.get(FAULT_ENV) != name:
        return
    action = os.environ.get(FAULT_ACTION_ENV, "sigterm")
    if action == "sigterm":
        os.kill(os.getpid(), signal.SIGTERM)
    if action == "raise":
        raise InjectedFault(name)
    raise RuntimeError(f"unknown {FAULT_ACTION_ENV} value: {action}")


class InjectedFault(RuntimeError):
    """Raised only when a test explicitly requests an in-process fault."""
