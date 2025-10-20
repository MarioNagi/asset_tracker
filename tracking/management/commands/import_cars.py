from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from tracking.excel_reader import ExcelReader
from tracking.models import Car
import os


class Command(BaseCommand):
    help = 'Import car data from Excel file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            help='Path to the Excel file',
            default='tracking/CARS 22-11- 2024.xlsx'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Perform a dry run without saving data',
        )
        parser.add_argument(
            '--max-rows',
            type=int,
            default=None,
            help='Maximum number of rows to process (default: all)'
        )
        parser.add_argument(
            '--max-columns',
            type=int,
            default=25,
            help='Maximum number of columns to read (default: 25)'
        )
        parser.add_argument(
            '--skip-existing',
            action='store_true',
            help='Skip existing records instead of updating them',
        )

    def handle(self, *args, **options):
        excel_file = options['file']
        dry_run = options['dry_run']
        max_rows = options['max_rows']
        max_columns = options['max_columns']
        skip_existing = options['skip_existing']

        self.stdout.write(f"Starting import from: {excel_file}")
        self.stdout.write(f"Dry run: {dry_run}")
        self.stdout.write(f"Skip existing records: {skip_existing}")

        try:
            # Initialize the Excel reader
            reader = ExcelReader(excel_file)
            
            # Read the Excel file
            self.stdout.write("Reading Excel file...")
            reader.read_excel(max_columns=max_columns, nrows=max_rows)
            
            # Show data statistics
            stats = reader.get_data_statistics()
            self.stdout.write(f"Data loaded: {stats.get('total_rows', 0)} total rows, {stats.get('total_columns', 0)} columns")
            if 'valid_rego_rows' in stats:
                self.stdout.write(f"Valid car records: {stats['valid_rego_rows']}")
                if stats.get('empty_rego_rows', 0) > 0:
                    self.stdout.write(f"Empty rows filtered out: {stats['empty_rego_rows']}")
            
            # Parse the description column
            self.stdout.write("Parsing description column...")
            reader.parse_description_column('Description of vehicle')
            
            # Transform for Django
            self.stdout.write("Transforming data for Django...")
            django_df = reader.transform_for_django()
            
            # Display summary
            summary = reader.get_import_summary()
            self.stdout.write(f"\n=== IMPORT SUMMARY ===")
            self.stdout.write(f"Total records: {summary['total_records']}")
            self.stdout.write(f"Makes found: {summary['makes_found']}")
            self.stdout.write(f"Years found: {summary['years_found']}")
            self.stdout.write(f"Colors found: {summary['colors_found']}")
            self.stdout.write(f"Body types found: {summary['body_types_found']}")
            
            if dry_run:
                self.stdout.write(f"\n=== DRY RUN - NO DATA SAVED ===")
                self.stdout.write(f"Would process {len(django_df)} records")
                if skip_existing:
                    self.stdout.write("Mode: Skip existing records")
                else:
                    self.stdout.write("Mode: Update existing records")
                self.stdout.write(f"\nSample data:")
                for index, row in django_df.head().iterrows():
                    self.stdout.write(f"  {row['rego']}: {row['make']} {row['model']} ({row['manufacturing_year']}) - {row['color']}")
                return
            
            # Perform actual import
            self.stdout.write(f"\n=== IMPORTING DATA ===")
            created_count = 0
            updated_count = 0
            skipped_count = 0
            error_count = 0
            
            with transaction.atomic():
                for index, row in django_df.iterrows():
                    try:
                        # Create car data dictionary, excluding NaN values
                        car_data = {}
                        for field_name in ['rego', 'rego_expiry_date', 'purchase_date', 'state', 
                                         'current_odometer', 'service_odometer', 'vin_number', 
                                         'make', 'model', 'manufacturing_year', 'color', 'body']:
                            if field_name in row and str(row[field_name]) != 'nan' and row[field_name] is not None:
                                car_data[field_name] = row[field_name]
                        
                        # Set required defaults for date fields
                        from datetime import date
                        if 'rego_expiry_date' not in car_data or car_data['rego_expiry_date'] is None:
                            car_data['rego_expiry_date'] = date.today()
                        
                        # Handle purchase_date - remove if it's None to avoid issues
                        if 'purchase_date' in car_data and car_data['purchase_date'] is None:
                            del car_data['purchase_date']
                        
                        if skip_existing:
                            # Check if car already exists and skip if it does
                            if Car.objects.filter(rego=row['rego']).exists():
                                self.stdout.write(f"⏭ Skipped: {row['rego']} (already exists)")
                                skipped_count += 1
                                continue
                            
                            # Create car data dictionary, excluding NaN values
                            car_data = {}
                            for field_name in ['rego', 'rego_expiry_date', 'purchase_date', 'state', 
                                             'current_odometer', 'service_odometer', 'vin_number', 
                                             'make', 'model', 'manufacturing_year', 'color', 'body']:
                                if field_name in row and str(row[field_name]) != 'nan' and row[field_name] is not None:
                                    car_data[field_name] = row[field_name]
                            
                            # Set required defaults for date fields
                            from datetime import date
                            if 'rego_expiry_date' not in car_data or car_data['rego_expiry_date'] is None:
                                car_data['rego_expiry_date'] = date.today()
                            
                            # Handle purchase_date - remove if it's None to avoid issues
                            if 'purchase_date' in car_data and car_data['purchase_date'] is None:
                                del car_data['purchase_date']
                            
                            # Create new car
                            car = Car.objects.create(**car_data)
                            created_count += 1
                            self.stdout.write(f"✓ Created: {car.rego} - {car.make} {car.model}")
                        else:
                            # Use update_or_create to handle both new and existing records
                            car, created = Car.objects.update_or_create(
                                rego=row['rego'],  # Use rego as the unique identifier
                                defaults=car_data  # Update these fields if record exists, or create with these values
                            )
                            
                            if created:
                                created_count += 1
                                self.stdout.write(f"✓ Created: {car.rego} - {car.make} {car.model}")
                            else:
                                updated_count += 1
                                self.stdout.write(f"↻ Updated: {car.rego} - {car.make} {car.model}")
                        
                    except Exception as e:
                        error_count += 1
                        self.stdout.write(
                            self.style.ERROR(f"✗ Error processing row {index}: {str(e)}")
                        )
            
            # Final summary
            self.stdout.write(f"\n=== IMPORT COMPLETE ===")
            self.stdout.write(
                self.style.SUCCESS(f"Successfully created: {created_count} cars")
            )
            if not skip_existing:
                self.stdout.write(
                    self.style.SUCCESS(f"Successfully updated: {updated_count} cars")
                )
            else:
                self.stdout.write(f"Skipped (already exist): {skipped_count} cars")
            if error_count > 0:
                self.stdout.write(
                    self.style.ERROR(f"Errors: {error_count} cars")
                )
            
        except Exception as e:
            raise CommandError(f"Import failed: {str(e)}")