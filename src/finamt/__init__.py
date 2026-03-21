"""
finamt
~~~~~~~~~
OCR-powered German tax receipt processor.

Typical usage::

    from finamt import FinanceAgent

    agent = FinanceAgent()
    result = agent.process_receipt("scan.pdf")

    if result.success:
        print(result.data.vendor, result.data.total_amount)
    else:
        print(result.error_message)
"""

from .agents.agent import FinanceAgent
from .agents.config import Config, ModelConfig, cfg
from .exceptions import (
    FinanceAgentError,
    InvalidReceiptError,
    LLMExtractionError,
    OCRProcessingError,
)
from .models import ExtractionResult, ReceiptCategory, ReceiptData, ReceiptItem
from .models import Posting, PostingDirection, PostingType
from .agents.prompts import RECEIPT_CATEGORIES

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
    # Private-use / double-entry
    "Posting",
    "PostingDirection",
    "PostingType",
    # Prompts / categories
    "RECEIPT_CATEGORIES",
    "build_extraction_prompt",
    # Exceptions
    "FinanceAgentError",
    "OCRProcessingError",
    "LLMExtractionError",
    "InvalidReceiptError",
]