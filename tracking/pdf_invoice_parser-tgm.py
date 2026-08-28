import re
import logging
from decimal import Decimal
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import pdfplumber
from pypdf import PdfReader
from io import BytesIO

logger = logging.getLogger(__name__)

@dataclass
class InvoiceItem:
    """Represents a single item on an invoice"""
    description: str
    quantity: int = 1
    unit_cost: Decimal = Decimal('0.00')
    item_type: str = 'parts'  # 'parts', 'labor', 'other'

@dataclass 
class InvoiceData:
    """Represents parsed invoice data"""
    invoice_number: str
    date: datetime.date
    vehicle_rego: str = ''
    vehicle_vin: str = ''
    odometer_reading: int = 0
    service_provider: str = ''
    total_cost: Decimal = Decimal('0.00')
    items: List[InvoiceItem] = None
    
    def __post_init__(self):
        if self.items is None:
            self.items = []

class PDFInvoiceParser:
    """Helper class to parse PDF invoices and extract maintenance data"""
    
    def __init__(self):
        self.patterns = {
            'invoice_number': [
                r'tax\s+invoice\s+number:?\s*([A-Z0-9-]+)',
                r'invoice\s*#?:?\s*([A-Z0-9-]+)',
                r'inv\s*#?:?\s*([A-Z0-9-]+)', 
                r'number:?\s*([A-Z0-9-]+)',
                r'([A-Z][0-9]{4,6})'  # Pattern like A26919
            ],
            'date': [
                r'date\s*:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
                r'invoice\s+date:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
                r'(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})'
            ],
            'rego': [
                r'reg\s+no\.?:?\s*([A-Z]{1,3}\d{2,4}[A-Z]{0,3})',  # "Reg No: DTY19U"
                r'rego:?\s*([A-Z]{1,3}\d{2,4}[A-Z]{0,3})',  # NSW: ABC123, 123ABC, etc.
                r'registration:?\s*([A-Z]{1,3}\d{2,4}[A-Z]{0,3})',
                r'plate:?\s*([A-Z]{1,3}\d{2,4}[A-Z]{0,3})',
                r'vehicle:?\s*([A-Z]{1,3}\d{2,4}[A-Z]{0,3})',
                r'\b([A-Z]{2}\d{2}[A-Z]{2})\b',  # Pattern like CR65PK, DTY19U
                r'\b([A-Z]{3}\d{3})\b',  # Pattern like ABC123
                r'\b(\d{3}[A-Z]{3})\b'   # Pattern like 123ABC
            ],
            'vin': [
                r'vin:?\s*([A-Z0-9]{17})',
                r'chassis:?\s*([A-Z0-9]{17})',
                r'vehicle\s+identification:?\s*([A-Z0-9]{17})'
            ],
            'odometer': [
                r'(?:odometer|kms?|kilometres?|mileage):?\s*([0-9,]+)',
                r'([0-9]{4,7})\s*(?:km|kms|miles?)'
            ],
            'service_provider': [
                r'([A-Z][A-Z\s&]{10,50}(?:SERVICES?|MOTORS?|AUTOMOTIVE|GARAGE|WORKSHOP|STREERING))',
                r'ABN[:\s]*\d+[:\s]*([A-Z][A-Z\s&]{5,50})',
                r'^([A-Z][A-Z\s&]{8,50})$'  # Lines with all caps company names
            ],
            'total': [
                r'total:?\s*\$?([0-9,]+\.?\d{0,2})',
                r'balance\s+due:?\s*\$?([0-9,]+\.?\d{0,2})',
                r'amount\s+due:?\s*\$?([0-9,]+\.?\d{0,2})',
                r'grand\s+total:?\s*\$?([0-9,]+\.?\d{0,2})',
                r'subtotal:?\s*\$?([0-9,]+\.?\d{0,2})'
            ]
        }
        
    def parse_pdf(self, pdf_path: str) -> Optional[InvoiceData]:
        """
        Parse a PDF invoice and extract maintenance data
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            InvoiceData object with extracted data or None if parsing fails
        """
        try:
            # Try pdfplumber first (better for formatted text)
            invoice_data = self._parse_with_pdfplumber(pdf_path)
            if not invoice_data:
                # Fallback to PyPDF2
                invoice_data = self._parse_with_pypdf2(pdf_path)
                
            return invoice_data
            
        except Exception as e:
            logger.error(f"Error parsing PDF {pdf_path}: {str(e)}")
            return None
    
    def _parse_with_pdfplumber(self, pdf_path: str) -> Optional[InvoiceData]:
        """Parse PDF using pdfplumber library"""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                text = ""
                tables = []
                
                for page in pdf.pages:
                    text += page.extract_text() + "\n"
                    # Extract tables for itemized data
                    page_tables = page.extract_tables()
                    if page_tables:
                        tables.extend(page_tables)
                
                return self._extract_data_from_text(text, tables)
                
        except Exception as e:
            logger.warning(f"pdfplumber failed for {pdf_path}: {str(e)}")
            return None
    
    def _parse_with_pypdf2(self, pdf_path: str) -> Optional[InvoiceData]:
        """Parse PDF using PyPDF2 library as fallback"""
        try:
            with open(pdf_path, 'rb') as file:
                reader = PdfReader(file)
                text = ""
                
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                
                return self._extract_data_from_text(text)
                
        except Exception as e:
            logger.warning(f"PyPDF2 failed for {pdf_path}: {str(e)}")
            return None
    
    def _extract_data_from_text(self, text: str, tables: List = None) -> Optional[InvoiceData]:
        """Extract structured data from raw text"""
        original_text = text  # Keep original for table parsing
        text = text.lower()  # Normalize case for pattern matching
        
        try:
            # Extract basic invoice information
            invoice_data = InvoiceData(
                invoice_number=self._extract_pattern(text, 'invoice_number'),
                date=self._extract_date(text),
                vehicle_rego=self._extract_pattern(text, 'rego'),
                vehicle_vin=self._extract_pattern(text, 'vin') or '',  # Default to empty string
                odometer_reading=self._extract_odometer(text) or 0,  # Default to 0
                service_provider=self._extract_service_provider(text),
                total_cost=self._extract_total(text)
            )
            
            # If rego not found with text patterns, try table extraction
            if not invoice_data.vehicle_rego and tables:
                invoice_data.vehicle_rego = self._extract_rego_from_tables(tables)
            
            # Extract items from tables or text
            if tables:
                invoice_data.items = self._extract_items_from_tables(tables)
            
            # If no items found from tables, try text extraction as fallback
            if not invoice_data.items:
                invoice_data.items = self._extract_items_from_text(text)
            
            # Debug: log what we found
            logger.debug(f"Extracted {len(invoice_data.items)} items from invoice")
            for item in invoice_data.items:
                logger.debug(f"Item: {item.description} - ${item.unit_cost}")
            
            # Validate required fields
            if not invoice_data.invoice_number:
                logger.warning("Could not extract invoice number")
                return None
                
            return invoice_data
            
        except Exception as e:
            logger.error(f"Error extracting data: {str(e)}")
            return None
    
    def _extract_pattern(self, text: str, pattern_type: str) -> str:
        """Extract data using regex patterns"""
        patterns = self.patterns.get(pattern_type, [])
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result = match.group(1).strip().upper()
                
                # Special validation for rego to avoid common false positives
                if pattern_type == 'rego':
                    if self._is_valid_rego(result):
                        return result
                else:
                    return result
        
        return ""
    
    def _is_valid_rego(self, rego: str) -> bool:
        """Validate if a string looks like a genuine vehicle registration"""
        if not rego or len(rego) < 4 or len(rego) > 8:
            return False
            
        # Exclude common false positives
        invalid_words = [
            'ALL', 'LIGHT', 'LIGHTS', 'GLOBES', 'GLOBE', 'BULB', 'BULBS',
            'OIL', 'FILTER', 'LABOUR', 'LABOR', 'SERVICE', 'TOTAL', 'COST',
            'ITEM', 'PRICE', 'AMOUNT', 'DATE', 'TIME', 'HOUR', 'HOURS',
            'PART', 'PARTS', 'WORK', 'REPAIR', 'FIX', 'CHANGE', 'REPLACE'
        ]
        
        if rego in invalid_words:
            return False
            
        # Must contain at least one digit and one letter
        has_digit = any(c.isdigit() for c in rego)
        has_letter = any(c.isalpha() for c in rego)
        
        if not (has_digit and has_letter):
            return False
            
        # Australian rego patterns: must match common formats
        aus_patterns = [
            r'^[A-Z]{2,3}\d{2,4}$',      # AB12, ABC123, etc.
            r'^\d{3}[A-Z]{2,3}$',        # 123AB, 123ABC
            r'^[A-Z]{1,2}\d{2,3}[A-Z]{1,2}$',  # A12B, AB12CD
            r'^[A-Z]{3}\d{2}[A-Z]$'      # ESY89C, DTY19U format (3 letters + 2 digits + 1 letter)
        ]
        
        return any(re.match(pattern, rego) for pattern in aus_patterns)
    
    def _extract_date(self, text: str) -> Optional[datetime.date]:
        """Extract and parse date from text"""
        for pattern in self.patterns['date']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                # Try different date formats
                for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%d/%m/%y']:
                    try:
                        return datetime.strptime(date_str, fmt).date()
                    except ValueError:
                        continue
        return None
    
    def _extract_service_provider(self, text: str) -> str:
        """Extract service provider name from text"""
        lines = text.split('\n')
        
        # Exclusion patterns - companies to ignore (client names, not service providers)
        exclusion_patterns = [
            r'koinonia\s+enterprises?',
            r'koinonia.*pty.*ltd',
            r'pty.*ltd.*koinonia',
        ]
        
        # First try pattern-based extraction
        for pattern in self.patterns.get('service_provider', []):
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                provider = match.group(1).strip()
                
                # Check against exclusion patterns
                is_excluded = any(re.search(excl_pattern, provider, re.IGNORECASE) 
                                for excl_pattern in exclusion_patterns)
                if is_excluded:
                    continue
                    
                # Clean up the provider name
                provider = re.sub(r'\s+', ' ', provider)  # Remove extra spaces
                if len(provider) > 5:  # Must be reasonably long
                    return provider
        
        # Fallback: look for lines with all caps that might be company names
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Check against exclusion patterns first
            is_excluded = any(re.search(excl_pattern, line, re.IGNORECASE) 
                            for excl_pattern in exclusion_patterns)
            if is_excluded:
                continue
                
            # Look for lines that are mostly uppercase and contain business-like words
            if (line.isupper() and 
                len(line) > 10 and 
                any(word in line.upper() for word in ['SERVICES', 'SERVICE', 'MOTORS', 'MOTOR', 'AUTOMOTIVE', 'GARAGE', 'WORKSHOP', 'PTY', 'LTD', 'STEERING']) and
                not any(skip in line.upper() for skip in ['TAX INVOICE', 'INVOICE NUMBER', 'PAYMENT', 'SUBTOTAL', 'TOTAL'])):
                return line
        
        # Another fallback: look for the first substantial line that's not a header
        skip_patterns = ['tax invoice', 'invoice number', 'date', 'po number', 'payment term']
        for line in lines:
            line = line.strip()
            if (len(line) > 8 and 
                not any(skip in line.lower() for skip in skip_patterns) and
                not re.match(r'^[\d\s\$\.,:-]+$', line) and  # Not just numbers/symbols
                any(c.isalpha() for c in line)):  # Contains letters
                
                # Check against exclusion patterns
                is_excluded = any(re.search(excl_pattern, line, re.IGNORECASE) 
                                for excl_pattern in exclusion_patterns)
                if is_excluded:
                    continue
                    
                # Check if it looks like a business name
                if any(word in line.upper() for word in ['SERVICES', 'MOTORS', 'AUTOMOTIVE', 'GARAGE', 'WORKSHOP', 'PTY', 'LTD']):
                    return line.upper()
        
        return ''
    
    def _extract_rego_from_tables(self, tables: List) -> str:
        """Extract vehicle registration from table structure"""
        for table in tables:
            if not table:
                continue
                
            # Look for table headers that contain registration info
            for row_idx, row in enumerate(table):
                if not row:
                    continue
                    
                # Check if this row contains registration headers
                for cell_idx, cell in enumerate(row):
                    if not cell:
                        continue
                        
                    cell_text = str(cell).strip()
                    
                    # Look for registration column headers
                    if re.search(r'reg\s*no\.?|registration|rego', cell_text, re.IGNORECASE):
                        # Found a registration column header
                        # Look for the corresponding value in subsequent rows
                        for data_row_idx in range(row_idx + 1, len(table)):
                            if data_row_idx < len(table) and cell_idx < len(table[data_row_idx]):
                                data_cell = table[data_row_idx][cell_idx]
                                if data_cell:
                                    rego_candidate = str(data_cell).strip()
                                    # Clean up newlines and extra text
                                    rego_candidate = re.sub(r'\n.*', '', rego_candidate)
                                    rego_candidate = rego_candidate.strip().upper()
                                    
                                    if self._is_valid_rego(rego_candidate):
                                        return rego_candidate
                    
                    # Also check if cell contains registration pattern with value
                    # Format like "Reg No.\nDI91YP"
                    if '\n' in cell_text:
                        lines = cell_text.split('\n')
                        if len(lines) >= 2:
                            header = lines[0].strip()
                            value = lines[1].strip().upper()
                            
                            if (re.search(r'reg\s*no\.?|registration|rego', header, re.IGNORECASE) and 
                                self._is_valid_rego(value)):
                                return value
        
        return ''
    
    def _extract_odometer(self, text: str) -> int:
        """Extract odometer reading"""
        for pattern in self.patterns['odometer']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1).replace(',', ''))
                except ValueError:
                    continue
        return 0
    
    def _extract_total(self, text: str) -> Decimal:
        """Extract total cost with enhanced pattern matching"""
        # First try to find the main total (Balance Due, Total, etc.)
        main_total_patterns = [
            r'balance\s+due:?\s*\$?([0-9,]+\.?\d{0,2})',
            r'total:?\s*\$?([0-9,]+\.?\d{0,2})',
            r'amount\s+due:?\s*\$?([0-9,]+\.?\d{0,2})',
            r'grand\s+total:?\s*\$?([0-9,]+\.?\d{0,2})'
        ]
        
        for pattern in main_total_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Get the last/largest value (often the final total)
                try:
                    values = [Decimal(match.replace(',', '')) for match in matches]
                    return max(values)  # Return the largest value found
                except (ValueError, TypeError):
                    continue
        
        # Fallback to subtotal if no main total found
        subtotal_patterns = [
            r'subtotal:?\s*\$?([0-9,]+\.?\d{0,2})'
        ]
        
        for pattern in subtotal_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return Decimal(match.group(1).replace(',', ''))
                except (ValueError, TypeError):
                    continue
        
        return Decimal('0.00')
    
    def _extract_items_from_tables(self, tables: List) -> List[InvoiceItem]:
        """Extract items from PDF tables"""
        items = []
        
        for table in tables:
            if not table:
                continue
                
            # First try standard table format (properly separated columns)
            items_found = self._extract_from_structured_table(table)
            if items_found:
                items.extend(items_found)
                continue
            
            # Fallback: try to extract from single-column table format
            items_found = self._extract_from_single_column_table(table)
            if items_found:
                items.extend(items_found)
        
        return items
    
    def _extract_from_structured_table(self, table: List) -> List[InvoiceItem]:
        """Extract items from properly structured table with separate columns"""
        items = []
        
        if not table or len(table) < 2:
            return items
            
        headers = [str(cell).lower() if cell else '' for cell in table[0]]
        
        # Find column indices - be more flexible with column names
        desc_col = self._find_column_index(headers, ['description', 'item', 'service', 'details', 'labour', 'labor'])
        qty_col = self._find_column_index(headers, ['qty', 'quantity', 'units'])
        cost_col = self._find_column_index(headers, ['cost', 'price', 'amount', 'total', 'unit price'])
        
        # If no headers found, assume standard automotive invoice layout
        # Typically: Description (col 0), Quantity (col 1), Unit Price (col 2), Total (col 3)
        if desc_col == -1 and len(table) > 0 and len(table[0]) >= 2:
            desc_col = 0
            if len(table[0]) >= 3:
                qty_col = 1
                if len(table[0]) >= 4:
                    cost_col = 2  # Unit price
                    total_col = 3  # Total price
                else:
                    cost_col = 2  # Total price
                    total_col = -1
            else:
                qty_col = -1
                cost_col = 1  # Just description and price
        
        # If we don't have proper column structure, return empty (let fallback handle it)
        if desc_col == -1 or len(table[0]) < 2:
            return items
        
        # Process data rows
        for row_idx, row in enumerate(table[1:], 1):
            if not row or not any(row):
                continue
                
            try:
                description = str(row[desc_col]).strip() if desc_col >= 0 and desc_col < len(row) else ''
                
                # Skip if description is empty or contains unwanted text
                if not description or len(description) < 2:
                    continue
                    
                # Skip summary rows and headers
                skip_terms = ['subtotal', 'gst', 'tax', 'total', 'paid', 'balance', 'due', 'service b']
                if any(term in description.lower() for term in skip_terms):
                    continue
                
                # Skip if description is just a service header without actual item
                if (len(description.split()) > 10 and '.' in description and 
                    not any(char.isdigit() for char in ' '.join(str(cell) for cell in row if cell))):
                    continue
                
                quantity = 1
                unit_cost = Decimal('0.00')
                total_cost = Decimal('0.00')
                
                # Extract quantity
                if qty_col >= 0 and qty_col < len(row) and row[qty_col]:
                    try:
                        qty_str = str(row[qty_col]).replace(',', '').strip()
                        if qty_str and qty_str.replace('.', '').isdigit():
                            quantity = int(float(qty_str))
                    except (ValueError, TypeError):
                        quantity = 1
                
                # Extract costs from multiple columns if available
                cost_found = False
                for col_idx in range(len(row)):
                    if col_idx == desc_col:  # Skip description column
                        continue
                        
                    cell_value = str(row[col_idx]).strip()
                    if not cell_value:
                        continue
                        
                    # Try to parse as currency
                    clean_value = cell_value.replace('$', '').replace(',', '').strip()
                    if clean_value and (clean_value.replace('.', '').isdigit()):
                        try:
                            cost_value = Decimal(clean_value)
                            if cost_value > 0:
                                if col_idx == len(row) - 1:  # Last column is typically total
                                    total_cost = cost_value
                                    cost_found = True
                                elif col_idx == cost_col or (not cost_found and col_idx > qty_col):
                                    unit_cost = cost_value
                                    cost_found = True
                        except (ValueError, TypeError):
                            continue
                
                # Calculate missing cost values
                if total_cost > 0 and unit_cost == 0 and quantity > 0:
                    unit_cost = total_cost / quantity
                elif unit_cost > 0 and total_cost == 0:
                    total_cost = unit_cost * quantity
                
                # Use the most appropriate cost
                final_cost = unit_cost if unit_cost > 0 else total_cost
                
                if final_cost > 0 and description:
                    # Determine item type
                    labor_keywords = ['labour', 'labor', 'service', 'install', 'check', 'adjust', 
                                    'inspect', 'test', 'reset', 'road test', 'visually inspect']
                    item_type = 'labor' if any(word in description.lower() for word in labor_keywords) else 'parts'
                    
                    items.append(InvoiceItem(
                        description=description,
                        quantity=max(1, quantity),
                        unit_cost=final_cost,
                        item_type=item_type
                    ))
                
            except Exception as e:
                logger.warning(f"Error parsing table row {row_idx}: {str(e)}")
                continue
        
        return items
    
    def _extract_from_single_column_table(self, table: List) -> List[InvoiceItem]:
        """Extract items from single-column table format where data is all in one cell"""
        items = []
        
        for row in table:
            if not row or not any(row):
                continue
                
            # Process each cell in the row
            for cell in row:
                if not cell:
                    continue
                    
                cell_text = str(cell).strip()
                
                # Skip obvious header rows and summary rows
                skip_terms = ['description', 'qty', 'unit price', 'amount', 'subtotal', 'gst', 'tax', 'total', 'paid', 'balance', 'due']
                if any(term in cell_text.lower() for term in skip_terms) and len(cell_text.split()) <= 5:
                    continue
                
                # Skip section headers (single words or short phrases without numbers)
                if len(cell_text.split()) <= 2 and not any(char.isdigit() for char in cell_text):
                    continue
                
                # Look for patterns that indicate this is an item line
                # Pattern: "Description quantity $price $total" or similar
                import re
                patterns = [
                    # Pattern: Description with quantity and costs
                    r'^(.+?)\s+([0-9.]+)\s+\$([0-9,]+\.?\d{2})\s+\$([0-9,]+\.?\d{2})\s*$',
                    # Pattern: Description with just one cost
                    r'^(.+?)\s+\$([0-9,]+\.?\d{2})\s*$',
                    # Pattern: Description with quantity and one cost
                    r'^(.+?)\s+([0-9.]+)\s+\$([0-9,]+\.?\d{2})\s*$'
                ]
                
                for pattern in patterns:
                    match = re.match(pattern, cell_text.strip())
                    if match:
                        groups = match.groups()
                        
                        description = groups[0].strip()
                        
                        # Skip if description is too short or contains unwanted content
                        if len(description) < 3:
                            continue
                            
                        if len(groups) == 4:  # Description, qty, unit_price, total
                            quantity = float(groups[1]) if groups[1] else 1
                            unit_cost = Decimal(groups[2].replace(',', ''))
                            total_cost = Decimal(groups[3].replace(',', ''))
                        elif len(groups) == 3:  # Description, qty, cost OR Description, unit_price, total
                            if '.' in groups[1] and float(groups[1]) < 10:  # Likely quantity
                                quantity = float(groups[1])
                                unit_cost = Decimal(groups[2].replace(',', ''))
                                total_cost = unit_cost * Decimal(str(quantity))
                            else:  # Likely two costs
                                quantity = 1
                                unit_cost = Decimal(groups[1].replace(',', ''))
                                total_cost = Decimal(groups[2].replace(',', ''))
                        else:  # Description, cost
                            quantity = 1
                            unit_cost = Decimal(groups[1].replace(',', ''))
                            total_cost = unit_cost
                        
                        # Determine item type
                        labor_keywords = ['labour', 'labor', 'service', 'install', 'check', 'adjust', 
                                        'inspect', 'test', 'reset', 'road test', 'visually inspect', 'inspection']
                        item_type = 'labor' if any(word in description.lower() for word in labor_keywords) else 'parts'
                        
                        items.append(InvoiceItem(
                            description=description,
                            quantity=max(1, int(quantity)),
                            unit_cost=unit_cost,
                            item_type=item_type
                        ))
                        break  # Found a match, move to next cell
        
        return items
    
    def _extract_items_from_text(self, text: str) -> List[InvoiceItem]:
        """Extract items from raw text when no tables are available"""
        items = []
        
        # Look for common patterns in service invoices
        patterns = [
            # Pattern: Description followed by quantity, unit price, and total (like the invoice table)
            r'^([a-zA-Z][a-zA-Z\s&.,()]{2,50}?)\s+([0-9.]+)\s+\$([0-9,]+\.?\d{2})\s+\$([0-9,]+\.?\d{2})\s*$',
            # Pattern: Description with quantity and total only
            r'^([a-zA-Z][a-zA-Z\s&.,()]{2,50}?)\s+([0-9.]+)\s+\$([0-9,]+\.?\d{2})\s*$', 
            # Pattern: Description followed by cost at end
            r'^([a-zA-Z][a-zA-Z\s&.,()]{3,50}?)\s+\$([0-9,]+\.?\d{2})\s*$',
            # Pattern: Any description followed by numbers (fallback)
            r'([a-zA-Z][a-zA-Z\s&.,()]{5,50}?)\s+([0-9.]+)\s*([0-9,]+\.?\d{2})\s*([0-9,]+\.?\d{2})',
        ]
        
        # Split text into lines for better parsing
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue
                
            # Skip total/summary lines and headers
            skip_keywords = ['subtotal', 'gst', 'total', 'paid', 'balance', 'due', 'service b', 'change oil', 'reset service']
            if any(keyword in line.lower() for keyword in skip_keywords):
                # Special case: if line starts with service description, try to parse it
                if not line.lower().startswith(('subtotal', 'gst', 'total', 'paid', 'balance')):
                    pass  # Continue to parsing
                else:
                    continue
            
            # Skip lines that are just service descriptions without prices
            if re.match(r'^[a-zA-Z\s.,&()]+\.\s*$', line) and '$' not in line:
                continue
            
            parsed = False
            
            # Try patterns in order of specificity
            for i, pattern in enumerate(patterns):
                match = re.match(pattern, line, re.IGNORECASE)
                if match:
                    try:
                        groups = match.groups()
                        description = groups[0].strip()
                        
                        # Skip if description is too short or looks like header
                        if len(description) < 3 or description.lower() in ['qty', 'unit', 'total']:
                            continue
                        
                        if i == 0:  # Full pattern: desc, qty, unit_price, total
                            quantity = int(float(groups[1]))
                            unit_cost = Decimal(groups[2].replace(',', ''))
                            total_cost = Decimal(groups[3].replace(',', ''))
                        elif i == 1:  # desc, qty, total
                            quantity = int(float(groups[1]))
                            total_cost = Decimal(groups[2].replace(',', ''))
                            unit_cost = total_cost / quantity if quantity > 0 else total_cost
                        elif i == 2:  # desc, total
                            quantity = 1
                            total_cost = Decimal(groups[1].replace(',', ''))
                            unit_cost = total_cost
                        else:  # fallback pattern
                            quantity = int(float(groups[1])) if groups[1] else 1
                            unit_cost = Decimal(groups[2].replace(',', '')) if len(groups) > 2 else Decimal('0')
                            total_cost = Decimal(groups[3].replace(',', '')) if len(groups) > 3 else unit_cost * quantity
                        
                        # Validate costs
                        if unit_cost <= 0 and total_cost <= 0:
                            continue
                        
                        # Use the appropriate cost
                        final_unit_cost = unit_cost if unit_cost > 0 else (total_cost / quantity if quantity > 0 else total_cost)
                        
                        # Determine item type
                        labor_keywords = ['labour', 'labor', 'service', 'install', 'check', 'adjust', 'inspect', 'test', 'reset', 'road test', 'visually inspect']
                        item_type = 'labor' if any(word in description.lower() for word in labor_keywords) else 'parts'
                        
                        items.append(InvoiceItem(
                            description=description,
                            quantity=quantity,
                            unit_cost=final_unit_cost,
                            item_type=item_type
                        ))
                        
                        parsed = True
                        break
                        
                    except (ValueError, TypeError, IndexError) as e:
                        logger.debug(f"Error parsing line '{line}' with pattern {i}: {str(e)}")
                        continue
        
        return items
    
    def _find_column_index(self, headers: List[str], possible_names: List[str]) -> int:
        """Find column index by matching header names"""
        for i, header in enumerate(headers):
            for name in possible_names:
                if name in header.lower():
                    return i
        return -1

# Example usage functions for Django integration
def parse_pdf_invoice(pdf_path: str) -> Optional[InvoiceData]:
    """
    Convenience function to parse a PDF invoice
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        InvoiceData or None if parsing fails
    """
    parser = PDFInvoiceParser()
    return parser.parse_pdf(pdf_path)

def validate_invoice_data(invoice_data: InvoiceData) -> List[str]:
    """
    Validate extracted invoice data
    
    Args:
        invoice_data: InvoiceData object
        
    Returns:
        List of validation error messages
    """
    errors = []
    
    if not invoice_data.invoice_number:
        errors.append("Invoice number is required")
    
    if not invoice_data.date:
        errors.append("Invoice date is required")
    
    if invoice_data.total_cost <= 0:
        errors.append("Total cost must be greater than 0")
    
    if not invoice_data.items:
        errors.append("At least one invoice item is required")
    
    return errors
