from django.core.management.base import BaseCommand
from tracking.models import Car, Maintenance, MaintenanceItem
from tracking.maintenance_service import MaintenanceInvoiceService, preview_pdf_invoice
from tracking.invoice_utils import normalize_invoice_number
from datetime import datetime
import csv
import os
from decimal import Decimal
from django.db import transaction

class Command(BaseCommand):
    help = 'Import maintenance invoices from a CSV file'

    def add_arguments(self, parser):
        parser.add_argument('input_path', type=str, help='Path to the CSV/PDF file or folder containing PDFs')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Do a dry run without saving to database',
        )
        parser.add_argument(
            '--auto-create-car',
            action='store_true',
            help='Automatically create car records if not found (PDF only)',
        )
        parser.add_argument(
            '--file-type',
            choices=['auto', 'csv', 'pdf'],
            default='auto',
            help='Specify file type (auto-detect by default)',
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip existing maintenance records instead of updating them',
        )
        parser.add_argument(
            '--recursive',
            action='store_true',
            help='Process folders recursively (when input is a folder)',
        )

    def handle(self, *args, **kwargs):
        input_path = kwargs['input_path']
        dry_run = kwargs.get('dry_run', False)
        auto_create_car = kwargs.get('auto_create_car', False)
        file_type = kwargs.get('file_type', 'auto')
        skip_existing = kwargs.get('skip_existing', False)
        recursive = kwargs.get('recursive', False)
        
        if dry_run:
            self.stdout.write('Performing dry run - no changes will be saved')
        
        self.stdout.write(f'Skip existing records: {skip_existing}')
        
        # Check if input is a file or directory
        if os.path.isfile(input_path):
            # Single file processing
            self._process_single_file(input_path, file_type, dry_run, auto_create_car, skip_existing)
        elif os.path.isdir(input_path):
            # Directory processing
            self._process_directory(input_path, dry_run, auto_create_car, skip_existing, recursive)
        else:
            self.stdout.write(self.style.ERROR(f'Path {input_path} does not exist'))
            return
                
        self.stdout.write(self.style.SUCCESS('Successfully processed all files'))
    
    def _process_single_file(self, file_path: str, file_type: str, dry_run: bool, auto_create_car: bool, skip_existing: bool):
        """Process a single file"""
        # Determine file type
        if file_type == 'auto':
            file_type = self._detect_file_type(file_path)
        
        self.stdout.write(f'Processing {file_type.upper()} file: {file_path}')
        
        try:
            if file_type == 'csv':
                self._handle_csv(file_path, dry_run, skip_existing)
            elif file_type == 'pdf':
                self._handle_pdf(file_path, dry_run, auto_create_car, skip_existing)
            else:
                self.stdout.write(self.style.ERROR(f'Unsupported file type: {file_type}'))
                return
                
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'File {file_path} not found'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error processing file {file_path}: {str(e)}'))
    
    def _process_directory(self, dir_path: str, dry_run: bool, auto_create_car: bool, skip_existing: bool, recursive: bool):
        """Process all PDF files in a directory"""
        self.stdout.write(f'Processing directory: {dir_path} (recursive: {recursive})')
        
        pdf_files = []
        
        if recursive:
            # Get all PDF files recursively
            for root, dirs, files in os.walk(dir_path):
                for file in files:
                    if file.lower().endswith('.pdf'):
                        pdf_files.append(os.path.join(root, file))
        else:
            # Get PDF files only in the specified directory
            for file in os.listdir(dir_path):
                file_path = os.path.join(dir_path, file)
                if os.path.isfile(file_path) and file.lower().endswith('.pdf'):
                    pdf_files.append(file_path)
        
        if not pdf_files:
            self.stdout.write(self.style.WARNING(f'No PDF files found in {dir_path}'))
            return
        
        self.stdout.write(f'Found {len(pdf_files)} PDF files to process')
        
        success_count = 0
        error_count = 0
        
        for pdf_file in sorted(pdf_files):
            relative_path = os.path.relpath(pdf_file, dir_path)
            try:
                self.stdout.write(f'\nProcessing: {relative_path}')
                ok = self._handle_pdf(pdf_file, dry_run, auto_create_car, skip_existing)
                if ok:
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error processing {relative_path}: {str(e)}'))
                error_count += 1
                continue
        
        # Summary
        self.stdout.write(f'\nSUMMARY:')
        self.stdout.write(f'Successfully processed: {success_count} files')
        if error_count > 0:
            self.stdout.write(f'Errors: {error_count} files')
        self.stdout.write(f'Total files: {len(pdf_files)}')
    
    def _detect_file_type(self, file_path: str) -> str:
        """Auto-detect file type based on extension"""
        _, ext = os.path.splitext(file_path.lower())
        if ext == '.csv':
            return 'csv'
        elif ext == '.pdf':
            return 'pdf'
        else:
            return 'csv'  # Default to CSV
    
    def _handle_csv(self, csv_file: str, dry_run: bool, skip_existing: bool = False):
        """Handle CSV file import"""
        with open(csv_file, 'r') as file:
            reader = csv.DictReader(file)
            current_invoice = None
            items = []
            
            for row in reader:
                self.stdout.write(f'Processing CSV row: {row}')
                inv_key = normalize_invoice_number(row.get('Invoice No', ''))
                if not inv_key:
                    self.stdout.write(self.style.ERROR(
                        'Skipping row: Invoice No is required and cannot be empty'
                    ))
                    continue
                # If this is a new invoice
                if current_invoice != inv_key:
                    # Save previous invoice if exists
                    if current_invoice and items:
                        self._create_maintenance_record(items, dry_run, skip_existing)
                    
                    # Start new invoice
                    current_invoice = inv_key
                    items = [row]
                else:
                    # Add item to current invoice
                    items.append(row)
            
            # Save last invoice
            if items:
                self._create_maintenance_record(items, dry_run, skip_existing)
    
    def _handle_pdf(self, pdf_file: str, dry_run: bool, auto_create_car: bool, skip_existing: bool = False):
        """Handle PDF file import. Returns True if import/preview succeeded, False otherwise."""
        if dry_run:
            # Preview the PDF data
            invoice_data = preview_pdf_invoice(pdf_file)
            if invoice_data:
                invoice_data.invoice_number = normalize_invoice_number(invoice_data.invoice_number)
                self.stdout.write('PDF Preview:')
                self.stdout.write(f'  Invoice: {invoice_data.invoice_number}')
                self.stdout.write(f'  Date: {invoice_data.date}')
                self.stdout.write(f'  Vehicle: {invoice_data.vehicle_rego}')
                self.stdout.write(f'  Total: ${invoice_data.total_cost}')
                self.stdout.write(f'  Items: {len(invoice_data.items)}')
                for item in invoice_data.items:
                    self.stdout.write(f'    - {item.description}: ${item.unit_cost}')
                
                # Check if record exists
                existing = Maintenance.objects.filter(invoice_number=invoice_data.invoice_number).exists()
                if existing:
                    if skip_existing:
                        self.stdout.write(f'  Would skip: Invoice {invoice_data.invoice_number} already exists')
                    else:
                        self.stdout.write(f'  Would update: Invoice {invoice_data.invoice_number} already exists')
                else:
                    self.stdout.write(f'  Would create: New invoice {invoice_data.invoice_number}')
                return True
            else:
                self.stdout.write(self.style.WARNING('Could not preview PDF data'))
                return False
        else:
            # Actually import the PDF
            service = MaintenanceInvoiceService()
            success, message, maintenance = service.import_pdf_invoice(pdf_file, auto_create_car, skip_existing)
            
            if success:
                self.stdout.write(self.style.SUCCESS(message))
            else:
                self.stdout.write(self.style.ERROR(message))
            return success
    
    def _parse_date(self, date_str):
        """Parse date from DD/MM/YYYY format"""
        try:
            return datetime.strptime(date_str, '%d/%m/%Y').date()
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f'Error parsing date {date_str}: {str(e)}'))
            raise
    
    def _create_maintenance_record(self, items, dry_run=False, skip_existing=False):
        """Create or update a maintenance record with its items from CSV rows"""
        if not items:
            return
            
        first_item = items[0]  # All items have same invoice details
        
        try:
            with transaction.atomic():
                # Get the car
                try:
                    car = Car.objects.get(rego=first_item['Rego'])
                except Car.DoesNotExist:
                    self.stdout.write(self.style.ERROR(f'Car with rego {first_item["Rego"]} not found'))
                    return

                invoice_number = normalize_invoice_number(first_item.get('Invoice No', ''))
                if not invoice_number:
                    self.stdout.write(self.style.ERROR(
                        'Invoice No is required and cannot be empty for CSV import'
                    ))
                    return

                if dry_run:
                    existing = Maintenance.objects.filter(invoice_number=invoice_number).exists()
                    if existing:
                        if skip_existing:
                            self.stdout.write(f'Would skip maintenance record for {car.rego} - Invoice {invoice_number} (already exists)')
                        else:
                            self.stdout.write(f'Would update maintenance record for {car.rego} - Invoice {invoice_number}')
                    else:
                        self.stdout.write(f'Would create maintenance record for {car.rego} - Invoice {invoice_number}')
                    return

                # Prepare maintenance data
                maintenance_data = {
                    'car': car,
                    'service_date': self._parse_date(first_item['Date']),
                    'odometer_reading': int(first_item['KMs']),
                    'service_type': 'regular',  # Default to regular service
                    'service_provider': 'Auto Import',  # Default service provider
                    'total_cost': Decimal(first_item['Total Invoice Cost']),
                    'description': f'Imported from CSV - {len(items)} items'
                }

                if skip_existing:
                    # Check if maintenance record already exists and skip if it does
                    if Maintenance.objects.filter(invoice_number=invoice_number).exists():
                        self.stdout.write(self.style.WARNING(
                            f'Skipped: Maintenance record with invoice {invoice_number} already exists'
                        ))
                        return
                    
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
                for item in items:
                    MaintenanceItem.objects.create(
                        maintenance=maintenance,
                        description=item['Item Description'],
                        item_type='parts' if 'Oil' in item['Item Description'] else 'labor',
                        quantity=1,  # Default quantity
                        unit_cost=Decimal(item['Item Cost'])
                    )
                
                action = 'Created' if created else 'Updated'
                symbol = '+' if created else '~'
                self.stdout.write(self.style.SUCCESS(
                    f'{symbol} {action} maintenance record for {car.rego} - Invoice {invoice_number} (${maintenance.total_cost})'
                ))
                    
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error processing maintenance record: {str(e)}'))
            raise