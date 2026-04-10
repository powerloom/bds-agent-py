from __future__ import annotations

import asyncio

from bds_agent.rules.state import Alert
from bds_agent.sinks import StdoutSink, build_sink, build_sinks, dispatch_all


def test_build_stdout() -> None:
    s = build_sink({"type": "stdout"})
    assert isinstance(s, StdoutSink)


def test_build_multiple() -> None:
    sinks = build_sinks([{"type": "stdout"}, {"type": "stdout"}])
    assert len(sinks) == 2


def test_dispatch_stdout() -> None:
    a = Alert(
        rule="min_usd",
        epoch=1,
        pool_address="0xp",
        message="hello",
    )
    asyncio.run(dispatch_all([StdoutSink()], a))
