"""
finanzamt.agents.agent1_text
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Agent 1: Text-based LLM extraction.

Input:  OCR text + rule-based hints dict
Output: dict (json1) or None on failure
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests

from ..utils import clean_json_response
from .config import AgentModelConfig
from .prompts import build_agent1_prompt


def run(
    text:      str,
    hints:     dict,
    cfg:       AgentModelConfig,
    debug_dir: Optional[Path] = None,
) -> Optional[dict]:
    """
    Call the text LLM with OCR text + rule-based hints.
    Saves prompt and full raw response to debug_dir if given.
    Returns parsed dict on success, None on failure.
    """
    prompt = build_agent1_prompt(text, hints)

    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "01_agent1_prompt.txt").write_text(prompt, encoding="utf-8")

    for attempt in range(1, cfg.max_retries + 1):
        try:
            response = requests.post(
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

            if response.status_code != 200:
                continue

            raw = response.json().get("response", "")

            if debug_dir is not None:
                (debug_dir / "01_agent1_raw_response.txt").write_text(raw, encoding="utf-8")

            parsed = json.loads(clean_json_response(raw))

            if debug_dir is not None:
                (debug_dir / "01_agent1_parsed.json").write_text(
                    json.dumps(parsed, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

            return parsed

        except json.JSONDecodeError:
            pass
        except requests.exceptions.Timeout:
            pass
        except requests.exceptions.RequestException:
            time.sleep(1)

    if debug_dir is not None:
        (debug_dir / "01_agent1_raw_response.txt").write_text(
            f"FAILED after {cfg.max_retries} attempts", encoding="utf-8"
        )
    return None