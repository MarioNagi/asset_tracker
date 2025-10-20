from django.core.management.base import BaseCommand
import pandas as pd
from django.contrib.auth.models import User
from tracking.models import Tool, Car

class Command(BaseCommand):
    help = 'Import tools from Excel file'

    def add_arguments(self, parser):
        parser.add_argument('excel_file', type=str, help='Path to the Excel file')

    def handle(self, *args, **kwargs):
        excel_file = kwargs['excel_file']
        
        try:
            df = pd.read_excel(excel_file)
            required_columns = [
                'internal_number', 'tool_name', 'state'
            ]
            
            # Optional columns
            optional_columns = [
                'serial_number', 'brand', 'description', 'size', 
                'calibration_date', 'store', 'quantity', 'estimated_cost',
                'assigned_user', 'assigned_car'
            ]
            
            # Validate required columns
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                self.stdout.write(
                    self.style.ERROR(
                        f'Missing required columns: {", ".join(missing_columns)}'
                    )
                )
                return

            for _, row in df.iterrows():
                try:
                    # Prepare tool data
                    tool_data = {
                        'tool_name': row['tool_name'],
                        'state': row['state'].upper(),
                    }

                    # Add optional fields if present
                    if 'serial_number' in df.columns and pd.notna(row['serial_number']):
                        tool_data['serial_number'] = row['serial_number']
                    if 'brand' in df.columns and pd.notna(row['brand']):
                        tool_data['brand'] = row['brand']
                    if 'description' in df.columns and pd.notna(row['description']):
                        tool_data['description'] = row['description']
                    if 'size' in df.columns and pd.notna(row['size']):
                        tool_data['size'] = row['size']
                    if 'calibration_date' in df.columns and pd.notna(row['calibration_date']):
                        tool_data['calibration_date'] = pd.to_datetime(row['calibration_date']).date()
                    if 'store' in df.columns and pd.notna(row['store']):
                        tool_data['store'] = row['store']
                    if 'quantity' in df.columns and pd.notna(row['quantity']):
                        tool_data['quantity'] = row['quantity']
                    if 'estimated_cost' in df.columns and pd.notna(row['estimated_cost']):
                        tool_data['estimated_cost'] = row['estimated_cost']

                    # Handle assigned user if present
                    if 'assigned_user' in df.columns and pd.notna(row['assigned_user']):
                        try:
                            assigned_user = User.objects.get(username=row['assigned_user'])
                            tool_data['assigned_user'] = assigned_user
                        except User.DoesNotExist:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'User {row["assigned_user"]} not found for tool {row["internal_number"]}'
                                )
                            )

                    # Handle assigned car if present
                    if 'assigned_car' in df.columns and pd.notna(row['assigned_car']):
                        try:
                            assigned_car = Car.objects.get(rego=row['assigned_car'])
                            tool_data['assigned_car'] = assigned_car
                        except Car.DoesNotExist:
                            self.stdout.write(
                                self.style.WARNING(
                                    f'Car {row["assigned_car"]} not found for tool {row["internal_number"]}'
                                )
                            )

                    # Create or update tool
                    tool, created = Tool.objects.update_or_create(
                        internal_number=row['internal_number'],
                        defaults=tool_data
                    )

                    action = 'Created' if created else 'Updated'
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'{action} tool: {tool.internal_number}'
                        )
                    )

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'Error processing tool {row["internal_number"]}: {str(e)}'
                        )
                    )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error reading Excel file: {str(e)}')
            )