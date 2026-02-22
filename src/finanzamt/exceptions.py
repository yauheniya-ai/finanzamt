"""
finanzamt.exceptions
~~~~~~~~~~~~~~~~~~~~
Exception hierarchy for the finanzamt library.

All exceptions inherit from ``FinanceAgentError`` so callers can catch
the entire family with a single ``except FinanceAgentError`` clause while
still being able to handle specific sub-types when needed.
"""

from __future__ import annotations


class FinanceAgentError(Exception):
    """Base exception for all finanzamt errors."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause          # original exception, if any
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