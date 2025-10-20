from django.core.management.base import BaseCommand
import pandas as pd
from django.contrib.auth.models import User
from tracking.models import Profile

class Command(BaseCommand):
    help = 'Import users from Excel file'

    def add_arguments(self, parser):
        parser.add_argument('excel_file', type=str, help='Path to the Excel file')

    def handle(self, *args, **kwargs):
        excel_file = kwargs['excel_file']
        
        try:
            df = pd.read_excel(excel_file)
            required_columns = [
                'username', 'email', 'first_name', 'last_name', 'password',
                'access_level', 'state'
            ]
            
            # Validate columns
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
                    # Create or update user
                    user, created = User.objects.update_or_create(
                        username=row['username'],
                        defaults={
                            'email': row['email'],
                            'first_name': row['first_name'],
                            'last_name': row['last_name'],
                        }
                    )
                    
                    if created:
                        user.set_password(row['password'])
                        user.save()

                    # Create or update profile
                    Profile.objects.update_or_create(
                        user=user,
                        defaults={
                            'access_level': row['access_level'].upper(),
                            'state': row['state'].upper(),
                        }
                    )

                    action = 'Created' if created else 'Updated'
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'{action} user: {user.username}'
                        )
                    )

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f'Error processing user {row["username"]}: {str(e)}'
                        )
                    )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error reading Excel file: {str(e)}')
            )