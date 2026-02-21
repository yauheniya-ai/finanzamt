class FinanceAgentError(Exception):
    """Base exception class for all Finance Agent exceptions."""
    pass

class OCRProcessingError(FinanceAgentError):
    """Exception raised for errors during OCR processing."""
    pass

class LLMExtractionError(FinanceAgentError):
    """Exception raised for errors during LLM extraction."""
    pass

class InvalidReceiptError(FinanceAgentError):
    """Exception raised when receipt data is invalid."""
    pass