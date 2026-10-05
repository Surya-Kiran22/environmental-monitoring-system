"""Shared helpers for agent nodes: execution trace steps and timeline events."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from ..utils import clean


class Step:
    """Context manager that records one agent execution for the visibility panel."""

    def __init__(self, agent: str, node: str, inputs: dict | None = None):
        self.agent, self.node, self.inputs = agent, node, inputs or {}
        self.tool_calls: list[dict] = []
        self.output: dict = {}
        self.llm_used = False

    def __enter__(self):
        self.t0 = time.perf_counter()
        self.started = datetime.now()
        return self

    def tool(self, name: str, args: dict, result: Any) -> Any:
        self.tool_calls.append({"tool": name, "args": clean(args), "result": clean(result)})
        return result

    def __exit__(self, *exc):
        self.duration_ms = round((time.perf_counter() - self.t0) * 1000, 1)
        return False

    def record(self) -> dict:
        return clean({"agent": self.agent, "node": self.node, "started_at": self.started, "duration_ms": self.duration_ms,
                      "input": self.inputs, "tool_calls": self.tool_calls, "output": self.output, "llm_used": self.llm_used})


def event(name: str, payload: dict) -> dict:
    return clean({"event": name, "timestamp": datetime.now(), "payload": payload})


def fmt(v, nd: int = 1) -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{nd}f}".rstrip("0").rstrip(".") if nd else f"{float(v):.0f}"
    except (TypeError, ValueError):
        return str(v)
