#!/usr/bin/env python3
"""Shared helpers for model-council scripts."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class OpenClawToolError(RuntimeError):
    """Raised when Gateway /tools/invoke fails."""


class OpenClawClient:
    """Minimal OpenClaw Gateway /tools/invoke client."""

    def __init__(
        self,
        gateway_url: str | None = None,
        token: str | None = None,
        session_key: str = "main",
        timeout: float = 30.0,
    ) -> None:
        self.gateway_url = gateway_url or os.getenv("OPENCLAW_GATEWAY_URL") or self._default_gateway_url()
        self.token = token or os.getenv("OPENCLAW_GATEWAY_TOKEN") or self._default_gateway_token()
        self.session_key = session_key
        self.timeout = timeout

        if not self.token:
            raise OpenClawToolError(
                "Gateway token not found. Set OPENCLAW_GATEWAY_TOKEN or configure ~/.openclaw/openclaw.json"
            )

    def invoke_tool(self, tool: str, args: dict[str, Any] | None = None, action: str = "json") -> dict[str, Any]:
        payload = {
            "tool": tool,
            "action": action,
            "args": args or {},
            "sessionKey": self.session_key,
            "dryRun": False,
        }
        req = urllib.request.Request(
            url=f"{self.gateway_url.rstrip('/')}/tools/invoke",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise OpenClawToolError(f"HTTP {exc.code} invoking {tool}: {text}") from exc
        except urllib.error.URLError as exc:
            raise OpenClawToolError(f"Cannot reach Gateway: {exc}") from exc

        parsed = json.loads(body)
        if not parsed.get("ok", False):
            error = parsed.get("error", {})
            raise OpenClawToolError(f"{tool} failed: {error}")

        result = parsed.get("result", {})
        if not isinstance(result, dict):
            raise OpenClawToolError(f"Unexpected {tool} result shape: {type(result)}")
        return result

    @staticmethod
    def _default_gateway_url() -> str:
        cfg = OpenClawClient._load_openclaw_config()
        port = cfg.get("gateway", {}).get("port", 18789)
        return f"http://127.0.0.1:{port}"

    @staticmethod
    def _default_gateway_token() -> str | None:
        cfg = OpenClawClient._load_openclaw_config()
        return cfg.get("gateway", {}).get("auth", {}).get("token")

    @staticmethod
    def _load_openclaw_config() -> dict[str, Any]:
        cfg_path = Path.home() / ".openclaw" / "openclaw.json"
        if not cfg_path.exists():
            return {}
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}


def project_root() -> Path:
    """Resolve skill root from scripts directory."""
    return Path(__file__).resolve().parents[1]


def extract_text_from_message(message: dict[str, Any]) -> str:
    """Convert transcript message content blocks to plain text."""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    chunks: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n\n".join(chunks).strip()
