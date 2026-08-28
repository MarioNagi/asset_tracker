from django import forms
from .models import (
    Tool, Car, Transfer, OdometerReading, Maintenance, MaintenanceItem, Accident,
    VehicleRetirementTask, CustodyLocation, TransferFollowUpTask, AlertContact,
    ToolCatalogueItem, FuelRecord, SpecialMaintenanceRequirement,
)
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django.forms.widgets import DateInput
from django.forms import inlineformset_factory
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.utils import timezone
from .models import Profile
from pathlib import Path
from django.core.files.uploadedfile import UploadedFile
from django.core.files.base import ContentFile
from PIL import Image, ImageOps
from io import BytesIO


UPLOAD_SIGNATURES = {
    '.pdf': (b'%PDF-',),
    '.jpg': (b'\xff\xd8\xff',),
    '.jpeg': (b'\xff\xd8\xff',),
    '.png': (b'\x89PNG\r\n\x1a\n',),
}


def validate_uploaded_file(upload, *, max_size, allowed_extensions, label):
    """Validate size, extension, and magic bytes for a new upload."""
    if not upload or not isinstance(upload, UploadedFile):
        return upload
    if upload.size > max_size:
        raise forms.ValidationError(
            f'{label} must be {max_size // (1024 * 1024)} MB or smaller.'
        )
    suffix = Path(upload.name).suffix.lower()
    if suffix not in allowed_extensions:
        raise forms.ValidationError(f'{label} must be a PDF, JPEG, or PNG file.')
    header = upload.read(8)
    upload.seek(0)
    if not any(header.startswith(signature) for signature in UPLOAD_SIGNATURES[suffix]):
        raise forms.ValidationError(
            f'{label} content does not match its file extension.'
        )
    return upload


def compress_receipt_image(upload):
    """Correct phone orientation and store a readable, bounded JPEG."""
    if not upload:
        return upload
    upload.seek(0)
    with Image.open(upload) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
        image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format='JPEG', quality=82, optimize=True)
    upload.seek(0)
    safe_name = f'{Path(upload.name).stem[:80] or "receipt"}.jpg'
    return ContentFile(output.getvalue(), name=safe_name)

# --------- Import Form ---------
class ImportForm(forms.Form):
    MAX_FILE_SIZE = 5 * 1024 * 1024
    FILE_TYPE_CHOICES = [
        ('User', 'User'),
        ('Tool', 'Tool'),
        ('Car', 'Car'),
    ]
    FILE_FORMAT_CHOICES = [
        ('csv', 'CSV'),
        ('excel', 'Excel')
    ]
    file = forms.FileField(help_text='Select a CSV or Excel file to import')
    type = forms.ChoiceField(choices=FILE_TYPE_CHOICES, help_text='Select the type of data to import')
    format = forms.ChoiceField(choices=FILE_FORMAT_CHOICES, help_text='Select the file format')

    def __init__(self, *args, **kwargs):
        super(ImportForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Import'))

    def clean(self):
        cleaned_data = super().clean()
        uploaded_file = cleaned_data.get('file')
        file_format = cleaned_data.get('format')
        if not uploaded_file or not file_format:
            return cleaned_data

        if uploaded_file.size > self.MAX_FILE_SIZE:
            self.add_error('file', 'The import file must be 5 MB or smaller.')
            return cleaned_data

        suffix = Path(uploaded_file.name).suffix.lower()
        allowed_suffixes = {'csv': {'.csv'}, 'excel': {'.xlsx'}}
        if suffix not in allowed_suffixes[file_format]:
            expected = '.csv' if file_format == 'csv' else '.xlsx'
            self.add_error('file', f'The selected format requires a {expected} file.')
            return cleaned_data

        header = uploaded_file.read(8)
        uploaded_file.seek(0)
        if file_format == 'excel' and not header.startswith(b'PK'):
            self.add_error('file', 'The uploaded file is not a valid .xlsx workbook.')
        elif file_format == 'csv' and (not header or b'\x00' in header):
            self.add_error('file', 'The uploaded file is not a valid CSV text file.')

        return cleaned_data


class PDFInvoiceUploadForm(forms.Form):
    MAX_FILE_SIZE = 10 * 1024 * 1024

    invoice_file = forms.FileField(
        label='PDF invoice',
        help_text='Select one PDF invoice no larger than 10 MB.',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'application/pdf,.pdf',
        }),
    )

    def clean_invoice_file(self):
        uploaded_file = self.cleaned_data['invoice_file']
        if uploaded_file.size > self.MAX_FILE_SIZE:
            raise forms.ValidationError('The PDF invoice must be 10 MB or smaller.')
        if Path(uploaded_file.name).suffix.lower() != '.pdf':
            raise forms.ValidationError('The invoice must use the .pdf file extension.')

        header = uploaded_file.read(5)
        uploaded_file.seek(0)
        if header != b'%PDF-':
            raise forms.ValidationError('The uploaded file is not a valid PDF document.')
        return uploaded_file


class PDFInvoiceConfirmForm(forms.Form):
    pending_token = forms.CharField(widget=forms.HiddenInput)
    confirm_details = forms.BooleanField(
        label='I reviewed the extracted details and confirm they are correct.'
    )

# --------- Tool Form ---------
class ToolForm(forms.ModelForm):
    tool_name = forms.ChoiceField(
        label='Tool or device type',
        widget=forms.TextInput(attrs={
            'list': 'tool-catalogue-options',
            'autocomplete': 'off',
            'placeholder': 'Start typing, for example PIM, OTDR, drill, or tool bag',
        }),
    )
    assigned_car = forms.ModelChoiceField(
        queryset=Car.objects.active(),
        required=False,
        label="Assigned Car",
        empty_label="Select a Car"
    )

    class Meta:
        model = Tool
        fields = [
            'internal_number', 'serial_number', 'tool_name', 'brand', 'description',
            'is_controlled', 'condition', 'estimated_cost', 'photo',
            'calibration_required', 'calibration_date',
            'size', 'store', 'state', 'quantity', 'assigned_user',
            'custody_location', 'assigned_car',
        ]
        widgets = {
            'calibration_date': DateInput(attrs={'type': 'date', 'class': 'form-control'})
        }
    def __init__(self, *args, **kwargs):
        super(ToolForm, self).__init__(*args, **kwargs)
        catalogue = list(ToolCatalogueItem.objects.filter(active=True).order_by('name'))
        current_name = self.instance.tool_name if self.instance.pk else ''
        choices = [(item.name, item.name) for item in catalogue]
        if current_name and current_name not in {value for value, _ in choices}:
            choices.append((current_name, f'{current_name} (legacy/inactive)'))
        self.fields['tool_name'].choices = [('', 'Start typing to search')] + choices
        self.catalogue_items = catalogue
        self.fields['assigned_user'].queryset = User.objects.all()
        self.fields['assigned_car'].queryset = Car.objects.active()
        self.fields['custody_location'].queryset = CustodyLocation.objects.filter(
            active=True
        ).order_by('state', 'name')
        self.fields['is_controlled'].label = 'Controlled device'
        self.fields['calibration_date'].label = 'Next calibration due date'
        self.fields['estimated_cost'].label = 'Estimated replacement value'
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Save Tool'))

    def clean_photo(self):
        return validate_uploaded_file(
            self.cleaned_data.get('photo'), max_size=10 * 1024 * 1024,
            allowed_extensions={'.jpg', '.jpeg', '.png'}, label='Tool photograph',
        )


class ToolCatalogueItemForm(forms.ModelForm):
    class Meta:
        model = ToolCatalogueItem
        fields = [
            'name', 'suggested_controlled',
            'suggested_calibration_required', 'notes', 'active',
        ]

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        duplicate = ToolCatalogueItem.objects.filter(
            name__iexact=name
        ).exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise forms.ValidationError('This tool or device type already exists.')
        return name

# --------- Car Form ---------
class CarForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = [
            'rego', 'rego_expiry_date', 'purchase_date', 'purchase_price', 'state',
            'assigned_user', 'current_odometer', 'service_odometer', 'make', 'model', 'vin_number','manufacturing_year', 'color', 'body', 'photo'
        ]
        widgets = {
            'rego_expiry_date': DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'purchase_date': DateInput(attrs={'type': 'date', 'class': 'form-control'})
        }
    def __init__(self, *args, **kwargs):
        super(CarForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Save Car'))

    def clean_photo(self):
        return validate_uploaded_file(
            self.cleaned_data.get('photo'), max_size=10 * 1024 * 1024,
            allowed_extensions={'.jpg', '.jpeg', '.png'}, label='Vehicle photograph',
        )

# --------- Odometer Reading Form ---------
class OdometerReadingForm(forms.ModelForm):
    class Meta:
        model = OdometerReading
        fields = ['car', 'reading_date', 'reading_value']

    def __init__(self, *args, **kwargs):
        super(OdometerReadingForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Save Odometer Reading'))

# --------- Odometer Update Form ---------
class OdometerUpdateForm(forms.ModelForm):
    class Meta:
        model = Car
        fields = ['current_odometer']
        widgets = {
            'current_odometer': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter current odometer reading',
                'min': 0
            })
        }
        labels = {
            'current_odometer': 'Current Odometer Reading (km)'
        }

    def __init__(self, *args, **kwargs):
        super(OdometerUpdateForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Update Odometer'))

    def clean_current_odometer(self):
        new_odometer = self.cleaned_data.get('current_odometer')
        current_odometer = self.instance.current_odometer
        
        if new_odometer is not None and new_odometer <= current_odometer:
            raise forms.ValidationError(
                f'New odometer reading ({new_odometer:,} km) must be higher than the current reading ({current_odometer:,} km).'
            )
        
        return new_odometer


class VehicleQRSubmissionForm(forms.Form):
    odometer = forms.IntegerField(min_value=0, label='Current odometer (km)')
    include_fuel = forms.BooleanField(required=False, label='I am recording a fuel purchase')
    liters = forms.DecimalField(
        required=False, min_value=0.01, max_value=300,
        max_digits=6, decimal_places=2,
    )
    cost_per_liter = forms.DecimalField(
        required=False, min_value=0.01, max_value=10,
        max_digits=4, decimal_places=2,
        label='Cost per litre',
    )
    fuel_type = forms.ChoiceField(required=False, choices=FuelRecord._meta.get_field('fuel_type').choices)
    station = forms.CharField(required=False, max_length=100)
    full_tank = forms.BooleanField(required=False, initial=True)
    receipt = forms.ImageField(required=False, help_text='Required for every fuel purchase.')
    odometer_photo = forms.ImageField(
        required=False,
        help_text='Required only when the reading is flagged as unusual.',
    )
    confirm_vehicle = forms.BooleanField(
        label='I confirm this is the vehicle I am currently driving.'
    )

    def __init__(self, *args, car=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.car = car
        self.suspicious_reason = ''

    def clean(self):
        cleaned = super().clean()
        if not self.car:
            raise forms.ValidationError('The vehicle could not be identified.')
        reading = cleaned.get('odometer')
        reasons = []
        if reading is not None:
            if reading <= self.car.current_odometer:
                reasons.append('Reading is not above the current recorded odometer.')
            latest = self.car.odometer_readings.filter(
                review_status='accepted'
            ).order_by('-created_at', '-reading_date', '-pk').first()
            if latest and reading > latest.reading_value:
                increase = reading - latest.reading_value
                if (latest.created_at and
                        latest.created_at >= timezone.now() - timezone.timedelta(hours=24) and
                        increase > 1000):
                    reasons.append('Reading increased by more than 1,000 km within 24 hours.')
                elif (latest.reading_date >= timezone.localdate() - timezone.timedelta(days=7)
                      and increase > 3000):
                    reasons.append('Reading increased by more than 3,000 km within seven days.')
            if self.car.odometer_readings.filter(review_status='pending').exists():
                reasons.append('This vehicle already has a reading waiting for review.')
        self.suspicious_reason = ' '.join(reasons)
        if self.suspicious_reason and not cleaned.get('odometer_photo'):
            self.add_error(
                'odometer_photo',
                f'{self.suspicious_reason} Add a dashboard photograph for review.',
            )

        if cleaned.get('include_fuel'):
            for field in ('liters', 'cost_per_liter', 'fuel_type', 'receipt'):
                if not cleaned.get(field):
                    self.add_error(field, 'This field is required for a fuel purchase.')
            if all(cleaned.get(field) is not None for field in ('odometer', 'liters', 'cost_per_liter')):
                if FuelRecord.objects.filter(
                    car=self.car, date=timezone.localdate(),
                    odometer=cleaned['odometer'], liters=cleaned['liters'],
                    cost_per_liter=cleaned['cost_per_liter'],
                ).exists():
                    raise forms.ValidationError(
                        'This appears to duplicate a fuel entry already recorded today.'
                    )
        return cleaned

    def clean_receipt(self):
        upload = self.cleaned_data.get('receipt')
        if not upload:
            return upload
        validated = validate_uploaded_file(
            upload, max_size=10 * 1024 * 1024,
            allowed_extensions={'.jpg', '.jpeg', '.png'}, label='Fuel receipt',
        )
        return compress_receipt_image(validated)

    def clean_odometer_photo(self):
        upload = self.cleaned_data.get('odometer_photo')
        if not upload:
            return upload
        validated = validate_uploaded_file(
            upload, max_size=10 * 1024 * 1024,
            allowed_extensions={'.jpg', '.jpeg', '.png'}, label='Odometer photograph',
        )
        return compress_receipt_image(validated)


class OdometerReviewForm(forms.Form):
    decision = forms.ChoiceField(choices=[('accept', 'Accept'), ('reject', 'Reject')])
    review_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))


class SpecialMaintenanceRequirementForm(forms.ModelForm):
    class Meta:
        model = SpecialMaintenanceRequirement
        fields = [
            'car', 'title', 'due_date', 'due_odometer', 'advance_notice_days',
            'advance_notice_km', 'recurrence_days', 'recurrence_km', 'notes',
        ]
        widgets = {
            'due_date': DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class SpecialMaintenanceCompleteForm(forms.ModelForm):
    class Meta:
        model = SpecialMaintenanceRequirement
        fields = ['completed_odometer', 'completion_notes', 'completion_document']
        widgets = {'completion_notes': forms.Textarea(attrs={'rows': 3})}

    def clean_completion_document(self):
        return validate_uploaded_file(
            self.cleaned_data.get('completion_document'),
            max_size=15 * 1024 * 1024,
            allowed_extensions={'.pdf', '.jpg', '.jpeg', '.png'},
            label='Completion document',
        )

# --------- Maintenance Form ---------
class MaintenanceForm(forms.ModelForm):
    class Meta:
        model = Maintenance
        fields = [
            'car', 'service_date', 'odometer_reading', 'service_type',
            'invoice_number', 'service_provider', 'description',
            'total_cost', 'documents'
        ]
        widgets = {
            'service_date': DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'documents': forms.FileInput(attrs={'class': 'form-control'})
        }

    def __init__(self, *args, **kwargs):
        super(MaintenanceForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Save Maintenance Record'))

    def clean_documents(self):
        return validate_uploaded_file(
            self.cleaned_data.get('documents'), max_size=15 * 1024 * 1024,
            allowed_extensions={'.pdf', '.jpg', '.jpeg', '.png'},
            label='Maintenance document',
        )

MaintenanceItemFormSet = inlineformset_factory(
    Maintenance, MaintenanceItem,
    fields=['description', 'item_type', 'quantity', 'unit_cost'],
    extra=1,
    can_delete=True
)

# --------- Transfer Form ---------
class TransferForm(forms.Form):
    from_user = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, label='From employee'
    )
    from_location = forms.ModelChoiceField(
        queryset=CustodyLocation.objects.none(), required=False,
        label='Or from company location',
    )
    to_user = forms.ModelChoiceField(
        queryset=User.objects.none(), required=False, label='To employee'
    )
    to_location = forms.ModelChoiceField(
        queryset=CustodyLocation.objects.none(), required=False,
        label='Or to company location',
    )
    tools = forms.ModelMultipleChoiceField(
        queryset=Tool.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    transfer_all_tools = forms.BooleanField(
        required=False, label='Transfer all tools held by this source'
    )
    car = forms.ModelChoiceField(
        queryset=Car.objects.none(), required=False, label='Vehicle (maximum one)'
    )
    date_of_transfer = forms.DateField(
        initial=timezone.localdate, widget=DateInput(attrs={'type': 'date'})
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, source_user=None, source_location=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_user = source_user
        self.source_location = source_location
        self.fields['from_user'].queryset = User.objects.filter(is_active=True).order_by(
            'first_name', 'last_name', 'username'
        )
        self.fields['to_user'].queryset = self.fields['from_user'].queryset
        locations = CustodyLocation.objects.filter(active=True)
        self.fields['from_location'].queryset = locations
        self.fields['to_location'].queryset = locations
        if source_user:
            self.fields['tools'].queryset = Tool.objects.filter(assigned_user=source_user)
            self.fields['car'].queryset = Car.objects.active().filter(assigned_user=source_user)
            self.fields['from_user'].initial = source_user
        elif source_location:
            self.fields['tools'].queryset = Tool.objects.filter(custody_location=source_location)
            self.fields['car'].queryset = Car.objects.active().filter(custody_location=source_location)
            self.fields['from_location'].initial = source_location

    def clean(self):
        cleaned = super().clean()
        from_user = cleaned.get('from_user')
        from_location = cleaned.get('from_location')
        to_user = cleaned.get('to_user')
        to_location = cleaned.get('to_location')
        if bool(from_user) == bool(from_location):
            raise forms.ValidationError('Choose one source employee or one source warehouse.')
        if bool(to_user) == bool(to_location):
            raise forms.ValidationError('Choose one destination employee or one destination warehouse.')
        if from_user and from_user == to_user:
            raise forms.ValidationError('Source and destination employees must be different.')
        if from_location and from_location == to_location:
            raise forms.ValidationError('Source and destination warehouses must be different.')

        source_tools = Tool.objects.filter(
            assigned_user=from_user
        ) if from_user else Tool.objects.filter(custody_location=from_location)
        source_car = Car.objects.active().filter(
            assigned_user=from_user
        ) if from_user else Car.objects.active().filter(custody_location=from_location)

        if cleaned.get('transfer_all_tools'):
            cleaned['tools'] = source_tools
        elif any(tool.pk not in set(source_tools.values_list('pk', flat=True)) for tool in cleaned.get('tools', [])):
            self.add_error('tools', 'One or more tools are no longer held by the selected source.')
        car = cleaned.get('car')
        if car and not source_car.filter(pk=car.pk).exists():
            self.add_error('car', 'The vehicle is no longer held by the selected source.')
        if not cleaned.get('tools') and not car:
            raise forms.ValidationError('Choose at least one tool or one vehicle.')
        if car and to_user and Car.objects.active().filter(assigned_user=to_user).exclude(pk=car.pk).exists():
            self.add_error('to_user', 'This employee already has an active vehicle.')
        return cleaned

# --------- User Creation Form ---------
class UserForm(UserCreationForm):
    access_level = forms.ChoiceField(choices=Profile.ACCESS_LEVELS)
    state = forms.ChoiceField(
        choices=Profile._meta.get_field('state').choices,
        required=False,
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name',
            'access_level', 'state', 'password1', 'password2',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Save User'))

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.access_level = self.cleaned_data['access_level']
            profile.state = self.cleaned_data.get('state') or None
            profile.save()
        return user


class CarRetirementForm(forms.ModelForm):
    confirm_retirement = forms.BooleanField(
        label='I confirm this vehicle must leave the active fleet',
    )

    class Meta:
        model = Car
        fields = [
            'status', 'retired_at', 'final_odometer', 'final_value',
            'final_payment_date', 'final_payment_source',
            'final_payment_reference', 'retirement_notes',
            'retirement_document',
        ]
        widgets = {
            'retired_at': DateInput(attrs={'type': 'date'}),
            'final_payment_date': DateInput(attrs={'type': 'date'}),
            'retirement_notes': forms.Textarea(attrs={'rows': 4}),
        }

    def clean_status(self):
        status = self.cleaned_data['status']
        if status == Car.STATUS_IN_SERVICE:
            raise forms.ValidationError('Choose Sold or Written off.')
        return status

    def clean_retirement_document(self):
        return validate_uploaded_file(
            self.cleaned_data.get('retirement_document'),
            max_size=15 * 1024 * 1024,
            allowed_extensions={'.pdf', '.jpg', '.jpeg', '.png'},
            label='Retirement document',
        )

    def clean(self):
        cleaned = super().clean()
        required = {
            'retired_at': 'Retirement date is required.',
            'final_odometer': 'Final odometer is required.',
            'final_value': 'Final amount received is required.',
            'final_payment_date': 'Payment date is required.',
            'final_payment_source': 'Payment source is required.',
            'retirement_notes': 'Retirement notes are required.',
        }
        for field, message in required.items():
            if cleaned.get(field) in (None, ''):
                self.add_error(field, message)
        final_value = cleaned.get('final_value')
        if final_value is not None and final_value < 0:
            self.add_error('final_value', 'Final amount cannot be negative.')
        final_odometer = cleaned.get('final_odometer')
        if final_odometer is not None and final_odometer < self.instance.current_odometer:
            self.add_error(
                'final_odometer',
                'Final odometer cannot be below the current recorded odometer.',
            )
        return cleaned


class VehicleRetirementTaskForm(forms.ModelForm):
    class Meta:
        model = VehicleRetirementTask
        fields = ['completed', 'notes']


class TransferFollowUpTaskForm(forms.ModelForm):
    class Meta:
        model = TransferFollowUpTask
        fields = ['completed']


class CompanyLocationForm(forms.ModelForm):
    class Meta:
        model = CustodyLocation
        fields = [
            'name', 'location_type', 'state', 'address',
            'responsible_manager', 'active', 'notes',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsible_manager'].queryset = User.objects.filter(
            profile__access_level__in=['Admin', 'Manager'], is_active=True,
        ).order_by('first_name', 'last_name', 'username')


class AlertContactForm(forms.ModelForm):
    categories = forms.MultipleChoiceField(
        choices=AlertContact.CATEGORY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        label='Email alert categories',
    )

    class Meta:
        model = AlertContact
        fields = [
            'name', 'email', 'responsibility', 'state', 'is_primary',
            'categories', 'linked_user', 'enabled',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['linked_user'].queryset = User.objects.filter(
            is_active=True
        ).order_by('first_name', 'last_name', 'username')
        if self.instance.pk:
            self.fields['categories'].initial = self.instance.categories

# --------- User Update Form ---------
class UserUpdateForm(UserChangeForm):
    access_level = forms.ChoiceField(choices=Profile.ACCESS_LEVELS)
    state = forms.ChoiceField(
        choices=Profile._meta.get_field('state').choices,
        required=False,
        label='Manager State'
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'access_level', 'state']

    def __init__(self, *args, **kwargs):
        super(UserUpdateForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Update User'))

        user = self.instance
        if hasattr(user, 'profile'):
            self.fields['access_level'].initial = user.profile.access_level
            self.fields['state'].initial = user.profile.state

    def save(self, commit=True):
        user = super(UserUpdateForm, self).save(commit=False)
        if commit:
            user.save()
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.access_level = self.cleaned_data['access_level']
            profile.state = self.cleaned_data.get('state') or None
            profile.save()
        return user
class MaintenanceItemForm(forms.ModelForm):
    class Meta:
        model = MaintenanceItem
        fields = ['description', 'item_type', 'quantity', 'unit_cost']


# --------- Accident Form ---------
class AccidentForm(forms.ModelForm):
    class Meta:
        model = Accident
        fields = [
            'car', 'accident_date', 'driver', 'accident_excess',
            'via_insurance', 'insurance_company', 'description',
            'location', 'claim_number'
        ]
        widgets = {
            'accident_date': DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'car': forms.Select(attrs={'class': 'form-control'}),
            'driver': forms.Select(attrs={'class': 'form-control'}),
            'accident_excess': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'via_insurance': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'insurance_company': forms.TextInput(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'claim_number': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        accident_date = cleaned_data.get('accident_date')
        accident_excess = cleaned_data.get('accident_excess')
        via_insurance = cleaned_data.get('via_insurance')
        insurance_company = (cleaned_data.get('insurance_company') or '').strip()
        claim_number = (cleaned_data.get('claim_number') or '').strip()

        if accident_date and accident_date > timezone.localdate():
            self.add_error('accident_date', 'The accident date cannot be in the future.')
        if accident_excess is not None and accident_excess < 0:
            self.add_error(
                'accident_excess', 'The recorded company cost cannot be negative.'
            )
        if via_insurance and not insurance_company:
            self.add_error(
                'insurance_company',
                'Enter the insurance company for an insured accident.',
            )
        if not via_insurance and (insurance_company or claim_number):
            self.add_error(
                'via_insurance',
                'Mark this accident as insured or clear the insurance details.',
            )
        return cleaned_data
