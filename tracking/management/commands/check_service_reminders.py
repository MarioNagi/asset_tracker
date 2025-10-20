from django.core.management.base import BaseCommand
from tracking.notifications import check_and_send_service_reminders
from tracking.models import Car
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check all cars and send service reminder emails for those that need them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--warning-km',
            type=int,
            default=1000,
            help='Send warning emails when within this many kilometers of service (default: 1000)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually sending emails'
        )

    def handle(self, *args, **options):
        warning_km = options['warning_km']
        dry_run = options['dry_run']
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Checking service reminders (warning threshold: {warning_km}km)'
            )
        )
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE - No emails will be sent')
            )
        
        # Get all cars with assigned users
        cars = Car.objects.filter(assigned_user__isnull=False)
        total_cars = cars.count()
        
        overdue_cars = []
        approaching_cars = []
        
        for car in cars:
            if car.is_service_due_by_km():
                overdue_cars.append(car)
                if not dry_run:
                    self.stdout.write(f'🚨 OVERDUE: {car.rego} - Current: {car.current_odometer}km, Due: {car.service_odometer}km')
                else:
                    self.stdout.write(f'[DRY RUN] 🚨 OVERDUE: {car.rego} - Current: {car.current_odometer}km, Due: {car.service_odometer}km')
            elif car.is_service_approaching(warning_km):
                approaching_cars.append(car)
                if not dry_run:
                    self.stdout.write(f'⚠️  APPROACHING: {car.rego} - Current: {car.current_odometer}km, Due: {car.service_odometer}km')
                else:
                    self.stdout.write(f'[DRY RUN] ⚠️  APPROACHING: {car.rego} - Current: {car.current_odometer}km, Due: {car.service_odometer}km')
        
        if not dry_run:
            # Send actual email notifications
            results = check_and_send_service_reminders(warning_km)
            
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('=== EMAIL RESULTS ==='))
            self.stdout.write(f'Total emails sent: {results["total_sent"]}')
            self.stdout.write(f'Overdue notifications: {len(results["overdue"])}')
            self.stdout.write(f'Approaching notifications: {len(results["approaching"])}')
        
        # Summary
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=== SUMMARY ==='))
        self.stdout.write(f'Total cars checked: {total_cars}')
        self.stdout.write(f'Cars overdue for service: {len(overdue_cars)}')
        self.stdout.write(f'Cars approaching service: {len(approaching_cars)}')
        self.stdout.write(f'Cars requiring attention: {len(overdue_cars) + len(approaching_cars)}')
        
        if overdue_cars:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR('OVERDUE VEHICLES:'))
            for car in overdue_cars:
                km_overdue = car.current_odometer - car.service_odometer
                assigned_to = car.assigned_user.get_full_name() if car.assigned_user else 'Unassigned'
                self.stdout.write(f'  • {car.rego} ({car.make} {car.model}) - {km_overdue}km overdue - Assigned to: {assigned_to}')
        
        if approaching_cars:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('APPROACHING SERVICE:'))
            for car in approaching_cars:
                km_until = car.km_until_service()
                assigned_to = car.assigned_user.get_full_name() if car.assigned_user else 'Unassigned'
                self.stdout.write(f'  • {car.rego} ({car.make} {car.model}) - {km_until}km until service - Assigned to: {assigned_to}')
        
        if not overdue_cars and not approaching_cars:
            self.stdout.write(self.style.SUCCESS('✅ All vehicles are up to date with their service schedules!'))