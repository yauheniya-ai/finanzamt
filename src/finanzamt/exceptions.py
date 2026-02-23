"""
finanzamt.exceptions
~~~~~~~~~~~~~~~~~~~~
Exception hierarchy for the finanzamt library.
"""

from __future__ import annotations


class FinanceAgentError(Exception):
    """Base exception for all finanzamt errors."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause
        self.message = message

    def __str__(self) -> str:
        if self.cause:
            return f"{self.message} (caused by {type(self.cause).__name__}: {self.cause})"
        return self.message


class OCRProcessingError(FinanceAgentError):
    """Raised when text cannot be extracted from an image or PDF."""


class LLMExtractionError(FinanceAgentError):
    """Raised when the Ollama LLM fails to return valid structured JSON."""


class InvalidReceiptError(FinanceAgentError):
    """Raised when extracted receipt data fails business-logic validation."""


class DuplicateReceiptError(FinanceAgentError):
    """
    Raised when a receipt with identical content already exists in the DB.

    Attributes:
        existing_id: The SHA-256 hash / DB id of the existing receipt.
    """

    def __init__(self, message: str, *, existing_id: str) -> None:
        super().__init__(message)
        self.existing_id = existing_id