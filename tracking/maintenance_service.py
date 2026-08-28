from django.db import transaction
from django.core.exceptions import ValidationError
from typing import Optional, List, Tuple
import logging

from .models import Car, Maintenance, MaintenanceItem
from .pdf_invoice_parser import PDFInvoiceParser, InvoiceData, validate_invoice_data
from .invoice_utils import normalize_invoice_number

logger = logging.getLogger(__name__)

class MaintenanceInvoiceService:
    """Service class to handle PDF invoice imports into Django maintenance system"""
    
    def __init__(self):
        self.pdf_parser = PDFInvoiceParser()
    
    def import_pdf_invoice(self, pdf_path: str, auto_create_car: bool = False, skip_existing: bool = False) -> Tuple[bool, str, Optional[Maintenance]]:
        """
        Import a PDF invoice into the maintenance system
        
        Args:
            pdf_path: Path to the PDF invoice file
            auto_create_car: Whether to create a new car if not found
            skip_existing: Whether to skip existing invoices instead of updating them
            
        Returns:
            Tuple of (success, message, maintenance_record)
        """
        try:
            # Parse the PDF
            invoice_data = self.pdf_parser.parse_pdf(pdf_path)
            if not invoice_data:
                return False, "Failed to parse PDF invoice", None

            invoice_data.invoice_number = normalize_invoice_number(invoice_data.invoice_number)
            
            # Validate that we have items to import
            if not invoice_data.items:
                return False, "No maintenance items found in PDF invoice", None
                
            # Validate the extracted data
            validation_errors = validate_invoice_data(invoice_data)
            if validation_errors:
                return False, f"Validation errors: {', '.join(validation_errors)}", None
            
            # Create maintenance record
            maintenance = self.create_maintenance_from_invoice(invoice_data, auto_create_car, skip_existing)
            if maintenance:
                return True, f"Successfully imported invoice {invoice_data.invoice_number}", maintenance
            else:
                return False, f"Skipped existing invoice {invoice_data.invoice_number}", None
            
        except Exception as e:
            logger.error(f"Error importing PDF invoice {pdf_path}: {str(e)}")
            return False, f"Import failed: {str(e)}", None
    
    def create_maintenance_from_invoice(self, invoice_data: InvoiceData, auto_create_car: bool = False, skip_existing: bool = False) -> Optional[Maintenance]:
        """
        Create or update maintenance record and items from parsed invoice data
        
        Args:
            invoice_data: Parsed invoice data
            auto_create_car: Whether to create car if not found
            skip_existing: Whether to skip existing invoices instead of updating them
            
        Returns:
            Created/Updated Maintenance instance, or None if skipped
            
        Raises:
            ValidationError: If car not found and auto_create_car is False
        """
        with transaction.atomic():
            invoice_number = normalize_invoice_number(invoice_data.invoice_number)
            invoice_data.invoice_number = invoice_number

            # Get or create the car
            car = self._get_or_create_car(invoice_data, auto_create_car)
            
            # Prepare maintenance data
            maintenance_data = {
                'car': car,
                'service_date': invoice_data.date,
                'odometer_reading': invoice_data.odometer_reading or 0,
                'service_type': self._determine_service_type(invoice_data),
                'service_provider': invoice_data.service_provider or 'PDF Import',
                'total_cost': invoice_data.total_cost,
                'description': f"Imported from PDF invoice: {invoice_data.invoice_number}"
            }
            
            if skip_existing:
                # Check if maintenance record already exists and skip if it does
                if Maintenance.objects.filter(invoice_number=invoice_number).exists():
                    logger.info(f"Skipped existing invoice {invoice_data.invoice_number}")
                    return None
                
                # Create new maintenance record
                maintenance = Maintenance.objects.create(
                    invoice_number=invoice_number,
                    **maintenance_data
                )
                created = True
            else:
                # Use update_or_create to handle both new and existing records
                maintenance, created = Maintenance.objects.update_or_create(
                    invoice_number=invoice_number,
                    defaults=maintenance_data
                )
                
                # Delete existing maintenance items if updating
                if not created:
                    maintenance.items.all().delete()
            
            # Create maintenance items
            for item_data in invoice_data.items:
                MaintenanceItem.objects.create(
                    maintenance=maintenance,
                    description=item_data.description,
                    item_type=item_data.item_type,
                    quantity=item_data.quantity,
                    unit_cost=item_data.unit_cost
                )
            
            action = "Created" if created else "Updated"
            logger.info(f"{action} maintenance record {maintenance.id} for car {car.rego}")
            return maintenance
    
    def _get_or_create_car(self, invoice_data: InvoiceData, auto_create: bool) -> Car:
        """Get existing car or create new one if auto_create is True"""
        
        # Try to find car by registration first
        if invoice_data.vehicle_rego:
            try:
                return Car.objects.get(rego=invoice_data.vehicle_rego)
            except Car.DoesNotExist:
                logger.warning(f"Car with rego {invoice_data.vehicle_rego} not found in database")
        
        # Try to find by VIN
        if invoice_data.vehicle_vin:
            try:
                return Car.objects.get(vin_number=invoice_data.vehicle_vin)
            except Car.DoesNotExist:
                logger.warning(f"Car with VIN {invoice_data.vehicle_vin} not found in database")
        
        # If not found and auto_create is True, create new car
        if auto_create:
            if not invoice_data.vehicle_rego:
                raise ValidationError("Cannot create car without registration number")
            
            from django.utils import timezone
            from datetime import timedelta
                
            car = Car.objects.create(
                rego=invoice_data.vehicle_rego,
                rego_expiry_date=timezone.now().date() + timedelta(days=365),  # Default to 1 year from now
                vin_number=invoice_data.vehicle_vin or f"VIN-{invoice_data.vehicle_rego}",  # Use rego as fallback for VIN
                make='Unknown',
                model='Unknown'
            )
            logger.info(f"Auto-created car {car.rego}")
            return car
        
        # Car not found and auto_create is False - provide helpful error
        if invoice_data.vehicle_rego:
            available_regos = Car.objects.all().values_list('rego', flat=True)[:10]  # Show first 10 for reference
            raise ValidationError(
                f"Car with registration '{invoice_data.vehicle_rego}' not found in database. "
                f"Available cars include: {', '.join(available_regos)}. "
                f"Please check the rego or add --auto-create-car flag if this is a new vehicle."
            )
        else:
            raise ValidationError("No vehicle registration found in invoice and auto_create_car is disabled")
    
    def _determine_service_type(self, invoice_data: InvoiceData) -> str:
        """Determine service type based on invoice items"""
        if not invoice_data.items:
            return 'regular'
        
        # Check item descriptions for service type indicators
        item_descriptions = [item.description.lower() for item in invoice_data.items]
        all_descriptions = ' '.join(item_descriptions)
        
        # Service type mapping based on keywords
        if any(keyword in all_descriptions for keyword in ['oil change', 'service', 'maintenance']):
            return 'regular'
        elif any(keyword in all_descriptions for keyword in ['repair', 'fix', 'replace']):
            return 'repair'
        elif any(keyword in all_descriptions for keyword in ['brake', 'brakes']):
            return 'repair'
        elif any(keyword in all_descriptions for keyword in ['tire', 'tyre', 'wheel']):
            return 'repair'
        elif any(keyword in all_descriptions for keyword in ['inspection', 'check']):
            return 'inspection'
        else:
            return 'regular'
    
    def batch_import_pdfs(
        self, pdf_paths: List[str], auto_create_car: bool = False, skip_existing: bool = False
    ) -> List[Tuple[str, bool, str]]:
        """
        Import multiple PDF invoices
        
        Args:
            pdf_paths: List of PDF file paths
            auto_create_car: Whether to create cars if not found
            skip_existing: If True, skip invoices that already exist instead of updating

        Returns:
            List of tuples (file_path, success, message)
        """
        results = []
        
        for pdf_path in pdf_paths:
            success, message, _ = self.import_pdf_invoice(pdf_path, auto_create_car, skip_existing)
            results.append((pdf_path, success, message))
            
            if success:
                logger.info(f"Successfully imported {pdf_path}")
            else:
                logger.error(f"Failed to import {pdf_path}: {message}")
        
        return results
    
    def preview_pdf_data(self, pdf_path: str) -> Optional[InvoiceData]:
        """
        Preview what data would be extracted from a PDF without saving
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            InvoiceData object or None if parsing fails
        """
        return self.pdf_parser.parse_pdf(pdf_path)
    
    def validate_pdf_for_import(self, pdf_path: str) -> Tuple[bool, List[str]]:
        """
        Validate if a PDF can be imported
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        try:
            invoice_data = self.pdf_parser.parse_pdf(pdf_path)
            if not invoice_data:
                return False, ["Failed to parse PDF"]

            invoice_data.invoice_number = normalize_invoice_number(invoice_data.invoice_number)
            
            errors = validate_invoice_data(invoice_data)
            
            # Additional Django-specific validations
            if invoice_data.vehicle_rego:
                if not Car.objects.filter(rego=invoice_data.vehicle_rego).exists():
                    errors.append(f"Car with registration {invoice_data.vehicle_rego} not found in database")
            
            return len(errors) == 0, errors
            
        except Exception as e:
            return False, [f"Validation error: {str(e)}"]

# Convenience functions
def import_pdf_invoice(pdf_path: str, auto_create_car: bool = False, skip_existing: bool = False) -> Tuple[bool, str, Optional[Maintenance]]:
    """
    Convenience function to import a single PDF invoice
    
    Args:
        pdf_path: Path to PDF file
        auto_create_car: Whether to create car if not found
        skip_existing: Whether to skip existing invoices instead of updating them
        
    Returns:
        Tuple of (success, message, maintenance_record)
    """
    service = MaintenanceInvoiceService()
    return service.import_pdf_invoice(pdf_path, auto_create_car, skip_existing)

def preview_pdf_invoice(pdf_path: str) -> Optional[InvoiceData]:
    """
    Convenience function to preview PDF data without importing
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        InvoiceData object or None
    """
    service = MaintenanceInvoiceService()
    return service.preview_pdf_data(pdf_path)
