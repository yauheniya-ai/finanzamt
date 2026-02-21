import re
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any, List
import json

logger = logging.getLogger(__name__)

class DataExtractor:
    """Utility class for extracting specific data from text."""
    
    # German date patterns
    DATE_PATTERNS = [
        r'\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b',  # DD.MM.YYYY
        r'\b(\d{1,2})\.(\d{1,2})\.(\d{2})\b',  # DD.MM.YY
        r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b',    # YYYY-MM-DD
        r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b',    # DD/MM/YYYY
        r'\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b'  # 12 Januar 2023
    ]
    
    # Amount patterns (German format)
    AMOUNT_PATTERNS = [
        r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*€',  # German format: 1.234,56 €
        r'€\s*(\d{1,3}(?:\.\d{3})*,\d{2})',  # € 1.234,56
        r'EUR\s*(\d{1,3}(?:\.\d{3})*,\d{2})',  # EUR 1.234,56
        r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*EUR',  # 1.234,56 EUR
    ]
    
    # VAT patterns
    VAT_PATTERNS = [
        r'(\d{1,2}(?:,\d{1,2})?)\s*%.*?(\d{1,3}(?:\.\d{3})*,\d{2})\s*€',  # 19% ... 12,34 €
        r'MwSt\.?\s*(\d{1,2}(?:,\d{1,2})?)\s*%.*?(\d{1,3}(?:\.\d{3})*,\d{2})',
        r'VAT\s*(\d{1,2}(?:,\d{1,2})?)\s*%.*?(\d{1,3}(?:\.\d{3})*,\d{2})',
    ]
    
    # Item line patterns for German receipts
    ITEM_PATTERNS = [
        # Pattern: Description Price
        r'^(.+?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*€?\s*$',
        # Pattern: Quantity x Description Price
        r'^(\d+(?:,\d+)?)\s*x\s*(.+?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})\s*€?\s*$',
        # Pattern: Description @ Unit Price = Total Price
        r'^(.+?)\s*@\s*(\d{1,3}(?:\.\d{3})*,\d{2})\s*=\s*(\d{1,3}(?:\.\d{3})*,\d{2})\s*€?\s*$'
    ]
    
    # Category keywords for German receipts
    CATEGORY_KEYWORDS = {
        'food_groceries': ['brot', 'milch', 'käse', 'fleisch', 'gemüse', 'obst', 'nudeln', 'reis', 'mehl', 'zucker', 'joghurt', 'butter', 'eier', 'wurst', 'fisch'],
        'food_restaurant': ['pizza', 'burger', 'pasta', 'salat', 'suppe', 'hauptgang', 'vorspeise', 'nachspeise', 'menü', 'gericht'],
        'beverages': ['wasser', 'saft', 'cola', 'bier', 'wein', 'kaffee', 'tee', 'limonade', 'mineralwasser', 'getränk'],
        'transportation': ['ticket', 'fahrkarte', 'bahncard', 'bus', 'taxi', 'fahrt', 'öpnv', 'verkehr'],
        'fuel': ['benzin', 'diesel', 'super', 'tankstelle', 'kraftstoff', 'sprit'],
        'office_supplies': ['papier', 'stift', 'kugelschreiber', 'ordner', 'hefter', 'büro', 'schreibwaren'],
        'electronics': ['handy', 'smartphone', 'laptop', 'computer', 'tablet', 'kabel', 'elektronik', 'technik'],
        'clothing': ['hemd', 'hose', 'kleid', 'schuhe', 'jacke', 'pullover', 'kleidung', 'mode'],
        'health_pharmacy': ['medikament', 'tablette', 'salbe', 'apotheke', 'gesundheit', 'pharma', 'arznei'],
        'household': ['reiniger', 'waschmittel', 'seife', 'shampoo', 'zahnpasta', 'haushalt', 'putzmittel'],
        'books_media': ['buch', 'zeitschrift', 'cd', 'dvd', 'blu-ray', 'magazin', 'zeitung', 'medien'],
        'services': ['service', 'dienstleistung', 'reparatur', 'wartung', 'beratung'],
        'entertainment': ['kino', 'theater', 'konzert', 'entertainment', 'unterhaltung', 'show', 'veranstaltung'],
        'travel': ['hotel', 'flug', 'zug', 'reise', 'übernachtung', 'unterkunft', 'travel'],
        'utilities': ['strom', 'gas', 'wasser', 'heizung', 'nebenkosten', 'versorgung'],
        'maintenance_repair': ['reparatur', 'werkstatt', 'ersatzteil', 'instandhaltung', 'wartung'],
        'professional_services': ['beratung', 'rechtsanwalt', 'steuerberater', 'notar', 'gutachten'],
        'insurance': ['versicherung', 'police', 'prämie', 'beitrag', 'schutz'],
        'taxes_fees': ['steuer', 'gebühr', 'abgabe', 'beitrag', 'amt', 'behörde']
    }
    
    @staticmethod
    def extract_company_name(text: str) -> Optional[str]:
        """Extract company name from receipt text."""
        lines = text.split('\n')
        for line in lines[:5]:
            line = line.strip()
            if line and not re.match(r'^\d', line) and len(line) > 3:
                skip_words = ['receipt', 'rechnung', 'kassenbon', 'beleg', 'quittung']
                if not any(word in line.lower() for word in skip_words):
                    return line
        return None
    
    @staticmethod
    def extract_date(text: str) -> Optional[datetime]:
        """Extract date from receipt text."""
        for pattern in DataExtractor.DATE_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    if len(match) == 3:
                        day, month, year = match
                        if len(year) == 2:  # YY format
                            year = int(year)
                            year = 2000 + year if year < 50 else 1900 + year
                        else:
                            year = int(year)
                        
                        month = month if month.isdigit() else month.lower()
                        if month.isdigit():
                            return datetime(year, int(month), int(day))
                        else:
                            # Handle month names (German)
                            month_map = {
                                'januar': 1, 'january': 1,
                                'februar': 2, 'february': 2,
                                'märz': 3, 'marz': 3, 'march': 3,
                                'april': 4,
                                'mai': 5, 'may': 5,
                                'juni': 6, 'june': 6,
                                'juli': 7, 'july': 7,
                                'august': 8,
                                'september': 9,
                                'oktober': 10, 'october': 10,
                                'november': 11,
                                'dezember': 12, 'december': 12
                            }
                            if month in month_map:
                                return datetime(year, month_map[month], int(day))
                except (ValueError, IndexError):
                    continue
        return None
    
    @staticmethod
    def extract_amounts(text: str) -> Dict[str, Optional[Decimal]]:
        """Extract monetary amounts from text."""
        amounts = []
        for pattern in DataExtractor.AMOUNT_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    amount_str = match.replace('.', '').replace(',', '.')
                    amount = Decimal(amount_str)
                    amounts.append(amount)
                except (InvalidOperation, ValueError):
                    continue
        
        total_amount = max(amounts) if amounts else None
        return {"total": total_amount, "amounts": amounts}
    
    @staticmethod
    def extract_vat_info(text: str) -> Dict[str, Optional[Decimal]]:
        """Extract VAT information from text."""
        for pattern in DataExtractor.VAT_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    vat_percentage = Decimal(match[0].replace(',', '.'))
                    vat_amount = Decimal(match[1].replace('.', '').replace(',', '.'))
                    return {
                        "vat_percentage": vat_percentage,
                        "vat_amount": vat_amount
                    }
                except (InvalidOperation, ValueError, IndexError):
                    continue
        return {"vat_percentage": None, "vat_amount": None}
    
    @staticmethod
    def extract_items(text: str) -> List[Dict[str, Any]]:
        """Extract individual items from receipt text."""
        items = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            for pattern in DataExtractor.ITEM_PATTERNS:
                match = re.match(pattern, line)
                if match:
                    groups = match.groups()
                    
                    if len(groups) == 2:  # Description and price
                        description = groups[0].strip()
                        price_str = groups[1].replace('.', '').replace(',', '.')
                        try:
                            price = Decimal(price_str)
                            category = DataExtractor._categorize_item(description)
                            items.append({
                                "description": description,
                                "quantity": None,
                                "unit_price": None,
                                "total_price": price,
                                "category": category,
                                "vat_rate": None
                            })
                        except (InvalidOperation, ValueError):
                            continue
                    
                    elif len(groups) == 3:  # Quantity, description, price
                        quantity_str = groups[0].replace(',', '.')
                        description = groups[1].strip()
                        price_str = groups[2].replace('.', '').replace(',', '.')
                        try:
                            quantity = Decimal(quantity_str)
                            price = Decimal(price_str)
                            unit_price = price / quantity if quantity > 0 else None
                            category = DataExtractor._categorize_item(description)
                            items.append({
                                "description": description,
                                "quantity": quantity,
                                "unit_price": unit_price,
                                "total_price": price,
                                "category": category,
                                "vat_rate": None
                            })
                        except (InvalidOperation, ValueError):
                            continue
                    
                    break
        
        return items
    
    @staticmethod
    def _categorize_item(description: str) -> str:
        """Categorize an item based on its description."""
        description_lower = description.lower()
        for category, keywords in DataExtractor.CATEGORY_KEYWORDS.items():
            if any(keyword in description_lower for keyword in keywords):
                return category
        return 'other'

def clean_json_response(response: str) -> str:
    """Clean and extract JSON from LLM response with robust error handling"""
    try:
        # Remove markdown code blocks
        response = re.sub(r'```(json)?\s*', '', response)
        response = re.sub(r'```\s*', '', response)
        
        # Fix common JSON issues
        response = response.strip()
        response = re.sub(r',\s*}', '}', response)  # Trailing commas
        response = re.sub(r',\s*]', ']', response)  # Trailing commas
        response = re.sub(r"(\w+)\s*:", r'"\1":', response)  # Unquoted keys
        
        # Find JSON object
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            # Validate JSON
            json.loads(json_match.group(0))  # Test parsing
            return json_match.group(0)
            
        return response
    except json.JSONDecodeError as e:
        logger.error(f"Failed to clean JSON: {e}")
        return '{}'  # Return empty object as fallback

def parse_decimal(value: Any) -> Optional[Decimal]:
    """Safely parse decimal value."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None

def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string to datetime object."""
    if not date_str:
        return None
    
    date_formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%d %B %Y",  # 12 January 2023
        "%d %b %Y"   # 12 Jan 2023
    ]
    
    for fmt in date_formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None