import os
from typing import Dict, Any

class Config:
    """Configuration class for the Finance Agent."""
    
    # Default Ollama settings
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    DEFAULT_MODEL = os.getenv("FINANCE_AGENT_MODEL", "llama3.2")
    
    # OCR settings
    TESSERACT_CMD = os.getenv("TESSERACT_CMD", "tesseract")
    OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "deu+eng")  # German + English
    OCR_PREPROCESS = os.getenv("OCR_PREPROCESS", "true").lower() == "true"
    
    # PDF processing
    PDF_DPI = int(os.getenv("PDF_DPI", "300"))
    
    # Request settings
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
    
    @classmethod
    def get_model_config(cls) -> Dict[str, Any]:
        """Get model configuration."""
        return {
            "base_url": cls.OLLAMA_BASE_URL,
            "model": cls.DEFAULT_MODEL,
            "temperature": 0.1,
            "top_p": 0.9,
            "num_ctx": 4096,
            "max_retries": cls.MAX_RETRIES,
            "timeout": cls.REQUEST_TIMEOUT
        }
    
    EXTRACTION_PROMPT_TEMPLATE = """
    You are a financial document processing agent. Extract the following information from this German receipt text:

    RECEIPT HEADER:
    1. Company name
    2. Date (in YYYY-MM-DD format)
    3. Total amount in EUR
    4. VAT percentage (%)
    5. VAT amount in EUR

    INDIVIDUAL ITEMS:
    Extract each purchased item with:
    - Description/name
    - Quantity (if available)
    - Unit price (if available)
    - Total price for that item
    - Category (choose from: food_groceries, food_restaurant, beverages, transportation, fuel, office_supplies, electronics, clothing, health_pharmacy, household, books_media, services, entertainment, travel, utilities, maintenance_repair, professional_services, insurance, taxes_fees, other)
    - VAT rate for that item (if different from main rate)

    Receipt text:
    {text}

    Respond with a JSON object containing:
    {{
        "company": "company name",
        "date": "YYYY-MM-DD",
        "amount_euro": decimal_number,
        "vat_percentage": decimal_number,
        "vat_euro": decimal_number,
        "confidence_score": float_between_0_and_1,
        "items": [
            {{
                "description": "item description",
                "quantity": decimal_number_or_null,
                "unit_price": decimal_number_or_null,
                "total_price": decimal_number,
                "category": "category_from_list_above",
                "vat_rate": decimal_number_or_null
            }}
        ]
    }}
    """