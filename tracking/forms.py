from django import forms
from .models import Tool, Car, Transfer, OdometerReading, Maintenance,MaintenanceItem
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django.forms.widgets import DateInput
from django.forms import inlineformset_factory
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import Profile

# --------- Import Form ---------
class ImportForm(forms.Form):
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

# --------- Tool Form ---------
class ToolForm(forms.ModelForm):
    assigned_car = forms.ModelChoiceField(
        queryset=Car.objects.all(),
        required=False,
        label="Assigned Car",
        empty_label="Select a Car"
    )

    class Meta:
        model = Tool
        fields = [
            'internal_number','serial_number', 'tool_name', 'brand', 'description', 'size', 'store', 'state', 'quantity',
            'calibration_date', 'assigned_user','photo', 'estimated_cost', 'assigned_car'
        ]
        widgets = {
            'calibration_date': DateInput(attrs={'type': 'date', 'class': 'form-control'})
        }
    def __init__(self, *args, **kwargs):
        super(ToolForm, self).__init__(*args, **kwargs)
        self.fields['assigned_user'].queryset = User.objects.all()
        self.fields['assigned_car'].queryset = Car.objects.all()
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Save Tool'))

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

MaintenanceItemFormSet = inlineformset_factory(
    Maintenance, MaintenanceItem,
    fields=['description', 'item_type', 'quantity', 'unit_cost'],
    extra=1,
    can_delete=True
)

# --------- Transfer Form ---------
class TransferForm(forms.ModelForm):
    class Meta:
        model = Transfer
        fields = ['transfer_type', 'item_id', 'from_user', 'to_user', 'date_of_transfer']

    def __init__(self, *args, **kwargs):
        super(TransferForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Transfer'))

# --------- User Creation Form ---------
class UserForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']

    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Save User'))

# --------- User Update Form ---------
class UserUpdateForm(UserChangeForm):
    state = forms.ChoiceField(
        choices=Profile._meta.get_field('state').choices,
        required=False,
        label='Manager State'
    )

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'state']

    def __init__(self, *args, **kwargs):
        super(UserUpdateForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.add_input(Submit('submit', 'Update User'))

        user = self.instance
        if hasattr(user, 'profile'):
            self.fields['state'].initial = user.profile.state

    def save(self, commit=True):
        user = super(UserUpdateForm, self).save(commit=False)
        if commit:
            user.save()
            if hasattr(user, 'profile'):
                user.profile.state = self.cleaned_data.get('state')
                user.profile.save()
        return user
class MaintenanceItemForm(forms.ModelForm):
    class Meta:
        model = MaintenanceItem
        fields = ['description', 'item_type', 'quantity', 'unit_cost']