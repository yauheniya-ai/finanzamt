"""
finanzamt.agents.config
~~~~~~~~~~~~~~~~~~~~~~~
All configuration for finanzamt in one place.

  Config        — OCR, Tesseract, general settings (env prefix: FINANZAMT_)
  AgentsConfig  — per-agent LLM model/timeout/ctx settings
  ModelConfig   — immutable snapshot returned by Config.get_model_config()
  AgentModelConfig — immutable snapshot returned by AgentsConfig.get_agentN_config()

Override via environment variables or a .env file:
  FINANZAMT_OLLAMA_BASE_URL=http://localhost:11434
  FINANZAMT_AGENT1_MODEL=llama3.1
  FINANZAMT_AGENT2_MODEL=qwen2.5vl:7b-q4_K_M
  FINANZAMT_AGENT3_MODEL=qwen2.5:7b-instruct-q4_K_M
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Immutable config snapshots
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    """Snapshot of the legacy single-model LLM settings (used by OCR pipeline)."""
    base_url:    str
    model:       str
    temperature: float
    top_p:       float
    num_ctx:     int
    max_retries: int
    timeout:     int


@dataclass(frozen=True)
class AgentModelConfig:
    """Snapshot of per-agent LLM settings."""
    base_url:    str
    model:       str
    temperature: float
    top_p:       float
    num_ctx:     int
    timeout:     int
    max_retries: int


# ---------------------------------------------------------------------------
# General config (OCR, Tesseract, PDF)
# ---------------------------------------------------------------------------

class Config(BaseSettings):
    """
    Runtime configuration for finanzamt.

    Reads from (in priority order):
      1. Environment variables prefixed with FINANZAMT_
      2. A .env file in the working directory
      3. The defaults below
    """

    model_config = SettingsConfigDict(
        env_prefix="FINANZAMT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL of the Ollama server.",
    )
    model: str = Field(
        default="llama3.2",
        description="Ollama model tag (legacy single-model path).",
    )
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    top_p:       float = Field(default=0.9, ge=0.0, le=1.0)
    num_ctx:     int   = Field(default=8192, ge=512)

    # OCR — Tesseract
    tesseract_cmd:  str  = Field(default="tesseract")
    ocr_language:   str  = Field(default="deu+eng")
    ocr_preprocess: bool = Field(default=True)

    # PDF rendering
    pdf_dpi: int = Field(default=300, ge=72, le=1200)

    # HTTP / retry
    max_retries:     int = Field(default=3,  ge=0, le=10)
    request_timeout: int = Field(default=30, ge=1)

    @field_validator("ollama_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("ocr_language")
    @classmethod
    def _validate_language(cls, v: str) -> str:
        codes = [c.strip() for c in v.split("+") if c.strip()]
        if not codes:
            raise ValueError("ocr_language must contain at least one Tesseract language code.")
        return "+".join(codes)

    @model_validator(mode="after")
    def _warn_temperature(self) -> "Config":
        if self.temperature > 0.5:
            warnings.warn(
                f"temperature={self.temperature} is high for structured extraction.",
                UserWarning, stacklevel=2,
            )
        return self

    def get_model_config(self) -> ModelConfig:
        return ModelConfig(
            base_url=self.ollama_base_url,
            model=self.model,
            temperature=self.temperature,
            top_p=self.top_p,
            num_ctx=self.num_ctx,
            max_retries=self.max_retries,
            timeout=self.request_timeout,
        )

    # Backward-compatible uppercase aliases
    @property
    def OLLAMA_BASE_URL(self) -> str:   return self.ollama_base_url  # noqa: N802
    @property
    def DEFAULT_MODEL(self) -> str:     return self.model             # noqa: N802
    @property
    def TESSERACT_CMD(self) -> str:     return self.tesseract_cmd     # noqa: N802
    @property
    def OCR_LANGUAGE(self) -> str:      return self.ocr_language      # noqa: N802
    @property
    def OCR_PREPROCESS(self) -> bool:   return self.ocr_preprocess    # noqa: N802
    @property
    def PDF_DPI(self) -> int:           return self.pdf_dpi           # noqa: N802
    @property
    def MAX_RETRIES(self) -> int:       return self.max_retries       # noqa: N802
    @property
    def REQUEST_TIMEOUT(self) -> int:   return self.request_timeout   # noqa: N802


# ---------------------------------------------------------------------------
# Per-agent config
# ---------------------------------------------------------------------------

class AgentsConfig(BaseSettings):
    """
    LLM model configuration for the 4-agent extraction pipeline.
    All 4 agents use the same model — override with FINANZAMT_AGENT_MODEL.
    Temperature is 0.0 for deterministic JSON extraction.
    """

    model_config = SettingsConfigDict(
        env_prefix="FINANZAMT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ollama_base_url: str = Field(default="http://localhost:11434")

    # Single model used by all 4 agents
    agent_model:       str   = Field(default="qwen2.5:7b-instruct-q4_K_M")
    agent_timeout:     int   = Field(default=60)
    agent_num_ctx:     int   = Field(default=4096)
    agent_max_retries: int   = Field(default=2)
    temperature:       float = Field(default=0.0)
    top_p:             float = Field(default=1.0)

    def get_agent_config(self) -> AgentModelConfig:
        return AgentModelConfig(
            base_url=    self.ollama_base_url.rstrip("/"),
            model=       self.agent_model,
            temperature= self.temperature,
            top_p=       self.top_p,
            num_ctx=     self.agent_num_ctx,
            timeout=     self.agent_timeout,
            max_retries= self.agent_max_retries,
        )

    # Backward-compat aliases so any code still calling get_agent1_config() doesnt crash
    def get_agent1_config(self) -> AgentModelConfig: return self.get_agent_config()
    def get_agent2_config(self) -> AgentModelConfig: return self.get_agent_config()
    def get_agent3_config(self) -> AgentModelConfig: return self.get_agent_config()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

cfg = Config()

__all__ = ["Config", "ModelConfig", "AgentsConfig", "AgentModelConfig", "cfg"]