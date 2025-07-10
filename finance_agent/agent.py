import json
import logging
import time
from typing import Union, Optional, Dict, Any
from pathlib import Path
import requests
from .models import ReceiptData, ExtractionResult, ReceiptItem, ItemCategory
from .ocr_processor import OCRProcessor
from .utils import DataExtractor, clean_json_response, parse_decimal, parse_date
from .config import Config
from .exceptions import LLMExtractionError, OCRProcessingError, InvalidReceiptError

logger = logging.getLogger(__name__)

class FinanceAgent:
    """
    Agentic AI system for processing financial receipts.
    
    This agent combines OCR processing with LLM-based extraction
    to extract structured data from German receipts.
    """
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.ocr_processor = OCRProcessor(self.config)
        self.data_extractor = DataExtractor()
        self._setup_logging()
    
    def _setup_logging(self):
        """Setup logging configuration."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    def process_receipt(self, pdf_path: Union[str, Path, bytes]) -> ExtractionResult:
        """
        Process a receipt PDF and extract financial data.
        
        Args:
            pdf_path: Path to PDF file or PDF bytes
            
        Returns:
            ExtractionResult containing extracted data
        """
        start_time = time.time()
        
        try:
            logger.info("Starting receipt processing...")
            
            # Step 1: Extract text using OCR
            logger.info("Extracting text from PDF...")
            raw_text = self.ocr_processor.extract_text_from_pdf(pdf_path)
            
            if not raw_text.strip():
                return ExtractionResult(
                    success=False,
                    error_message="No text could be extracted from the PDF",
                    processing_time=time.time() - start_time
                )
            
            # Step 2: Use LLM for structured extraction
            logger.info("Processing with LLM...")
            llm_result = self._extract_with_llm(raw_text)
            
            # Step 3: Fallback to rule-based extraction if LLM fails
            if not llm_result or not llm_result.get("items"):
                logger.info("LLM extraction failed or incomplete, using fallback method...")
                llm_result = self._extract_with_rules(raw_text)
            
            # Step 4: Create result with items
            items = []
            if llm_result.get("items"):
                for item_data in llm_result["items"]:
                    try:
                        item = ReceiptItem(
                            description=item_data.get("description", ""),
                            quantity=parse_decimal(item_data.get("quantity")),
                            unit_price=parse_decimal(item_data.get("unit_price")),
                            total_price=parse_decimal(item_data.get("total_price")),
                            category=ItemCategory.from_string(item_data.get("category", "other")),
                            vat_rate=parse_decimal(item_data.get("vat_rate"))
                        )
                        items.append(item)
                    except Exception as e:
                        logger.warning(f"Failed to parse item: {e}")
                        continue
            
            receipt_data = ReceiptData(
                company=llm_result.get("company"),
                date=parse_date(llm_result.get("date")) if llm_result.get("date") else None,
                amount_euro=parse_decimal(llm_result.get("amount_euro")),
                vat_percentage=parse_decimal(llm_result.get("vat_percentage")),
                vat_euro=parse_decimal(llm_result.get("vat_euro")),
                confidence_score=llm_result.get("confidence_score", 0.5),
                raw_text=raw_text,
                items=items
            )
            
            # Validate the extracted data
            if not receipt_data.validate():
                raise InvalidReceiptError("Extracted receipt data failed validation")
            
            processing_time = time.time() - start_time
            
            return ExtractionResult(
                success=True,
                data=receipt_data,
                processing_time=processing_time
            )
            
        except OCRProcessingError as e:
            logger.error(f"OCR processing error: {e}")
            return ExtractionResult(
                success=False,
                error_message=str(e),
                processing_time=time.time() - start_time
            )
        except LLMExtractionError as e:
            logger.error(f"LLM extraction error: {e}")
            return ExtractionResult(
                success=False,
                error_message=str(e),
                processing_time=time.time() - start_time
            )
        except InvalidReceiptError as e:
            logger.error(f"Invalid receipt data: {e}")
            return ExtractionResult(
                success=False,
                error_message=str(e),
                processing_time=time.time() - start_time
            )
        except Exception as e:
            logger.error(f"Unexpected error processing receipt: {e}")
            return ExtractionResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}",
                processing_time=time.time() - start_time
            )
    
    def _extract_with_llm(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract data using LLM (Ollama).
        
        Args:
            text: OCR extracted text
            
        Returns:
            Extracted data dictionary
            
        Raises:
            LLMExtractionError: If extraction fails
        """
        model_config = self.config.get_model_config()
        
        for attempt in range(model_config["max_retries"]):
            try:
                response = requests.post(
                    f"{model_config['base_url']}/api/generate",
                    json={
                        "model": model_config["model"],
                        "prompt": self.config.EXTRACTION_PROMPT_TEMPLATE.format(text=text),
                        "stream": False,
                        "options": {
                            "temperature": model_config["temperature"],
                            "top_p": model_config["top_p"],
                            "num_ctx": model_config["num_ctx"]
                        }
                    },
                    timeout=model_config["timeout"]
                )
                
                if response.status_code == 200:
                    try:
                        result = response.json()
                        response_text = result.get("response", "")
                        cleaned_response = clean_json_response(response_text)
                        return json.loads(cleaned_response)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Attempt {attempt + 1} failed to decode JSON: {e}")
                        continue
                else:
                    logger.warning(f"Attempt {attempt + 1} failed with status {response.status_code}")
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                time.sleep(1)  # Backoff
        
        raise LLMExtractionError("Failed to extract data with LLM after multiple attempts")
    
    def _extract_with_rules(self, text: str) -> Dict[str, Any]:
        """
        Fallback rule-based extraction.
        
        Args:
            text: OCR extracted text
            
        Returns:
            Extracted data dictionary
        """
        # Extract company name
        company = self.data_extractor.extract_company_name(text)
        
        # Extract date
        date = self.data_extractor.extract_date(text)
        
        # Extract amounts
        amounts = self.data_extractor.extract_amounts(text)
        
        # Extract VAT info
        vat_info = self.data_extractor.extract_vat_info(text)
        
        # Extract items
        items = self.data_extractor.extract_items(text)
        
        return {
            "company": company,
            "date": date.strftime("%Y-%m-%d") if date else None,
            "amount_euro": float(amounts["total"]) if amounts["total"] else None,
            "vat_percentage": float(vat_info["vat_percentage"]) if vat_info["vat_percentage"] else None,
            "vat_euro": float(vat_info["vat_amount"]) if vat_info["vat_amount"] else None,
            "confidence_score": 0.3,  # Lower confidence for rule-based extraction
            "items": items
        }
    
    def batch_process(self, pdf_paths: list) -> Dict[str, ExtractionResult]:
        """
        Process multiple receipts in batch.
        
        Args:
            pdf_paths: List of PDF paths
            
        Returns:
            Dictionary mapping paths to results
        """
        results = {}
        
        for pdf_path in pdf_paths:
            logger.info(f"Processing {pdf_path}...")
            results[str(pdf_path)] = self.process_receipt(pdf_path)
        
        return results