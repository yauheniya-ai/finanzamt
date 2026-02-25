"""
finanzamt.config
~~~~~~~~~~~~~~~~
Central configuration for the finanzamt library.

All values have sensible defaults that work out of the box (local Ollama +
Tesseract). Override any field via a ``.env`` file or environment variables
— pydantic-settings picks them up automatically.

Usage::

    from finanzamt.config import cfg

    print(cfg.ollama_base_url)          # "http://localhost:11434"
    print(cfg.get_model_config())       # typed ModelConfig dataclass
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Typed return value for model configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    """Immutable snapshot of the LLM model settings."""

    base_url: str
    model: str
    temperature: float
    top_p: float
    num_ctx: int
    max_retries: int
    timeout: int


# ---------------------------------------------------------------------------
# Main settings class
# ---------------------------------------------------------------------------

class Config(BaseSettings):
    """
    Runtime configuration for finanzamt.

    Reads from (in priority order):
      1. Environment variables (prefixed with ``FINANZAMT_``)
      2. A ``.env`` file in the working directory
      3. The defaults defined below
    """

    model_config = SettingsConfigDict(
        env_prefix="FINANZAMT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Ollama / LLM
    # ------------------------------------------------------------------

    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL of the Ollama server.",
    )
    model: str = Field(
        default="llama3.2",
        description="Ollama model tag to use for extraction.",
    )

    # LLM inference parameters
    temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Sampling temperature (0 = deterministic).",
    )
    top_p: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description="Nucleus sampling threshold.",
    )
    num_ctx: int = Field(
        default=8192,
        ge=512,
        description="Context window size in tokens.",
    )

    # ------------------------------------------------------------------
    # OCR — Tesseract
    # ------------------------------------------------------------------

    tesseract_cmd: str = Field(
        default="tesseract",
        description=(
            "Path to the Tesseract binary. "
            "On Windows this is typically 'C:/Program Files/Tesseract-OCR/tesseract.exe'."
        ),
    )
    ocr_language: str = Field(
        default="deu+eng",
        description=(
            "Tesseract language codes joined with '+'. "
            "Requires the corresponding language packs to be installed. "
            "Example: 'deu+eng' for German + English."
        ),
    )
    ocr_preprocess: bool = Field(
        default=True,
        description=(
            "Whether to apply image pre-processing (deskew, denoise, "
            "contrast normalisation) before OCR. Improves accuracy on "
            "low-quality scans at the cost of speed."
        ),
    )

    # ------------------------------------------------------------------
    # PDF rendering
    # ------------------------------------------------------------------

    pdf_dpi: int = Field(
        default=300,
        ge=72,
        le=1200,
        description="DPI used when rasterising PDF pages for OCR.",
    )

    # ------------------------------------------------------------------
    # HTTP / retry
    # ------------------------------------------------------------------

    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Number of retry attempts for Ollama API calls.",
    )
    request_timeout: int = Field(
        default=30,
        ge=1,
        description="HTTP request timeout in seconds.",
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("ollama_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("ocr_language")
    @classmethod
    def _validate_language(cls, v: str) -> str:
        codes = [c.strip() for c in v.split("+") if c.strip()]
        if not codes:
            raise ValueError("ocr_language must contain at least one Tesseract language code.")
        return "+".join(codes)

    @model_validator(mode="after")
    def _warn_on_high_temperature(self) -> "Config":
        if self.temperature > 0.5:
            warnings.warn(
                f"temperature={self.temperature} is high for structured extraction. "
                "Values above 0.3 may produce inconsistent JSON output.",
                UserWarning,
                stacklevel=2,
            )
        return self

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def get_model_config(self) -> ModelConfig:
        """Return an immutable, typed snapshot of the LLM configuration."""
        return ModelConfig(
            base_url=self.ollama_base_url,
            model=self.model,
            temperature=self.temperature,
            top_p=self.top_p,
            num_ctx=self.num_ctx,
            max_retries=self.max_retries,
            timeout=self.request_timeout,
        )

    # ------------------------------------------------------------------
    # Backward-compatible uppercase aliases
    # These mirror the original os.getenv-based class attributes so that
    # existing code (agent.py, ocr_processor.py, etc.) keeps working
    # without any changes. New code should use the lowercase names.
    # ------------------------------------------------------------------

    @property
    def OLLAMA_BASE_URL(self) -> str:  # noqa: N802
        return self.ollama_base_url

    @property
    def DEFAULT_MODEL(self) -> str:  # noqa: N802
        return self.model

    @property
    def TESSERACT_CMD(self) -> str:  # noqa: N802
        return self.tesseract_cmd

    @property
    def OCR_LANGUAGE(self) -> str:  # noqa: N802
        return self.ocr_language

    @property
    def OCR_PREPROCESS(self) -> bool:  # noqa: N802
        return self.ocr_preprocess

    @property
    def PDF_DPI(self) -> int:  # noqa: N802
        return self.pdf_dpi

    @property
    def MAX_RETRIES(self) -> int:  # noqa: N802
        return self.max_retries

    @property
    def REQUEST_TIMEOUT(self) -> int:  # noqa: N802
        return self.request_timeout


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------

cfg = Config()

__all__ = ["Config", "ModelConfig", "cfg"]