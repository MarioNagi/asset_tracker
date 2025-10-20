from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from tracking.models import Car
import pandas as pd
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Import car data from an Excel file'

    def add_arguments(self, parser):
        parser.add_argument(
            'file_path',
            type=str,
            help='Path to the Excel file containing car data'
        )
        parser.add_argument(
            '--sheet',
            type=str,
            default=0,
            help='Sheet name or index to read from (default: 0 - first sheet)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would be imported without actually creating records'
        )

    def handle(self, *args, **options):
        file_path = Path(options['file_path'])
        sheet = options['sheet']
        dry_run = options['dry_run']
        
        if not file_path.exists():
            self.stdout.write(
                self.style.ERROR(f'File not found: {file_path}')
            )
            return

        try:
            # Try to convert sheet to int if it's a number
            try:
                sheet = int(sheet)
            except ValueError:
                pass  # Keep as string (sheet name)
            
            # Read Excel file
            self.stdout.write(f'Reading Excel file: {file_path}')
            df = pd.read_excel(file_path, sheet_name=sheet)
            
            self.stdout.write(f'Found {len(df)} rows of data')
            
            if dry_run:
                self.stdout.write(
                    self.style.WARNING('DRY RUN MODE - No records will be created')
                )
            
            # Display column information
            self.stdout.write('\nColumns found in Excel file:')
            for i, col in enumerate(df.columns):
                self.stdout.write(f'  {i+1}. {col}')
            
            # Required columns
            required_cols = ['rego', 'rego_expiry_date', 'state', 'make', 'model', 'vin_number']
            missing_cols = [col for col in required_cols if col not in df.columns]
            
            if missing_cols:
                self.stdout.write(
                    self.style.ERROR(f'Missing required columns: {missing_cols}')
                )
                self.stdout.write('Required columns: rego, rego_expiry_date, state, make, model, vin_number')
                return
            
            # Optional columns that will be used if present
            optional_cols = [
                'manufacturing_year', 'color', 'body', 'assigned_user', 
                'current_odometer', 'service_odometer', 'purchase_date', 
                'purchase_price', 'service_interval_km', 'last_service_km'
            ]
            
            available_optional = [col for col in optional_cols if col in df.columns]
            if available_optional:
                self.stdout.write(f'\nOptional columns found: {available_optional}')
            
            # Show sample data
            self.stdout.write('\nSample data (first 3 rows):')
            print(df.head(3).to_string())
            
            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS('\nDry run completed. Use without --dry-run to import the data.')
                )
                return
            
            # Confirm import
            confirm = input('\nProceed with import? (y/N): ')
            if confirm.lower() != 'y':
                self.stdout.write('Import cancelled.')
                return
            
            # Process import
            success_count = 0
            error_count = 0
            
            for index, row in df.iterrows():
                try:
                    # Get assigned user if specified
                    assigned_user = None
                    if 'assigned_user' in df.columns and pd.notna(row['assigned_user']):
                        try:
                            assigned_user = User.objects.get(username=row['assigned_user'])
                        except User.DoesNotExist:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"User '{row['assigned_user']}' not found for car {row['rego']}, importing without user assignment"
                                )
                            )

                    # Prepare car data with required fields
                    car_data = {
                        'rego_expiry_date': pd.to_datetime(row['rego_expiry_date']).date(),
                        'state': str(row['state']).upper(),
                        'make': str(row['make']),
                        'model': str(row['model']),
                        'vin_number': str(row['vin_number']),
                        'assigned_user': assigned_user,
                    }

                    # Add optional fields if present and not null
                    if 'manufacturing_year' in df.columns and pd.notna(row['manufacturing_year']):
                        car_data['manufacturing_year'] = int(row['manufacturing_year'])
                    
                    if 'color' in df.columns and pd.notna(row['color']):
                        car_data['color'] = str(row['color'])
                    
                    if 'body' in df.columns and pd.notna(row['body']):
                        car_data['body'] = str(row['body'])
                    
                    if 'current_odometer' in df.columns and pd.notna(row['current_odometer']):
                        car_data['current_odometer'] = int(row['current_odometer'])
                    else:
                        car_data['current_odometer'] = 0  # Default value
                    
                    if 'service_odometer' in df.columns and pd.notna(row['service_odometer']):
                        car_data['service_odometer'] = int(row['service_odometer'])
                    else:
                        # Default to current_odometer + 10000 if not specified
                        car_data['service_odometer'] = car_data['current_odometer'] + 10000

                    # Handle dates
                    if 'purchase_date' in df.columns and pd.notna(row['purchase_date']):
                        car_data['purchase_date'] = pd.to_datetime(row['purchase_date']).date()
                    
                    # Handle numeric fields
                    if 'purchase_price' in df.columns and pd.notna(row['purchase_price']):
                        car_data['purchase_price'] = float(row['purchase_price'])
                    
                    if 'service_interval_km' in df.columns and pd.notna(row['service_interval_km']):
                        car_data['service_interval_km'] = int(row['service_interval_km'])
                    
                    if 'last_service_km' in df.columns and pd.notna(row['last_service_km']):
                        car_data['last_service_km'] = int(row['last_service_km'])

                    # Create or update car
                    car, created = Car.objects.update_or_create(
                        rego=str(row['rego']).upper(),
                        defaults=car_data
                    )
                    
                    success_count += 1
                    action = "Created" if created else "Updated"
                    self.stdout.write(f"✅ {action} car: {car.rego} ({car.make} {car.model})")
                    
                except Exception as e:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(f"❌ Error importing car at row {index + 2}: {str(e)}")
                    )
                    logger.error(f"Car import error at row {index + 2}: {str(e)}")
            
            # Summary
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('=== IMPORT SUMMARY ==='))
            self.stdout.write(f'Total rows processed: {len(df)}')
            self.stdout.write(f'Successfully imported: {success_count}')
            self.stdout.write(f'Errors: {error_count}')
            
            if success_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(f'✅ Import completed successfully!')
                )
            
            if error_count > 0:
                self.stdout.write(
                    self.style.WARNING(f'⚠️  {error_count} records had errors. Check the output above for details.')
                )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to read Excel file: {str(e)}')
            )
            return