"""
finamt.progress
~~~~~~~~~~~~~~~~~~
Thread-local progress emitter.

Call ``emit(msg)`` instead of ``print(msg)`` in processing code.  It:

1. Prints to stdout (same as before).
2. If a callback has been registered for the current thread via
   ``set_callback()``, also calls that callback — used by the SSE streaming
   endpoint to forward progress to the client in real time.

Usage in the API layer::

    import asyncio
    from finamt import progress as _progress

    loop = asyncio.get_running_loop()
    async_q: asyncio.Queue[str | None] = asyncio.Queue()

    def _run():
        _progress.set_callback(
            lambda msg: loop.call_soon_threadsafe(async_q.put_nowait, msg)
        )
        try:
            ...         # call agent / OCR pipeline
        finally:
            _progress.clear_callback()
            loop.call_soon_threadsafe(async_q.put_nowait, None)   # sentinel

    asyncio.get_event_loop().run_in_executor(None, _run)
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

_local = threading.local()


def set_callback(cb: Callable[[str], None]) -> None:
    """Register a progress callback for the current thread."""
    _local.callback = cb


def clear_callback() -> None:
    """Remove any registered callback from the current thread."""
    _local.callback = None


def emit(msg: str, flush: bool = True) -> None:
    """Print *msg* to stdout and forward it to any registered callback."""
    print(msg, flush=flush)
    cb: Optional[Callable[[str], None]] = getattr(_local, "callback", None)
    if cb is not None:
        try:
            cb(msg)
        except Exception:
            pass
