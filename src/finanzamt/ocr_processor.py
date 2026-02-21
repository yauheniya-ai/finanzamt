import io
import logging
from typing import Optional, Union
from pathlib import Path
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import cv2
import numpy as np
from .config import Config
from .exceptions import OCRProcessingError

logger = logging.getLogger(__name__)

class OCRProcessor:
    """OCR processor for extracting text from PDF receipts."""
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self._setup_tesseract()
    
    def _setup_tesseract(self):
        """Setup Tesseract configuration."""
        if self.config.TESSERACT_CMD != "tesseract":
            pytesseract.pytesseract.tesseract_cmd = self.config.TESSERACT_CMD
    
    def extract_text_from_pdf(self, pdf_path: Union[str, Path, bytes]) -> str:
        """
        Extract text from PDF using OCR.
        
        Args:
            pdf_path: Path to PDF file or PDF bytes
            
        Returns:
            Extracted text
            
        Raises:
            OCRProcessingError: If text extraction fails
        """
        try:
            if isinstance(pdf_path, bytes):
                pdf_document = fitz.open(stream=pdf_path, filetype="pdf")
            else:
                pdf_document = fitz.open(pdf_path)
            
            extracted_text = ""
            
            for page_num in range(pdf_document.page_count):
                page = pdf_document[page_num]
                
                # First try direct text extraction
                page_text = page.get_text()
                if page_text.strip():
                    extracted_text += page_text + "\n"
                else:
                    # Fall back to OCR if no direct text
                    extracted_text += self._ocr_page(page) + "\n"
            
            pdf_document.close()
            return extracted_text.strip()
            
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}")
            raise OCRProcessingError(f"Failed to extract text from PDF: {e}")
    
    def _ocr_page(self, page) -> str:
        """
        Perform OCR on a single page.
        
        Args:
            page: PyMuPDF page object
            
        Returns:
            Extracted text
        """
        try:
            # Convert page to image
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x scale for better OCR
            img_data = pix.tobytes("png")
            
            # Load image with PIL
            image = Image.open(io.BytesIO(img_data))
            
            # Preprocess image if enabled
            if self.config.OCR_PREPROCESS:
                image = self._preprocess_image(image)
            
            # Perform OCR
            custom_config = f'--oem 3 --psm 6 -l {self.config.OCR_LANGUAGE}'
            text = pytesseract.image_to_string(image, config=custom_config)
            
            return text
            
        except Exception as e:
            logger.error(f"Error during OCR: {e}")
            return ""
    
    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocess image for better OCR results.
        
        Args:
            image: PIL Image
            
        Returns:
            Preprocessed image
        """
        try:
            # Convert to grayscale
            if image.mode != 'L':
                image = image.convert('L')
            
            # Convert to numpy array
            img_array = np.array(image)
            
            # Apply denoising
            img_array = cv2.fastNlMeansDenoising(img_array, None, 10, 7, 21)
            
            # Enhance contrast
            img_array = cv2.convertScaleAbs(img_array, alpha=1.2, beta=10)
            
            # Apply threshold
            _, img_array = cv2.threshold(img_array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            return Image.fromarray(img_array)
        except Exception as e:
            logger.warning(f"Image preprocessing failed: {e}")
            return image