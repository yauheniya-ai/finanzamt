"""
finanzamt.agents.agent3_validator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Agent 3: Validator.

Input:  json1 (Agent 1) + json2 (Agent 2) — either may be None
Output: dict (json3) or best-available fallback
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests

from ..utils import clean_json_response
from .config import AgentModelConfig
from .prompts import build_agent3_prompt


def run(
    json1:     Optional[dict],
    json2:     Optional[dict],
    cfg:       AgentModelConfig,
    debug_dir: Optional[Path] = None,
) -> Optional[dict]:
    """
    Merge and validate json1 + json2.
    Saves prompt and full raw response to debug_dir if given.
    Returns merged dict on success, best-available fallback, or None.
    """
    if json1 is None and json2 is None:
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / "03_agent3_raw_response.txt").write_text(
                "SKIPPED: both agent1 and agent2 returned None",
                encoding="utf-8",
            )
        return None

    # If only one succeeded, pass it to both slots for normalisation
    effective_json1 = json1 if json1 is not None else json2
    effective_json2 = json2 if json2 is not None else json1

    prompt = build_agent3_prompt(effective_json1, effective_json2)

    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "03_agent3_prompt.txt").write_text(prompt, encoding="utf-8")

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
                (debug_dir / "03_agent3_raw_response.txt").write_text(raw, encoding="utf-8")

            parsed = json.loads(clean_json_response(raw))

            if debug_dir is not None:
                (debug_dir / "03_agent3_parsed.json").write_text(
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

    # Validator failed — return whichever agent result has more non-null fields
    if debug_dir is not None:
        (debug_dir / "03_agent3_raw_response.txt").write_text(
            f"FAILED after {cfg.max_retries} attempts — using best-score fallback",
            encoding="utf-8",
        )

    def _score(d: Optional[dict]) -> int:
        return sum(1 for v in (d or {}).values() if v is not None and v not in ([], {}))

    return json1 if _score(json1) >= _score(json2) else json2