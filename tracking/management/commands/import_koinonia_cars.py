from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from tracking.models import Car
import pandas as pd
import logging
from pathlib import Path
import re

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Import car data from the specific CARS Excel file with custom column mapping'

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
        parser.add_argument(
            '--max-rows',
            type=int,
            default=1000,
            help='Maximum number of rows to process (default: 1000)'
        )

    def handle(self, *args, **options):
        file_path = Path(options['file_path'])
        sheet = options['sheet']
        dry_run = options['dry_run']
        max_rows = options['max_rows']
        
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
            
            # Read Excel file with limited rows to avoid memory issues
            self.stdout.write(f'Reading Excel file: {file_path}')
            df = pd.read_excel(file_path, sheet_name=sheet, nrows=max_rows)
            
            # Clean the dataframe - remove rows where Rego is empty
            df = df.dropna(subset=['Rego'])
            df = df[df['Rego'].str.strip() != '']
            
            self.stdout.write(f'Found {len(df)} valid rows with registration data')
            
            if dry_run:
                self.stdout.write(
                    self.style.WARNING('DRY RUN MODE - No records will be created')
                )
            
            # Display column mapping
            self.stdout.write('\nColumn mapping:')
            column_mapping = {
                'Rego': 'rego',
                'Rego exp.': 'rego_expiry_date', 
                'state': 'state',
                'Description of vehicle': 'description',
                'Driver': 'assigned_user',
                'Current odometer': 'current_odometer',
                'service odometer': 'service_odometer',
                'vin': 'vin_number',
                'inv. date': 'purchase_date',
                'purchase price': 'purchase_price'
            }
            
            for excel_col, model_field in column_mapping.items():
                status = "✅" if excel_col in df.columns else "❌"
                self.stdout.write(f'  {status} {excel_col} -> {model_field}')
            
            # Check for missing critical columns
            required_cols = ['Rego', 'state', 'vin']
            missing_cols = [col for col in required_cols if col not in df.columns]
            
            if missing_cols:
                self.stdout.write(
                    self.style.ERROR(f'Missing critical columns: {missing_cols}')
                )
                return
            
            # Show sample data
            self.stdout.write('\nSample data (first 3 rows):')
            sample_cols = ['Rego', 'Description of vehicle', 'state', 'Driver', 'Current odometer', 'service odometer']
            available_sample_cols = [col for col in sample_cols if col in df.columns]
            print(df[available_sample_cols].head(3).to_string())
            
            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS(f'\nDry run completed. Found {len(df)} valid car records.')
                )
                return
            
            # Confirm import
            confirm = input(f'\nProceed with importing {len(df)} cars? (y/N): ')
            if confirm.lower() != 'y':
                self.stdout.write('Import cancelled.')
                return
            
            # Process import
            success_count = 0
            error_count = 0
            
            for index, row in df.iterrows():
                try:
                    # Extract make and model from description
                    description = str(row.get('Description of vehicle', '')).strip()
                    make, model = self.extract_make_model(description)
                    
                    # Get assigned user if specified
                    assigned_user = None
                    if 'Driver' in df.columns and pd.notna(row['Driver']):
                        driver_name = str(row['Driver']).strip()
                        if driver_name:
                            # Try to find user by first name, last name, or username
                            assigned_user = self.find_user(driver_name)
                            if not assigned_user:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"User '{driver_name}' not found for car {row['Rego']}"
                                    )
                                )

                    # Prepare car data
                    car_data = {
                        'state': str(row['state']).upper(),
                        'make': make,
                        'model': model,
                        'vin_number': str(row.get('vin', f"VIN_{row['Rego']}")),
                        'assigned_user': assigned_user,
                    }

                    # Handle rego expiry date
                    if 'Rego exp.' in df.columns and pd.notna(row['Rego exp.']):
                        try:
                            car_data['rego_expiry_date'] = pd.to_datetime(row['Rego exp.']).date()
                        except:
                            # Default to 1 year from now if can't parse
                            from datetime import date, timedelta
                            car_data['rego_expiry_date'] = date.today() + timedelta(days=365)
                    else:
                        from datetime import date, timedelta
                        car_data['rego_expiry_date'] = date.today() + timedelta(days=365)
                    
                    # Handle odometer readings
                    if 'Current odometer' in df.columns and pd.notna(row['Current odometer']):
                        try:
                            car_data['current_odometer'] = int(float(str(row['Current odometer']).replace(',', '')))
                        except:
                            car_data['current_odometer'] = 0
                    else:
                        car_data['current_odometer'] = 0
                    
                    if 'service odometer' in df.columns and pd.notna(row['service odometer']):
                        try:
                            car_data['service_odometer'] = int(float(str(row['service odometer']).replace(',', '')))
                        except:
                            car_data['service_odometer'] = car_data['current_odometer'] + 10000
                    else:
                        car_data['service_odometer'] = car_data['current_odometer'] + 10000

                    # Handle purchase date
                    if 'inv. date' in df.columns and pd.notna(row['inv. date']):
                        try:
                            car_data['purchase_date'] = pd.to_datetime(row['inv. date']).date()
                        except:
                            pass  # Skip if can't parse

                    # Handle purchase price
                    if 'purchase price' in df.columns and pd.notna(row['purchase price']):
                        try:
                            price_str = str(row['purchase price']).replace('$', '').replace(',', '')
                            car_data['purchase_price'] = float(price_str)
                        except:
                            pass  # Skip if can't parse

                    # Create or update car
                    car, created = Car.objects.update_or_create(
                        rego=str(row['Rego']).upper().strip(),
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

    def extract_make_model(self, description):
        """Extract make and model from vehicle description"""
        if not description or pd.isna(description):
            return "Unknown", "Unknown"
        
        description = description.strip()
        
        # Common car makes to look for
        makes = [
            'Toyota', 'Ford', 'Holden', 'Mazda', 'Nissan', 'Honda', 'Hyundai', 
            'Volkswagen', 'BMW', 'Mercedes', 'Audi', 'Subaru', 'Mitsubishi',
            'Isuzu', 'Suzuki', 'Kia', 'Peugeot', 'Renault', 'Citroen', 'Volvo',
            'Jeep', 'Ram', 'Chevrolet', 'GMC', 'Dodge', 'Fiat'
        ]
        
        # Try to find a make in the description
        description_upper = description.upper()
        found_make = None
        
        for make in makes:
            if make.upper() in description_upper:
                found_make = make
                break
        
        if found_make:
            # Try to extract model (everything after the make)
            pattern = rf'{found_make}\s+(.+?)(?:\s+\d{{4}}|\s*$)'
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                model = match.group(1).strip()
                # Remove year if it's at the end
                model = re.sub(r'\s+\d{4}$', '', model).strip()
                return found_make, model if model else "Unknown"
            else:
                return found_make, "Unknown"
        else:
            # If no known make found, try to parse as "Make Model"
            parts = description.split()
            if len(parts) >= 2:
                return parts[0], ' '.join(parts[1:3])  # Take first two words after make
            else:
                return "Unknown", description[:50] if description else "Unknown"

    def find_user(self, driver_name):
        """Try to find a user by various name matching strategies"""
        if not driver_name:
            return None
        
        # Try exact username match
        try:
            return User.objects.get(username=driver_name)
        except User.DoesNotExist:
            pass
        
        # Try email match
        try:
            return User.objects.get(email=driver_name)
        except User.DoesNotExist:
            pass
        
        # Try first name + last name combinations
        name_parts = driver_name.split()
        if len(name_parts) >= 2:
            try:
                return User.objects.get(first_name__icontains=name_parts[0], last_name__icontains=name_parts[-1])
            except (User.DoesNotExist, User.MultipleObjectsReturned):
                pass
        
        # Try partial match on full name
        try:
            users = User.objects.filter(
                models.Q(first_name__icontains=driver_name) | 
                models.Q(last_name__icontains=driver_name) |
                models.Q(username__icontains=driver_name)
            )
            if users.count() == 1:
                return users.first()
        except:
            pass
        
        return None