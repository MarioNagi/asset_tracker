from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import pre_save
from django.dispatch import receiver
from decimal import Decimal
import uuid


# --------- Profile Model ---------
class Profile(models.Model):
    ACCESS_LEVELS = [
        ('User', 'User'),
        ('Manager', 'Manager'),
        ('Admin', 'Admin'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    access_level = models.CharField(max_length=10, choices=ACCESS_LEVELS, default='User')
    state = models.CharField(
        max_length=15,
        choices=[('NSW-Wireless', 'NSW-Wireless'),('NSW-Special', 'NSW-Special'), ('VIC', 'VIC'), ('WA', 'WA'), ('SA', 'SA'), ('QLD', 'QLD'), ('TZ', 'TZ')],
        blank=True,
        null=True
    )
    photo = models.ImageField(upload_to='user_photos/', null=True, blank=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class CustodyLocation(models.Model):
    """A real non-person custody destination owned by the company."""
    TYPE_OFFICE = 'office'
    TYPE_WAREHOUSE = 'warehouse'
    TYPE_CHOICES = [
        (TYPE_OFFICE, 'Office'),
        (TYPE_WAREHOUSE, 'Warehouse'),
    ]

    name = models.CharField(max_length=120, unique=True)
    location_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_WAREHOUSE,
    )
    state = models.CharField(max_length=10, choices=[
        ('NSW', 'NSW'), ('VIC', 'VIC'), ('WA', 'WA'), ('SA', 'SA'),
        ('QLD', 'QLD'), ('TZ', 'TZ'),
    ])
    address = models.TextField(blank=True, default='')
    responsible_manager = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='responsible_company_locations',
    )
    notes = models.TextField(blank=True, default='')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        ordering = ['state', 'location_type', 'name']

    def clean(self):
        super().clean()
        if self.responsible_manager_id:
            profile = getattr(self.responsible_manager, 'profile', None)
            if not (
                self.responsible_manager.is_superuser or
                (profile and profile.access_level in {'Admin', 'Manager'})
            ):
                raise ValidationError({
                    'responsible_manager': 'Choose an Admin or Manager as the responsible contact.'
                })
        if self.pk and not self.active and (
            self.tools.exists() or self.cars.filter(status=Car.STATUS_IN_SERVICE).exists()
        ):
            raise ValidationError({
                'active': 'Transfer all active vehicles and tools before deactivating this location.'
            })

    def __str__(self):
        return f'{self.name} - {self.get_location_type_display()} ({self.state})'


class AlertContact(models.Model):
    ROLE_FLEET_MANAGER = 'fleet_manager'
    ROLE_STATE_MANAGER = 'state_manager'
    ROLE_ADMIN_ALERTS = 'admin_alerts'
    ROLE_CHOICES = [
        (ROLE_FLEET_MANAGER, 'Fleet Manager'),
        (ROLE_STATE_MANAGER, 'State Manager'),
        (ROLE_ADMIN_ALERTS, 'Admin Alerts'),
    ]
    CATEGORY_VEHICLE_SERVICE = 'vehicle_service'
    CATEGORY_SPECIAL_MAINTENANCE = 'special_maintenance'
    CATEGORY_CALIBRATION = 'calibration'
    CATEGORY_WRITTEN_OFF = 'written_off'
    CATEGORY_RETIREMENT = 'retirement'
    CATEGORY_CONTROLLED_TRANSFER = 'controlled_transfer'
    CATEGORY_ODOMETER = 'odometer'
    CATEGORY_CHOICES = [
        (CATEGORY_VEHICLE_SERVICE, 'Vehicle service'),
        (CATEGORY_SPECIAL_MAINTENANCE, 'Special maintenance'),
        (CATEGORY_CALIBRATION, 'Tool calibration'),
        (CATEGORY_WRITTEN_OFF, 'Vehicle written off'),
        (CATEGORY_RETIREMENT, 'Retirement checklist'),
        (CATEGORY_CONTROLLED_TRANSFER, 'Controlled-device transfers'),
        (CATEGORY_ODOMETER, 'Odometer reminders'),
    ]

    name = models.CharField(max_length=120)
    email = models.EmailField()
    responsibility = models.CharField(max_length=30, choices=ROLE_CHOICES)
    state = models.CharField(
        max_length=10, choices=[
            ('NSW', 'NSW'), ('VIC', 'VIC'), ('WA', 'WA'),
            ('SA', 'SA'), ('QLD', 'QLD'), ('TZ', 'TZ'),
        ], null=True, blank=True,
    )
    is_primary = models.BooleanField(
        default=False,
        help_text='Primary State Manager used for controlled-device routing.',
    )
    categories = models.JSONField(default=list)
    linked_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alert_contacts',
    )
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_alert_contacts',
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='updated_alert_contacts',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['responsibility', 'state', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['state'],
                condition=Q(
                    responsibility='state_manager', is_primary=True,
                ),
                name='one_primary_state_alert_contact',
            ),
        ]

    def clean(self):
        super().clean()
        valid_categories = {value for value, _ in self.CATEGORY_CHOICES}
        if not self.categories:
            raise ValidationError({'categories': 'Select at least one alert category.'})
        if set(self.categories) - valid_categories:
            raise ValidationError({'categories': 'One or more alert categories are invalid.'})
        if self.responsibility == self.ROLE_STATE_MANAGER:
            if not self.state:
                raise ValidationError({'state': 'State is required for a State Manager contact.'})
            if self.is_primary:
                existing_primary = AlertContact.objects.filter(
                    responsibility=self.ROLE_STATE_MANAGER,
                    state=self.state,
                    is_primary=True,
                ).exclude(pk=self.pk)
                if existing_primary.exists():
                    raise ValidationError({
                        'is_primary': 'A primary State Manager alert mailbox already exists for this state.'
                    })
        else:
            if self.state:
                raise ValidationError({'state': 'State is only used for State Manager contacts.'})
            if self.is_primary:
                raise ValidationError({'is_primary': 'Only a State Manager can be primary for a state.'})

        duplicate = AlertContact.objects.filter(
            email__iexact=self.email,
            responsibility=self.responsibility,
            state=self.state,
        ).exclude(pk=self.pk)
        if duplicate.exists():
            raise ValidationError('This mailbox already has the same alert responsibility and state.')

    def __str__(self):
        state = f' - {self.state}' if self.state else ''
        return f'{self.name} ({self.get_responsibility_display()}{state})'

    @property
    def category_labels(self):
        labels = dict(self.CATEGORY_CHOICES)
        return [labels.get(category, category) for category in self.categories]


class NotificationDelivery(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
    ]

    event_type = models.CharField(max_length=50, choices=AlertContact.CATEGORY_CHOICES)
    related_object = models.CharField(max_length=150, blank=True, default='')
    recipients = models.JSONField(default=list)
    subject = models.CharField(max_length=250)
    message = models.TextField()
    deduplication_key = models.CharField(max_length=200, unique=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING,
    )
    scheduled_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    failure_reason = models.TextField(blank=True, default='')
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_event_type_display()}: {self.subject}'


# --------- Tool Model ---------
class ToolCatalogueItem(models.Model):
    name = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    suggested_controlled = models.BooleanField(
        default=False,
        help_text='Suggest controlled-device handling when this type is selected.',
    )
    suggested_calibration_required = models.BooleanField(
        default=False,
        help_text='Suggest calibration tracking when this type is selected.',
    )
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_tool_catalogue_items',
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='updated_tool_catalogue_items',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'), name='unique_tool_catalogue_name_ci'
            ),
        ]

    def clean(self):
        super().clean()
        self.name = ' '.join((self.name or '').split())
        if not self.name:
            return
        duplicate = ToolCatalogueItem.objects.filter(
            name__iexact=self.name
        ).exclude(pk=self.pk)
        if duplicate.exists():
            raise ValidationError({'name': 'This tool or device type already exists.'})

    def __str__(self):
        return self.name


class Tool(models.Model):
    CONDITION_GOOD = 'good'
    CONDITION_FAIR = 'fair'
    CONDITION_NEEDS_REPAIR = 'needs_repair'
    CONDITION_OUT_OF_SERVICE = 'out_of_service'
    CONDITION_CHOICES = [
        (CONDITION_GOOD, 'Good'),
        (CONDITION_FAIR, 'Fair'),
        (CONDITION_NEEDS_REPAIR, 'Needs repair'),
        (CONDITION_OUT_OF_SERVICE, 'Out of service'),
    ]

    internal_number = models.CharField(max_length=100, primary_key=True, unique=True, blank=True, db_index=True)  # Add db_index
    serial_number =models.CharField(max_length=100, unique=True, blank=True, null=True, db_index=True)  # Add db_index  
    tool_name = models.CharField(max_length=100, db_index=True)
    brand = models.CharField(max_length=100, default='Generic Brand')
    description = models.TextField(blank=True, null=True)
    size = models.CharField(max_length=50, blank=True, null=True)
    calibration_date = models.DateField(null=True, blank=True)  # Newly Added Field
    store = models.CharField(
        max_length=50,
        choices=[
            ('Online', 'Online'),
            ('Bunnings', 'Bunnings'),
            ('other local stores', 'other local stores')
        ]
    )
    state = models.CharField(
        max_length=50,
        choices=[
            ('NSW', 'NSW'),
            ('VIC', 'VIC'),
            ('WA', 'WA'),
            ('SA', 'SA'),
            ('QLD', 'QLD'),
            ('TZ', 'TZ')
        ]
    )
    quantity = models.PositiveIntegerField(default=1)
    photo = models.ImageField(upload_to='tool_photos/', blank=True, null=True)  # New field for photo
    estimated_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # New field for cost
    is_controlled = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Rare, shared, important, or high-value device requiring enhanced custody controls.',
    )
    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        default=CONDITION_GOOD,
    )
    calibration_required = models.BooleanField(
        default=False,
        help_text='This device must always have a next calibration due date.',
    )
    assigned_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tools'
    )
    assigned_car = models.ForeignKey('Car', on_delete=models.SET_NULL, null=True, blank=True, related_name='tools')
    custody_location = models.ForeignKey(
        CustodyLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='tools',
    )

    def clean(self):
        super().clean()
        if self.assigned_user_id and self.custody_location_id:
            raise ValidationError(
                'A tool cannot be held by an employee and a company location at the same time.'
            )
        if not self.is_controlled:
            return
        errors = {}
        if not self.internal_number:
            errors['internal_number'] = 'An internal number is required for a controlled device.'
        if not self.serial_number:
            errors['serial_number'] = 'A serial number is required for a controlled device.'
        if not self.photo:
            errors['photo'] = 'A photograph is required for a controlled device.'
        if not self.assigned_user_id and not self.custody_location_id:
            errors['assigned_user'] = (
                'Choose the employee or company location currently holding this controlled device.'
            )
        if self.calibration_required and not self.calibration_date:
            errors['calibration_date'] = (
                'Enter the next calibration due date for this controlled device.'
            )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.tool_name} - {self.internal_number}"
# Automatically Assign Default Serial Number if Empty
@receiver(pre_save, sender=Tool)
def add_default_internal_number(sender, instance, **kwargs):
    if not instance.internal_number:
        last_tool = Tool.objects.filter(internal_number__startswith='KE-').order_by('-internal_number').first()
        if last_tool and last_tool.internal_number.startswith('KE-'):
            try:
                last_number = int(last_tool.internal_number.replace('KE-', '') or 0)
                instance.internal_number = f"KE-{last_number + 1}"
            except ValueError:
                instance.internal_number = "KE-01"
        else:
            instance.internal_number = "KE-01"
# --------- Car Model ---------
class CarQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=Car.STATUS_IN_SERVICE)

    def retired(self):
        return self.exclude(status=Car.STATUS_IN_SERVICE)


class Car(models.Model):
    STATUS_IN_SERVICE = 'in_service'
    STATUS_SOLD = 'sold'
    STATUS_WRITTEN_OFF = 'written_off'
    STATUS_CHOICES = [
        (STATUS_IN_SERVICE, 'In service'),
        (STATUS_SOLD, 'Sold'),
        (STATUS_WRITTEN_OFF, 'Written off'),
    ]
    STATE_CHOICES = [('NSW', 'NSW'), ('VIC', 'VIC'), ('WA', 'WA'), ('SA', 'SA'), ('QLD', 'QLD'), ('TZ', 'TZ')]
    BODY_CHOICES = [
        ('Sedan', 'Sedan'),
        ('Hatchback', 'Hatchback'),
        ('SUV', 'SUV'),
        ('Ute', 'Ute'),
        ('Van', 'Van'),
        ('Truck', 'Truck'),
        ('EWP', 'EWP'),
        ('trailer', 'trailer'),
        ('Other', 'Other')
    ]

    rego = models.CharField(max_length=20, unique=True, db_index=True)  # Add db_index
    rego_expiry_date = models.DateField()
    purchase_date = models.DateField(null=True, blank=True)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default='NSW', db_index=True)  # Add db_index
    assigned_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='cars', db_index=True)  # Add db_index
    custody_location = models.ForeignKey(
        CustodyLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cars',
    )
    current_odometer = models.PositiveIntegerField(default=0, help_text='Current odometer reading in kilometers')
    service_odometer = models.PositiveIntegerField(default=10000, help_text='Odometer reading when next service is due')
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    vin_number = models.CharField(max_length=100, unique=True)
    manufacturing_year = models.PositiveIntegerField(null=True, blank=True)  # New field for manufacturing year
    color = models.CharField(max_length=30, blank=True, null=True)  # New field for color
    body = models.CharField(max_length=50, choices=BODY_CHOICES, default='Sedan')  # New field for car body type
    photo = models.ImageField(upload_to='car_photos/', null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_IN_SERVICE,
        db_index=True,
    )
    retired_at = models.DateField(null=True, blank=True)
    final_odometer = models.PositiveIntegerField(null=True, blank=True)
    final_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    final_payment_date = models.DateField(null=True, blank=True)
    final_payment_source = models.CharField(max_length=200, blank=True, default='')
    final_payment_reference = models.CharField(max_length=150, blank=True, default='')
    retirement_notes = models.TextField(blank=True, default='')
    retirement_document = models.FileField(
        upload_to='vehicle_retirement_docs/', null=True, blank=True
    )
    retired_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='retired_vehicles',
    )
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    objects = CarQuerySet.as_manager()
    
    # Maintenance related fields
    next_service_date = models.DateField(null=True, blank=True)
    service_interval_km = models.PositiveIntegerField(default=10000)
    last_service_km = models.PositiveIntegerField(null=True, blank=True)
    monthly_odometer_check = models.BooleanField(default=True)
    odometer_tracking_started_at = models.DateField(default=timezone.localdate)
    total_maintenance_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    
    def is_service_due(self):
        if not self.next_service_date:
            return False
        return timezone.now().date() >= self.next_service_date

    def is_service_due_by_km(self):
        """Check if service is due based on odometer reading"""
        return self.current_odometer >= self.service_odometer
    
    def is_service_approaching(self, warning_km=1000):
        """Check if service is approaching within warning_km"""
        return (self.service_odometer - self.current_odometer) <= warning_km and self.current_odometer < self.service_odometer
    
    def km_until_service(self):
        """Calculate kilometers until next service"""
        return max(0, self.service_odometer - self.current_odometer)

    def get_latest_odometer(self):
        """Get the latest odometer reading.

        Reuses a prefetched ``odometer_readings`` cache when the caller has
        prefetched it, so list and analytics pages do not issue one query per
        vehicle. Falls back to a direct query otherwise.
        """
        if 'odometer_readings' in getattr(self, '_prefetched_objects_cache', {}):
            readings = [
                reading for reading in self.odometer_readings.all()
                if reading.review_status == OdometerReading.STATUS_ACCEPTED
            ]
            return max(readings, key=lambda r: r.reading_date, default=None)
        return self.odometer_readings.filter(
            review_status=OdometerReading.STATUS_ACCEPTED
        ).order_by('-reading_date', '-created_at').first()

    def odometer_due_date(self):
        latest = self.get_latest_odometer()
        baseline = latest.reading_date if latest else self.odometer_tracking_started_at
        return baseline + timezone.timedelta(days=7)

    def is_odometer_overdue(self):
        return self.monthly_odometer_check and self.odometer_due_date() < timezone.localdate()

    def get_current_km(self):
        """Get current odometer reading value."""
        latest = self.get_latest_odometer()
        return latest.reading_value if latest else 0

    def get_km_since_service(self):
        """Calculate kilometers driven since last service."""
        if not self.last_service_km:
            return None
        latest = self.get_latest_odometer()
        if not latest:
            return None
        return latest.reading_value - self.last_service_km

    def get_service_status(self):
        """Get detailed service status."""
        km_since_service = self.get_km_since_service()
        days_to_service = (self.next_service_date - timezone.now().date()).days if self.next_service_date else None
        
        return {
            'km_since_service': km_since_service,
            'km_until_service': self.service_interval_km - km_since_service if km_since_service else None,
            'days_to_service': days_to_service,
            'service_due': self.is_service_due() or self.is_service_due_by_km(),
            'next_service_date': self.next_service_date
        }

    def get_maintenance_costs(self, start_date=None, end_date=None):
        """Get maintenance costs for a specific period."""
        records = self.maintenance_records.all()
        if start_date:
            records = records.filter(service_date__gte=start_date)
        if end_date:
            records = records.filter(service_date__lte=end_date)
        
        total_cost = sum(
            (record.total_cost for record in records), Decimal('0.00')
        )
        return {
            'total_cost': total_cost,
            'record_count': records.count(),
            'records': records
        }

    def get_fuel_efficiency(self, last_n_records=5):
        """Calculate average fuel efficiency from last N full tank records."""
        # One older reading is needed to calculate the efficiency of the last
        # requested fill. Fetch it in the same query instead of asking every
        # FuelRecord to find its predecessor separately.
        fuel_records = list(
            self.fuel_records.filter(full_tank=True)
            .order_by('-date', '-pk')[:last_n_records + 1]
        )
        return self.calculate_fuel_efficiency(fuel_records, last_n_records)

    @staticmethod
    def calculate_fuel_efficiency(fuel_records, last_n_records=5):
        """Calculate efficiency from newest-first full-tank records in memory."""
        records = list(fuel_records)
        efficiencies = []
        for current, previous in zip(
            records[:last_n_records], records[1:last_n_records + 1]
        ):
            if previous.odometer < current.odometer:
                distance = current.odometer - previous.odometer
                efficiencies.append((current.liters * 100) / distance)

        if not efficiencies:
            return None

        return {
            'current': efficiencies[0],
            'previous': efficiencies[1] if len(efficiencies) > 1 else None,
            'average': sum(efficiencies) / len(efficiencies),
            'best': min(efficiencies),
            'worst': max(efficiencies),
        }

    def get_total_costs(self, start_date=None, end_date=None):
        """Calculate total costs including maintenance, fuel, and accidents."""
        maintenance_data = self.get_maintenance_costs(start_date, end_date)
        
        fuel_records = self.fuel_records.all()
        if start_date:
            fuel_records = fuel_records.filter(date__gte=start_date)
        if end_date:
            fuel_records = fuel_records.filter(date__lte=end_date)
        
        fuel_cost = sum(
            (record.total_cost for record in fuel_records), Decimal('0.00')
        )
        
        # Get accident costs
        accident_records = self.accidents.all()
        if start_date:
            accident_records = accident_records.filter(accident_date__gte=start_date)
        if end_date:
            accident_records = accident_records.filter(accident_date__lte=end_date)

        accident_cost = sum(
            (record.accident_excess for record in accident_records),
            Decimal('0.00'),
        )

        return {
            'maintenance_cost': maintenance_data['total_cost'],
            'fuel_cost': fuel_cost,
            'accident_cost': accident_cost,
            'total_cost': maintenance_data['total_cost'] + fuel_cost + accident_cost
        }

    def get_tire_status(self):
        """Get status of current tires."""
        # Reuse a prefetched cache when present; templates call this per row.
        if 'tire_records' in getattr(self, '_prefetched_objects_cache', {}):
            latest_record = max(
                self.tire_records.all(),
                key=lambda r: r.change_date,
                default=None,
            )
        else:
            latest_record = self.tire_records.order_by('-change_date').first()
        if not latest_record:
            return None
            
        current_km = self.get_current_km()
        km_since_change = current_km - latest_record.change_date_km if current_km else None
        
        return {
            'last_change_date': latest_record.change_date,
            'km_since_change': km_since_change,
            'km_until_change': latest_record.next_change_km - current_km if current_km else None,
            'tire_positions': latest_record.tire_positions,
            'change_due': current_km >= latest_record.next_change_km if current_km else False
        }

    def __str__(self):
        return f"{self.make} {self.model} ({self.rego})"

    class Meta:
        ordering = ['rego']
        indexes = [
            models.Index(fields=['rego']),
            models.Index(fields=['state']),
            models.Index(fields=['assigned_user']),
        ]

    @property
    def is_active(self):
        return self.status == self.STATUS_IN_SERVICE


class VehicleRetirementTask(models.Model):
    TASK_CHOICES = [
        ('rego_refund', 'Apply for registration refund'),
        ('ctp_refund', 'Apply for CTP refund'),
        ('nrma_remove', 'Remove from NRMA roadside assistance'),
        ('insurance_remove', 'Remove from insurance policy'),
        ('fuel_card', 'Cancel or recover fuel card'),
        ('toll_tag', 'Remove toll account or tag'),
        ('tracking', 'Remove GPS or tracking equipment'),
        ('equipment', 'Recover company tools and equipment'),
        ('documents', 'Upload retirement documents'),
        ('payment', 'Confirm final payment received'),
    ]

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='retirement_tasks')
    task_type = models.CharField(max_length=30, choices=TASK_CHOICES)
    completed = models.BooleanField(default=False)
    completed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='completed_vehicle_retirement_tasks',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(
                fields=['car', 'task_type'], name='vehicle_retirement_task_unique'
            ),
        ]

    def __str__(self):
        return f'{self.car.rego}: {self.get_task_type_display()}'


# --------- TireRecord Model ---------
class TireRecord(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='tire_records')
    change_date = models.DateField()
    next_change_km = models.PositiveIntegerField()
    alignment_done = models.BooleanField(default=False)
    tire_positions = models.JSONField(default=dict)  # {'FL': 'New', 'FR': 'Good', 'RL': 'Worn', 'RR': 'Replaced'}
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Tire service for {self.car.rego} on {self.change_date}"


# --------- Maintenance Model ---------
class Maintenance(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='maintenance_records')
    service_date = models.DateField(default=timezone.now)
    odometer_reading = models.PositiveIntegerField(default=0)
    service_type = models.CharField(
        max_length=50, 
        choices=[
            ('regular', 'Regular Service'),
            ('repair', 'Repair'),
            ('inspection', 'Inspection'),
            ('accident', 'Accident Repair'),
            ('other', 'Other')
        ],
        default='regular'
    )
    invoice_number = models.CharField(max_length=100, blank=True, default='')
    service_provider = models.CharField(max_length=200, default='Unknown Provider')
    description = models.TextField(default='')
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    documents = models.FileField(upload_to='maintenance_docs/', null=True, blank=True)
    
    def save(self, *args, **kwargs):
        # Update car's last service info
        if self.service_type == 'regular':
            if self.odometer_reading:
                self.car.last_service_km = self.odometer_reading
                self.car.current_odometer = max(
                    self.car.current_odometer,
                    self.odometer_reading,
                )
                self.car.service_odometer = (
                    self.odometer_reading + self.car.service_interval_km
                )
            self.car.next_service_date = self.service_date + timezone.timedelta(days=180)  # 6 months
            self.car.save()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.service_type} for {self.car.rego} on {self.service_date}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["invoice_number"],
                condition=~Q(invoice_number=""),
                name="maintenance_invoice_number_nonempty_unique",
            ),
        ]


# --------- MaintenanceItem Model ---------
class MaintenanceItem(models.Model):
    maintenance = models.ForeignKey(Maintenance, on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField(max_length=50, choices=[
        ('parts', 'Parts'),
        ('labor', 'Labor'),
        ('consumables', 'Consumables'),
        ('other', 'Other')
    ],default='parts')
    description = models.CharField(max_length=255)
    quantity = models.FloatField(default=1.0, help_text='Quantity can be decimal (e.g., 1.5 liters)')
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2,default=0.00)
    
    @property
    def total_cost(self):
        return Decimal(str(self.quantity)) * self.unit_cost

    def __str__(self):
        return f"{self.description} - ${self.total_cost}"


# --------- Odometer Reading ---------
class OdometerReading(models.Model):
    STATUS_ACCEPTED = 'accepted'
    STATUS_PENDING = 'pending'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_PENDING, 'Needs review'),
        (STATUS_REJECTED, 'Rejected'),
    ]
    SOURCE_MANUAL = 'manual'
    SOURCE_QR = 'qr'
    SOURCE_CHOICES = [(SOURCE_MANUAL, 'Manual'), (SOURCE_QR, 'Vehicle QR')]

    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='odometer_readings', db_index=True)  # Add db_index
    reading_date = models.DateField(default=timezone.now)
    reading_value = models.PositiveIntegerField()
    submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='submitted_odometer_readings',
    )
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    review_status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_ACCEPTED, db_index=True,
    )
    suspicious_reason = models.CharField(max_length=250, blank=True, default='')
    evidence_photo = models.ImageField(upload_to='odometer_evidence/', null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_odometer_readings',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ['-reading_date']

    def __str__(self):
        return f"{self.car.rego} - {self.reading_date}: {self.reading_value} km"


# --------- Transfer Model ---------
class Transfer(models.Model):
    TRANSFER_TYPE_CHOICES = [('Tool', 'Tool'), ('Car', 'Car')]

    transfer_type = models.CharField(max_length=10, choices=TRANSFER_TYPE_CHOICES)
    item_id = models.CharField(
        max_length=100,
        help_text='Enter the tool internal number or the car numeric ID.',
    )
    from_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transfers_from')
    to_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transfers_to')
    date_of_transfer = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.transfer_type} Transfer on {self.date_of_transfer}"


class TransferBatch(models.Model):
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    from_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='custody_batches_from',
    )
    from_location = models.ForeignKey(
        CustodyLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='custody_batches_from',
    )
    to_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='custody_batches_to',
    )
    to_location = models.ForeignKey(
        CustodyLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='custody_batches_to',
    )
    date_of_transfer = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='created_custody_batches'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reversal_of = models.OneToOneField(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='reversal',
    )

    class Meta:
        ordering = ['-created_at']

    def clean(self):
        if bool(self.from_user_id) == bool(self.from_location_id):
            raise ValidationError('Choose exactly one source user or warehouse.')
        if bool(self.to_user_id) == bool(self.to_location_id):
            raise ValidationError('Choose exactly one destination user or warehouse.')
        if self.from_user_id and self.from_user_id == self.to_user_id:
            raise ValidationError('Source and destination cannot be the same user.')
        if self.from_location_id and self.from_location_id == self.to_location_id:
            raise ValidationError('Source and destination cannot be the same warehouse.')

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Transfer batches are immutable; create a reversal.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Transfer batches cannot be deleted; create a reversal.')

    @property
    def source_label(self):
        return str(self.from_user or self.from_location)

    @property
    def destination_label(self):
        return str(self.to_user or self.to_location)


class TransferLedgerEntry(models.Model):
    ASSET_TOOL = 'tool'
    ASSET_CAR = 'car'
    ASSET_CHOICES = [(ASSET_TOOL, 'Tool'), (ASSET_CAR, 'Car')]

    batch = models.ForeignKey(
        TransferBatch, on_delete=models.PROTECT, related_name='entries'
    )
    asset_type = models.CharField(max_length=10, choices=ASSET_CHOICES)
    tool = models.ForeignKey(
        Tool, on_delete=models.PROTECT, null=True, blank=True,
        related_name='custody_ledger_entries',
    )
    car = models.ForeignKey(
        Car, on_delete=models.PROTECT, null=True, blank=True,
        related_name='custody_ledger_entries',
    )
    asset_identifier = models.CharField(max_length=100)
    from_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='custody_ledger_entries_from',
    )
    from_location = models.ForeignKey(
        CustodyLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='custody_ledger_entries_from',
    )
    to_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='custody_ledger_entries_to',
    )
    to_location = models.ForeignKey(
        CustodyLocation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='custody_ledger_entries_to',
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(asset_type='tool', tool__isnull=False, car__isnull=True) |
                    Q(asset_type='car', car__isnull=False, tool__isnull=True)
                ),
                name='ledger_entry_exact_asset',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Transfer ledger entries are immutable; create a reversal.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Transfer ledger entries cannot be deleted; create a reversal.')


class TransferFollowUpTask(models.Model):
    batch = models.ForeignKey(
        TransferBatch, on_delete=models.PROTECT, related_name='follow_up_tasks'
    )
    car = models.ForeignKey(Car, on_delete=models.PROTECT)
    state = models.CharField(max_length=10)
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='transfer_follow_up_tasks',
    )
    description = models.CharField(max_length=250)
    completed = models.BooleanField(default=False)
    completed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='completed_transfer_follow_up_tasks',
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['completed', 'created_at']


# --------- FuelRecord Model ---------
class FuelRecord(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='fuel_records')
    date = models.DateField()
    odometer = models.PositiveIntegerField()
    liters = models.DecimalField(max_digits=6, decimal_places=2)
    cost_per_liter = models.DecimalField(max_digits=4, decimal_places=2)
    total_cost = models.DecimalField(max_digits=8, decimal_places=2)
    fuel_type = models.CharField(max_length=20, choices=[
        ('diesel', 'Diesel'),
        ('petrol_91', 'Petrol 91'),
        ('petrol_95', 'Petrol 95'),
        ('petrol_98', 'Petrol 98'),
        ('lpg', 'LPG')
    ])
    station = models.CharField(max_length=100, blank=True)
    full_tank = models.BooleanField(default=True)
    receipt = models.ImageField(upload_to='fuel_receipts/', null=True, blank=True)
    submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='submitted_fuel_records',
    )
    odometer_reading = models.OneToOneField(
        OdometerReading, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fuel_record',
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    
    def save(self, *args, **kwargs):
        self.total_cost = self.liters * self.cost_per_liter
        super().save(*args, **kwargs)

    @property
    def fuel_efficiency(self):
        """Calculate fuel efficiency in L/100km"""
        previous_record = FuelRecord.objects.filter(
            car=self.car,
            date__lt=self.date,
            full_tank=True
        ).order_by('-date').first()
        
        if previous_record and previous_record.odometer < self.odometer:
            distance = self.odometer - previous_record.odometer
            return (self.liters * 100) / distance
        return None

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.car.rego} - {self.date} - {self.liters}L"


class SpecialMaintenanceRequirement(models.Model):
    car = models.ForeignKey(
        Car, on_delete=models.CASCADE, related_name='special_maintenance_requirements'
    )
    title = models.CharField(max_length=120)
    due_date = models.DateField(null=True, blank=True)
    due_odometer = models.PositiveIntegerField(null=True, blank=True)
    advance_notice_days = models.PositiveIntegerField(default=30)
    advance_notice_km = models.PositiveIntegerField(default=1000)
    recurrence_days = models.PositiveIntegerField(null=True, blank=True)
    recurrence_km = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    active = models.BooleanField(default=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_odometer = models.PositiveIntegerField(null=True, blank=True)
    completion_notes = models.TextField(blank=True, default='')
    completion_document = models.FileField(
        upload_to='special_maintenance_docs/', null=True, blank=True
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_special_maintenance_requirements',
    )
    completed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='completed_special_maintenance_requirements',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['active', 'due_date', 'due_odometer', 'car__rego']

    def clean(self):
        super().clean()
        if self.active and not self.due_date and self.due_odometer is None:
            raise ValidationError('Enter a due date, due odometer, or both.')

    @property
    def status(self):
        if not self.active:
            return 'completed'
        today = timezone.localdate()
        if ((self.due_date and self.due_date <= today) or
                (self.due_odometer is not None and self.car.current_odometer >= self.due_odometer)):
            return 'overdue'
        if ((self.due_date and self.due_date <= today + timezone.timedelta(days=self.advance_notice_days)) or
                (self.due_odometer is not None and self.car.current_odometer + self.advance_notice_km >= self.due_odometer)):
            return 'upcoming'
        return 'scheduled'

    def __str__(self):
        return f'{self.car.rego} - {self.title}'


# --------- Accident Model ---------
class Accident(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='accidents')
    accident_date = models.DateField(default=timezone.now)
    driver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='accidents')
    accident_excess = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text='Excess amount paid')
    via_insurance = models.BooleanField(default=True, help_text='Was this processed through insurance?')
    insurance_company = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True, default='', help_text='Description of the accident')
    location = models.CharField(max_length=255, blank=True, default='')
    claim_number = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        ordering = ['-accident_date']
        constraints = [
            models.CheckConstraint(
                check=Q(accident_excess__gte=0),
                name='accident_excess_nonnegative',
            ),
        ]

    def __str__(self):
        return f"{self.car.rego} - {self.accident_date} - ${self.accident_excess}"
