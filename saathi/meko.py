"""Thin async client for the Meko MCP server, plus an in-memory fake for offline tests.

Meko speaks MCP over streamable HTTP at https://mcp.mekodata.ai/mcp.
Auth: ``Authorization: Bearer <MEKO_API_KEY>``; Meko also requires a ``User-Agent`` header.
"""
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

MEKO_URL = "https://mcp.mekodata.ai/mcp"
USER_AGENT = "yojana-saathi/0.1 (+https://github.com/shaon5775/contextcon-meko)"


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {"text": value}
    return value


def _parse_tool_result(result: Any) -> Any:
    """Turn an MCP CallToolResult into plain Python data.

    Live Meko (checked 9 Nov 2026) wraps most replies as {"result": "<JSON text>"}; a few (track_token_usage)
    return a plain dict. Both are unwrapped here."""
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if structured:
        # FastMCP wraps non-dict returns as {"result": ...}
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return _maybe_json(structured["result"])
        return structured
    texts = [c.text for c in (getattr(result, "content", None) or []) if getattr(c, "text", None)]
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except (json.JSONDecodeError, TypeError):
        return {"text": joined}


class MekoClient:
    """Async context manager wrapping a single MCP session to Meko."""

    def __init__(self, api_key: str, datapack_id: str, url: str = MEKO_URL):
        if not api_key:
            raise ValueError("MEKO_API_KEY is missing. Put it in your .env file (never in code).")
        self.api_key = api_key
        self.datapack_id = datapack_id
        self.url = url
        self._stack: AsyncExitStack | None = None
        self._session = None
        self.timings: dict[str, list[float]] = {}   # seconds per Meko tool call, for the evaluation

    async def __aenter__(self) -> "MekoClient":
        from mcp import ClientSession  # imported lazily so tests run without network

        headers = {"Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT}
        self._stack = AsyncExitStack()
        try:  # mcp >= 2.x
            from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

            http = await self._stack.enter_async_context(create_mcp_http_client(headers=headers))
            streams = await self._stack.enter_async_context(streamable_http_client(self.url, http_client=http))
        except ImportError:  # mcp 1.x
            from mcp.client.streamable_http import streamablehttp_client

            streams = await self._stack.enter_async_context(streamablehttp_client(self.url, headers=headers))
        read, write = streams[0], streams[1]
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._stack:
            await self._stack.aclose()

    async def call(self, tool: str, **args: Any) -> Any:
        args = {k: v for k, v in args.items() if v is not None}
        args.setdefault("datapack_id", self.datapack_id)
        t0 = time.perf_counter()
        result = await self._session.call_tool(tool, args)
        self.timings.setdefault(tool, []).append(time.perf_counter() - t0)
        if getattr(result, "isError", False) or getattr(result, "is_error", False):
            raise RuntimeError(f"Meko tool {tool} failed: {_parse_tool_result(result)}")
        data = _parse_tool_result(result)
        # Meko reports some failures as a normal reply: {"error": "...", "detail": "..."}
        if isinstance(data, dict) and data.get("error") and not data.get("results") and not data.get("id"):
            raise RuntimeError(f"Meko tool {tool} failed: {data}")
        return data

    # ---- convenience wrappers -------------------------------------------------
    async def conversation_create(self, agent_id: str, title: str) -> str:
        res = await self.call("conversation_create", agent_id=agent_id, title=title)
        return res["id"]

    async def add_turn(self, conversation_id: str, agent_id: str, user: str, assistant: str,
                       reasoning: str | None = None, plan: list[str] | None = None,
                       metadata: dict | None = None) -> Any:
        return await self.call("conversation_add_message", conversation_id=conversation_id, agent_id=agent_id,
                               input=user, output=assistant, reasoning=reasoning, plan=plan,
                               metadata=json.dumps(metadata) if metadata else None)

    async def context_search(self, query: str, conversation_id: str, agent_id: str, limit: int = 5) -> dict:
        return await self.call("context_search", query=query, conversation_id=conversation_id,
                               agent_id=agent_id, limit=limit)

    async def kb_search(self, query: str, conversation_id: str, agent_id: str, limit: int = 4) -> Any:
        return await self.call("knowledgebase_search", query=query, conversation_id=conversation_id,
                               agent_id=agent_id, limit=limit)

    async def memory_add(self, text: str, conversation_id: str, agent_id: str, metadata: dict) -> Any:
        return await self.call("memory_add", text=text, conversation_id=conversation_id, agent_id=agent_id,
                               metadata=json.dumps(metadata))

    async def memory_promote(self, memory_ids: list[str], conversation_id: str, agent_id: str) -> Any:
        return await self.call("memory_promote", memory_ids=memory_ids, conversation_id=conversation_id,
                               agent_id=agent_id)

    async def track_tokens(self, conversation_id: str, name: str, model: str, input_tokens: int,
                           output_tokens: int) -> Any:
        return await self.call("track_token_usage", conversation_id=conversation_id, name=name, model=model,
                               input_tokens=input_tokens, output_tokens=output_tokens,
                               total_tokens=input_tokens + output_tokens)

    async def artifact_put(self, filename: str, content: bytes, content_type: str, conversation_id: str,
                           agent_id: str) -> Any:
        return await self.call("artifact_put", filename=filename, content_type=content_type,
                               content_base64=base64.b64encode(content).decode(),
                               conversation_id=conversation_id, agent_id=agent_id)


# ------------------------------------------------------------------------------
# Offline fake: same interface, stores everything in memory. Used by tests and
# by `--offline` runs so the pipeline can be checked without network access.
# ------------------------------------------------------------------------------
def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[\w\-]+", text.lower()) if len(t) > 2}


@dataclass
class FakeMeko:
    datapack_id: str = "offline"
    knowledge: dict[str, str] = field(default_factory=dict)
    memories: list[dict] = field(default_factory=list)
    promoted: list[dict] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    token_log: list[dict] = field(default_factory=list)
    turns: list[dict] = field(default_factory=list)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def _score(self, a: str, b: str) -> float:
        ta, tb = _tokens(a), _tokens(b)
        return len(ta & tb) / max(1, min(len(ta), len(tb)))

    async def conversation_create(self, agent_id, title):
        self.calls.append("conversation_create")
        return uuid.uuid4().hex

    async def add_turn(self, conversation_id, agent_id, user, assistant, reasoning=None, plan=None, metadata=None):
        self.calls.append("conversation_add_message")
        self.turns.append({"agent": agent_id, "user": user, "assistant": assistant, "metadata": metadata})

    async def context_search(self, query, conversation_id, agent_id, limit=5):
        self.calls.append("context_search")
        mem = sorted(({**m, "score": self._score(query, m["memory"] + " " + json.dumps(m["metadata"]))}
                      for m in self.memories), key=lambda m: -m["score"])[:limit]
        kb = await self.kb_search(query, conversation_id, agent_id, limit, _count=False)
        return {"results": {"memory": mem, "knowledge_base": kb, "conversation": {"hits": []}}}

    async def kb_search(self, query, conversation_id, agent_id, limit=4, _count=True):
        if _count:
            self.calls.append("knowledgebase_search")
        chunks = []
        for name, text in self.knowledge.items():
            for para in text.split("\n## "):
                chunks.append({"document": name, "text": para[:1200], "score": self._score(query, para)})
        return sorted(chunks, key=lambda c: -c["score"])[:limit]

    async def memory_add(self, text, conversation_id, agent_id, metadata):
        self.calls.append("memory_add")
        mid = uuid.uuid4().hex
        self.memories.append({"id": mid, "memory": text, "metadata": metadata, "agent_id": agent_id})
        return {"results": [{"id": mid, "memory": text, "event": "ADD"}]}

    async def memory_promote(self, memory_ids, conversation_id, agent_id):
        # Same as live Meko (checked 10 Nov 2026): promoting MOVES the memory out of the searchable store.
        self.calls.append("memory_promote")
        moved = [m for m in self.memories if m["id"] in memory_ids]
        self.memories = [m for m in self.memories if m["id"] not in memory_ids]
        self.promoted.extend(moved)
        return {"promoted": memory_ids}

    async def track_tokens(self, conversation_id, name, model, input_tokens, output_tokens):
        self.calls.append("track_token_usage")
        self.token_log.append({"name": name, "in": input_tokens, "out": output_tokens})

    async def artifact_put(self, filename, content, content_type, conversation_id, agent_id):
        self.calls.append("artifact_put")
        return {"filename": filename, "size": len(content)}
