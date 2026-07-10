"""Async concurrency helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import anyio.to_thread
from anyio import CapacityLimiter

_T = TypeVar("_T")


async def run_sync(
    func: Callable[..., _T],
    *args: object,
    abandon_on_cancel: bool = False,
    limiter: CapacityLimiter | None = None,
) -> _T:
    """Run a blocking callable in a worker thread.

    Thin typed wrapper over ``anyio.to_thread.run_sync`` (forwarding its
    ``abandon_on_cancel`` / ``limiter`` keyword args). It exists to work around
    a pyright false-positive (anyio >= 4.13 on Python 3.14) where
    ``anyio.to_thread`` resolves to ``type[BrokenWorkerInterpreter]`` and
    ``.run_sync`` is reported as an unknown attribute. Centralising the call
    confines the single necessary ``type: ignore`` to one line instead of
    scattering it across ~65 call sites.
    """
    return await anyio.to_thread.run_sync(  # type: ignore[attr-defined]
        func, *args, abandon_on_cancel=abandon_on_cancel, limiter=limiter
    )
