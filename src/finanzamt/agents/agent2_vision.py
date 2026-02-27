"""
finanzamt.agents.agent2_vision
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Agent 2: Vision-based LLM extraction.

Input:  PDF rendered as PNG (base64)
Output: dict (json2) or None on failure
"""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import Optional, Union

import requests

from ..utils import clean_json_response
from .config import AgentModelConfig
from .prompts import build_agent2_prompt


def _pdf_to_png_base64(pdf_path: Union[str, Path]) -> Optional[str]:
    try:
        from pdf2image import convert_from_path  # type: ignore
        pages = convert_from_path(str(pdf_path), dpi=150, first_page=1, last_page=1)
        if not pages:
            return None
        buf = io.BytesIO()
        pages[0].save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except ImportError:
        return None
    except Exception:
        return None


def run(
    pdf_path:  Union[str, Path],
    cfg:       AgentModelConfig,
    debug_dir: Optional[Path] = None,
) -> Optional[dict]:
    """
    Render PDF as PNG and call the vision LLM.
    Saves prompt, rendered PNG, and full raw response to debug_dir if given.
    Returns parsed dict on success, None on failure.
    """
    png_b64 = _pdf_to_png_base64(pdf_path)
    if not png_b64:
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / "02_agent2_raw_response.txt").write_text(
                "SKIPPED: PDF→PNG conversion failed or pdf2image not installed",
                encoding="utf-8",
            )
        return None

    prompt = build_agent2_prompt()

    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "02_agent2_prompt.txt").write_text(prompt, encoding="utf-8")
        # Save the rendered PNG for inspection
        (debug_dir / "02_agent2_input.png").write_bytes(base64.b64decode(png_b64))

    for attempt in range(1, cfg.max_retries + 1):
        try:
            response = requests.post(
                f"{cfg.base_url}/api/generate",
                json={
                    "model":  cfg.model,
                    "prompt": prompt,
                    "images": [png_b64],
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
                (debug_dir / "02_agent2_raw_response.txt").write_text(raw, encoding="utf-8")

            parsed = json.loads(clean_json_response(raw))

            if debug_dir is not None:
                (debug_dir / "02_agent2_parsed.json").write_text(
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
        (debug_dir / "02_agent2_raw_response.txt").write_text(
            f"FAILED after {cfg.max_retries} attempts", encoding="utf-8"
        )
    return None