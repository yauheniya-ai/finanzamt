from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal
from enum import Enum
import json

class ItemCategory(Enum):
    """Predefined item categories for receipt items."""
    FOOD_GROCERIES = "food_groceries"
    FOOD_RESTAURANT = "food_restaurant"
    BEVERAGES = "beverages"
    TRANSPORTATION = "transportation"
    FUEL = "fuel"
    OFFICE_SUPPLIES = "office_supplies"
    ELECTRONICS = "electronics"
    CLOTHING = "clothing"
    HEALTH_PHARMACY = "health_pharmacy"
    HOUSEHOLD = "household"
    BOOKS_MEDIA = "books_media"
    SERVICES = "services"
    ENTERTAINMENT = "entertainment"
    TRAVEL = "travel"
    UTILITIES = "utilities"
    MAINTENANCE_REPAIR = "maintenance_repair"
    PROFESSIONAL_SERVICES = "professional_services"
    INSURANCE = "insurance"
    TAXES_FEES = "taxes_fees"
    OTHER = "other"
    
    @classmethod
    def from_string(cls, category_str: str) -> 'ItemCategory':
        """Convert string to ItemCategory, defaulting to OTHER if not found."""
        try:
            return cls(category_str.lower())
        except ValueError:
            return cls.OTHER

@dataclass
class ReceiptItem:
    """Data model for individual receipt items."""
    description: str
    quantity: Optional[Decimal] = None
    unit_price: Optional[Decimal] = None
    total_price: Optional[Decimal] = None
    category: ItemCategory = ItemCategory.OTHER
    vat_rate: Optional[Decimal] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "description": self.description,
            "quantity": float(self.quantity) if self.quantity else None,
            "unit_price": float(self.unit_price) if self.unit_price else None,
            "total_price": float(self.total_price) if self.total_price else None,
            "category": self.category.value,
            "vat_rate": float(self.vat_rate) if self.vat_rate else None
        }

@dataclass
class ReceiptData:
    """Data model for extracted receipt information."""
    company: Optional[str] = None
    date: Optional[datetime] = None
    amount_euro: Optional[Decimal] = None
    vat_percentage: Optional[Decimal] = None
    vat_euro: Optional[Decimal] = None
    confidence_score: Optional[float] = None
    raw_text: Optional[str] = None
    items: List[ReceiptItem] = field(default_factory=list)
    
    def validate(self) -> bool:
        """Validate the extracted data."""
        if self.date and self.date > datetime.now():
            return False
        if self.amount_euro and self.amount_euro <= 0:
            return False
        if self.vat_percentage and not (0 <= self.vat_percentage <= 100):
            return False
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "company": self.company,
            "date": self.date.isoformat() if self.date else None,
            "amount_euro": float(self.amount_euro) if self.amount_euro else None,
            "vat_percentage": float(self.vat_percentage) if self.vat_percentage else None,
            "vat_euro": float(self.vat_euro) if self.vat_euro else None,
            "confidence_score": self.confidence_score,
            "raw_text": self.raw_text,
            "items": [item.to_dict() for item in self.items]
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

@dataclass
class ExtractionResult:
    """Result container for the extraction process."""
    success: bool
    data: Optional[ReceiptData] = None
    error_message: Optional[str] = None
    processing_time: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "data": self.data.to_dict() if self.data else None,
            "error_message": self.error_message,
            "processing_time": self.processing_time
        }