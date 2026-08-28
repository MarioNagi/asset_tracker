import re
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pdfplumber
from pypdf import PdfReader
from io import BytesIO

from .invoice_parsers import InvoiceData, InvoiceItem, parse_known_invoice

logger = logging.getLogger(__name__)

class PDFInvoiceParser:
    """Helper class to parse PDF invoices and extract maintenance data"""
    
    def __init__(self):
        self.patterns = {
            'invoice_number': [
                r'invoice\s+no\.\s*([A-Z0-9-]+)',               # "Invoice No. S0031"
                # New format patterns for numbered invoices  
                r'invoice\s*#\s*(\d+)',                          # "Invoice # 204"
                r'bill\s+to\s+invoice\s*#\s*(\d+)',             # "Bill To Invoice # 204"
                # Original patterns for A-format invoices
                r'tax\s+invoice\s+number:?\s*([A-Z0-9-]+)',
                r'invoice\s*#?:?\s*([A-Z0-9-]+)',
                r'inv\s*#?:?\s*([A-Z0-9-]+)', 
                r'number:?\s*([A-Z0-9-]+)',
                r'([A-Z][0-9]{4,6})'  # Pattern like A26919
            ],
            'date': [
                r'date:\s*(\d{1,2}/\d{1,2}/\d{4})',            # "Date: 08/10/2025"
                # Enhanced patterns for different date formats in various invoice styles
                r'koinonia enterprises.*?(\d{1,2}/\d{1,2}/\d{4})',  # "koinonia enterprises pty ltd 30/08/2025"
                r'date\s*:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
                r'invoice\s+date:?\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
                # MVR format: "Invoice Date\n<estimate#> <date>" - allow digits/whitespace between label and date
                r'invoice\s+date[:\s\d]*?(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
                r'(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})',
                r'ISSUED\s+[:\s]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
                # Add pattern for 2-digit years (convert to 4-digit)
                r'(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2})(?!\d)'  # Match 2-digit year but not if followed by more digits
            ],
            'rego': [
                # High priority patterns - look for explicit rego/registration labels
                r'rego\.?\s*([A-Z0-9\s]{3,8})',                 # "Rego. 1GZ 6OP" 
                r'registration\s+no\.?\s*([A-Z0-9\s]{3,8})',
                r'registration\s+No\.?\s*([A-Z0-9\s]{3,8})',    # "Registration No. 2BF 1TV"
                r'reg\s+no\.?\s*([A-Z0-9\s]{3,8})',             # "Reg No: DTY19U"
                r'registration:?\s*([A-Z0-9\s]{3,8})',
                r'plate:?\s*([A-Z0-9\s]{3,8})',
                r'(?i)\b(?:1IEI177|CY02JR|1YX1XD|CP38VU|1ZR7EC|DI91YP|BZ60RY|DH24PO|CT85GN|CJ42AH|1LW8OK|YXD845|1IDG306|1HEI701|1HDC949|2BS7YE|1GZ6OP|1NI3GR|CD87LK|2BF1TV|1WL8YT|CP34VT|DH24RW|CS31DC|DI90ZM|CX31BM|CR65PK|DTY19U|1GHT436|CK55DY|ESY89C|DPJ35U|XK0547)\b',
                
                # Medium priority - patterns with more specific context
                r'(?:vehicle|car)\s+reg(?:istration)?:?\s*([A-Z0-9\s]{3,8})',
                
                # Lower priority - standalone patterns (more prone to false matches)
                r'\b([A-Z]{2}\d{2}[A-Z]{2})\b',                 # Pattern like CR65PK, DTY19U, CJ42AH - move this higher priority
                r'\b([A-Z]{1,3}\s*\d{2,4}\s*[A-Z]{0,3})\b',    # Pattern like "2BF 1TV" or "1GZ 6OP"
                r'\b([A-Z]{3}\d{3})\b',                         # Pattern like ABC123
                r'\b(\d{3}[A-Z]{3})\b',                         # Pattern like 123ABC
                r'\b([A-Z]\d{3}[A-Z]{3})\b',                    # Pattern like 1HDC949 (1 letter + 3 digits + 3 letters)
                r'\b(\d[A-Z]{2,3}\d{3})\b'                      # Pattern like 1HDC949 (1 digit + letters + digits)
            ],
            'vin': [
                r'vin:?\s*([A-Z0-9]{17})',
                r'chassis:?\s*([A-Z0-9]{17})',
                r'vehicle\s+identification:?\s*([A-Z0-9]{17})'
            ],
            'odometer': [
                r'serviced\s+at:\s*([0-9,]+)\s*km',            # "Serviced At: 242186 Km"
                r'odometer\s*:?\s*([0-9,]+)',                   # "ODOMETER: 293408"
                r'ODOMETER\s*[:\s]*([0-9,]+)',                  # "ODOMETER 293408"
                # New pattern for this invoice format: look for numbers on the vehicle line
                r'volkswagen\s+([0-9,]{5,7})',                 # "VOLKSWAGEN 293408"
                r'(?:kms?|kilometres?|mileage):?\s*([0-9,]+)',
                r'([0-9]{4,7})\s*(?:km|kms|miles?)'
            ],
            'service_provider': [
                r'([A-Z][a-z]+\s+[A-Z][a-z]+\s+Pty\s+Ltd)',    # "Milestone Tyres Pty Ltd"
                # Enhanced patterns for Bridgestone and other service providers
                r'(?i)(Bridgestone\s+Select\s+Tyre\s+&\s+Auto\s+[A-Z][a-z]+)',  # "Bridgestone Select Tyre & Auto Revesby"
                r'(?i)([A-Z][a-z]+\s+Select\s+Tyre\s+&\s+Auto\s+[A-Z][a-z]+)',  # Generic "Select Tyre & Auto" pattern
                r'([A-Z][A-Z\s&]{10,50}(?:SERVICES?|MOTORS?|AUTOMOTIVE|GARAGE|WORKSHOP|TYRES?|TYRE|STEERING))',
                r'ABN[:\s]*\d+[:\s]*([A-Z][A-Z\s&]{5,50})',
                r'^([A-Z][A-Z\s&]{8,50})$'  # Lines with all caps company names
            ],
            'total': [
                r'total\s*\(inc\s+gst\)\s*\$([0-9,]+\.?\d{0,2})',  # "TOTAL (INC GST) $263.00"
                r'total\s+payable\s+including\s+gst\s*\$?\s*([0-9,]+\.?\d{0,2})',  # MVR: "Total Payable Including GST $ 727.10"
                r'\btotal:?\s*\$?([0-9,]+\.?\d{0,2})',
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
                
                invoice_data = self._extract_data_from_text(text, tables)
                return self._add_preview_metadata(invoice_data, text)
                
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
                
                invoice_data = self._extract_data_from_text(text)
                return self._add_preview_metadata(invoice_data, text)
                
        except Exception as e:
            logger.warning(f"PyPDF2 failed for {pdf_path}: {str(e)}")
            return None
    
    def _extract_data_from_text(self, text: str, tables: List = None) -> Optional[InvoiceData]:
        """Extract structured data from raw text"""
        original_text = text  # Keep original for table parsing
        text = text.lower()  # Normalize case for pattern matching

        known_invoice = parse_known_invoice(original_text)
        if known_invoice:
            return known_invoice

        # Vendor-specific fast paths for Bayside Access and FluidKraft.
        # These vendors have unusual layouts (concatenated words / single-column
        # description+amount tables) that the generic parsers don't handle, and
        # both are tied to a single fixed asset.
        if 'baysideaccess' in text or 'bayside access' in text:
            bayside = self._parse_bayside_invoice(original_text)
            if bayside:
                return bayside
        if 'fluidkraft' in text:
            fluidkraft = self._parse_fluidkraft_invoice(original_text)
            if fluidkraft:
                return fluidkraft
        if 'anz auto parts' in text or 'anzautoparts' in text:
            anz = self._parse_anz_auto_parts_invoice(original_text)
            if anz:
                return anz
        if 'city discount tyres' in text or 'citydiscounttyres' in text:
            cdt = self._parse_city_discount_tyres_invoice(original_text)
            if cdt:
                return cdt
        if 'southern auto repairs' in text:
            sar = self._parse_southern_auto_repairs_invoice(original_text)
            if sar:
                return sar
        if 't & j trailers' in text or 'tjtrailers' in text:
            tj = self._parse_tj_trailers_invoice(original_text)
            if tj:
                return tj
        if 'carlton towbars' in text or 'carlton 4x4' in text or 'carltontowbars' in text:
            carlton = self._parse_carlton_invoice(original_text)
            if carlton:
                return carlton
        if 'gearbox solutions' in text:
            gb = self._parse_gearbox_solutions_invoice(original_text)
            if gb:
                return gb
        if 'two raptors' in text or 'pirtek' in text:
            tr = self._parse_two_raptors_invoice(original_text)
            if tr:
                return tr
        if 'tdr mechanical' in text:
            tdr = self._parse_tdr_mechanical_invoice(original_text)
            if tdr:
                return tdr
        if 'wagga city auto' in text:
            wagga = self._parse_wagga_city_auto_invoice(original_text)
            if wagga:
                return wagga
        if 'tamworth car carrying' in text:
            tcc = self._parse_tamworth_car_carrying_invoice(original_text)
            if tcc:
                return tcc
        if 'tamworth automotive services' in text:
            tas = self._parse_tamworth_automotive_invoice(original_text)
            if tas:
                return tas
        if 'centreline smash' in text:
            cl = self._parse_centreline_smash_invoice(original_text)
            if cl:
                return cl
        if "davids auto repairs" in text or "david's auto repairs" in text:
            davids = self._parse_davids_auto_invoice(original_text)
            if davids:
                return davids
        if 'brar mechanical' in text:
            brar = self._parse_brar_mechanical_invoice(original_text)
            if brar:
                return brar
        if 'jd windscreen' in text or 'truevaluewindscreens' in text or 'true value windscreens' in text:
            jd = self._parse_jd_windscreen_invoice(original_text)
            if jd:
                return jd
        if 'imax group' in text:
            imax = self._parse_imax_group_invoice(original_text)
            if imax:
                return imax
        if 'access services group' in text or 'accessservices.net' in text or 'accessgroup.net.au' in text:
            ag = self._parse_access_group_invoice(original_text)
            if ag:
                return ag

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
    
    def _parse_bayside_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Bayside Access invoices are always for the Genie ZX135 (rego stored as
        'zx-135 13-2243'). Their PDF text strips spaces between words, so the
        generic patterns can't pick up rego or items reliably.
        """
        invoice_match = re.search(r'(INV-\d+)', text, re.IGNORECASE)
        if not invoice_match:
            return None

        invoice_number = invoice_match.group(1).upper()

        date_obj = None
        date_match = re.search(r'(\d{1,2})\s*([A-Za-z]{3,9})\s*(\d{4})', text)
        if date_match:
            for fmt in ('%d %b %Y', '%d %B %Y'):
                try:
                    date_obj = datetime.strptime(
                        f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)}",
                        fmt,
                    ).date()
                    break
                except ValueError:
                    continue
        if not date_obj:
            date_obj = self._extract_date(text.lower())

        total_cost = Decimal('0.00')
        total_match = re.search(r'TOTAL\s*AUD\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # Item rows look like: "Callout 1.00 140.00 10% 140.00"
        item_re = re.compile(
            r'^(.+?)\s+(\d+\.\d{2})\s+([0-9,]+\.\d{2})\s+\d+%\s+([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['labour', 'labor', 'callout', 'service', 'inspection',
                          'test', 'testandtag']
        for raw in text.split('\n'):
            line = raw.strip()
            m = item_re.match(line)
            if not m:
                continue
            description = m.group(1).strip()
            try:
                quantity = int(float(m.group(2))) or 1
                unit_cost = Decimal(m.group(3).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=max(1, quantity),
                unit_cost=unit_cost,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego='zx-135 13-2243',
            vehicle_vin='',
            odometer_reading=0,
            service_provider='Bayside Access Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _parse_fluidkraft_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        FluidKraft invoices are always for the Isuzu NLR45 (rego DH24PO).
        Layout is a single Description column with the line-item amount on the
        next line and a Subtotal/Invoice Total block at the bottom.
        """
        # Invoice number sits a couple of lines below the "Invoice Number"
        # header, and the same line also contains "Invoice To:" / email text.
        invoice_number = ''
        header_match = re.search(r'Invoice\s*Number', text, re.IGNORECASE)
        if header_match:
            tail = text[header_match.end():header_match.end() + 200]
            num_match = re.search(r'\b(\d{4,6})\b', tail)
            if num_match:
                invoice_number = num_match.group(1)
        if not invoice_number:
            num_match = re.search(r'\b(\d{4,6})\b', text)
            if num_match:
                invoice_number = num_match.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Invoice\s*Date\s*\n?\s*(\d{1,2}/\d{1,2}/\d{2,4})', text, re.IGNORECASE)
        if not date_match:
            date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2,4})', text)
        if date_match:
            for fmt in ('%d/%m/%Y', '%d/%m/%y'):
                try:
                    date_obj = datetime.strptime(date_match.group(1), fmt).date()
                    break
                except ValueError:
                    continue

        total_cost = Decimal('0.00')
        total_match = re.search(r'Invoice\s*Total\s*[:\-]?\s*\$?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        # Item description lives between "Description Amount" header and the
        # "Description of works completed" block / Subtotal. Amount is on the
        # line above (or same line) as the description and prefixed with $.
        items: List[InvoiceItem] = []
        lines = [ln.strip() for ln in text.split('\n')]
        in_section = False
        pending_amount: Optional[Decimal] = None
        for line in lines:
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if 'description' in lower and 'amount' in lower:
                    in_section = True
                continue
            if lower.startswith('description of works'):
                continue
            if (lower.startswith('subtotal') or lower.startswith('credit card surcharge')
                    or lower.startswith('total gst') or lower.startswith('invoice total')
                    or lower.startswith('hydraulic cylinder warranty')):
                break

            amt_only = re.match(r'^\$?\s*([0-9,]+\.\d{2})\s*$', line)
            if amt_only:
                try:
                    pending_amount = Decimal(amt_only.group(1).replace(',', ''))
                except (InvalidOperation, ValueError):
                    pending_amount = None
                continue

            if pending_amount is not None and re.search(r'[A-Za-z]', line):
                items.append(InvoiceItem(
                    description=line,
                    quantity=1,
                    unit_cost=pending_amount,
                    item_type='labor',
                ))
                pending_amount = None

        if not items and total_cost > 0:
            items.append(InvoiceItem(
                description='FluidKraft hydraulic service',
                quantity=1,
                unit_cost=total_cost,
                item_type='labor',
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego='DH24PO',
            vehicle_vin='',
            odometer_reading=0,
            service_provider='FluidKraft Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _parse_anz_auto_parts_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        ANZ Auto Parts invoices use US date format (MM/DD/YY), put the invoice
        number on its own line under "Customer ID ABN ..", and place item rows
        as "<description> <unit_price> <total>" with the description sometimes
        wrapping over multiple lines.
        """
        lines = [ln.rstrip() for ln in text.split('\n')]

        invoice_number = ''
        for idx, line in enumerate(lines):
            if 'customer id' in line.lower() and 'abn' in line.lower():
                for j in range(idx + 1, min(idx + 4, len(lines))):
                    candidate = lines[j].strip()
                    m = re.match(r'^(\d{4,8})$', candidate)
                    if m:
                        invoice_number = m.group(1)
                        break
                if invoice_number:
                    break
        if not invoice_number:
            m = re.search(r'invoice\s*no\.?\s*\n?\s*(\d{4,8})', text, re.IGNORECASE)
            if m:
                invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b', text)
        if date_match:
            for fmt in ('%m/%d/%y', '%m/%d/%Y'):
                try:
                    date_obj = datetime.strptime(date_match.group(1), fmt).date()
                    break
                except ValueError:
                    continue

        rego = ''
        rego_match = re.search(r'Rego:\s*([A-Z0-9]{4,8})', text, re.IGNORECASE)
        if rego_match:
            rego = rego_match.group(1).upper()

        vin = ''
        vin_match = re.search(r'Vin:\s*([A-Z0-9]{17})', text, re.IGNORECASE)
        if vin_match:
            vin = vin_match.group(1).upper()

        total_cost = Decimal('0.00')
        total_match = re.search(r'\bTotal\s+([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        item_re = re.compile(r'^(.+?)\s+([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})\s*$')
        in_section = False
        pending_desc: List[str] = []
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if 'part description' in lower and 'unit price' in lower:
                    in_section = True
                continue
            if (lower.startswith('payment/credits') or lower.startswith('payment:')
                    or lower.startswith('total:') or lower.startswith('amount due')
                    or lower.startswith('please send remittances')
                    or lower.startswith('gst')):
                break
            m = item_re.match(line)
            if m:
                description = m.group(1).strip()
                if pending_desc:
                    description = f"{description} {' '.join(pending_desc)}".strip()
                    pending_desc = []
                try:
                    unit_cost = Decimal(m.group(2).replace(',', ''))
                except (InvalidOperation, ValueError):
                    continue
                items.append(InvoiceItem(
                    description=description,
                    quantity=1,
                    unit_cost=unit_cost,
                    item_type='parts',
                ))
            else:
                if items and re.search(r'[A-Za-z]', line) and not re.match(r'^\d', line):
                    items[-1].description = f"{items[-1].description} {line}".strip()

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin=vin,
            odometer_reading=0,
            service_provider='ANZ Auto Parts Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _parse_city_discount_tyres_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        City Discount Tyres invoices put the invoice number at the end of the
        "Document Type Number" header row ("COPY TAX INVOICE 130237"), use
        DD/MM/YY dates, and have item rows as
        "<description> <qty> <price> <amount>".
        """
        invoice_number = ''
        m = re.search(r'TAX\s+INVOICE\s+(\d{4,7})\b', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'\b(\d{2}/\d{2}/\d{2,4})\b', text)
        if date_match:
            for fmt in ('%d/%m/%y', '%d/%m/%Y'):
                try:
                    date_obj = datetime.strptime(date_match.group(1), fmt).date()
                    break
                except ValueError:
                    continue

        rego = ''
        odometer = 0
        # The data row after the "Registration No. ... Odometer:" header has the
        # form: "<rego> <make> <model> <odometer>" e.g. "1IEI177 FORD RANGER 142738".
        header_match = re.search(r'Registration\s+No\.', text, re.IGNORECASE)
        if header_match:
            tail_lines = text[header_match.end():].split('\n')[:6]
            for tail in tail_lines:
                tail = tail.strip()
                if not tail or tail.lower().startswith(('vehicle', 'date', 'product')):
                    continue
                parts = tail.split()
                if not parts:
                    continue
                first = parts[0].upper()
                if self._is_valid_rego(first):
                    rego = first
                    for token in reversed(parts[1:]):
                        if token.isdigit() and len(token) >= 4:
                            try:
                                odometer = int(token)
                            except ValueError:
                                pass
                            break
                    break

        total_cost = Decimal('0.00')
        total_match = re.search(r'TOTAL\s*\$?\s*([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # CDT item rows: "<description> <qty> <price> <amount>" - all three
        # numerics use decimal point notation (qty can be "1" or "7.50").
        item_re = re.compile(
            r'^(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['labour', 'labor', 'fitting', 'balance', 'alignment',
                          'service', 'workshop']
        in_section = False
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if 'product description' in lower and 'qty' in lower:
                    in_section = True
                continue
            if (lower.startswith('goods remain property')
                    or lower.startswith('total ')
                    or lower.startswith('* indicates')
                    or lower.startswith('bsb')):
                break
            m = item_re.match(line)
            if not m:
                continue
            description = m.group(1).strip().lstrip('-').strip()
            try:
                qty = int(float(m.group(2))) or 1
                amount = Decimal(m.group(4).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=max(1, qty),
                unit_cost=amount,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=odometer,
            service_provider='City Discount Tyres Maddington',
            total_cost=total_cost,
            items=items,
        )

    def _parse_southern_auto_repairs_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Southern Auto Repairs invoices have section subtotal rows ("Parts Total",
        "Consumables Total") that the generic parser mistakes for line items.
        Item rows are "<item> <description> <qty> $unit $gst $total".
        """
        invoice_number = ''
        m = re.search(r'Invoice\s*#\s*[:\-]?\s*(\d{3,7})', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'\b(\d{1,2}/\d{1,2}/\d{4})\b', text)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        rego = ''
        rego_match = re.search(r'Registration\s+([A-Z0-9]{5,8})', text)
        if rego_match:
            candidate = rego_match.group(1).upper()
            if self._is_valid_rego(candidate):
                rego = candidate

        vin = ''
        vin_match = re.search(r'VIN\s+([A-Z0-9]{17})', text)
        if vin_match:
            vin = vin_match.group(1).upper()

        odometer = 0
        odo_match = re.search(r'Odometer\s+(\d{4,7})', text)
        if odo_match:
            try:
                odometer = int(odo_match.group(1))
            except ValueError:
                odometer = 0

        total_cost = Decimal('0.00')
        total_match = re.search(r'Balance\s+Due\s*\$?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'\bTotal\s*\$?\s*([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # Item rows: "<item_code> <description> <qty> $<unit> $<gst> $<total>"
        item_re = re.compile(
            r'^(\S+)\s+(.+?)\s+([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['labour', 'labor', 'service', 'install', 'check', 'inspect',
                          'test', 'repair', 'clean', 'fitting', 'recycling', 'refil',
                          'refill', 'remove', 'replace']
        skip_keywords = ['parts total', 'consumables total', 'labour total',
                         'subtotal', 'gst', 'total', 'balance due']
        in_section = False
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if ('item' in lower and 'description' in lower
                        and 'quantity' in lower and 'unit price' in lower):
                    in_section = True
                continue
            if any(lower.startswith(kw) for kw in skip_keywords):
                continue
            if lower.startswith('balance due') or lower.startswith('page '):
                break
            # Section headers like "PARTS" or "CONSUMABLES" - single uppercase word
            if re.match(r'^[A-Z]+$', line):
                continue
            m = item_re.match(line)
            if not m:
                continue
            item_code = m.group(1).strip()
            description = m.group(2).strip()
            try:
                qty = int(float(m.group(3))) or 1
                unit_cost = Decimal(m.group(4).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            full_desc = f"{item_code} {description}".strip()
            item_type = 'labor' if any(kw in full_desc.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=full_desc,
                quantity=max(1, qty),
                unit_cost=unit_cost,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin=vin,
            odometer_reading=odometer,
            service_provider='Southern Auto Repairs Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _parse_tj_trailers_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        T & J Trailers invoices have a "Quantity Description Amount" table with
        '#VALUE!' artefacts between rows, "Date: DD MMM YYYY" header and
        "INVOICE NO. <num>" inline. Plate No./VIN No. lines hold the rego.
        Some invoices contain multiple "Trailer <REGO>:" sections; we still
        record the first rego.
        """
        invoice_number = ''
        m = re.search(r'INVOICE\s*NO\.\s*([A-Z0-9-]+)', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1).strip()
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Date:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})', text)
        if date_match:
            for fmt in ('%d %b %Y', '%d %B %Y'):
                try:
                    date_obj = datetime.strptime(date_match.group(1), fmt).date()
                    break
                except ValueError:
                    continue

        rego = ''
        plate_match = re.search(r'Plate\s*No\.?\s*:?\s*([A-Z0-9]{4,8})', text, re.IGNORECASE)
        if plate_match:
            rego = plate_match.group(1).upper()
        if not rego:
            trailer_match = re.search(r'Trailer\s+([A-Z0-9]{4,8})\s*:', text)
            if trailer_match:
                rego = trailer_match.group(1).upper()

        vin = ''
        vin_match = re.search(r'VIN\s*No\.?\s*:?\s*([A-Z0-9]{17})', text, re.IGNORECASE)
        if vin_match:
            vin = vin_match.group(1).upper()

        total_cost = Decimal('0.00')
        total_match = re.search(r'\bTotal\s+\$?\s*([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # T&J item rows: "<qty> <description> $<amount>" — qty can be int or
        # decimal (e.g. "2.5"), amount may be negative ("-$150.00").
        # Some PDFs split "$183.00" into "$ 1 83.00" (PDF text-extraction
        # artifact); the second pattern joins those leading digits back on.
        item_re = re.compile(
            r'^([0-9]+(?:\.\d{1,2})?)\s+(.+?)\s+-?\$\s*([0-9,]+\.\d{2})\s*$'
        )
        split_amount_re = re.compile(
            r'^([0-9]+(?:\.\d{1,2})?)\s+(.+?)\s+-?\$\s+(\d+)\s+([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['labour', 'labor', 'service', 'install', 'replace',
                          'repair', 'check', 'fitting']
        for raw in text.split('\n'):
            line = raw.strip()
            if not line or '#VALUE!' in line or '#N/A' in line or '#REF!' in line:
                continue
            lower = line.lower()
            if (lower.startswith('subtotal') or lower.startswith('gst')
                    or lower.startswith('total ') or lower.startswith('balance')):
                continue
            m = item_re.match(line)
            split_m = None if m else split_amount_re.match(line)
            if not m and not split_m:
                continue
            try:
                if m:
                    qty = int(float(m.group(1))) or 1
                    amount = Decimal(m.group(3).replace(',', ''))
                    description = m.group(2).strip()
                else:
                    qty = int(float(split_m.group(1))) or 1
                    amount = Decimal(split_m.group(3) + split_m.group(4).replace(',', ''))
                    description = split_m.group(2).strip()
            except (InvalidOperation, ValueError):
                continue
            # Preserve negative amounts (returns) by checking the original line
            if '-$' in line:
                amount = -amount
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=max(1, qty),
                unit_cost=amount,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin=vin,
            odometer_reading=0,
            service_provider='T & J Trailers Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _parse_carlton_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Carlton 4X4 / Carlton Towbars: "Docket No <num>" or "Order No.: <num>",
        DD/MM/YYYY date, item rows shaped:
          "<barcode> <description> GST <qty> <unit> <total>" (Sales Order),
          "<barcode> <description> GST <unit> <qty> <total>" (Tax Invoice).
        Rego sometimes appears as "Order No CP 34 VT" — i.e. spaced rego.
        """
        invoice_number = ''
        m = re.search(r'Docket\s*No\.?\s*(\d{3,8})', text, re.IGNORECASE)
        if not m:
            m = re.search(r'Order\s*No\.?\s*:?\s*(\d{3,8})', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})', text)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        rego = ''
        # Newer Carlton invoices include explicit "Rego no:" / "Registration no:"
        # labels; check those first.
        for label_re in (
            r'Rego\s*no\.?\s*:?\s*([A-Z0-9 ]{4,10})',
            r'Registration\s*no\.?\s*:?\s*([A-Z0-9 ]{4,10})',
        ):
            label_match = re.search(label_re, text, re.IGNORECASE)
            if label_match:
                candidate = label_match.group(1).split('\n')[0].replace(' ', '').upper()
                if self._is_valid_rego(candidate):
                    rego = candidate
                    break
        # Older invoices: "Order No CP 34 VT" — spaced rego after Order No (no colon)
        if not rego:
            ord_match = re.search(r'Order\s*No\s+([A-Z0-9 ]{4,10})\s*$', text, re.IGNORECASE | re.MULTILINE)
            if ord_match:
                candidate = ord_match.group(1).replace(' ', '').upper()
                if self._is_valid_rego(candidate):
                    rego = candidate

        total_cost = Decimal('0.00')
        total_match = re.search(r'TOTAL\s*inc\s*GST\s*\$?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'\bTotal\s*\$?\s*([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # Two layouts share a "GST" tax tag between description and numbers.
        # Tax invoice header:  "Tax Price $ Qty Total $" → <unit> <qty> <total>
        # Sales order header:  "Tax Qty Price $ Total $" → <qty> <unit> <total>
        # We detect the layout from the column header rather than from the
        # arithmetic, because qty=1 and unit=total makes a*b == c hold either
        # way and gives the wrong answer for whole-dollar items.
        item_re = re.compile(
            r'^(\S+)\s+(.+?)\s+GST\s+([0-9,]+(?:\.\d{1,2})?)\s+([0-9,]+(?:\.\d{1,2})?)\s+([0-9,]+\.\d{2})\s*$'
        )
        layout = None  # 'qty_first' (sales order) or 'price_first' (tax invoice)
        in_section = False
        labor_keywords = ['labour', 'labor', 'fitting', 'install', 'service']
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if 'bar code' in lower and 'description' in lower:
                    in_section = True
                    qty_idx = lower.find('qty')
                    price_idx = lower.find('price')
                    if qty_idx != -1 and price_idx != -1 and qty_idx < price_idx:
                        layout = 'qty_first'
                    else:
                        layout = 'price_first'
                continue
            if (lower.startswith('no. of items') or lower.startswith('payment details')
                    or lower.startswith('sub total') or lower.startswith('subtotal')
                    or lower.startswith('total inc') or lower.startswith('total ')
                    or lower.startswith('comments')):
                break
            m = item_re.match(line)
            if not m:
                continue
            description = m.group(2).strip()
            a_str = m.group(3).replace(',', '')
            b_str = m.group(4).replace(',', '')
            c_str = m.group(5).replace(',', '')
            try:
                if layout == 'qty_first':
                    qty = max(1, int(float(a_str)))
                    unit_cost = Decimal(b_str)
                else:
                    unit_cost = Decimal(a_str)
                    qty = max(1, int(float(b_str)))
            except (InvalidOperation, ValueError):
                continue
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=qty,
                unit_cost=unit_cost,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=0,
            service_provider='Carlton 4X4 / Carlton Towbars Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _parse_gearbox_solutions_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Gearbox Solutions: "Job #: <num>" is the invoice number, DD/MM/YYYY
        date at the top, "Registration <REGO>" and "Odometer <num>" labels,
        items as "<code> <description> <qty> $<unit> $<gst> $<total>".
        Section header rows ("PARTS") and totals ("Parts Total") are skipped.
        """
        invoice_number = ''
        m = re.search(r'Job\s*#\s*:?\s*(\d{4,8})', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', text)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        rego = ''
        rego_match = re.search(r'Registration\s+([A-Z0-9]{5,8})', text)
        if rego_match:
            candidate = rego_match.group(1).upper()
            if self._is_valid_rego(candidate):
                rego = candidate

        vin = ''
        vin_match = re.search(r'VIN\s+([A-Z0-9]{17})', text)
        if vin_match:
            vin = vin_match.group(1).upper()

        odometer = 0
        odo_match = re.search(r'Odometer\s+(\d{4,7})', text)
        if odo_match:
            try:
                odometer = int(odo_match.group(1))
            except ValueError:
                odometer = 0

        total_cost = Decimal('0.00')
        total_match = re.search(r'Balance\s+Due\s*\$?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'\bTotal\s*\$?\s*([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        item_re = re.compile(
            r'^(\S+)\s+(.+?)\s+([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s*$'
        )
        skip_keywords = ['parts total', 'labour total', 'consumables total',
                         'subtotal', 'gst', 'total', 'balance due']
        labor_keywords = ['labour', 'labor', 'service', 'install', 'check',
                          'inspect', 'test', 'repair', 'replace', 'remove']
        in_section = False
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if ('item' in lower and 'description' in lower
                        and 'quantity' in lower and 'unit price' in lower):
                    in_section = True
                continue
            if any(lower.startswith(kw) for kw in skip_keywords):
                continue
            if lower.startswith('invoice notes') or lower.startswith('warranty'):
                break
            if re.match(r'^[A-Z]+$', line):
                continue
            m = item_re.match(line)
            if not m:
                continue
            code = m.group(1).strip()
            description = f"{code} {m.group(2).strip()}".strip()
            try:
                qty = int(float(m.group(3))) or 1
                unit_cost = Decimal(m.group(4).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=max(1, qty),
                unit_cost=unit_cost,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin=vin,
            odometer_reading=odometer,
            service_provider='Gearbox Solutions',
            total_cost=total_cost,
            items=items,
        )

    def _parse_two_raptors_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Two Raptors / Pirtek: invoice number sits at the top right as
        "DG-T<digits>"; date appears as "Date : DD/MM/YYYY"; the machine
        (boomlift) is referenced as "Machine No: GENIE ZX-135/70". Item lines:
        "<line#> <code> <desc> <ordered> <invoiced> <backorder> [UM] <price> <ext>".
        """
        invoice_number = ''
        m = re.search(r'\b(DG-[A-Z0-9]+)\b', text)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})', text)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        rego = ''
        machine_match = re.search(r'Machine\s*No\s*:\s*([A-Z0-9\-/ ]+)', text, re.IGNORECASE)
        if machine_match:
            rego = machine_match.group(1).strip().lower()

        total_cost = Decimal('0.00')
        total_match = re.search(r'Total\s+AUD\s*:?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'Sub\s*Total\s*:?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # Match: 1 R1AT04K HOSE ASSEMBLY 1.000 1.000 0.000 EA 330.66 330.66
        # UM (EA) is optional - LABOUR / SERVICE / TRAVEL omit it.
        item_re = re.compile(
            r'^\d+\s+(\S+)\s+(.+?)\s+'
            r'([0-9,]+\.\d{3})\s+([0-9,]+\.\d{3})\s+([0-9,]+\.\d{3})\s+'
            r'(?:[A-Z]{1,3}\s+)?'
            r'([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['labour', 'labor', 'service', 'travel', 'callout',
                          'install', 'check']
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            m = item_re.match(line)
            if not m:
                continue
            code = m.group(1).strip()
            desc = m.group(2).strip()
            full_desc = f"{code} {desc}".strip()
            try:
                qty = int(float(m.group(4))) or 1
                unit_cost = Decimal(m.group(6).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            item_type = 'labor' if any(kw in full_desc.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=full_desc,
                quantity=max(1, qty),
                unit_cost=unit_cost,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=0,
            service_provider='Two Raptors Pty Ltd (Pirtek)',
            total_cost=total_cost,
            items=items,
        )

    def _parse_tdr_mechanical_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        TDR Mechanical: header has "Invoice number" column with INV-<num> and
        "Reference" column with the rego. Items use multi-line descriptions
        followed by "<qty> <unit_price> <tax%> <amount>" — sometimes the
        first item is a vehicle-info block with all-zero prices.
        """
        invoice_number = ''
        m = re.search(r'\b(INV-\d{2,7})\b', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1).upper()
        if not invoice_number:
            return None

        date_obj = None
        # "Issue date <DD MMM YYYY>"
        date_match = re.search(r'Issue\s*date\s*\n?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})', text, re.IGNORECASE)
        if not date_match:
            date_match = re.search(r'(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})', text)
        if date_match:
            for fmt in ('%d %b %Y', '%d %B %Y'):
                try:
                    date_obj = datetime.strptime(date_match.group(1), fmt).date()
                    break
                except ValueError:
                    continue

        rego = ''
        # The Reference column ends each row of the header block; pick a
        # standalone token that validates as a rego.
        for token in re.findall(r'\b([A-Z]{2}\d{2}[A-Z]{2}|\d[A-Z]{2,3}\d{3}|[A-Z]{3}\d{2,3}|\d{3}[A-Z]{3})\b', text):
            if self._is_valid_rego(token):
                rego = token
                break

        total_cost = Decimal('0.00')
        total_match = re.search(r'\bTotal\s+([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # Item rows: "<qty> <unit_price> <tax%>% <amount>" with description
        # spread across preceding lines until we hit a numeric tail.
        item_tail_re = re.compile(
            r'^(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+([0-9,]+\.\d{2,4})\s+(\d{1,2})%\s+([0-9,]+\.\d{2})\s*$'
        )
        # Pricing tail with no leading description (line is just numerics) —
        # description comes from pending/preceding lines.
        bare_tail_re = re.compile(
            r'^([0-9]+(?:\.\d{1,2})?)\s+([0-9,]+\.\d{2,4})\s+(\d{1,2})%\s+([0-9,]+\.\d{2})\s*$'
        )
        zero_tail_re = re.compile(r'^(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+0\.00\s+0\.00\s*$')
        labor_keywords = ['labour', 'labor', 'service', 'install', 'fit', 'fitting',
                          'replace', 'repair', 'diagnose', 'test', 'check', 'top up',
                          'bleed', 'remove']
        pending: List[str] = []
        in_section = False
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if ('description' in lower and 'quantity' in lower
                        and 'price' in lower and 'amount' in lower):
                    in_section = True
                continue
            if (lower.startswith('subtotal') or lower.startswith('total gst')
                    or lower.startswith('view online') or lower.startswith('please note')
                    or lower.startswith('amount due') or lower.startswith('total ')):
                break
            m = item_tail_re.match(line)
            if m:
                description = m.group(1).strip()
                if pending:
                    description = (' '.join(pending) + ' ' + description).strip()
                    pending = []
                try:
                    qty = int(float(m.group(2))) or 1
                    unit_cost = Decimal(m.group(3).replace(',', ''))
                except (InvalidOperation, ValueError):
                    continue
                item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
                items.append(InvoiceItem(
                    description=description,
                    quantity=max(1, qty),
                    unit_cost=unit_cost,
                    item_type=item_type,
                ))
                continue
            bm = bare_tail_re.match(line)
            if bm and pending:
                description = ' '.join(pending).strip()
                pending = []
                try:
                    qty = int(float(bm.group(1))) or 1
                    unit_cost = Decimal(bm.group(2).replace(',', ''))
                except (InvalidOperation, ValueError):
                    continue
                item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
                items.append(InvoiceItem(
                    description=description,
                    quantity=max(1, qty),
                    unit_cost=unit_cost,
                    item_type=item_type,
                ))
                continue
            zm = zero_tail_re.match(line)
            if zm:
                # Vehicle info / zero-price descriptive block — flush pending.
                pending = []
                continue
            if re.search(r'[A-Za-z]', line):
                pending.append(line)

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=0,
            service_provider='TDR Mechanical Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _parse_wagga_city_auto_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Wagga City Auto Centre: "Invoice Number" / "INV-<num>" header block,
        "Invoice Date <DD MMM YYYY>", "Registration <REGO>" label, item rows
        end with "<qty> <unit> <tax%>% <amount>" and descriptions wrap.
        """
        invoice_number = ''
        m = re.search(r'\b(INV-\d{2,7})\b', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1).upper()
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Invoice\s*Date\s*\n?\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})', text, re.IGNORECASE)
        if not date_match:
            date_match = re.search(r'(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})', text)
        if date_match:
            for fmt in ('%d %b %Y', '%d %B %Y'):
                try:
                    date_obj = datetime.strptime(date_match.group(1), fmt).date()
                    break
                except ValueError:
                    continue

        rego = ''
        rego_match = re.search(r'Registration\s*\n?\s*([A-Z0-9]{4,8})', text)
        if rego_match:
            candidate = rego_match.group(1).upper()
            if self._is_valid_rego(candidate):
                rego = candidate

        total_cost = Decimal('0.00')
        total_match = re.search(r'Invoice\s*Total\s*AUD\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'Amount\s*Due\s*AUD\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        item_tail_re = re.compile(
            r'^(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+([0-9,]+\.\d{2,4})\s+(\d{1,2})%\s+([0-9,]+\.\d{2})\s*$'
        )
        zero_tail_re = re.compile(r'^(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+0\.00\s+0\.00\s*$')
        labor_keywords = ['labour', 'labor', 'service', 'install', 'check',
                          'inspect', 'test', 'repair', 'replace', 'diagnose',
                          'remove']
        pending: List[str] = []
        in_section = False
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if ('description' in lower and 'quantity' in lower
                        and 'unit price' in lower and 'amount' in lower):
                    in_section = True
                continue
            if (lower.startswith('subtotal') or lower.startswith('total gst')
                    or lower.startswith('invoice total')
                    or lower.startswith('total net') or lower.startswith('amount due')
                    or lower.startswith('due date')):
                break
            m = item_tail_re.match(line)
            if m:
                description = m.group(1).strip()
                if pending:
                    description = (' '.join(pending) + ' ' + description).strip()
                    pending = []
                try:
                    qty = int(float(m.group(2))) or 1
                    unit_cost = Decimal(m.group(3).replace(',', ''))
                except (InvalidOperation, ValueError):
                    continue
                item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
                items.append(InvoiceItem(
                    description=description,
                    quantity=max(1, qty),
                    unit_cost=unit_cost,
                    item_type=item_type,
                ))
                continue
            zm = zero_tail_re.match(line)
            if zm:
                pending = []
                continue
            if re.search(r'[A-Za-z]', line):
                pending.append(line)

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=0,
            service_provider='Wagga City Auto Centre',
            total_cost=total_cost,
            items=items,
        )

    def _parse_tamworth_car_carrying_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Tamworth Car Carrying: header table "Invoice number Issue date Due date"
        followed by the data row "<num> <issue> <due>". Items are
        "<item_id> <description> <UoM> <qty> <unit> <tax> <amount>"; the
        description embeds the rego (e.g. "CP34VT - HYUNDAI - U616608").
        """
        invoice_number = ''
        date_obj = None
        # Match the data row right after the header.
        m = re.search(
            r'Invoice\s*number\s*Issue\s*date\s*Due\s*date\s*\n\s*(\d{4,8})\s+(\d{2}/\d{2}/\d{4})',
            text, re.IGNORECASE,
        )
        if m:
            invoice_number = m.group(1)
            try:
                date_obj = datetime.strptime(m.group(2), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None
        if not invoice_number:
            return None

        rego = ''
        # Description column embeds rego as "<REGO> - MAKE - VIN/CODE".
        for token in re.findall(r'\b([A-Z]{2}\d{2}[A-Z]{2}|\d[A-Z]{2,3}\d{3}|[A-Z]{3}\d{2,3}|\d{3}[A-Z]{3})\b', text):
            if self._is_valid_rego(token):
                rego = token
                break

        total_cost = Decimal('0.00')
        total_match = re.search(r'Total\s*Amount\s*\(inc\.\s*tax\)\s*\$?([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'Balance\s*due\s*\$?([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # Item row: "<item_id> <description> <qty> <unit> <tax_label> <amount>"
        # The UoM column ends up empty in extracted text for these invoices.
        item_re = re.compile(
            r'^(\S+)\s+(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+([0-9,]+\.\d{2})\s+(?:GST|FREE|EXEMPT)\s+([0-9,]+\.\d{2})\s*$',
            re.IGNORECASE,
        )
        in_section = False
        labor_keywords = ['transport', 'tow', 'carry', 'service', 'labour', 'labor']
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if 'item id' in lower and 'description' in lower and 'amount' in lower:
                    in_section = True
                continue
            if (lower.startswith('subtotal') or lower.startswith('tax ')
                    or lower.startswith('total amount') or lower.startswith('notes')):
                break
            m = item_re.match(line)
            if not m:
                continue
            description = f"{m.group(1).strip()} {m.group(2).strip()}".strip()
            try:
                qty = int(float(m.group(3))) or 1
                unit_cost = Decimal(m.group(4).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=max(1, qty),
                unit_cost=unit_cost,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=0,
            service_provider='Tamworth Car Carrying',
            total_cost=total_cost,
            items=items,
        )

    def _parse_tamworth_automotive_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Tamworth Automotive Services: "Tax Invoice <num>" in the header,
        "Date: DD/MM/YYYY", "Registration No.: <rego>", "Odometer: <num>",
        items "<code> - <description> <qty> $<unit> $<gst> $<amount>".
        """
        invoice_number = ''
        m = re.search(r'Tax\s*Invoice\s*(\d{3,7})', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})', text)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        rego = ''
        rego_match = re.search(r'Registration\s*No\.?\s*:?\s*([A-Z0-9]{4,8})', text, re.IGNORECASE)
        if rego_match:
            candidate = rego_match.group(1).upper()
            if self._is_valid_rego(candidate):
                rego = candidate

        odometer = 0
        odo_match = re.search(r'Odometer\s*:?\s*([0-9,]+)', text, re.IGNORECASE)
        if odo_match:
            try:
                odometer = int(odo_match.group(1).replace(',', ''))
            except ValueError:
                odometer = 0

        total_cost = Decimal('0.00')
        total_match = re.search(r'Balance\s+Due\s*\$?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'\bTotal\s*\$?\s*([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # Item rows: "<code-or-words> <qty> $<unit> $<gst> $<amount>"
        # Description may include hyphen and code prefix.
        item_re = re.compile(
            r'^(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['labour', 'labor', 'service', 'install', 'check',
                          'inspect', 'test', 'repair', 'replace', 'remove',
                          'fee', 'supply']
        in_section = False
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if ('description' in lower and 'qty' in lower
                        and 'unit price' in lower and 'amount' in lower):
                    in_section = True
                continue
            if (lower.startswith('subtotal') or lower.startswith('thank you')
                    or lower.startswith('balance due') or lower.startswith('total')
                    or lower.startswith('mvrl')):
                break
            m = item_re.match(line)
            if not m:
                continue
            description = m.group(1).strip()
            try:
                qty = int(float(m.group(2))) or 1
                unit_cost = Decimal(m.group(3).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=max(1, qty),
                unit_cost=unit_cost,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=odometer,
            service_provider='Tamworth Automotive Services',
            total_cost=total_cost,
            items=items,
        )

    def _parse_centreline_smash_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Centreline Smash Repairs: "Invoice # <num>-S", "Invoiced Date DD/MM/YYYY",
        "Rego <REGO>", "Mileage <num>", parts table:
          "<part_name> <type> <part#> <units> <unit_price> <total>"
        plus a "LABOUR AS PER AUTHORITY <amount>" line and optional Misc rows.
        """
        invoice_number = ''
        m = re.search(r'Invoice\s*#\s*([A-Z0-9-]+)', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1).upper()
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Invoiced\s*Date\s*(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        rego = ''
        rego_match = re.search(r'Rego\s+([A-Z0-9]{5,8})', text)
        if rego_match:
            candidate = rego_match.group(1).upper()
            if self._is_valid_rego(candidate):
                rego = candidate

        vin = ''
        vin_match = re.search(r'VIN\s+([A-Z0-9]{17})', text)
        if vin_match:
            vin = vin_match.group(1).upper()

        odometer = 0
        odo_match = re.search(r'Mileage\s+(\d{4,7})', text, re.IGNORECASE)
        if odo_match:
            try:
                odometer = int(odo_match.group(1))
            except ValueError:
                odometer = 0

        total_cost = Decimal('0.00')
        total_match = re.search(r'TOTAL\s*PAYABLE\s*\(\$\)\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'Total\s*Inc\s*GST\s*\(\$\)\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'BALANCE\s*DUE\s*\(\$\)\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []

        # LABOUR AS PER AUTHORITY <amount>
        lab_match = re.search(r'LABOUR\s+AS\s+PER\s+AUTHORITY\s+([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if lab_match:
            try:
                lab_amount = Decimal(lab_match.group(1).replace(',', ''))
                items.append(InvoiceItem(
                    description='Labour as per authority',
                    quantity=1,
                    unit_cost=lab_amount,
                    item_type='labor',
                ))
            except (InvalidOperation, ValueError):
                pass

        # Parts table: lines look like
        # "<descriptive name> <Type> <part#> <units> <unit_price> <total>"
        # but extracted text may wrap the description across multiple lines.
        # Use a tail-anchored regex: trailing 3 numerics.
        item_tail_re = re.compile(
            r'^(.+?)\s+(\S+)\s+([0-9]+(?:\.\d{1,2})?)\s+([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})\s*$'
        )
        in_section = False
        pending: List[str] = []
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if ('parts' in lower and 'type' in lower and 'part #' in lower
                        and 'units' in lower):
                    in_section = True
                continue
            if (lower.startswith('sub total') or lower.startswith('subtotal')
                    or lower.startswith('ship via') or lower.startswith('total inc')
                    or lower.startswith('plus gst') or lower.startswith('nett total')
                    or lower.startswith('misc')):
                # Misc block has its own simple "<desc> <units> <rate> <total>"
                # which we treat as a single labor item.
                if lower.startswith('misc'):
                    pending = []
                    continue
                break
            m = item_tail_re.match(line)
            if not m:
                if re.search(r'[A-Za-z]', line):
                    pending.append(line)
                continue
            description = m.group(1).strip()
            if pending:
                description = (' '.join(pending) + ' ' + description).strip()
                pending = []
            try:
                units = float(m.group(3))
                unit_cost = Decimal(m.group(4).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            if unit_cost <= 0:
                continue
            qty = max(1, int(units)) if units >= 1 else 1
            items.append(InvoiceItem(
                description=description,
                quantity=qty,
                unit_cost=unit_cost,
                item_type='parts',
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin=vin,
            odometer_reading=odometer,
            service_provider='Centreline Smash Repairs Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _parse_davids_auto_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Davids Auto Repairs: "TAX INVOICE # F<num>" or "INVOICE NO. F<num>",
        "DATE DD/MM/YYYY", a header row "MAKE/MODEL REGO KMS" with the data
        row beneath it (rego may be spaced "CY 02 JR"). Items are
        "<description> <qty> <rate> <amount>" with multi-line descriptions
        before the numeric tail.
        """
        invoice_number = ''
        m = re.search(r'(?:TAX\s+INVOICE\s*#|INVOICE\s*NO\.?)\s*([A-Z0-9-]+)', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1).upper()
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'\bDATE\s+(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
        if not date_match:
            date_match = re.search(r'\b(\d{1,2}/\d{1,2}/\d{4})\b', text)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        rego = ''
        odometer = 0
        # Find data row after "MAKE/MODEL REGO KMS" header.
        header_match = re.search(r'MAKE/MODEL\s+REGO\s+KMS', text, re.IGNORECASE)
        if header_match:
            tail = text[header_match.end():header_match.end() + 200]
            tail_lines = [ln.strip() for ln in tail.split('\n') if ln.strip()]
            if tail_lines:
                row = tail_lines[0]
                # row e.g. "TOYOTA HIACE CY 02 JR 312924" or "VW TRANSPORTER DH 24 RW 140240"
                tokens = row.split()
                if tokens and tokens[-1].replace(',', '').isdigit():
                    try:
                        odometer = int(tokens[-1].replace(',', ''))
                    except ValueError:
                        pass
                    tokens = tokens[:-1]
                # Try to recombine spaced rego from tail tokens.
                for length in (3, 2):
                    if len(tokens) >= length:
                        candidate = ''.join(tokens[-length:]).upper()
                        if self._is_valid_rego(candidate):
                            rego = candidate
                            break

        total_cost = Decimal('0.00')
        total_match = re.search(r'BALANCE\s+DUE\s+A?\$?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'\bTOTAL\s+([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # Item rows: "<desc> <qty> <rate> <amount>" with description wrapping.
        item_tail_re = re.compile(
            r'^(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['diagnose', 'labour', 'labor', 'service', 'install',
                          'check', 'inspect', 'test', 'repair', 'replace',
                          'remove', 'wash', 'refit', 'clean']
        in_section = False
        pending: List[str] = []
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if 'parts & labour' in lower or 'parts and labour' in lower:
                    in_section = True
                continue
            if (lower.startswith('subtotal') or lower.startswith('total gst')
                    or lower.startswith('gst total') or lower.startswith('total ')
                    or lower.startswith('balance due') or lower.startswith('recommendations')):
                break
            m = item_tail_re.match(line)
            if not m:
                if re.search(r'[A-Za-z]', line) and not re.match(r'^[-*]+\s', line):
                    pending.append(line.lstrip('- ').strip())
                else:
                    pending.append(line)
                continue
            description = m.group(1).strip().lstrip('- ').strip()
            if pending:
                description = (' '.join(pending) + ' ' + description).strip()
                pending = []
            try:
                qty = int(float(m.group(2))) or 1
                rate = Decimal(m.group(3).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            if rate <= 0:
                continue
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=max(1, qty),
                unit_cost=rate,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=odometer,
            service_provider='Davids Auto Repairs',
            total_cost=total_cost,
            items=items,
        )

    def _parse_brar_mechanical_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Brar Mechanical Services: invoice number appears as "#<num>" near the
        top, "Issued DD/M/YYYY" sets the date, items table is
        "DESCRIPTION QTY PRICE, AUD AMOUNT, AUD" with rows
        "<description> <qty> $<price> $<amount>".
        """
        invoice_number = ''
        m = re.search(r'#(\d{4,7})\b', text)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Issued\s+(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
        if not date_match:
            date_match = re.search(r'\b(\d{1,2}/\d{1,2}/\d{4})\b', text)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        rego = ''
        for label_re in (
            r'Rego\s*no\.?\s*:?\s*([A-Z0-9 ]{4,10})',
            r'Registration\s*no\.?\s*:?\s*([A-Z0-9 ]{4,10})',
        ):
            label_match = re.search(label_re, text, re.IGNORECASE)
            if label_match:
                candidate = label_match.group(1).split('\n')[0].replace(' ', '').upper()
                if self._is_valid_rego(candidate):
                    rego = candidate
                    break

        total_cost = Decimal('0.00')
        total_match = re.search(r'\bTotal\s+\$?\s*([0-9,]+\.\d{2})', text)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        item_re = re.compile(
            r'^(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['service', 'labour', 'labor', 'disposal', 'install',
                          'check', 'inspect', 'test', 'repair', 'replace']
        in_section = False
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if 'description' in lower and 'qty' in lower and 'amount' in lower:
                    in_section = True
                continue
            if (lower.startswith('subtotal') or lower.startswith('gst')
                    or lower.startswith('total ') or lower.startswith('payment')):
                break
            m = item_re.match(line)
            if not m:
                continue
            description = m.group(1).strip()
            try:
                qty = int(float(m.group(2))) or 1
                price = Decimal(m.group(3).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=max(1, qty),
                unit_cost=price,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=0,
            service_provider='Brar Mechanical Services Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _parse_jd_windscreen_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        JD Windscreen / True Value Windscreens: "Invoice Num <num>",
        "Date <DD MMM YYYY>", "Rego: <REGO>" on its own line, item rows
        as "<desc> <qty> $<rate> $<amount>".
        """
        invoice_number = ''
        m = re.search(r'Invoice\s*Num\.?\s*(\d{2,7})', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'\bDate\s+(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})', text, re.IGNORECASE)
        if date_match:
            for fmt in ('%d %b %Y', '%d %B %Y'):
                try:
                    date_obj = datetime.strptime(date_match.group(1), fmt).date()
                    break
                except ValueError:
                    continue

        rego = ''
        rego_match = re.search(r'Rego\s*:\s*([A-Z0-9 ]{4,10})', text, re.IGNORECASE)
        if rego_match:
            candidate = rego_match.group(1).split('\n')[0].replace(' ', '').upper()
            if self._is_valid_rego(candidate):
                rego = candidate

        total_cost = Decimal('0.00')
        total_match = re.search(r'Balance\s+Due\s*\$?([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'\bTotal\s*\$?([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        item_re = re.compile(
            r'^(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+\$([0-9,]+\.\d{2})\s+\$([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['supplied', 'fitted', 'fit', 'install', 'service',
                          'labour', 'labor', 'replace', 'repair']
        in_section = False
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if ('description' in lower and 'quantity' in lower
                        and 'rate' in lower and 'amount' in lower):
                    in_section = True
                continue
            if (lower.startswith('rego') or lower.startswith('subtotal')
                    or lower.startswith('gst') or lower.startswith('total')
                    or lower.startswith('paid') or lower.startswith('balance')
                    or lower.startswith('bsb') or lower.startswith('acc')
                    or lower.startswith('abn') or lower.startswith('true value')
                    or lower == 'ali'):
                continue
            m = item_re.match(line)
            if not m:
                # Description wrap-line for the previous item — append to it.
                if items and re.search(r'[A-Za-z]', line):
                    items[-1].description = f"{items[-1].description} {line}".strip()
                continue
            description = m.group(1).strip()
            try:
                qty = int(float(m.group(2))) or 1
                rate = Decimal(m.group(3).replace(',', ''))
            except (InvalidOperation, ValueError):
                continue
            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'
            items.append(InvoiceItem(
                description=description,
                quantity=max(1, qty),
                unit_cost=rate,
                item_type=item_type,
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=0,
            service_provider='JD Windscreen / True Value Windscreens',
            total_cost=total_cost,
            items=items,
        )

    def _parse_imax_group_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        IMAX Group windscreen invoices: "Invoice #<num>", "Date: DD/MM/YYYY",
        single-line "SUPPLIED AND FITTED ..." description and
        "Subtotal: $X / GST (10%): $Y / Total Payable: $Z" totals.
        No rego field — these invoices identify the vehicle only by name in
        the description (e.g. "VW TRANSPORTER").
        """
        invoice_number = ''
        m = re.search(r'Invoice\s*#\s*(\d{1,7})', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        rego = ''
        for label_re in (
            r'Rego\s*no\.?\s*:?\s*([A-Z0-9 ]{4,10})',
            r'Rego\s*:\s*([A-Z0-9 ]{4,10})',
            r'Registration\s*no\.?\s*:?\s*([A-Z0-9 ]{4,10})',
        ):
            label_match = re.search(label_re, text, re.IGNORECASE)
            if label_match:
                candidate = label_match.group(1).split('\n')[0].replace(' ', '').upper()
                if self._is_valid_rego(candidate):
                    rego = candidate
                    break

        total_cost = Decimal('0.00')
        total_match = re.search(r'Total\s*Payable\s*:?\s*\$?([0-9,]+(?:\.\d{2})?)', text, re.IGNORECASE)
        if total_match:
            try:
                amount = total_match.group(1).replace(',', '')
                if '.' not in amount:
                    amount += '.00'
                total_cost = Decimal(amount)
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        # Subtotal is the actual ex-GST line item amount when present;
        # otherwise fall back to Total Payable (some IMAX invoices omit the
        # Subtotal/GST breakdown and only list the final total).
        item_amount = Decimal('0.00')
        sub_match = re.search(r'Subtotal\s*:?\s*\$?([0-9,]+(?:\.\d{2})?)', text, re.IGNORECASE)
        if sub_match:
            try:
                amount = sub_match.group(1).replace(',', '')
                if '.' not in amount:
                    amount += '.00'
                item_amount = Decimal(amount)
            except (InvalidOperation, ValueError):
                item_amount = Decimal('0.00')
        if item_amount <= 0:
            item_amount = total_cost

        items: List[InvoiceItem] = []
        # Description sits between "Service Description" and the next totals
        # line. Some IMAX invoices include "Subtotal:" / "GST" rows; others
        # jump straight to "Total Payable:" — accept either as the terminator.
        desc_match = re.search(
            r'Service\s+Description\s*\n+(.+?)\n+\s*(?:Subtotal|GST|Total\s+Payable)',
            text, re.IGNORECASE | re.DOTALL,
        )
        description = ''
        if desc_match:
            description = ' '.join(line.strip() for line in desc_match.group(1).splitlines()
                                   if line.strip())
        if not description:
            description = 'Windscreen replacement'

        if item_amount > 0:
            items.append(InvoiceItem(
                description=description,
                quantity=1,
                unit_cost=item_amount,
                item_type='labor',
            ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego=rego,
            vehicle_vin='',
            odometer_reading=0,
            service_provider='IMAX Group',
            total_cost=total_cost,
            items=items,
        )

    def _parse_access_group_invoice(self, text: str) -> Optional[InvoiceData]:
        """
        Access Services Group: "Job Invoice <num>" near the top, "Invoice
        Date DD/MM/YYYY", item rows
          "<code> <description> <qty> <amount>" (qty optional — LABOUR row
          omits it). Totals appear as "Sub Total: <amt>", "GST Total: <amt>",
          "Invoice Total $<amt>".
        These invoices are always for the Genie Z13512-1710 (no rego in PDF).
        """
        invoice_number = ''
        m = re.search(r'Job\s*Invoice\s+(\d{4,12})', text, re.IGNORECASE)
        if m:
            invoice_number = m.group(1)
        if not invoice_number:
            return None

        date_obj = None
        date_match = re.search(r'Invoice\s*Date\s*(\d{1,2}/\d{1,2}/\d{4})', text, re.IGNORECASE)
        if date_match:
            try:
                date_obj = datetime.strptime(date_match.group(1), '%d/%m/%Y').date()
            except ValueError:
                date_obj = None

        total_cost = Decimal('0.00')
        total_match = re.search(r'Invoice\s*Total\s*\$?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if not total_match:
            total_match = re.search(r'Sub\s*Total\s*:?\s*([0-9,]+\.\d{2})', text, re.IGNORECASE)
        if total_match:
            try:
                total_cost = Decimal(total_match.group(1).replace(',', ''))
            except (InvalidOperation, ValueError):
                total_cost = Decimal('0.00')

        items: List[InvoiceItem] = []
        # Two row shapes share the "<code> <desc> ... <amount>" tail:
        #   "CONS Consumable Charge 2.00 22.41"  (with qty)
        #   "LABOUR Labour 600.00"               (no qty)
        item_qty_re = re.compile(
            r'^(\S+)\s+(.+?)\s+([0-9]+(?:\.\d{1,2})?)\s+([0-9,]+\.\d{2})\s*$'
        )
        item_noqty_re = re.compile(
            r'^(\S+)\s+(.+?)\s+([0-9,]+\.\d{2})\s*$'
        )
        labor_keywords = ['labour', 'labor', 'service', 'install', 'travel',
                          'callout', 'check', 'inspect']
        skip_prefixes = ('sub total', 'subtotal', 'gst', 'invoice total',
                         'payment', 'bank', 'account', 'bsb', 'please',
                         'any requests', 'po box', 'page ', 'eop')
        in_section = False
        for raw in text.split('\n'):
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if not in_section:
                if 'item' in lower and 'description' in lower and ('qty' in lower or 'charge' in lower):
                    in_section = True
                continue
            if any(lower.startswith(p) for p in skip_prefixes):
                continue
            # "[Allocated to Item Number ...]" annotation under each item row.
            if line.startswith('['):
                continue
            m_qty = item_qty_re.match(line)
            if m_qty:
                code = m_qty.group(1).strip()
                desc = m_qty.group(2).strip()
                full_desc = f"{code} {desc}".strip()
                try:
                    qty = int(float(m_qty.group(3))) or 1
                    amount = Decimal(m_qty.group(4).replace(',', ''))
                except (InvalidOperation, ValueError):
                    continue
                if amount <= 0:
                    continue
                item_type = 'labor' if any(kw in full_desc.lower() for kw in labor_keywords) else 'parts'
                items.append(InvoiceItem(
                    description=full_desc,
                    quantity=max(1, qty),
                    unit_cost=amount,
                    item_type=item_type,
                ))
                continue
            m_noqty = item_noqty_re.match(line)
            if m_noqty:
                code = m_noqty.group(1).strip()
                desc = m_noqty.group(2).strip()
                full_desc = f"{code} {desc}".strip()
                try:
                    amount = Decimal(m_noqty.group(3).replace(',', ''))
                except (InvalidOperation, ValueError):
                    continue
                if amount <= 0:
                    continue
                item_type = 'labor' if any(kw in full_desc.lower() for kw in labor_keywords) else 'parts'
                items.append(InvoiceItem(
                    description=full_desc,
                    quantity=1,
                    unit_cost=amount,
                    item_type=item_type,
                ))

        return InvoiceData(
            invoice_number=invoice_number,
            date=date_obj,
            vehicle_rego='Z13512-1710',
            vehicle_vin='',
            odometer_reading=0,
            service_provider='Access Services Group Pty Ltd',
            total_cost=total_cost,
            items=items,
        )

    def _extract_pattern(self, text: str, pattern_type: str) -> str:
        """Extract data using regex patterns"""
        patterns = self.patterns.get(pattern_type, [])
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # Take the first match for most types, but for rego we need to validate
                result = matches[0].strip().upper()
                
                # Special handling for different pattern types
                if pattern_type == 'rego':
                    # For rego, iterate through all matches to find the first valid one
                    for match in matches:
                        candidate = match.strip().upper()
                        # Clean up registration number - remove any trailing text after newline
                        candidate = candidate.split('\n')[0].strip()
                        # Clean up spacing for validation and final result
                        clean_rego = candidate.replace(' ', '')
                        if self._is_valid_rego(clean_rego):
                            return clean_rego  # Return without spaces
                    # If no valid rego found, continue to next pattern
                    continue
                elif pattern_type == 'date':
                    # Don't convert to uppercase for dates
                    return matches[0].strip()
                elif pattern_type == 'invoice_number':
                    # For invoice numbers, prefer shorter, cleaner matches
                    # Sort by length and return the shortest reasonable match
                    sorted_matches = sorted(matches, key=len)
                    for match in sorted_matches:
                        clean_match = match.strip().upper()
                        # Skip overly long matches that might include extra text
                        if len(clean_match) <= 10 and clean_match.isalnum():
                            return clean_match
                    # If no clean match found, return the first one
                    return sorted_matches[0].strip().upper()
                elif pattern_type == 'service_provider':
                    # Special handling for service provider to format properly
                    if re.search(r'bridgestone.*select.*tyre.*auto', result, re.IGNORECASE):
                        # Format properly: "Bridgestone Select Tyre & Auto Revesby"
                        parts = result.split('&')
                        if len(parts) == 2:
                            return f"{parts[0].strip().title()} & {parts[1].strip().title()}"
                        else:
                            return result.title()
                    else:
                        return result
                else:
                    # Default: return first match (used by 'total', 'vin', etc.)
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
            'PART', 'PARTS', 'WORK', 'REPAIR', 'FIX', 'CHANGE', 'REPLACE',
            'VIC3175', 'NSW2000', 'QLD4000', 'SA5000', 'WA6000', 'TAS7000',
            'NT0800', 'ACT2600',  # Exclude address postcodes
            'ABN79', 'ABN', 'VINNO', 'VIN', 'NO', 'C109'  # Exclude specific false matches from this invoice
        ]
        
        if rego in invalid_words:
            return False
            
        # Exclude patterns that look like addresses/postcodes
        if re.match(r'^[A-Z]{2,3}\d{4}$', rego) and any(state in rego for state in ['VIC', 'NSW', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT']):
            return False
            
        # Exclude ABN-like patterns
        if rego.startswith('ABN'):
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
            r'^[A-Z]{3}\d{2}[A-Z]$',     # ESY89C, DTY19U format (3 letters + 2 digits + 1 letter)
            r'^\d[A-Z]{2,3}\d{3}$',      # 1HDC949 format (1 digit + letters + 3 digits)
            r'^[A-Z]\d{3}[A-Z]{3}$',     # Alternative format for 1HDC949-style regos
            r'^\d[A-Z]{2}\d[A-Z]{2}$',   # 2BF1TV format (1 digit + 2 letters + 1 digit + 2 letters)
            r'^[A-Z]{2}\d{2}[A-Z]{2}$'  # CJ42AH format (2 letters + 2 digits + 2 letters)
        ]
        
        return any(re.match(pattern, rego) for pattern in aus_patterns)
    
    def _extract_date(self, text: str) -> Optional[datetime.date]:
        """Extract and parse date from text"""
        # Extract date using patterns
        date_str = self._extract_pattern(text, 'date')
        if date_str:
            # Try different date formats
            for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%d/%m/%y', '%d-%m-%y']:
                try:
                    parsed_date = datetime.strptime(date_str, fmt).date()
                    # If it's a 2-digit year and less than 50, assume 2000s, otherwise 1900s
                    if parsed_date.year < 50:
                        parsed_date = parsed_date.replace(year=parsed_date.year + 2000)
                    elif parsed_date.year < 100:
                        parsed_date = parsed_date.replace(year=parsed_date.year + 1900)
                    return parsed_date
                except ValueError:
                    continue
        return None
    
    def _extract_service_provider(self, text: str) -> str:
        """Extract service provider name from text"""
        lines = text.split('\n')

        # MVR vendor: identified by support email; no "Pty Ltd" line in the doc.
        if 'service@mvr.com.au' in text or 'mvr.com.au' in text:
            return 'MVR'

        # Exclusion patterns - companies to ignore (client names, not service providers)
        exclusion_patterns = [
            r'koinonia\s+enterprises?',
            r'koinonia.*pty.*ltd',
            r'pty.*ltd.*koinonia',
        ]
        
        # First try pattern-based extraction (enhanced for new formats)
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
        
        # Enhanced lookup in first few lines for business names
        for i, line in enumerate(lines[:15]):  # Check first 15 lines instead of 10
            line = line.strip()
            if not line:
                continue
                
            # Check against exclusion patterns first
            is_excluded = any(re.search(excl_pattern, line, re.IGNORECASE) 
                            for excl_pattern in exclusion_patterns)
            if is_excluded:
                continue
            
            # Specific pattern for Bridgestone format
            if re.search(r'bridgestone\s+select\s+tyre\s+&\s+auto', line, re.IGNORECASE):
                # Format properly: "Bridgestone Select Tyre & Auto Revesby"
                formatted_line = re.sub(r'\s+', ' ', line.strip())
                # Handle the ampersand properly in title case
                parts = formatted_line.split('&')
                if len(parts) == 2:
                    return f"{parts[0].strip().title()} & {parts[1].strip().title()}"
                else:
                    return formatted_line.title()
            
            # Look for "Company Name Pty Ltd" pattern (case insensitive)
            match = re.search(r'^([A-Z][a-z]+\s+[A-Z][a-z]+\s+Pty\s+Ltd)', line, re.IGNORECASE)
            if match:
                return match.group(1).title()  # Convert to proper case
            
            # Look for lines that contain business indicators (but skip contact info)
            if (line and 
                len(line) > 5 and 
                any(word in line.upper() for word in ['TYRE', 'TYRES', 'AUTO', 'MOTORS', 'AUTOMOTIVE', 'SERVICES']) and
                not any(skip in line.upper() for skip in ['TAX INVOICE', 'BILL TO', 'ADDRESS', 'PHONE', 'INVOICE NUMBER', 'EMAIL', '@']) and
                not re.match(r'^\d+', line.strip())):  # Skip lines starting with numbers (addresses, phone numbers)
                
                # Clean up the line
                clean_line = re.sub(r'\s+', ' ', line.strip())
                return clean_line.title()
        
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
                any(word in line.upper() for word in ['SERVICES', 'SERVICE', 'MOTORS', 'MOTOR', 'AUTOMOTIVE', 'GARAGE', 'WORKSHOP', 'PTY', 'LTD', 'TYRE', 'TYRES']) and
                not any(skip in line.upper() for skip in ['TAX INVOICE', 'INVOICE NUMBER', 'PAYMENT', 'SUBTOTAL', 'TOTAL', 'STEWARDSHIP', 'AUSTRALIA'])):
                return line
        
        # Another fallback: look for the first substantial line that's not a header
        skip_patterns = ['tax invoice', 'invoice number', 'date', 'po number', 'payment term', 'abn', 'mvrl']
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
                if any(word in line.upper() for word in ['SERVICES', 'MOTORS', 'AUTOMOTIVE', 'GARAGE', 'WORKSHOP', 'PTY', 'LTD', 'TYRE', 'TYRES']):
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
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                try:
                    # Take the first match and convert to int
                    odometer_str = matches[0].replace(',', '')
                    return int(odometer_str)
                except ValueError:
                    continue
        return 0
    
    def _extract_total(self, text: str) -> Decimal:
        """Extract total cost with enhanced pattern matching"""
        # Use the pattern extraction method for consistency
        total_str = self._extract_pattern(text, 'total')
        if total_str:
            try:
                # Remove any non-numeric characters except decimal point
                clean_total = re.sub(r'[^\d.]', '', total_str)
                return Decimal(clean_total)
            except (ValueError, TypeError):
                pass
        
        # Fallback to original method if pattern extraction fails
        # First try to find the main total (Balance Due, Total, etc.)
        main_total_patterns = [
            r'total\s*\(inc\s+gst\)\s*\$([0-9,]+\.?\d{0,2})',  # Priority pattern for new format
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

    def _add_preview_metadata(
        self, invoice_data: Optional[InvoiceData], text: str
    ) -> Optional[InvoiceData]:
        """Add financial summary and confidence information for operator review."""
        if not invoice_data:
            return None

        def extract_amount(patterns):
            for pattern in patterns:
                matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
                if matches:
                    try:
                        return Decimal(matches[-1].replace(',', ''))
                    except (InvalidOperation, ValueError):
                        continue
            return None

        subtotal = extract_amount([
            r'^\s*sub\s*total\s*:?[ \t]*\$?[ \t]*([0-9,]+\.\d{2})\s*$',
            r'^\s*subtotal\s*:?[ \t]*\$?[ \t]*([0-9,]+\.\d{2})\s*$',
        ])
        tax_amount = extract_amount([
            r'^\s*(?:gst|total\s+gst|tax)\s*:?[ \t]*\$?[ \t]*([0-9,]+\.\d{2})\s*$',
        ])
        explicit_total = extract_amount([
            r'^\s*(?:grand\s+)?total(?:\s*\(inc\.?\s*gst\))?\s*:?[ \t]*\$?[ \t]*([0-9,]+\.\d{2})\s*$',
            r'^\s*balance\s+due\s*:?[ \t]*\$?[ \t]*([0-9,]+\.\d{2})\s*$',
            r'^\s*amount\s+due\s*:?[ \t]*\$?[ \t]*([0-9,]+\.\d{2})\s*$',
        ])

        invoice_data.subtotal = subtotal
        invoice_data.tax_amount = tax_amount
        if explicit_total is not None:
            invoice_data.total_cost = explicit_total

        invoice_data.confidence = {
            'invoice_number': 'high' if invoice_data.invoice_number else 'low',
            'date': 'high' if invoice_data.date else 'low',
            'vehicle': 'high' if invoice_data.vehicle_rego or invoice_data.vehicle_vin else 'low',
            'odometer': 'high' if invoice_data.odometer_reading else 'low',
            'service_provider': 'high' if invoice_data.service_provider else 'low',
            'items': 'high' if invoice_data.items else 'low',
            'subtotal': 'high' if subtotal is not None else 'low',
            'tax': 'high' if tax_amount is not None else 'low',
            'total': 'high' if explicit_total is not None else 'low',
        }
        return invoice_data
    
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

        # Split text into lines for processing
        lines = text.split('\n')

        # MVR vendor format: items appear between "Miscellaneous Amount" header
        # and "Total Excluding GST" footer, as "DESCRIPTION  AMOUNT" lines.
        # Detected via the MVR support email so it doesn't affect other vendors.
        if 'service@mvr.com.au' in text or 'mvr.com.au' in text:
            mvr_items = self._extract_mvr_items(lines)
            if mvr_items:
                return mvr_items

        # First, try to detect numbered list items (like "1. oil and oil filter a changed")
        numbered_items = self._extract_numbered_items(lines)
        if numbered_items:
            items.extend(numbered_items)
        
        # Second, try to detect simple format items (description price without numbering)
        if not items:
            simple_items = self._extract_simple_format_items(lines)
            if simple_items:
                items.extend(simple_items)
        
        # If no simple items found, try other patterns as final fallback
        if not items:
            items = self._extract_line_items_patterns(lines)
        
        logger.debug(f"Extracted {len(items)} items from text")
        return items
    
    def _extract_mvr_items(self, lines: List[str]) -> List[InvoiceItem]:
        """
        Extract items from MVR-format invoices. Items live between the
        "Miscellaneous Amount" header and the "Total Excluding GST" footer,
        in "<description>  <amount>" form (no $, no quantity column).
        """
        items = []
        in_section = False

        labor_keywords = ['labour', 'labor', 'service', 'install', 'check',
                          'inspection', 'adjustment', 'adjust', 'remove',
                          'replace', 'repair', 'top up', 'reset', 'test']
        # Trailing amount, optional minus sign, no $ sign
        amount_re = re.compile(r'^(.+?)\s+(-?\d+\.\d{2})\s*$')

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            lower = line.lower()

            if not in_section:
                if 'miscellaneous' in lower and 'amount' in lower:
                    in_section = True
                continue

            # End of items section
            if (lower.startswith('total excluding gst')
                    or lower.startswith('gst amount')
                    or lower.startswith('total payable')
                    or lower.startswith('payment terms')):
                break

            m = amount_re.match(line)
            if not m:
                # Description-only continuation line (e.g. "AND REPLACE BRAKE PADS")
                # belongs to the previous item; merge into its description.
                if items and re.search(r'[A-Za-z]', line):
                    items[-1].description = f"{items[-1].description} {line}".strip()
                continue

            description = m.group(1).strip()
            try:
                amount = Decimal(m.group(2))
            except (InvalidOperation, ValueError):
                continue

            # Skip the bare subtotal line (description ends up empty / numeric)
            if not description or not re.search(r'[A-Za-z]', description):
                continue

            # Skip invoice adjustment / discount rows that aren't real items
            if 'invoice adjustment' in description.lower():
                continue

            item_type = 'labor' if any(kw in description.lower() for kw in labor_keywords) else 'parts'

            items.append(InvoiceItem(
                description=description,
                quantity=1,
                unit_cost=amount,
                item_type=item_type,
            ))

        return items

    def _extract_numbered_items(self, lines: List[str]) -> List[InvoiceItem]:
        """
        Extract items from numbered lists like:
        1. oil and oil filter a changed 240.00
        Ford Ranger 2020 
        1HEI701
        """
        items = []
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            # Look for numbered item pattern like "1. description price" (price on same line)
            numbered_match = re.match(r'^(\d+)\.\s+(.+?)\s+(\d+\.?\d{0,2})$', line, re.IGNORECASE)
            if numbered_match:
                item_number = numbered_match.group(1)
                description = numbered_match.group(2).strip()
                price = Decimal(numbered_match.group(3))
                
                # Look ahead for vehicle info and rego
                vehicle_info = ""
                rego = ""
                
                # Check next few lines for vehicle details
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_line = lines[j].strip()
                    if not next_line:
                        continue
                    
                    # Check if this line contains vehicle info (like "Ford Ranger 2020")
                    if re.match(r'^[A-Za-z]+\s+[A-Za-z]+\s+\d{4}$', next_line):
                        vehicle_info = next_line
                        continue
                    
                    # Check if this line is a rego number
                    rego_match = re.match(r'^([A-Z0-9]{6,8})$', next_line)
                    if rego_match:
                        rego = rego_match.group(1)
                        i = j  # Move index to after the rego line
                        break
                    
                    # If we hit another numbered item, stop looking
                    if re.match(r'^\d+\.\s+', next_line):
                        break
                
                # Create item
                if price > 0:
                    # Enhance description with vehicle info if available
                    full_description = description
                    if vehicle_info:
                        full_description += f" ({vehicle_info})"
                    if rego:
                        full_description += f" - {rego}"
                    
                    # Determine item type
                    labor_keywords = ['labour', 'labor', 'service', 'install', 'check', 'adjust', 
                                    'inspect', 'test', 'reset', 'road test', 'visually inspect', 
                                    'change', 'changed', 'replace', 'replaced']
                    item_type = 'labor' if any(word in description.lower() for word in labor_keywords) else 'parts'
                    
                    items.append(InvoiceItem(
                        description=full_description,
                        quantity=1,
                        unit_cost=price,
                        item_type=item_type
                    ))
                    
                    logger.debug(f"Found numbered item {item_number}: {full_description} - ${price}")
            
            i += 1
        
        return items
    
    def _extract_simple_format_items(self, lines: List[str]) -> List[InvoiceItem]:
        """
        Extract items from simple format like:
        oil and oil filter a changed 240.00
        Globe a changed 50.00
        Vehicle Safety checked 0.00
        """
        items = []
        
        # Keywords that indicate maintenance items
        maintenance_keywords = ['oil', 'filter', 'changed', 'globe', 'safety', 'checked', 'service', 
                               'labour', 'labor', 'repair', 'replace', 'brake', 'pad', 'diesel', 
                               'light', 'bulb', 'transmission', 'engine', 'tire', 'tyre', 'wheel', 
                               'battery', 'alternator', 'starter', 'radiator', 'coolant', 'spark', 
                               'plug', 'belt', 'hose', 'gasket', 'seal', 'bearing', 'suspension',
                               'shock', 'strut', 'spring', 'exhaust', 'muffler', 'catalytic',
                               'air', 'fuel', 'cabin', 'wiper', 'headlight', 'taillight', 'indicator']
        
        # Skip keywords that indicate non-item lines
        skip_keywords = ['ayp auto repairs', 'services wa pty', 'burwash place', 'maddington', 
                        'abn:', 'mrb no:', 'bill to', 'invoice #', 'invoice date', 'ford ranger',
                        'toyota hilux', 'description amount', 'subtotal', 'gst', 'invoice total',
                        'terms & conditions', 'payment is due', 'bank :', 'bsb:', 'account',
                        'contact', 'email', 'phone', 'address', 'pty ltd', 'ltd', 'wa', 'nsw',
                        'qld', 'vic', 'sa', 'nt', 'tas', 'act']
        
        for line in lines:
            line = line.strip()
            if not line or len(line) < 10:  # Skip very short lines
                continue
                
            # Skip lines that contain skip keywords
            if any(keyword in line.lower() for keyword in skip_keywords):
                continue
            
            # Only process lines that contain maintenance keywords
            has_maintenance_keyword = any(keyword in line.lower() for keyword in maintenance_keywords)
            if not has_maintenance_keyword:
                continue
            
            # Look for pattern: description followed by price (description price)
            simple_match = re.match(r'^(.+?)\s+(\d+\.?\d{0,2})$', line)
            if simple_match:
                description = simple_match.group(1).strip()
                price_str = simple_match.group(2)
                
                # Additional validation
                try:
                    price = Decimal(price_str)
                    
                    # Make sure description is reasonable length and contains letters
                    if len(description) >= 5 and re.search(r'[a-zA-Z]', description):
                        # Skip if it looks like a year, invoice number, or other ID
                        if not re.match(r'^(19|20)\d{2}$', price_str) and price >= 0:
                            # Determine item type based on keywords
                            labor_keywords = ['service', 'labour', 'labor', 'install', 'check', 'checked',
                                            'inspect', 'repair', 'fix', 'adjust', 'calibrate', 'test',
                                            'change', 'changed', 'replace', 'replaced']
                            item_type = 'labor' if any(word in description.lower() for word in labor_keywords) else 'parts'
                            
                            items.append(InvoiceItem(
                                description=description,
                                quantity=1,
                                unit_cost=price,
                                item_type=item_type
                            ))
                            
                            logger.debug(f"Found simple format item: {description} - ${price}")
                            
                except (ValueError, InvalidOperation):
                    # Skip lines where price can't be converted to decimal
                    continue
        
        return items
    
    def _extract_line_items_patterns(self, lines: List[str]) -> List[InvoiceItem]:
        """Extract items using various line patterns as fallback"""
        items = []
        
        # Look for common patterns in service invoices
        patterns = [
            # New pattern for numbered invoices: "×2 Headlight Globe a changed 100.00"
            r'^×(\d+)\s+([a-zA-Z][a-zA-Z\s&.,()]{2,50}?)\s+([0-9,]+\.?\d{2})\s*$',
            # Pattern: Description followed by quantity, unit price, and total (like the invoice table)
            r'^([a-zA-Z][a-zA-Z\s&.,()]{2,50}?)\s+([0-9.]+)\s+\$([0-9,]+\.?\d{2})\s+\$([0-9,]+\.?\d{2})\s*$',
            # Pattern: Description with quantity and total only
            r'^([a-zA-Z][a-zA-Z\s&.,()]{2,50}?)\s+([0-9.]+)\s+\$([0-9,]+\.?\d{2})\s*$', 
            # Pattern: Description followed by cost at end
            r'^([a-zA-Z][a-zA-Z\s&.,()]{3,50}?)\s+\$([0-9,]+\.?\d{2})\s*$',
            # Pattern: Any description followed by numbers (fallback)
            r'([a-zA-Z][a-zA-Z\s&.,()]{5,50}?)\s+([0-9.]+)\s*([0-9,]+\.?\d{2})\s*([0-9,]+\.?\d{2})',
        ]
        
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
                        
                        if i == 0:  # New format: ×qty description total
                            quantity = int(groups[0])
                            description = groups[1].strip()
                            total_cost = Decimal(groups[2].replace(',', ''))
                            unit_cost = total_cost / quantity if quantity > 0 else total_cost
                        elif i == 1:  # Full pattern: desc, qty, unit_price, total
                            description = groups[0].strip()
                            quantity = int(float(groups[1]))
                            unit_cost = Decimal(groups[2].replace(',', ''))
                            total_cost = Decimal(groups[3].replace(',', ''))
                        elif i == 2:  # desc, qty, total
                            description = groups[0].strip()
                            quantity = int(float(groups[1]))
                            total_cost = Decimal(groups[2].replace(',', ''))
                            unit_cost = total_cost / quantity if quantity > 0 else total_cost
                        elif i == 3:  # desc, total
                            description = groups[0].strip()
                            quantity = 1
                            total_cost = Decimal(groups[1].replace(',', ''))
                            unit_cost = total_cost
                        else:  # fallback pattern
                            description = groups[0].strip()
                            quantity = int(float(groups[1])) if groups[1] else 1
                            unit_cost = Decimal(groups[2].replace(',', '')) if len(groups) > 2 else Decimal('0')
                            total_cost = Decimal(groups[3].replace(',', '')) if len(groups) > 3 else unit_cost * quantity
                        
                        # Skip if description is too short or looks like header
                        if len(description) < 3 or description.lower() in ['qty', 'unit', 'total']:
                            continue
                        
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
