from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models.signals import pre_save
from django.dispatch import receiver


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


# --------- Tool Model ---------
class Tool(models.Model):
    internal_number = models.CharField(max_length=100, primary_key=True, unique=True, blank=True, db_index=True)  # Add db_index
    serial_number =models.CharField(max_length=100, unique=True, blank=True, null=True, db_index=True)  # Add db_index  
    tool_name = models.CharField(max_length=100, choices = [
    ('radman', 'radman'),
    ('ladsaf', 'ladsaf'),
    ('harness', 'harness'),
    ('pole strap', 'pole strap'),
    ('double lanyard', 'double lanyard'),
    ('triple action carabiner', 'triple action carabiner'),
    ('tools lanyard', 'tools lanyard'),
    ('bag for harness and rigging gears', 'bag for harness and rigging gears'),
    ('helmet for rigger', 'helmet for rigger'),
    ('gloves', 'gloves'),
    ('glasses', 'glasses'),
    ('rescue kit', 'rescue kit'),
    ('spills kit', 'spills kit'),
    ('fire blanket', 'fire blanket'),
    ('slings length and capacity yellow', 'slings length and capacity yellow'),
    ('slings length and capacity green', 'slings length and capacity green'),
    ('first aid kit - survival work place', 'first aid kit - survival work place'),
    ('fire extinguisher 4.5 kg abe dry powder', 'fire extinguisher 4.5 kg abe dry powder'),
    ('cable tie gun', 'cable tie gun'),
    ('tools bag', 'tools bag'),
    ('screwdrivers set', 'screwdrivers set'),
    ('insulated screwdriver 6pcs', 'insulated screwdriver 6pcs'),
    ('allen key (big set)', 'allen key (big set)'),
    ('alan key set star', 'alan key set star'),
    ('ratchet podger 32,30,19', 'ratchet podger 32,30,19'),
    ('adjustable wrench small', 'adjustable wrench small'),
    ('adjustable wrench medium', 'adjustable wrench medium'),
    ('adjustable wrench large', 'adjustable wrench large'),
    ('adjustable wrench xlarge', 'adjustable wrench xlarge'),
    ('stuppy set', 'stuppy set'),
    ('spanner set', 'spanner set'),
    ('reverse combination wrench set', 'reverse combination wrench set'),
    ('drive socket set', 'drive socket set'),
    ('3 piece plier set', '3 piece plier set'),
    ('cable cutter for edge small', 'cable cutter for edge small'),
    ('cable cutter for edge medium', 'cable cutter for edge medium'),
    ('cable cutter large 20 cm to 25 cm', 'cable cutter large 20 cm to 25 cm'),
    ('cable cutter yellow xlarge', 'cable cutter yellow xlarge'),
    ('irwin snips', 'irwin snips'),
    ('cordless hammer drill', 'cordless hammer drill'),
    ('cordless drill', 'cordless drill'),
    ('cordless impact wrench', 'cordless impact wrench'),
    ('cordless driver', 'cordless driver'),
    ('cordless grinder', 'cordless grinder'),
    ('charger makita', 'charger makita'),
    ('battery makita', 'battery makita'),
    ('impact drive socket set', 'impact drive socket set'),
    ('1/4", 3/8" & 1/2" impact socket adaptor set', '1/4", 3/8" & 1/2" impact socket adaptor set'),
    ('sutton hole saw kit', 'sutton hole saw kit'),
    ('steel drill bits set', 'steel drill bits set'),
    ('masonry bits set', 'masonry bits set'),
    ('drill bit set 246', 'drill bit set 246'),
    ('screwdrivers & socket bits set', 'screwdrivers & socket bits set'),
    ('hammer', 'hammer'),
    ('rj45 crimper', 'rj45 crimper'),
    ('hot air gun', 'hot air gun'),
    ('digital level', 'digital level'),
    ('water level', 'water level'),
    ('tape measure', 'tape measure'),
    ('meter tape - laser', 'meter tape - laser'),
    ('rivet gun', 'rivet gun'),
    ('multimeter digital aaa or aa', 'multimeter digital aaa or aa'),
    ('silicon gun', 'silicon gun'),
    ('small lugs crimper size 1 small', 'small lugs crimper size 1 small'),
    ('small lugs crimper size 2 medium', 'small lugs crimper size 2 medium'),
    ('big lugs crimper size 3 large', 'big lugs crimper size 3 large'),
    ('big lugs crimper hydraulic size 4 xlarge', 'big lugs crimper hydraulic size 4 xlarge'),
    ('rcd', 'rcd'),
    ('power lead (20 meters)', 'power lead (20 meters)'),
    ('shovel', 'shovel'),
    ('heavy duty wrecking bar', 'heavy duty wrecking bar'),
    ('jma antenna torque wrench', 'jma antenna torque wrench'),
    ('ladder fibre glass 3m', 'ladder fibre glass 3m'),
    ('filler', 'filler'),
    ('heat gun gas', 'heat gun gas'),
    ('heat gun electrical', 'heat gun electrical'),
    ('ratchets spanner set', 'ratchets spanner set'),
    ('generator', 'generator'),
    ('rain coats', 'rain coats'),
    ('cones 700mm', 'cones 700mm'),
    ('yellow hazard tape', 'yellow hazard tape'),
    ('workers ahead sign', 'workers ahead sign'),
    ('pedestrian sign', 'pedestrian sign'),
    ('tent', 'tent'),
    ('vacuum', 'vacuum'),
    ('brady label printer', 'brady label printer'),
    ('chain block', 'chain block'),
    ('lever block come along', 'lever block come along'),
    ('rope 100 to meters', 'rope 100 to meters'),
    ('otdr + charger + bag + port protector', 'otdr + charger + bag + port protector'),
    ('launch cable', 'launch cable'),
    ('power meter', 'power meter'),
    ('light source', 'light source'),
    ('traffic identifier', 'traffic identifier'),
    ('microscope electronic', 'microscope electronic'),
    ('laser pen 30mw', 'laser pen 30mw'),
    ('cleaner 2.5mm pen', 'cleaner 2.5mm pen'),
    ('cleaner 1.25mm pen', 'cleaner 1.25mm pen'),
    ('cleaner cassette', 'cleaner cassette'),
    ('pon meter', 'pon meter'),
    ('splicer single', 'splicer single'),
    ('cleaver', 'cleaver'),
    ('stripper yellow', 'stripper yellow'),
    ('small blue jacket remover', 'small blue jacket remover'),
    ('big blue jacket remover', 'big blue jacket remover'),
    ('seal breaker', 'seal breaker'),
    ('manhole guards', 'manhole guards'),
    ('pit keys', 'pit keys'),
    ('gas tester with charger + probe (set of 2 devices)', 'gas tester with charger + probe (set of 2 devices)'),
    ('alcohol dispenser', 'alcohol dispenser'),
    ('scissors', 'scissors'),
    ('g jacket remover', 'g jacket remover'),
    ('tpg fist joint holder', 'tpg fist joint holder'),
    ('t jacket remover', 't jacket remover'),
    ('opti tab cable', 'opti tab cable'),
    ('rodder 6mm', 'rodder 6mm'),
    ('rodder 11mm', 'rodder 11mm'),
    ('snake', 'snake'),
    ('printer a4 with usb cable', 'printer a4 with usb cable'),
    ('laptop', 'laptop'),
    ('all data cables needed for projects', 'all data cables needed for projects'),
    ('dymo label printer small', 'dymo label printer small'),
    ('label printer for feeder', 'label printer for feeder'),
    ('dymo embossing rhino heavy duty tool kit m1011', 'dymo embossing rhino heavy duty tool kit m1011'),
    ('laminator', 'laminator'),
    ('wire tracker', 'wire tracker'),
    ('ethernet tester', 'ethernet tester'),
    ('cat5/6 puncher', 'cat5/6 puncher'),
    ('multimeter', 'multimeter'),
]
, db_index=True)  # Add db_index
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
    assigned_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='tools')
    assigned_car = models.ForeignKey('Car', on_delete=models.SET_NULL, null=True, blank=True, related_name='tools')

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
class Car(models.Model):
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
    current_odometer = models.PositiveIntegerField(default=0, help_text='Current odometer reading in kilometers')
    service_odometer = models.PositiveIntegerField(default=10000, help_text='Odometer reading when next service is due')
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    vin_number = models.CharField(max_length=100, unique=True)
    manufacturing_year = models.PositiveIntegerField(null=True, blank=True)  # New field for manufacturing year
    color = models.CharField(max_length=30, blank=True, null=True)  # New field for color
    body = models.CharField(max_length=50, choices=BODY_CHOICES, default='Sedan')  # New field for car body type
    photo = models.ImageField(upload_to='car_photos/', null=True, blank=True)
    
    # Maintenance related fields
    next_service_date = models.DateField(null=True, blank=True)
    service_interval_km = models.PositiveIntegerField(default=10000)
    last_service_km = models.PositiveIntegerField(null=True, blank=True)
    monthly_odometer_check = models.BooleanField(default=True)
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
        """Get the latest odometer reading."""
        return self.odometer_readings.order_by('-reading_date').first()

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
        
        total_cost = sum(record.total_cost for record in records)
        return {
            'total_cost': total_cost,
            'record_count': records.count(),
            'records': records
        }

    def get_fuel_efficiency(self, last_n_records=5):
        """Calculate average fuel efficiency from last N full tank records."""
        fuel_records = self.fuel_records.filter(full_tank=True).order_by('-date')[:last_n_records]
        efficiencies = [r.fuel_efficiency for r in fuel_records if r.fuel_efficiency]
        
        if not efficiencies:
            return None
            
        return {
            'current': efficiencies[0] if efficiencies else None,
            'average': sum(efficiencies) / len(efficiencies) if efficiencies else None,
            'best': min(efficiencies) if efficiencies else None,
            'worst': max(efficiencies) if efficiencies else None
        }

    def get_total_costs(self, start_date=None, end_date=None):
        """Calculate total costs including maintenance and fuel."""
        maintenance_data = self.get_maintenance_costs(start_date, end_date)
        
        fuel_records = self.fuel_records.all()
        if start_date:
            fuel_records = fuel_records.filter(date__gte=start_date)
        if end_date:
            fuel_records = fuel_records.filter(date__lte=end_date)
        
        fuel_cost = sum(record.total_cost for record in fuel_records)
        
        return {
            'maintenance_cost': maintenance_data['total_cost'],
            'fuel_cost': fuel_cost,
            'total_cost': maintenance_data['total_cost'] + fuel_cost
        }

    def get_tire_status(self):
        """Get status of current tires."""
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
            self.car.last_service_km = self.odometer_reading
            self.car.next_service_date = self.service_date + timezone.timedelta(days=180)  # 6 months
            self.car.save()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.service_type} for {self.car.rego} on {self.service_date}"


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
        return self.quantity * self.unit_cost

    def __str__(self):
        return f"{self.description} - ${self.total_cost}"


# --------- Odometer Reading ---------
class OdometerReading(models.Model):
    car = models.ForeignKey(Car, on_delete=models.CASCADE, related_name='odometer_readings', db_index=True)  # Add db_index
    reading_date = models.DateField(default=timezone.now)
    reading_value = models.PositiveIntegerField()

    class Meta:
        ordering = ['-reading_date']

    def __str__(self):
        return f"{self.car.rego} - {self.reading_date}: {self.reading_value} km"


# --------- Transfer Model ---------
class Transfer(models.Model):
    TRANSFER_TYPE_CHOICES = [('Tool', 'Tool'), ('Car', 'Car')]

    transfer_type = models.CharField(max_length=10, choices=TRANSFER_TYPE_CHOICES)
    item_id = models.PositiveIntegerField()
    from_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transfers_from')
    to_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='transfers_to')
    date_of_transfer = models.DateField(default=timezone.now)

    def __str__(self):
        return f"{self.transfer_type} Transfer on {self.date_of_transfer}"


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
