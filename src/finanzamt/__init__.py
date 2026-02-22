"""
finanzamt
~~~~~~~~~
A Python library for processing receipts, extracting key information, and assisting in the preparation of all essential tax return statements.

Typical usage::

    from finanzamt import FinanceAgent

    agent = FinanceAgent()
    result = agent.process_receipt("scan.pdf")

    if result.success:
        print(result.data.vendor, result.data.total_amount)
    else:
        print(result.error_message)
"""

from .agent import FinanceAgent
from .config import Config, ModelConfig, cfg
from .exceptions import (
    FinanceAgentError,
    InvalidReceiptError,
    LLMExtractionError,
    OCRProcessingError,
)
from .models import ExtractionResult, ReceiptCategory, ReceiptData, ReceiptItem
from .prompts import RECEIPT_CATEGORIES, build_extraction_prompt

__all__ = [
    # Core agent
    "FinanceAgent",
    # Configuration
    "Config",
    "ModelConfig",
    "cfg",
    # Models
    "ReceiptData",
    "ReceiptItem",
    "ReceiptCategory",
    "ExtractionResult",
    # Prompts / categories
    "RECEIPT_CATEGORIES",
    "build_extraction_prompt",
    # Exceptions
    "FinanceAgentError",
    "OCRProcessingError",
    "LLMExtractionError",
    "InvalidReceiptError",
]
