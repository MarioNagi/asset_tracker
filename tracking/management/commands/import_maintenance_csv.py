import csv
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_date
from tracking.models import Car, Maintenance, MaintenanceItem
from tracking.invoice_utils import normalize_invoice_number


class Command(BaseCommand):
    help = 'Import maintenance records from CSV file'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'csv_file',
            type=str,
            help='Path to the CSV file containing maintenance data'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would be imported without actually saving to database'
        )
        parser.add_argument(
            '--auto-create-car',
            action='store_true',
            help='Automatically create car if it does not exist'
        )
    
    def handle(self, *args, **options):
        csv_file = options['csv_file']
        dry_run = options.get('dry_run', False)
        auto_create_car = options.get('auto_create_car', False)
        
        if not os.path.exists(csv_file):
            self.stdout.write(
                self.style.ERROR(f'CSV file not found: {csv_file}')
            )
            return
        
        self.stdout.write(f'Processing CSV file: {csv_file}')
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No data will be saved'))
        
        try:
            with open(csv_file, 'r', encoding='utf-8-sig') as file:
                # Peek at first line to detect format
                first_line = file.readline().strip()
                file.seek(0)
                
                if self._is_maintenance_format(first_line):
                    self._import_maintenance_records(file, dry_run, auto_create_car)
                elif self._is_maintenance_items_format(first_line):
                    self._import_maintenance_items(file, dry_run)
                else:
                    self.stdout.write(
                        self.style.ERROR('Unknown CSV format. Expected headers for maintenance records or maintenance items.')
                    )
                    self._show_expected_formats()
                    
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error processing CSV file: {str(e)}')
            )
    
    def _is_maintenance_format(self, first_line):
        """Check if CSV has maintenance record headers"""
        required_headers = {'car_rego', 'service_date', 'service_type'}
        headers = {h.strip().lower() for h in first_line.split(',')}
        return required_headers.issubset(headers)
    
    def _is_maintenance_items_format(self, first_line):
        """Check if CSV has maintenance items headers"""
        required_headers = {'maintenance_id', 'description', 'quantity', 'unit_cost'}
        headers = {h.strip().lower() for h in first_line.split(',')}
        return required_headers.issubset(headers)
    
    def _import_maintenance_records(self, file, dry_run, auto_create_car):
        """Import maintenance records from CSV"""
        reader = csv.DictReader(file)
        
        # Normalize headers (remove spaces, convert to lowercase)
        reader.fieldnames = [header.strip().lower().replace(' ', '_') for header in reader.fieldnames]
        
        success_count = 0
        error_count = 0
        
        for row_num, row in enumerate(reader, start=2):
            try:
                with transaction.atomic():
                    maintenance_data = self._process_maintenance_row(row, auto_create_car, dry_run)
                    
                    if dry_run:
                        car_rego = maintenance_data.get('car_rego', '')
                        inv = normalize_invoice_number(maintenance_data.get('invoice_number', ''))
                        if inv:
                            exists = Maintenance.objects.filter(invoice_number=inv).exists()
                            verb = 'Would update' if exists else 'Would create'
                            self.stdout.write(
                                f'Row {row_num}: {verb} maintenance record for {car_rego} (invoice {inv})'
                            )
                        else:
                            self.stdout.write(
                                f'Row {row_num}: Would create maintenance record for {car_rego} (no invoice_number)'
                            )
                    else:
                        car = maintenance_data['car']
                        inv = normalize_invoice_number(maintenance_data.get('invoice_number', ''))
                        if inv:
                            defaults = dict(maintenance_data)
                            maintenance, created = Maintenance.objects.update_or_create(
                                invoice_number=inv,
                                defaults=defaults,
                            )
                            action = 'Updated' if not created else 'Created'
                        else:
                            maintenance = Maintenance.objects.create(**maintenance_data)
                            action = 'Created'
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'Row {row_num}: {action} maintenance record #{maintenance.id} for {maintenance.car.rego}'
                            )
                        )
                    
                    success_count += 1
                    
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'Row {row_num}: Error - {str(e)}')
                )
        
        self.stdout.write(f'\nSummary: {success_count} successful, {error_count} errors')
    
    def _import_maintenance_items(self, file, dry_run):
        """Import maintenance items from CSV"""
        reader = csv.DictReader(file)
        
        # Normalize headers
        reader.fieldnames = [header.strip().lower().replace(' ', '_') for header in reader.fieldnames]
        
        success_count = 0
        error_count = 0
        
        for row_num, row in enumerate(reader, start=2):
            try:
                with transaction.atomic():
                    item_data = self._process_maintenance_item_row(row, dry_run)
                    
                    if dry_run:
                        self.stdout.write(f'Row {row_num}: Would create maintenance item for maintenance #{item_data["maintenance_id"]}')
                    else:
                        item = MaintenanceItem.objects.create(**item_data)
                        self.stdout.write(
                            self.style.SUCCESS(f'Row {row_num}: Created maintenance item #{item.id}')
                        )
                    
                    success_count += 1
                    
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'Row {row_num}: Error - {str(e)}')
                )
        
        self.stdout.write(f'\nSummary: {success_count} successful, {error_count} errors')
    
    def _process_maintenance_row(self, row, auto_create_car, dry_run):
        """Process a single maintenance record row"""
        # Required fields
        car_rego = row.get('car_rego', '').strip()
        if not car_rego:
            raise ValueError('car_rego is required')
        
        service_date_str = row.get('service_date', '').strip()
        if not service_date_str:
            raise ValueError('service_date is required')
        
        service_type = row.get('service_type', '').strip().lower()
        if not service_type:
            service_type = 'regular'
        
        # Validate service_type
        valid_service_types = ['regular', 'repair', 'inspection', 'accident', 'other']
        if service_type not in valid_service_types:
            raise ValueError(f'Invalid service_type: {service_type}. Must be one of: {valid_service_types}')
        
        # Parse date
        service_date = self._parse_date(service_date_str)
        if not service_date:
            raise ValueError(f'Invalid date format: {service_date_str}. Use YYYY-MM-DD or DD/MM/YYYY')
        
        # Get or create car
        try:
            car = Car.objects.get(rego=car_rego)
        except Car.DoesNotExist:
            if auto_create_car and not dry_run:
                car = Car.objects.create(
                    rego=car_rego,
                    make='Unknown',
                    model='Unknown',
                    year=2020,
                    state='NSW-Wireless'  # Default state
                )
                self.stdout.write(f'Created new car: {car_rego}')
            elif dry_run:
                # For dry run, we'll assume the car would be created
                pass
            else:
                raise ValueError(f'Car with rego {car_rego} not found. Use --auto-create-car to create it automatically.')
        
        # Optional fields
        odometer_reading = self._parse_int(row.get('odometer_reading', '0'))
        invoice_number = normalize_invoice_number(row.get('invoice_number', ''))
        service_provider = row.get('service_provider', 'Unknown Provider').strip()
        description = row.get('description', '').strip()
        total_cost = self._parse_decimal(row.get('total_cost', '0.00'))
        
        maintenance_data = {
            'service_date': service_date,
            'odometer_reading': odometer_reading,
            'service_type': service_type,
            'invoice_number': invoice_number,
            'service_provider': service_provider,
            'description': description,
            'total_cost': total_cost,
        }
        
        if not dry_run:
            maintenance_data['car'] = car
        else:
            maintenance_data['car_rego'] = car_rego
        
        return maintenance_data
    
    def _process_maintenance_item_row(self, row, dry_run):
        """Process a single maintenance item row"""
        # Required fields
        maintenance_id = self._parse_int(row.get('maintenance_id', ''))
        if not maintenance_id:
            raise ValueError('maintenance_id is required')
        
        description = row.get('description', '').strip()
        if not description:
            raise ValueError('description is required')
        
        quantity = self._parse_float(row.get('quantity', '1.0'))
        unit_cost = self._parse_decimal(row.get('unit_cost', '0.00'))
        
        # Optional fields
        item_type = row.get('item_type', 'parts').strip().lower()
        valid_item_types = ['parts', 'labor', 'consumables', 'other']
        if item_type not in valid_item_types:
            item_type = 'parts'
        
        # Get maintenance record
        if not dry_run:
            try:
                maintenance = Maintenance.objects.get(id=maintenance_id)
            except Maintenance.DoesNotExist:
                raise ValueError(f'Maintenance record with ID {maintenance_id} not found')
        
        item_data = {
            'item_type': item_type,
            'description': description,
            'quantity': quantity,
            'unit_cost': unit_cost,
        }
        
        if not dry_run:
            item_data['maintenance'] = maintenance
        else:
            item_data['maintenance_id'] = maintenance_id
        
        return item_data
    
    def _parse_date(self, date_str):
        """Parse date from various formats"""
        if not date_str:
            return None
        
        # Try Django's built-in parser first (YYYY-MM-DD)
        date_obj = parse_date(date_str)
        if date_obj:
            return date_obj
        
        # Try common formats
        formats = ['%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d', '%m/%d/%Y']
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        return None
    
    def _parse_int(self, value):
        """Parse integer value"""
        if not value or value == '':
            return 0
        try:
            return int(float(str(value).replace(',', '')))
        except (ValueError, TypeError):
            return 0
    
    def _parse_float(self, value):
        """Parse float value"""
        if not value or value == '':
            return 1.0
        try:
            return float(str(value).replace(',', ''))
        except (ValueError, TypeError):
            return 1.0
    
    def _parse_decimal(self, value):
        """Parse decimal value"""
        if not value or value == '':
            return Decimal('0.00')
        try:
            # Remove currency symbols and commas
            cleaned_value = str(value).replace('$', '').replace(',', '').strip()
            return Decimal(cleaned_value)
        except (ValueError, TypeError, InvalidOperation):
            return Decimal('0.00')
    
    def _show_expected_formats(self):
        """Show expected CSV formats"""
        self.stdout.write('\nExpected CSV formats:')
        self.stdout.write('\n1. Maintenance Records CSV:')
        self.stdout.write('   Required headers: car_rego, service_date, service_type')
        self.stdout.write('   Optional headers: odometer_reading, invoice_number, service_provider, description, total_cost')
        self.stdout.write('   Example:')
        self.stdout.write('   car_rego,service_date,service_type,odometer_reading,service_provider,total_cost')
        self.stdout.write('   ABC123,2024-01-15,regular,50000,Joe\'s Garage,250.00')
        
        self.stdout.write('\n2. Maintenance Items CSV:')
        self.stdout.write('   Required headers: maintenance_id, description, quantity, unit_cost')
        self.stdout.write('   Optional headers: item_type')
        self.stdout.write('   Example:')
        self.stdout.write('   maintenance_id,item_type,description,quantity,unit_cost')
        self.stdout.write('   1,parts,Oil Filter,1,25.00')
        self.stdout.write('   1,labor,Oil Change Labor,1,50.00')