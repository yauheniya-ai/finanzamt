"""
finanzamt.agents.llm_caller
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Generic Ollama LLM caller used by all 4 extraction agents.
Handles retries, debug output, and JSON parsing with fallback.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

import requests

from ..utils import clean_json_response
from .config import AgentModelConfig


def _regex_fallback(raw: str, expected_keys: list[str]) -> dict:
    """
    Last-resort per-key regex extraction when json.loads fails entirely.
    Handles:  "key": "value"  |  "key": 123.4  |  "key": null  |  "key": true/false
    """
    result: dict = {}
    for key in expected_keys:
        pattern = rf'"{re.escape(key)}"\s*:\s*("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|null|true|false|\[.*?\])'
        m = re.search(pattern, raw, re.DOTALL)
        if m:
            try:
                result[key] = json.loads(m.group(1))
            except Exception:
                result[key] = m.group(1).strip('"')
    return result


def call_llm(
    prompt:        str,
    cfg:           AgentModelConfig,
    agent_name:    str,
    expected_keys: list[str],
    debug_dir:     Optional[Path] = None,
) -> Optional[dict]:
    """
    Send prompt to Ollama, parse JSON response, return dict or None.

    Saves to debug_dir:
      {agent_name}_prompt.txt
      {agent_name}_raw.txt
      {agent_name}_parsed.json
    """
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"{agent_name}_prompt.txt").write_text(prompt, encoding="utf-8")

    raw = ""
    for attempt in range(1, cfg.max_retries + 1):
        try:
            resp = requests.post(
                f"{cfg.base_url}/api/generate",
                json={
                    "model":  cfg.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": cfg.temperature,
                        "top_p":       cfg.top_p,
                        "num_ctx":     cfg.num_ctx,
                    },
                },
                timeout=cfg.timeout,
            )
            if resp.status_code != 200:
                continue
            raw = resp.json().get("response", "")
            break
        except requests.exceptions.Timeout:
            pass
        except requests.exceptions.RequestException:
            if attempt < cfg.max_retries:
                time.sleep(1)

    if debug_dir is not None:
        (debug_dir / f"{agent_name}_raw.txt").write_text(
            raw or f"FAILED after {cfg.max_retries} attempts", encoding="utf-8"
        )

    if not raw:
        return None

    # ── Parse ──────────────────────────────────────────────────────────────
    parsed: Optional[dict] = None

    # 1. Standard path via clean_json_response
    try:
        parsed = json.loads(clean_json_response(raw))
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Regex fallback — extract each key individually
    if not parsed:
        parsed = _regex_fallback(raw, expected_keys)

    if not parsed:
        if debug_dir is not None:
            (debug_dir / f"{agent_name}_parsed.json").write_text(
                '{"_error": "parse_failed"}', encoding="utf-8"
            )
        return None

    if debug_dir is not None:
        (debug_dir / f"{agent_name}_parsed.json").write_text(
            json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    return parsed