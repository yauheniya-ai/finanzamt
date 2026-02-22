"""
tests/test_config.py
~~~~~~~~~~~~~~~~~~~~
Tests for finanzamt.config — validation, defaults, env-var overrides,
ModelConfig dataclass, and backward-compatible uppercase aliases.
"""

from __future__ import annotations

import os
import warnings
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from finanzamt.config import Config, ModelConfig, cfg


class TestDefaults:
    def test_ollama_base_url_default(self):
        c = Config()
        assert c.ollama_base_url == "http://localhost:11434"

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


class TestValidation:
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

    def test_ocr_language_whitespace_only(self):
        with pytest.raises(ValidationError):
            Config(ocr_language="  +  ")

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


class TestEnvVarOverride:
    def test_env_var_overrides_model(self):
        with patch.dict(os.environ, {"FINANZAMT_MODEL": "mistral"}):
            c = Config()
            assert c.model == "mistral"

    def test_env_var_overrides_pdf_dpi(self):
        with patch.dict(os.environ, {"FINANZAMT_PDF_DPI": "150"}):
            c = Config()
            assert c.pdf_dpi == 150

    def test_env_var_overrides_ocr_preprocess(self):
        with patch.dict(os.environ, {"FINANZAMT_OCR_PREPROCESS": "false"}):
            c = Config()
            assert c.ocr_preprocess is False


class TestModelConfig:
    def test_returns_model_config_dataclass(self):
        mc = Config().get_model_config()
        assert isinstance(mc, ModelConfig)

    def test_model_config_fields(self):
        c = Config(model="phi3", max_retries=5, request_timeout=60)
        mc = c.get_model_config()
        assert mc.model == "phi3"
        assert mc.max_retries == 5
        assert mc.timeout == 60

    def test_model_config_is_frozen(self):
        mc = Config().get_model_config()
        with pytest.raises(Exception):
            mc.model = "changed"  # type: ignore[misc]


class TestSingleton:
    def test_cfg_is_config_instance(self):
        assert isinstance(cfg, Config)
