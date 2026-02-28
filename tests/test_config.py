"""
tests/test_config.py
~~~~~~~~~~~~~~~~~~~~
Tests for finanzamt.agents.config — Config, AgentsConfig, ModelConfig,
AgentModelConfig dataclasses, and backward-compatible aliases.
"""

from __future__ import annotations

import os
import warnings
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from finanzamt.agents.config import AgentModelConfig, AgentsConfig, Config, ModelConfig, cfg


class TestConfigDefaults:
    def test_ollama_base_url_default(self):
        assert Config().ollama_base_url == "http://localhost:11434"

    def test_model_default(self):
        assert Config().model == "llama3.2"

    def test_ocr_language_default(self):
        assert Config().ocr_language == "deu+eng"

    def test_ocr_preprocess_default(self):
        assert Config().ocr_preprocess is True

    def test_pdf_dpi_default(self):
        assert Config().pdf_dpi == 300

    def test_max_retries_default(self):
        assert Config().max_retries == 3

    def test_request_timeout_default(self):
        assert Config().request_timeout == 30

    def test_temperature_default(self):
        assert Config().temperature == 0.1


class TestConfigValidation:
    def test_trailing_slash_stripped(self):
        c = Config(ollama_base_url="http://localhost:11434/")
        assert not c.ollama_base_url.endswith("/")

    def test_multiple_trailing_slashes_stripped(self):
        c = Config(ollama_base_url="http://localhost:11434///")
        assert c.ollama_base_url == "http://localhost:11434"

    def test_pdf_dpi_minimum(self):
        with pytest.raises(ValidationError):
            Config(pdf_dpi=10)

    def test_pdf_dpi_maximum(self):
        with pytest.raises(ValidationError):
            Config(pdf_dpi=9999)

    def test_max_retries_negative(self):
        with pytest.raises(ValidationError):
            Config(max_retries=-1)

    def test_max_retries_too_high(self):
        with pytest.raises(ValidationError):
            Config(max_retries=100)

    def test_temperature_out_of_range(self):
        with pytest.raises(ValidationError):
            Config(temperature=3.0)

    def test_top_p_out_of_range(self):
        with pytest.raises(ValidationError):
            Config(top_p=1.5)

    def test_ocr_language_empty_string(self):
        with pytest.raises(ValidationError):
            Config(ocr_language="")

    def test_ocr_language_normalised(self):
        c = Config(ocr_language=" deu + eng ")
        assert c.ocr_language == "deu+eng"

    def test_high_temperature_warns(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Config(temperature=0.9)
            assert any(issubclass(x.category, UserWarning) for x in w)

    def test_low_temperature_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Config(temperature=0.1)
            assert not any(issubclass(x.category, UserWarning) for x in w)


class TestConfigEnvVarOverride:
    def test_env_var_overrides_model(self):
        with patch.dict(os.environ, {"FINANZAMT_MODEL": "mistral"}):
            assert Config().model == "mistral"

    def test_env_var_overrides_pdf_dpi(self):
        with patch.dict(os.environ, {"FINANZAMT_PDF_DPI": "150"}):
            assert Config().pdf_dpi == 150

    def test_env_var_overrides_ocr_preprocess(self):
        with patch.dict(os.environ, {"FINANZAMT_OCR_PREPROCESS": "false"}):
            assert Config().ocr_preprocess is False


class TestModelConfig:
    def test_returns_model_config_dataclass(self):
        assert isinstance(Config().get_model_config(), ModelConfig)

    def test_model_config_fields(self):
        mc = Config(model="phi3", max_retries=5, request_timeout=60).get_model_config()
        assert mc.model == "phi3"
        assert mc.max_retries == 5
        assert mc.timeout == 60

    def test_model_config_is_frozen(self):
        mc = Config().get_model_config()
        with pytest.raises(Exception):
            mc.model = "changed"  # type: ignore[misc]


class TestAgentsConfig:
    def test_single_model_used_for_all_agents(self):
        cfg = AgentsConfig(agent_model="mistral")
        ac = cfg.get_agent_config()
        assert ac.model == "mistral"

    def test_temperature_is_zero(self):
        assert AgentsConfig().get_agent_config().temperature == 0.0

    def test_returns_agent_model_config_dataclass(self):
        assert isinstance(AgentsConfig().get_agent_config(), AgentModelConfig)

    def test_backward_compat_get_agent1_config(self):
        cfg = AgentsConfig()
        assert cfg.get_agent1_config().model == cfg.get_agent_config().model

    def test_backward_compat_get_agent2_config(self):
        cfg = AgentsConfig()
        assert cfg.get_agent2_config().model == cfg.get_agent_config().model

    def test_backward_compat_get_agent3_config(self):
        cfg = AgentsConfig()
        assert cfg.get_agent3_config().model == cfg.get_agent_config().model

    def test_env_var_overrides_agent_model(self):
        with patch.dict(os.environ, {"FINANZAMT_AGENT_MODEL": "llama3.1"}):
            assert AgentsConfig().agent_model == "llama3.1"

    def test_agent_model_config_is_frozen(self):
        ac = AgentsConfig().get_agent_config()
        with pytest.raises(Exception):
            ac.model = "changed"  # type: ignore[misc]


class TestSingleton:
    def test_cfg_is_config_instance(self):
        assert isinstance(cfg, Config)