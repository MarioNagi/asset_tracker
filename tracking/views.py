import csv
import calendar
import xlsxwriter
import json
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from datetime import date, datetime, timedelta
from django.utils import timezone
import pandas as pd
import logging
import re
import qrcode
from io import BytesIO
from decimal import Decimal
from django.db import transaction
from django.db.models import Max, Q, Count, Sum
from django.http import HttpResponseForbidden
from django.core.files import File
from django.core.exceptions import ValidationError
from allauth.account.views import LoginView as AllauthLoginView
from .mixins import (
    UserRequiredMixin, ManagerRequiredMixin, AdminRequiredMixin,
    AdminManagerRequiredMixin, get_user_role, get_user_state,
)
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView, ListView, CreateView, UpdateView, DeleteView, DetailView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.urls import reverse_lazy
from django.contrib.auth.models import User
from django.contrib.auth.forms import SetPasswordForm
from django.contrib import messages
from .models import (
    Tool, Car, Transfer, OdometerReading, Maintenance, Profile, Accident,
    FuelRecord, VehicleRetirementTask, CustodyLocation, TransferBatch,
    TransferLedgerEntry, TransferFollowUpTask, AlertContact,
    NotificationDelivery, ToolCatalogueItem,
    SpecialMaintenanceRequirement,
)
from .forms import (
    ToolForm, CarForm, TransferForm, OdometerReadingForm, 
    MaintenanceForm, ImportForm, PDFInvoiceUploadForm, PDFInvoiceConfirmForm,
    UserForm, UserUpdateForm, MaintenanceItemFormSet, OdometerUpdateForm,
    AccidentForm, CarRetirementForm, VehicleRetirementTaskForm,
    TransferFollowUpTaskForm, CompanyLocationForm, AlertContactForm,
    ToolCatalogueItemForm,
    VehicleQRSubmissionForm, OdometerReviewForm,
    SpecialMaintenanceRequirementForm, SpecialMaintenanceCompleteForm,
)
from .notifications import (
    send_odometer_update_notification, check_and_send_service_reminders,
    send_vehicle_retirement_notification, send_transfer_notification,
)
from .invoice_utils import normalize_invoice_number
from .maintenance_service import MaintenanceInvoiceService
from .pdf_invoice_parser import validate_invoice_data
from .pdf_import_workflow import (
    PendingPDFError, PendingPDFInvoiceStore, validate_pdf_structure,
)
from .notification_service import retry_failed_notification

logger = logging.getLogger(__name__)


class ImportDataError(ValueError):
    """A safe validation error that can be shown to an import operator."""


def visible_cars_for(user, include_retired=False):
    """Return only the vehicles the signed-in user is allowed to see."""
    cars = Car.objects.all() if include_retired else Car.objects.active()
    role = get_user_role(user)
    if role == 'admin':
        return cars
    if role == 'manager':
        return cars.filter(state=get_user_state(user))
    return cars.filter(assigned_user=user)


def visible_tools_for(user):
    """Return only the tools the signed-in user is allowed to see."""
    role = get_user_role(user)
    if role == 'admin':
        return Tool.objects.all()
    if role == 'manager':
        return Tool.objects.filter(state=get_user_state(user))
    return Tool.objects.filter(assigned_user=user)


def visible_drivers_for_manager(user):
    """Return drivers in the manager's operational state."""
    state = get_user_state(user)
    if state == 'NSW':
        return User.objects.filter(profile__state__startswith='NSW-')
    return User.objects.filter(profile__state=state)


def visible_maintenance_for(user):
    """Return only the maintenance records the signed-in user may see."""
    role = get_user_role(user)
    if role == 'admin':
        return Maintenance.objects.all()
    if role == 'manager':
        return Maintenance.objects.filter(car__state=get_user_state(user))
    return Maintenance.objects.filter(car__assigned_user=user)


def _protected_file(field_file, *, inline=False):
    """Return a private upload only after its parent object was authorized."""
    if not field_file:
        raise Http404
    try:
        field_file.open('rb')
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise Http404 from exc
    response = FileResponse(
        field_file,
        as_attachment=not inline,
        filename=field_file.name.rsplit('/', 1)[-1].rsplit('\\', 1)[-1],
    )
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
def maintenance_document_download(request, pk):
    record = get_object_or_404(visible_maintenance_for(request.user), pk=pk)
    return _protected_file(record.documents)


@login_required
def car_photo_download(request, pk):
    car = get_object_or_404(
        visible_cars_for(request.user, include_retired=True), pk=pk
    )
    return _protected_file(car.photo, inline=True)


@login_required
def car_retirement_document_download(request, pk):
    car = get_object_or_404(
        visible_cars_for(request.user, include_retired=True), pk=pk
    )
    return _protected_file(car.retirement_document)


@login_required
def tool_photo_download(request, pk):
    tool = get_object_or_404(visible_tools_for(request.user), pk=pk)
    return _protected_file(tool.photo, inline=True)


@login_required
def fuel_receipt_download(request, pk):
    record = get_object_or_404(FuelRecord.objects.filter(
        Q(car__in=visible_cars_for(request.user)) | Q(submitted_by=request.user)
    ).distinct(), pk=pk)
    return _protected_file(record.receipt, inline=True)


@login_required
def odometer_evidence_download(request, pk):
    record = get_object_or_404(OdometerReading.objects.filter(
        Q(car__in=visible_cars_for(request.user)) | Q(submitted_by=request.user)
    ).distinct(), pk=pk)
    return _protected_file(record.evidence_photo, inline=True)


@login_required
def special_maintenance_document_download(request, pk):
    requirement = get_object_or_404(
        SpecialMaintenanceRequirement.objects.filter(
            car__in=visible_cars_for(request.user, include_retired=True)
        ), pk=pk,
    )
    return _protected_file(requirement.completion_document)


@login_required
def vehicle_qr_code(request, pk):
    car = get_object_or_404(visible_cars_for(request.user), pk=pk)
    entry_url = request.build_absolute_uri(
        reverse_lazy('vehicle_qr_entry', kwargs={'token': car.qr_token})
    )
    image = qrcode.make(entry_url)
    output = BytesIO()
    image.save(output, format='PNG')
    response = HttpResponse(output.getvalue(), content_type='image/png')
    response['Cache-Control'] = 'private, no-store'
    response['Content-Disposition'] = f'inline; filename="{car.rego}-qr.png"'
    return response


class DashboardView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        access_level = get_user_role(request.user)
        if access_level == 'admin':
            return redirect('admin_dashboard')
        elif access_level == 'manager':
            return redirect('manager_dashboard')
        else:  # User level
            return redirect('user_dashboard')

# ----- Login View -----
class CustomLoginView(AllauthLoginView):
    template_name = 'registration/login.html'

# ----- Dashboard Views -----
class AdminDashboardView(AdminRequiredMixin, TemplateView):
    template_name = 'tracking/admin_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tool_count'] = Tool.objects.count()
        context['cars'] = list(Car.objects.active())
        context['car_count'] = len(context['cars'])
        context['user_count'] = User.objects.count()
        context['maintenance_record_count'] = Maintenance.objects.filter(
            car__status=Car.STATUS_IN_SERVICE
        ).count()
        return context

class ManagerDashboardView(ManagerRequiredMixin, TemplateView):
    template_name = 'tracking/manager_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_state = get_user_state(self.request.user)
        context['tool_count'] = Tool.objects.filter(state=user_state).count()
        context['cars'] = list(Car.objects.active().filter(state=user_state))
        context['car_count'] = len(context['cars'])
        return context

class UserDashboardView(UserRequiredMixin, TemplateView):
    template_name = 'tracking/user_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['cars'] = Car.objects.active().filter(
            assigned_user=self.request.user
        ).prefetch_related('odometer_readings', 'tools')
        context['tools'] = Tool.objects.filter(assigned_user=self.request.user)
        context['recent_qr_cars'] = Car.objects.active().filter(
            odometer_readings__submitted_by=self.request.user,
            odometer_readings__source=OdometerReading.SOURCE_QR,
        ).exclude(assigned_user=self.request.user).distinct()[:3]
        return context

# ----- Role-Specific Car Views -----
class UserCarView(UserRequiredMixin, ListView):
    model = Car
    template_name = 'tracking/user_car_list.html'
    context_object_name = 'cars'
    paginate_by = 50

    def get_queryset(self):
        return Car.objects.active().filter(assigned_user=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['odometer_readings'] = OdometerReading.objects.filter(
            car__assigned_user=self.request.user
        ).order_by('-reading_date')[:5]
        return context

class AdminCarView(AdminRequiredMixin, ListView):
    model = Car
    template_name = 'tracking/car_list.html'
    context_object_name = 'cars'
    paginate_by = 50

    def get_queryset(self):
        return Car.objects.active().select_related('assigned_user')

# ----- Manager-Specific Views -----
class ManagerToolListView(ManagerRequiredMixin, ListView):
    model = Tool
    template_name = 'tracking/manager_tool_list.html'
    context_object_name = 'tools'
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        if get_user_role(user) == 'manager':
            return Tool.objects.filter(
                state=get_user_state(user)
            ).select_related('assigned_user').order_by('internal_number')
        return Tool.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['state'] = self.request.user.profile.state
        return context

class ManagerCarListView(ManagerRequiredMixin, ListView):
    model = Car
    template_name = 'tracking/manager_car_list.html'
    context_object_name = 'cars'
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        if get_user_role(user) == 'manager':
            return Car.objects.active().filter(
                state=get_user_state(user)
            ).select_related('assigned_user')
        return Car.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['state'] = self.request.user.profile.state
        return context

# ----- Tool Views -----
class ToolListView(LoginRequiredMixin, ListView):
    model = Tool
    template_name = 'tracking/tool_list.html'
    context_object_name = 'tools'
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset().select_related(
            'assigned_user', 'assigned_car', 'custody_location'
        )
        
        # Apply filters
        user_filter = self.request.GET.get('user')
        tool_name_filter = self.request.GET.get('tool_name')
        state_filter = self.request.GET.get('state')
        brand_filter = self.request.GET.get('brand')
        car_filter = self.request.GET.get('car')
        controlled_filter = self.request.GET.get('controlled')

        if user_filter:
            queryset = queryset.filter(assigned_user_id=user_filter)
        if tool_name_filter:
            queryset = queryset.filter(tool_name=tool_name_filter)
        if state_filter:
            queryset = queryset.filter(state=state_filter)
        if brand_filter:
            queryset = queryset.filter(brand=brand_filter)
        if car_filter:
            queryset = queryset.filter(assigned_car__rego=car_filter)
        if controlled_filter in {'yes', 'no'}:
            queryset = queryset.filter(is_controlled=(controlled_filter == 'yes'))
        
        # Apply user-level filtering
        if get_user_role(user) == 'manager':
            queryset = queryset.filter(state=get_user_state(user))
        elif get_user_role(user) != 'admin':
            queryset = queryset.filter(assigned_user=user)
        return queryset.order_by('internal_number')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Get available users based on access level
        if get_user_role(user) == 'admin':
            context['users'] = User.objects.all()
        elif get_user_role(user) == 'manager':
            context['users'] = User.objects.filter(profile__state=user.profile.state)
        else:
            context['users'] = User.objects.filter(id=user.id)

        # Get unique values for filter dropdowns
        accessible_tools = visible_tools_for(user)
        context['tool_names'] = accessible_tools.values_list('tool_name', flat=True).distinct()
        context['states'] = accessible_tools.values_list('state', flat=True).distinct()
        context['brands'] = accessible_tools.values_list('brand', flat=True).distinct()
        context['cars'] = visible_cars_for(user).values('rego').distinct()
        
        return context


class ToolDetailView(LoginRequiredMixin, DetailView):
    model = Tool
    template_name = 'tracking/tool_detail.html'
    context_object_name = 'tool'

    def get_queryset(self):
        return visible_tools_for(self.request.user).select_related(
            'assigned_user', 'assigned_car', 'custody_location'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['ledger_entries'] = self.object.custody_ledger_entries.select_related(
            'batch', 'batch__created_by', 'from_user', 'from_location',
            'to_user', 'to_location',
        ).order_by('-recorded_at')
        today = timezone.localdate()
        if not self.object.calibration_required:
            context['calibration_status'] = 'Not required'
            context['calibration_status_class'] = 'secondary'
        elif not self.object.calibration_date:
            context['calibration_status'] = 'Due date missing'
            context['calibration_status_class'] = 'danger'
        elif self.object.calibration_date < today:
            context['calibration_status'] = 'Overdue'
            context['calibration_status_class'] = 'danger'
        elif self.object.calibration_date <= today + timedelta(days=30):
            context['calibration_status'] = 'Due soon'
            context['calibration_status_class'] = 'warning'
        else:
            context['calibration_status'] = 'Current'
            context['calibration_status_class'] = 'success'
        return context

class ToolCreateView(AdminManagerRequiredMixin, CreateView):
    model = Tool
    form_class = ToolForm
    template_name = 'tracking/tool_form.html'
    success_url = reverse_lazy('tool_list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        if get_user_role(user) != 'admin':
            manager_state = get_user_state(user)
            form.fields['state'].initial = manager_state
            form.fields['state'].disabled = True
            form.fields['is_controlled'].disabled = True
            form.fields['assigned_user'].queryset = User.objects.filter(
                profile__state=user.profile.state
            )
            form.fields['assigned_car'].queryset = Car.objects.active().filter(
                state=manager_state
            )
            form.fields['custody_location'].queryset = CustodyLocation.objects.filter(
                state=manager_state, active=True,
            ).order_by('name')
        return form

class ToolUpdateView(AdminManagerRequiredMixin, UpdateView):
    model = Tool
    form_class = ToolForm
    template_name = 'tracking/tool_form.html'
    success_url = reverse_lazy('tool_list')

    def get_queryset(self):
        user = self.request.user
        if get_user_role(user) == 'admin':
            return super().get_queryset()
        return super().get_queryset().filter(state=get_user_state(user))

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        if get_user_role(user) != 'admin':
            manager_state = get_user_state(user)
            form.fields['state'].disabled = True
            form.fields['is_controlled'].disabled = True
            form.fields['assigned_user'].queryset = User.objects.filter(
                profile__state=user.profile.state
            )
            form.fields['assigned_car'].queryset = Car.objects.active().filter(
                state=manager_state
            )
            form.fields['custody_location'].queryset = CustodyLocation.objects.filter(
                state=manager_state, active=True,
            ).order_by('name')
        return form

class ToolCatalogueListView(AdminRequiredMixin, ListView):
    model = ToolCatalogueItem
    template_name = 'tracking/tool_catalogue_list.html'
    context_object_name = 'catalogue_items'
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset().select_related('updated_by')
        query = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', 'active')
        if query:
            queryset = queryset.filter(name__icontains=query)
        if status in {'active', 'inactive'}:
            queryset = queryset.filter(active=(status == 'active'))
        return queryset


class ToolCatalogueCreateView(AdminRequiredMixin, CreateView):
    model = ToolCatalogueItem
    form_class = ToolCatalogueItemForm
    template_name = 'tracking/tool_catalogue_form.html'
    success_url = reverse_lazy('tool_catalogue_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        messages.success(self.request, 'Tool catalogue item created and ready for selection.')
        return super().form_valid(form)


class ToolCatalogueUpdateView(AdminRequiredMixin, UpdateView):
    model = ToolCatalogueItem
    form_class = ToolCatalogueItemForm
    template_name = 'tracking/tool_catalogue_form.html'
    success_url = reverse_lazy('tool_catalogue_list')

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        messages.success(self.request, 'Tool catalogue item updated.')
        return super().form_valid(form)


class ToolDeleteView(AdminRequiredMixin, DeleteView):
    model = Tool
    template_name = 'tracking/tool_confirm_delete.html'
    success_url = reverse_lazy('tool_list')


class CompanyLocationListView(AdminManagerRequiredMixin, ListView):
    model = CustodyLocation
    template_name = 'tracking/company_location_list.html'
    context_object_name = 'locations'
    paginate_by = 30

    def get_queryset(self):
        queryset = CustodyLocation.objects.select_related('responsible_manager')
        if get_user_role(self.request.user) == 'manager':
            queryset = queryset.filter(state=get_user_state(self.request.user))

        status = self.request.GET.get('status', 'active')
        if status == 'inactive':
            queryset = queryset.filter(active=False)
        elif status != 'all':
            queryset = queryset.filter(active=True)

        location_type = self.request.GET.get('type', '')
        if location_type in dict(CustodyLocation.TYPE_CHOICES):
            queryset = queryset.filter(location_type=location_type)
        state = self.request.GET.get('state', '')
        if state:
            queryset = queryset.filter(state=state)
        search = self.request.GET.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(address__icontains=search)
            )
        return queryset.annotate(
            tool_count=Count('tools', distinct=True),
            active_car_count=Count(
                'cars', filter=Q(cars__status=Car.STATUS_IN_SERVICE), distinct=True,
            ),
        ).order_by('state', 'location_type', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['location_types'] = CustodyLocation.TYPE_CHOICES
        context['states'] = Car.STATE_CHOICES
        return context


class CompanyLocationDetailView(AdminManagerRequiredMixin, DetailView):
    model = CustodyLocation
    template_name = 'tracking/company_location_detail.html'
    context_object_name = 'location'

    def get_queryset(self):
        queryset = CustodyLocation.objects.select_related('responsible_manager')
        if get_user_role(self.request.user) == 'manager':
            queryset = queryset.filter(state=get_user_state(self.request.user))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tools'] = self.object.tools.select_related('assigned_user', 'assigned_car')
        context['cars'] = self.object.cars.active().select_related('assigned_user')
        context['transfers'] = TransferBatch.objects.filter(
            Q(from_location=self.object) | Q(to_location=self.object)
        ).select_related(
            'from_user', 'from_location', 'to_user', 'to_location', 'created_by'
        ).prefetch_related('entries')[:30]
        return context


class CompanyLocationCreateView(AdminRequiredMixin, CreateView):
    model = CustodyLocation
    form_class = CompanyLocationForm
    template_name = 'tracking/company_location_form.html'
    success_url = reverse_lazy('company_location_list')

    def form_valid(self, form):
        messages.success(self.request, 'Company location created.')
        return super().form_valid(form)


class CompanyLocationUpdateView(AdminRequiredMixin, UpdateView):
    model = CustodyLocation
    form_class = CompanyLocationForm
    template_name = 'tracking/company_location_form.html'

    def form_valid(self, form):
        messages.success(self.request, 'Company location updated.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('company_location_detail', kwargs={'pk': self.object.pk})

# ----- Car Views -----
class CarListView(LoginRequiredMixin, ListView):
    model = Car
    template_name = 'tracking/car_list.html'
    context_object_name = 'cars'
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        queryset = Car.objects.active().select_related('assigned_user')
        
        # Apply filters
        rego = self.request.GET.get('rego')
        year = self.request.GET.get('year')
        rego_expiry = self.request.GET.get('rego_expiry')
        
        if rego:
            queryset = queryset.filter(rego__icontains=rego)
        if year:
            queryset = queryset.filter(manufacturing_year=year)
        if rego_expiry:
            queryset = queryset.filter(rego_expiry_date__year=rego_expiry)
        
        # Apply user-level filtering
        if get_user_role(user) == 'admin':
            return queryset
        elif get_user_role(user) == 'manager':
            return queryset.filter(state=get_user_state(user))
        else:  # User level
            return queryset.filter(assigned_user=user)
            
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Get unique, non-empty, sorted values for filter dropdowns
        accessible_cars = visible_cars_for(self.request.user)
        context['regos'] = accessible_cars.values_list('rego', flat=True).distinct()
        all_years = accessible_cars.values_list('manufacturing_year', flat=True)
        years = sorted(set(y for y in all_years if y))
        context['years'] = years
        context['rego_expiry_years'] = accessible_cars.dates('rego_expiry_date', 'year').distinct()
        return context

class CarCreateView(AdminManagerRequiredMixin, CreateView):
    model = Car
    form_class = CarForm
    template_name = 'tracking/car_form.html'
    success_url = reverse_lazy('car_list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        if get_user_role(user) != 'admin':
            form.fields['state'].initial = get_user_state(user)
            form.fields['state'].disabled = True
            form.fields['assigned_user'].queryset = User.objects.filter(
                profile__state=user.profile.state
            )
        return form

class CarUpdateView(AdminManagerRequiredMixin, UpdateView):
    model = Car
    form_class = CarForm
    template_name = 'tracking/car_form.html'
    success_url = reverse_lazy('car_list')

    def get_queryset(self):
        user = self.request.user
        if get_user_role(user) == 'admin':
            return Car.objects.active()
        return Car.objects.active().filter(state=get_user_state(user))

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        if get_user_role(user) != 'admin':
            form.fields['state'].disabled = True
            form.fields['assigned_user'].queryset = User.objects.filter(
                profile__state=user.profile.state
            )
        return form

class CarDeleteView(AdminRequiredMixin, UpdateView):
    model = Car
    form_class = CarRetirementForm
    template_name = 'tracking/car_retire_form.html'
    success_url = reverse_lazy('car_list')

    def get_queryset(self):
        return Car.objects.active()

    def form_valid(self, form):
        with transaction.atomic():
            self.object = form.save(commit=False)
            self.object.retired_by = self.request.user
            self.object.current_odometer = self.object.final_odometer
            self.object.assigned_user = None
            self.object.save()
            Tool.objects.filter(assigned_car=self.object).update(assigned_car=None)
            VehicleRetirementTask.objects.bulk_create([
                VehicleRetirementTask(car=self.object, task_type=task_type)
                for task_type, _ in VehicleRetirementTask.TASK_CHOICES
            ])

        if send_vehicle_retirement_notification(self.object):
            messages.success(
                self.request,
                f'{self.object.rego} was moved to Vehicle History and the retirement checklist was created.',
            )
        else:
            messages.warning(
                self.request,
                f'{self.object.rego} was retired and its checklist was created, but no reminder email could be sent.',
            )
        return HttpResponseRedirect(self.get_success_url())


class VehicleHistoryListView(AdminManagerRequiredMixin, ListView):
    model = Car
    template_name = 'tracking/vehicle_history_list.html'
    context_object_name = 'cars'
    paginate_by = 50

    def get_queryset(self):
        return visible_cars_for(self.request.user, include_retired=True).retired().select_related(
            'retired_by'
        )


class CarDetailView(LoginRequiredMixin, DetailView):
    model = Car
    template_name = 'tracking/car_detail.html'
    context_object_name = 'car'

    def get_queryset(self):
        return visible_cars_for(self.request.user, include_retired=True).select_related(
            'assigned_user', 'retired_by'
        ).prefetch_related('retirement_tasks')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        maintenance = self.object.maintenance_records.select_related('car').prefetch_related(
            'items'
        ).order_by('-service_date', '-pk')
        maintenance_summary = maintenance.aggregate(
            record_count=Count('pk'), total_cost=Sum('total_cost')
        )
        context['recent_maintenance'] = maintenance[:5]
        context['maintenance_record_count'] = maintenance_summary['record_count'] or 0
        context['maintenance_total_cost'] = maintenance_summary['total_cost'] or Decimal('0.00')
        context['accident_record_count'] = self.object.accidents.count()
        context['odometer_record_count'] = self.object.odometer_readings.count()
        context['special_requirements'] = self.object.special_maintenance_requirements.all()
        return context


class VehicleQRLabelView(AdminManagerRequiredMixin, DetailView):
    model = Car
    template_name = 'tracking/vehicle_qr_label.html'
    context_object_name = 'car'

    def get_queryset(self):
        return visible_cars_for(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['entry_url'] = self.request.build_absolute_uri(
            reverse_lazy('vehicle_qr_entry', kwargs={'token': self.object.qr_token})
        )
        return context


class VehicleRetirementTaskUpdateView(AdminManagerRequiredMixin, UpdateView):
    model = VehicleRetirementTask
    form_class = VehicleRetirementTaskForm
    template_name = 'tracking/vehicle_retirement_task_form.html'

    def get_queryset(self):
        cars = visible_cars_for(self.request.user, include_retired=True).retired()
        return VehicleRetirementTask.objects.filter(car__in=cars).select_related('car')

    def form_valid(self, form):
        task = form.save(commit=False)
        if task.completed:
            task.completed_by = self.request.user
            task.completed_at = timezone.now()
        else:
            task.completed_by = None
            task.completed_at = None
        task.save()
        self.object = task
        messages.success(self.request, 'Retirement checklist updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse_lazy('car_detail', kwargs={'pk': self.object.car_id})

# ----- Odometer Reading Views -----
class OdometerReadingListView(LoginRequiredMixin, ListView):
    model = OdometerReading
    template_name = 'tracking/odometer_list.html'
    context_object_name = 'odometer_readings'
    paginate_by = 50
    
    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset().filter(
            car__status=Car.STATUS_IN_SERVICE
        ).select_related('car')
        
        if get_user_role(user) == 'admin':
            return queryset
        elif get_user_role(user) == 'manager':
            return queryset.filter(car__state=get_user_state(user))
        else:  # User level
            return queryset.filter(car__assigned_user=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        if get_user_role(user) == 'admin':
            context['cars'] = Car.objects.active()
        elif get_user_role(user) == 'manager':
            context['cars'] = Car.objects.active().filter(state=get_user_state(user))
        else:
            context['cars'] = Car.objects.active().filter(assigned_user=user)
        return context

class OdometerReadingCreateView(LoginRequiredMixin, CreateView):
    model = OdometerReading
    form_class = OdometerReadingForm
    template_name = 'tracking/odometer_form.html'
    success_url = reverse_lazy('odometer_list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        if get_user_role(user) == 'admin':
            form.fields['car'].queryset = Car.objects.active()
        elif get_user_role(user) == 'manager':
            form.fields['car'].queryset = Car.objects.active().filter(state=get_user_state(user))
        else:
            form.fields['car'].queryset = Car.objects.active().filter(assigned_user=user)
        return form

class OdometerReadingUpdateView(LoginRequiredMixin, UpdateView):
    model = OdometerReading
    form_class = OdometerReadingForm
    template_name = 'tracking/odometer_form.html'
    success_url = reverse_lazy('odometer_list')

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset().filter(car__status=Car.STATUS_IN_SERVICE)
        if get_user_role(user) == 'admin':
            return queryset
        if get_user_role(user) == 'manager':
            return queryset.filter(car__state=get_user_state(user))
        return queryset.filter(car__assigned_user=user)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        if get_user_role(user) == 'admin':
            form.fields['car'].queryset = Car.objects.active()
        elif get_user_role(user) == 'manager':
            form.fields['car'].queryset = Car.objects.active().filter(state=get_user_state(user))
        else:
            form.fields['car'].queryset = Car.objects.active().filter(assigned_user=user)
        return form

class OdometerReadingDeleteView(AdminRequiredMixin, DeleteView):
    model = OdometerReading
    template_name = 'tracking/odometer_confirm_delete.html'
    success_url = reverse_lazy('odometer_list')

# ----- Odometer Update View -----
class OdometerUpdateView(LoginRequiredMixin, UpdateView):
    model = Car
    form_class = OdometerUpdateForm
    template_name = 'tracking/odometer_update.html'
    success_url = reverse_lazy('car_list')

    def get_queryset(self):
        user = self.request.user
        if get_user_role(user) == 'admin':
            return Car.objects.active()
        elif get_user_role(user) == 'manager':
            return Car.objects.active().filter(state=get_user_state(user))
        else:
            return Car.objects.active().filter(assigned_user=user)

    def form_valid(self, form):
        car = form.instance
        old_odometer = Car.objects.get(pk=car.pk).current_odometer
        new_odometer = form.cleaned_data['current_odometer']
        
        # Save the form
        response = super().form_valid(form)
        
        # Send notification email
        try:
            send_odometer_update_notification(car, old_odometer, new_odometer, self.request.user)
            
            # Check if service reminders need to be sent
            if car.is_service_due_by_km() or car.is_service_approaching():
                from django.contrib import messages
                if car.is_service_due_by_km():
                    messages.warning(self.request, f'Service is overdue for {car.rego}! Current: {new_odometer}km, Service due at: {car.service_odometer}km')
                else:
                    messages.info(self.request, f'Service approaching for {car.rego}. Current: {new_odometer}km, Service due at: {car.service_odometer}km')
        except Exception as e:
            logger.error(f"Failed to send odometer update notification: {e}")
        
        return response


class VehicleQRSubmissionView(LoginRequiredMixin, FormView):
    form_class = VehicleQRSubmissionForm
    template_name = 'tracking/vehicle_qr_entry.html'

    def dispatch(self, request, *args, **kwargs):
        self.car = get_object_or_404(
            Car.objects.active().select_related('assigned_user'),
            qr_token=kwargs['token'],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['car'] = self.car
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['car'] = self.car
        return context

    @transaction.atomic
    def form_valid(self, form):
        reading_value = form.cleaned_data['odometer']
        previous_odometer = self.car.current_odometer
        suspicious = bool(form.suspicious_reason)
        reading = OdometerReading.objects.create(
            car=self.car,
            reading_date=timezone.localdate(),
            reading_value=reading_value,
            submitted_by=self.request.user,
            source=OdometerReading.SOURCE_QR,
            review_status=(
                OdometerReading.STATUS_PENDING if suspicious
                else OdometerReading.STATUS_ACCEPTED
            ),
            suspicious_reason=form.suspicious_reason,
            evidence_photo=form.cleaned_data.get('odometer_photo'),
        )
        if not suspicious:
            self.car.current_odometer = max(self.car.current_odometer, reading_value)
            self.car.save(update_fields=['current_odometer'])

        if form.cleaned_data.get('include_fuel'):
            FuelRecord.objects.create(
                car=self.car,
                date=timezone.localdate(),
                odometer=reading_value,
                liters=form.cleaned_data['liters'],
                cost_per_liter=form.cleaned_data['cost_per_liter'],
                fuel_type=form.cleaned_data['fuel_type'],
                station=form.cleaned_data.get('station', ''),
                full_tank=form.cleaned_data.get('full_tank', False),
                receipt=form.cleaned_data['receipt'],
                submitted_by=self.request.user,
                odometer_reading=reading,
            )
        if suspicious:
            messages.warning(
                self.request,
                'Entry saved for fleet review. The official odometer was not changed.',
            )
        else:
            messages.success(self.request, f'{self.car.rego} was updated successfully.')
            send_odometer_update_notification(
                self.car, previous_odometer, reading_value, self.request.user
            )
        return redirect('user_dashboard')


class OdometerReviewListView(AdminManagerRequiredMixin, ListView):
    model = OdometerReading
    template_name = 'tracking/odometer_review_list.html'
    context_object_name = 'readings'
    paginate_by = 50

    def get_queryset(self):
        queryset = OdometerReading.objects.filter(
            review_status=OdometerReading.STATUS_PENDING,
            car__status=Car.STATUS_IN_SERVICE,
        ).select_related('car', 'submitted_by')
        if get_user_role(self.request.user) == 'admin':
            return queryset
        return queryset.filter(car__state=get_user_state(self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        fleet = visible_cars_for(self.request.user).prefetch_related('odometer_readings')
        context['overdue_cars'] = [car for car in fleet if car.is_odometer_overdue()]
        context['unassigned_cars'] = fleet.filter(assigned_user__isnull=True)
        context['recent_submissions'] = OdometerReading.objects.filter(
            car__in=visible_cars_for(self.request.user),
            source=OdometerReading.SOURCE_QR,
        ).select_related('car', 'submitted_by').order_by('-created_at')[:10]
        return context


class OdometerReviewView(AdminManagerRequiredMixin, FormView):
    form_class = OdometerReviewForm
    template_name = 'tracking/odometer_review_form.html'

    def dispatch(self, request, *args, **kwargs):
        queryset = OdometerReading.objects.filter(
            review_status=OdometerReading.STATUS_PENDING,
            car__in=visible_cars_for(request.user),
        ).select_related('car', 'submitted_by')
        self.reading = get_object_or_404(queryset, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reading'] = self.reading
        return context

    @transaction.atomic
    def form_valid(self, form):
        accepted = form.cleaned_data['decision'] == 'accept'
        self.reading.review_status = (
            OdometerReading.STATUS_ACCEPTED if accepted
            else OdometerReading.STATUS_REJECTED
        )
        self.reading.review_notes = form.cleaned_data.get('review_notes', '')
        self.reading.reviewed_by = self.request.user
        self.reading.reviewed_at = timezone.now()
        self.reading.save(update_fields=[
            'review_status', 'review_notes', 'reviewed_by', 'reviewed_at'
        ])
        if accepted:
            car = self.reading.car
            car.current_odometer = max(car.current_odometer, self.reading.reading_value)
            car.save(update_fields=['current_odometer'])
        messages.success(self.request, 'Odometer review recorded.')
        return redirect('odometer_review_list')


class SpecialMaintenanceListView(AdminManagerRequiredMixin, ListView):
    model = SpecialMaintenanceRequirement
    template_name = 'tracking/special_maintenance_list.html'
    context_object_name = 'requirements'
    paginate_by = 50

    def get_queryset(self):
        queryset = SpecialMaintenanceRequirement.objects.select_related('car')
        if get_user_role(self.request.user) != 'admin':
            queryset = queryset.filter(car__state=get_user_state(self.request.user))
        status = self.request.GET.get('status')
        if status == 'active':
            queryset = queryset.filter(active=True)
        elif status == 'completed':
            queryset = queryset.filter(active=False)
        return queryset


class SpecialMaintenanceCreateView(AdminManagerRequiredMixin, CreateView):
    model = SpecialMaintenanceRequirement
    form_class = SpecialMaintenanceRequirementForm
    template_name = 'tracking/special_maintenance_form.html'
    success_url = reverse_lazy('special_maintenance_list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['car'].queryset = visible_cars_for(self.request.user)
        return form

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Special maintenance requirement created.')
        return super().form_valid(form)


class SpecialMaintenanceUpdateView(AdminManagerRequiredMixin, UpdateView):
    model = SpecialMaintenanceRequirement
    form_class = SpecialMaintenanceRequirementForm
    template_name = 'tracking/special_maintenance_form.html'
    success_url = reverse_lazy('special_maintenance_list')

    def get_queryset(self):
        return SpecialMaintenanceRequirement.objects.filter(
            car__in=visible_cars_for(self.request.user), active=True
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['car'].queryset = visible_cars_for(self.request.user)
        return form


class SpecialMaintenanceCompleteView(AdminManagerRequiredMixin, UpdateView):
    model = SpecialMaintenanceRequirement
    form_class = SpecialMaintenanceCompleteForm
    template_name = 'tracking/special_maintenance_complete.html'
    success_url = reverse_lazy('special_maintenance_list')

    def get_queryset(self):
        return SpecialMaintenanceRequirement.objects.filter(
            car__in=visible_cars_for(self.request.user), active=True
        )

    @transaction.atomic
    def form_valid(self, form):
        requirement = form.save(commit=False)
        requirement.active = False
        requirement.completed_by = self.request.user
        requirement.completed_at = timezone.now()
        requirement.save()
        if requirement.recurrence_days or requirement.recurrence_km:
            SpecialMaintenanceRequirement.objects.create(
                car=requirement.car,
                title=requirement.title,
                due_date=(
                    timezone.localdate() + timedelta(days=requirement.recurrence_days)
                    if requirement.recurrence_days else None
                ),
                due_odometer=(
                    (requirement.completed_odometer or requirement.car.current_odometer)
                    + requirement.recurrence_km
                    if requirement.recurrence_km else None
                ),
                advance_notice_days=requirement.advance_notice_days,
                advance_notice_km=requirement.advance_notice_km,
                recurrence_days=requirement.recurrence_days,
                recurrence_km=requirement.recurrence_km,
                notes=requirement.notes,
                created_by=self.request.user,
            )
        messages.success(self.request, 'Special maintenance marked complete.')
        return HttpResponseRedirect(self.get_success_url())

# ----- Maintenance Views -----
class MaintenanceRecordListView(LoginRequiredMixin, ListView):
    model = Maintenance
    template_name = 'tracking/maintenance_list.html'
    context_object_name = 'maintenance_records'
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset().filter(
            car__status=Car.STATUS_IN_SERVICE
        ).select_related('car').prefetch_related('items').order_by('-service_date', '-pk')
        user = self.request.user
        
        # Apply rego filter
        rego = self.request.GET.get('rego')
        if rego:
            queryset = queryset.filter(car__rego__icontains=rego)
            # Apply service provider filter
        service_provider = self.request.GET.get('service_provider')
        if service_provider:
            queryset = queryset.filter(service_provider=service_provider)
        service_type = self.request.GET.get('service_type')
        if service_type:
            queryset = queryset.filter(service_type=service_type)
        
        # Apply user-level filtering
        if get_user_role(user) == 'admin':
            return queryset
        elif get_user_role(user) == 'manager':
            return queryset.filter(car__state=get_user_state(user))
        else:  # User level
            return queryset.filter(car__assigned_user=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['regos'] = visible_cars_for(user).values_list('rego', flat=True).distinct()
        context['service_providers'] = visible_maintenance_for(user).values_list(
            'service_provider', flat=True
        ).distinct()
        context['service_types'] = Maintenance._meta.get_field('service_type').choices
        summary = self.object_list.aggregate(
            record_count=Count('pk'),
            total_cost=Sum('total_cost'),
            invoice_count=Count('pk', filter=~Q(invoice_number='')),
            document_count=Count('pk', filter=~Q(documents='')),
        )
        context['maintenance_summary'] = {
            'record_count': summary['record_count'] or 0,
            'total_cost': summary['total_cost'] or Decimal('0.00'),
            'invoice_count': summary['invoice_count'] or 0,
            'document_count': summary['document_count'] or 0,
        }
        return context


class MaintenanceRecordDetailView(LoginRequiredMixin, DetailView):
    model = Maintenance
    template_name = 'tracking/maintenance_detail.html'
    context_object_name = 'maintenance'

    def get_queryset(self):
        return visible_maintenance_for(self.request.user).select_related(
            'car', 'car__assigned_user'
        ).prefetch_related('items')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['line_item_total'] = sum(
            (item.total_cost for item in self.object.items.all()),
            Decimal('0.00'),
        )
        return context

class MaintenanceRecordCreateView(AdminManagerRequiredMixin, CreateView):
    model = Maintenance
    form_class = MaintenanceForm
    template_name = 'tracking/maintenance_form.html'
    success_url = reverse_lazy('maintenance_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['item_formset'] = MaintenanceItemFormSet(
                self.request.POST,
                self.request.FILES,
            )
        else:
            context['item_formset'] = MaintenanceItemFormSet()
        return context

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        if get_user_role(user) == 'admin':
            form.fields['car'].queryset = Car.objects.active()
        else:
            form.fields['car'].queryset = Car.objects.active().filter(state=get_user_state(user))
        return form

    @transaction.atomic
    def form_valid(self, form):
        context = self.get_context_data(form=form)
        item_formset = context['item_formset']
        if item_formset.is_valid():
            self.object = form.save()
            item_formset.instance = self.object
            item_formset.save()
            return HttpResponseRedirect(self.get_success_url())
        return self.render_to_response(context)

class MaintenanceRecordUpdateView(AdminManagerRequiredMixin, UpdateView):
    model = Maintenance
    form_class = MaintenanceForm
    template_name = 'tracking/maintenance_form.html'
    success_url = reverse_lazy('maintenance_list')

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset().filter(car__status=Car.STATUS_IN_SERVICE)
        if get_user_role(user) == 'admin':
            return queryset
        return queryset.filter(car__state=get_user_state(user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['item_formset'] = MaintenanceItemFormSet(
                self.request.POST,
                self.request.FILES,
                instance=self.object,
            )
        else:
            context['item_formset'] = MaintenanceItemFormSet(instance=self.object)
        return context

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        if get_user_role(user) == 'admin':
            form.fields['car'].queryset = Car.objects.active()
        else:
            form.fields['car'].queryset = Car.objects.active().filter(state=get_user_state(user))
        return form

    @transaction.atomic
    def form_valid(self, form):
        context = self.get_context_data(form=form)
        item_formset = context['item_formset']
        if item_formset.is_valid():
            self.object = form.save()
            item_formset.instance = self.object
            item_formset.save()
            return HttpResponseRedirect(self.get_success_url())
        return self.render_to_response(context)

class MaintenanceRecordDeleteView(AdminRequiredMixin, DeleteView):
    model = Maintenance
    template_name = 'tracking/maintenance_confirm_delete.html'
    success_url = reverse_lazy('maintenance_list')

# ----- Transfer Views -----
class TransferListView(AdminManagerRequiredMixin, ListView):
    model = TransferBatch
    template_name = 'tracking/transfer_list.html'
    context_object_name = 'transfers'
    paginate_by = 50

    def get_queryset(self):
        user = self.request.user
        queryset = super().get_queryset().select_related(
            'from_user', 'from_location', 'to_user', 'to_location', 'created_by'
        ).prefetch_related('entries', 'follow_up_tasks')
        if get_user_role(user) == 'admin':
            return queryset
        state = get_user_state(user)
        return queryset.filter(
            Q(from_user__profile__state__startswith=state) |
            Q(to_user__profile__state__startswith=state) |
            Q(from_location__state=state) | Q(to_location__state=state)
        ).distinct()

class TransferCreateView(AdminRequiredMixin, FormView):
    form_class = TransferForm
    template_name = 'tracking/transfer_form.html'
    success_url = reverse_lazy('transfer_list')

    def _source(self):
        data = self.request.POST if self.request.method == 'POST' else self.request.GET
        user_id = (data.get('from_user') or '').strip()
        location_id = (data.get('from_location') or '').strip()
        source_user = (
            User.objects.filter(pk=int(user_id)).first()
            if user_id.isdecimal() else None
        )
        source_location = (
            CustodyLocation.objects.filter(pk=int(location_id), active=True).first()
            if location_id.isdecimal() else None
        )
        return source_user, source_location

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['source_user'], kwargs['source_location'] = self._source()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['source_user'], context['source_location'] = self._source()
        context['users'] = User.objects.filter(is_active=True).order_by(
            'first_name', 'last_name', 'username'
        )
        context['locations'] = CustodyLocation.objects.filter(active=True)
        return context

    def form_valid(self, form):
        data = form.cleaned_data
        with transaction.atomic():
            batch = TransferBatch(
                from_user=data['from_user'], from_location=data['from_location'],
                to_user=data['to_user'], to_location=data['to_location'],
                date_of_transfer=data['date_of_transfer'], notes=data['notes'],
                created_by=self.request.user,
            )
            batch.full_clean()
            batch.save()

            for tool in data['tools']:
                TransferLedgerEntry.objects.create(
                    batch=batch, asset_type=TransferLedgerEntry.ASSET_TOOL,
                    tool=tool, asset_identifier=tool.internal_number,
                    from_user=batch.from_user, from_location=batch.from_location,
                    to_user=batch.to_user, to_location=batch.to_location,
                )
                tool.assigned_user = batch.to_user
                tool.custody_location = batch.to_location
                tool.assigned_car = None
                tool.save(update_fields=['assigned_user', 'custody_location', 'assigned_car'])

            car = data.get('car')
            if car:
                old_state = car.state
                destination_state = (
                    get_user_state(batch.to_user) if batch.to_user else batch.to_location.state
                )
                TransferLedgerEntry.objects.create(
                    batch=batch, asset_type=TransferLedgerEntry.ASSET_CAR,
                    car=car, asset_identifier=car.rego,
                    from_user=batch.from_user, from_location=batch.from_location,
                    to_user=batch.to_user, to_location=batch.to_location,
                )
                car.assigned_user = batch.to_user
                car.custody_location = batch.to_location
                if destination_state:
                    car.state = destination_state
                car.save(update_fields=['assigned_user', 'custody_location', 'state'])
                if destination_state and destination_state != old_state:
                    description = f'Change registration for {car.rego} from {old_state} to {destination_state}.'
                    TransferFollowUpTask.objects.create(
                        batch=batch, car=car, state=destination_state,
                        description=description,
                    )
                    managers = User.objects.filter(profile__access_level='Manager', is_active=True)
                    for manager in managers:
                        if get_user_state(manager) == destination_state:
                            TransferFollowUpTask.objects.create(
                                batch=batch, car=car, state=destination_state,
                                assigned_to=manager, description=description,
                            )

            transaction.on_commit(lambda: send_transfer_notification(batch.pk))

        messages.success(
            self.request,
            f'Transfer recorded with {batch.entries.count()} ledger entries.',
        )
        return HttpResponseRedirect(self.get_success_url())


class TransferReverseView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        with transaction.atomic():
            original = get_object_or_404(
                TransferBatch.objects.select_for_update().prefetch_related('entries'),
                pk=kwargs['pk'],
            )
            if hasattr(original, 'reversal'):
                messages.error(request, 'This transfer has already been reversed.')
                return redirect('transfer_list')

            entries = list(original.entries.all())
            for entry in entries:
                asset = entry.tool if entry.tool_id else entry.car
                if (
                    asset.assigned_user_id != original.to_user_id or
                    asset.custody_location_id != original.to_location_id
                ):
                    messages.error(
                        request,
                        f'{entry.asset_identifier} has moved again, so this transfer cannot be reversed directly.',
                    )
                    return redirect('transfer_list')

            reversal = TransferBatch.objects.create(
                from_user=original.to_user, from_location=original.to_location,
                to_user=original.from_user, to_location=original.from_location,
                date_of_transfer=timezone.localdate(),
                notes=f'Reversal of {original.reference}.',
                created_by=request.user, reversal_of=original,
            )
            cross_state_car = False
            for entry in entries:
                TransferLedgerEntry.objects.create(
                    batch=reversal, asset_type=entry.asset_type,
                    tool=entry.tool, car=entry.car,
                    asset_identifier=entry.asset_identifier,
                    from_user=original.to_user, from_location=original.to_location,
                    to_user=original.from_user, to_location=original.from_location,
                )
                asset = entry.tool if entry.tool_id else entry.car
                asset.assigned_user = original.from_user
                asset.custody_location = original.from_location
                update_fields = ['assigned_user', 'custody_location']
                if entry.tool_id:
                    asset.assigned_car = None
                    update_fields.append('assigned_car')
                else:
                    destination_state = (
                        get_user_state(original.from_user)
                        if original.from_user else original.from_location.state
                    )
                    if destination_state and destination_state != asset.state:
                        asset.state = destination_state
                        update_fields.append('state')
                        cross_state_car = True
                asset.save(update_fields=update_fields)
            if cross_state_car:
                transaction.on_commit(lambda: send_transfer_notification(reversal.pk))

        messages.success(request, 'The transfer was reversed with a new ledger entry.')
        return redirect('transfer_list')


class TransferFollowUpTaskUpdateView(AdminManagerRequiredMixin, UpdateView):
    model = TransferFollowUpTask
    form_class = TransferFollowUpTaskForm
    template_name = 'tracking/transfer_follow_up_task_form.html'

    def get_queryset(self):
        queryset = super().get_queryset().select_related('batch', 'car')
        if get_user_role(self.request.user) == 'admin':
            return queryset
        return queryset.filter(assigned_to=self.request.user)

    def form_valid(self, form):
        task = form.save(commit=False)
        if task.completed:
            task.completed_by = self.request.user
            task.completed_at = timezone.now()
        else:
            task.completed_by = None
            task.completed_at = None
        task.save()
        messages.success(self.request, 'Transfer follow-up task updated.')
        return redirect('transfer_list')

# ----- User Management Views -----
class UserListView(AdminRequiredMixin, ListView):
    model = User
    template_name = 'tracking/user_list.html'
    context_object_name = 'users'
    paginate_by = 50

    def get_queryset(self):
        return super().get_queryset().select_related('profile').order_by('username')

class UserCreateView(AdminRequiredMixin, CreateView):
    model = User
    form_class = UserForm
    template_name = 'tracking/user_form.html'
    success_url = reverse_lazy('user_list')

class UserUpdateView(AdminRequiredMixin, UpdateView):
    model = User
    form_class = UserUpdateForm
    template_name = 'tracking/user_form.html'
    success_url = reverse_lazy('user_list')

class UserDeleteView(AdminRequiredMixin, DeleteView):
    model = User
    template_name = 'tracking/user_confirm_delete.html'
    success_url = reverse_lazy('user_list')


class AlertContactListView(AdminRequiredMixin, ListView):
    model = AlertContact
    template_name = 'tracking/alert_contact_list.html'
    context_object_name = 'contacts'
    paginate_by = 50

    def get_queryset(self):
        queryset = AlertContact.objects.select_related(
            'linked_user', 'created_by', 'updated_by'
        )
        responsibility = self.request.GET.get('responsibility', '')
        if responsibility in dict(AlertContact.ROLE_CHOICES):
            queryset = queryset.filter(responsibility=responsibility)
        state = self.request.GET.get('state', '')
        if state:
            queryset = queryset.filter(state=state)
        enabled = self.request.GET.get('enabled', '')
        if enabled in {'yes', 'no'}:
            queryset = queryset.filter(enabled=(enabled == 'yes'))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['responsibilities'] = AlertContact.ROLE_CHOICES
        context['states'] = Car.STATE_CHOICES
        return context


class AlertContactCreateView(AdminRequiredMixin, CreateView):
    model = AlertContact
    form_class = AlertContactForm
    template_name = 'tracking/alert_contact_form.html'
    success_url = reverse_lazy('alert_contact_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        messages.success(self.request, 'Email alert mailbox created.')
        return super().form_valid(form)


class AlertContactUpdateView(AdminRequiredMixin, UpdateView):
    model = AlertContact
    form_class = AlertContactForm
    template_name = 'tracking/alert_contact_form.html'
    success_url = reverse_lazy('alert_contact_list')

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        messages.success(self.request, 'Email alert mailbox updated.')
        return super().form_valid(form)


class NotificationDeliveryListView(AdminRequiredMixin, ListView):
    model = NotificationDelivery
    template_name = 'tracking/notification_delivery_list.html'
    context_object_name = 'deliveries'
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset()
        status = self.request.GET.get('status', '')
        if status in dict(NotificationDelivery.STATUS_CHOICES):
            queryset = queryset.filter(status=status)
        event_type = self.request.GET.get('event_type', '')
        if event_type in dict(AlertContact.CATEGORY_CHOICES):
            queryset = queryset.filter(event_type=event_type)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = NotificationDelivery.STATUS_CHOICES
        context['event_types'] = AlertContact.CATEGORY_CHOICES
        return context


class NotificationDeliveryRetryView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        delivery = get_object_or_404(NotificationDelivery, pk=kwargs['pk'])
        if retry_failed_notification(delivery):
            messages.success(request, 'Notification sent successfully on retry.')
        elif delivery.status == NotificationDelivery.STATUS_FAILED:
            messages.error(request, 'Notification retry failed. Review the recorded error.')
        else:
            messages.info(request, 'Only failed notifications can be retried.')
        return redirect('notification_delivery_list')


class AdminSetPasswordView(AdminRequiredMixin, FormView):
    form_class = SetPasswordForm
    template_name = 'registration/password_change_form.html'
    success_url = reverse_lazy('user_list')

    def dispatch(self, request, *args, **kwargs):
        if get_user_role(request.user) == 'admin':
            self.target_user = get_object_or_404(User, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.target_user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['target_user'] = self.target_user
        return context

    @transaction.atomic
    def form_valid(self, form):
        form.save()
        messages.success(self.request, f'Password updated for {self.target_user.username}.')
        return super().form_valid(form)

# ----- Import/Export Views -----
class PDFInvoiceImportView(AdminManagerRequiredMixin, View):
    template_name = 'tracking/pdf_invoice_import.html'

    def get(self, request):
        PendingPDFInvoiceStore(request).cleanup_stale_files()
        return render(request, self.template_name, {
            'upload_form': PDFInvoiceUploadForm(),
        })

    def post(self, request):
        action = request.POST.get('action')
        store = PendingPDFInvoiceStore(request)

        if action == 'cancel':
            store.discard()
            messages.info(request, 'The pending PDF invoice was discarded.')
            return redirect('pdf_invoice_import')
        if action == 'preview':
            return self._preview_upload(request, store)
        if action == 'confirm':
            return self._confirm_import(request, store)

        messages.error(request, 'Choose an invoice import action and try again.')
        return redirect('pdf_invoice_import')

    def _preview_upload(self, request, store):
        upload_form = PDFInvoiceUploadForm(request.POST, request.FILES)
        if not upload_form.is_valid():
            return render(request, self.template_name, {'upload_form': upload_form})

        pending = store.create(upload_form.cleaned_data['invoice_file'])
        try:
            preview = self._build_preview(request, store, pending)
        except PendingPDFError as exc:
            store.discard()
            upload_form.add_error('invoice_file', str(exc))
            return render(request, self.template_name, {'upload_form': upload_form})

        return render(request, self.template_name, {
            'upload_form': PDFInvoiceUploadForm(),
            'confirm_form': PDFInvoiceConfirmForm(initial={
                'pending_token': pending['token'],
            }),
            **preview,
        })

    def _confirm_import(self, request, store):
        confirm_form = PDFInvoiceConfirmForm(request.POST)
        if not confirm_form.is_valid():
            return render(request, self.template_name, {
                'upload_form': PDFInvoiceUploadForm(),
                'confirm_form': confirm_form,
            })

        try:
            pending = store.get(confirm_form.cleaned_data['pending_token'])
            preview = self._build_preview(request, store, pending)
            if preview['validation_errors']:
                return render(request, self.template_name, {
                    'upload_form': PDFInvoiceUploadForm(),
                    'confirm_form': confirm_form,
                    **preview,
                })

            invoice_data = preview['invoice_data']
            service = MaintenanceInvoiceService()
            saved_document_name = None
            try:
                with transaction.atomic():
                    if Maintenance.objects.filter(
                        invoice_number=invoice_data.invoice_number
                    ).exists():
                        raise PendingPDFError(
                            f'Invoice {invoice_data.invoice_number} has already been imported.'
                        )
                    maintenance = service.create_maintenance_from_invoice(
                        invoice_data, auto_create_car=False, skip_existing=True
                    )
                    if not maintenance:
                        raise PendingPDFError(
                            f'Invoice {invoice_data.invoice_number} has already been imported.'
                        )
                    with store.open(pending) as stream:
                        maintenance.documents.save(
                            pending['original_name'], File(stream), save=True
                        )
                    saved_document_name = maintenance.documents.name
            except Exception:
                if saved_document_name:
                    maintenance.documents.storage.delete(saved_document_name)
                raise

        except (PendingPDFError, ValidationError) as exc:
            messages.error(request, str(exc))
            return redirect('pdf_invoice_import')
        except Exception:
            logger.exception('Unexpected PDF invoice confirmation failure')
            messages.error(
                request,
                'The PDF invoice could not be saved. No maintenance record was created.',
            )
            return redirect('pdf_invoice_import')

        store.discard()
        messages.success(
            request,
            f'Invoice {invoice_data.invoice_number} was imported successfully.',
        )
        return redirect('maintenance_list')

    def _build_preview(self, request, store, pending):
        pending = store.get(pending['token'])
        pdf_path = store.path(pending)
        page_count = validate_pdf_structure(pdf_path)
        invoice_data = MaintenanceInvoiceService().preview_pdf_data(pdf_path)
        if not invoice_data:
            raise PendingPDFError(
                'No invoice information could be extracted from this PDF.'
            )

        invoice_data.invoice_number = normalize_invoice_number(
            invoice_data.invoice_number
        )
        validation_errors = list(validate_invoice_data(invoice_data))
        warnings = []

        car = None
        visible_cars = visible_cars_for(request.user)
        if invoice_data.vehicle_rego:
            car = visible_cars.filter(rego__iexact=invoice_data.vehicle_rego).first()
        if not car and invoice_data.vehicle_vin:
            car = visible_cars.filter(vin_number__iexact=invoice_data.vehicle_vin).first()
        if not car:
            validation_errors.append(
                'The invoice vehicle was not found among the vehicles you can manage.'
            )
        else:
            invoice_data.vehicle_rego = car.rego
            invoice_data.vehicle_vin = invoice_data.vehicle_vin or car.vin_number
            invoice_data.confidence['vehicle'] = 'high'

        if invoice_data.invoice_number and Maintenance.objects.filter(
            invoice_number=invoice_data.invoice_number
        ).exists():
            validation_errors.append(
                f'Invoice {invoice_data.invoice_number} has already been imported.'
            )
        if not invoice_data.odometer_reading:
            warnings.append('No odometer reading was extracted; 0 km will be saved.')
        if invoice_data.subtotal is None:
            warnings.append('The subtotal was not extracted and needs manual review.')
        if invoice_data.tax_amount is None:
            warnings.append('The tax amount was not extracted and needs manual review.')
        if (
            invoice_data.subtotal is not None
            and invoice_data.tax_amount is not None
            and invoice_data.subtotal + invoice_data.tax_amount
            != invoice_data.total_cost
        ):
            warnings.append('Subtotal plus tax does not match the extracted total.')

        item_total = sum(
            (
                Decimal(str(item.quantity)) * item.unit_cost
                for item in invoice_data.items
            ),
            Decimal('0.00'),
        )
        expected_item_total = (
            invoice_data.subtotal
            if invoice_data.subtotal is not None
            else invoice_data.total_cost
        )
        if item_total != expected_item_total:
            warnings.append(
                'The extracted line items do not add up to the invoice '
                f"{'subtotal' if invoice_data.subtotal is not None else 'total'}."
            )

        return {
            'invoice_data': invoice_data,
            'matched_car': car,
            'page_count': page_count,
            'original_name': pending['original_name'],
            'validation_errors': list(dict.fromkeys(validation_errors)),
            'preview_warnings': list(dict.fromkeys(warnings)),
            'can_confirm': not validation_errors,
        }


class ImportView(AdminRequiredMixin, FormView):
    form_class = ImportForm
    template_name = 'tracking/import_form.html'
    success_url = reverse_lazy('dashboard')

    def form_valid(self, form):
        file = form.cleaned_data['file']
        import_type = form.cleaned_data['type']
        file_format = form.cleaned_data['format']

        try:
            df = self._read_dataframe(file, file_format)
            with transaction.atomic():
                if import_type == 'User':
                    self._process_user_import(df)
                elif import_type == 'Car':
                    self._process_car_import(df)
                elif import_type == 'Tool':
                    self._process_tool_import(df)

            messages.success(
                self.request,
                f'Successfully imported {len(df.index)} {import_type} row(s).',
            )
            return super().form_valid(form)

        except ImportDataError as exc:
            form.add_error('file', str(exc))
            logger.warning('Import validation failed for %s: %s', import_type, exc)
            return super().form_invalid(form)
        except Exception:
            form.add_error(
                'file',
                'The import could not be completed. No rows were saved. Check the template and values.',
            )
            logger.exception('Unexpected %s import failure', import_type)
            return super().form_invalid(form)

    @staticmethod
    def _read_dataframe(file, file_format):
        try:
            if file_format == 'csv':
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file, engine='openpyxl')
        except Exception as exc:
            raise ImportDataError(
                'The file could not be read. Confirm that it uses the selected format and template.'
            ) from exc

        if df.empty:
            raise ImportDataError('The import file contains no data rows.')
        if len(df.index) > 5000:
            raise ImportDataError('The import file cannot contain more than 5,000 rows.')

        normalized_columns = [str(column).strip().lower() for column in df.columns]
        if len(normalized_columns) != len(set(normalized_columns)):
            raise ImportDataError('The import file contains duplicate column names.')
        df.columns = normalized_columns
        return df

    @staticmethod
    def _required_text(row, column, row_number):
        value = row[column]
        if pd.isna(value) or not str(value).strip():
            raise ImportDataError(
                f'Row {row_number} is missing the required {column} value. No rows were saved.'
            )
        return str(value).strip()

    def _process_user_import(self, df):
        required_cols = ['username', 'email', 'first_name', 'last_name', 
                        'password', 'access_level', 'state']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ImportDataError(f'Missing required user columns: {", ".join(missing_cols)}.')
        
        for index, row in df.iterrows():
            row_number = index + 2
            username = self._required_text(row, 'username', row_number)
            access_level = self._required_text(row, 'access_level', row_number).title()
            state = self._required_text(row, 'state', row_number)
            valid_roles = {choice[0] for choice in Profile.ACCESS_LEVELS}
            valid_states = {choice[0] for choice in Profile._meta.get_field('state').choices}
            if access_level not in valid_roles or state not in valid_states:
                raise ImportDataError(
                    f'Row {row_number} has an unsupported role or state. No rows were saved.'
                )
            user, created = User.objects.update_or_create(
                username=username,
                defaults={
                    'email': '' if pd.isna(row['email']) else str(row['email']).strip(),
                    'first_name': '' if pd.isna(row['first_name']) else str(row['first_name']).strip(),
                    'last_name': '' if pd.isna(row['last_name']) else str(row['last_name']).strip(),
                }
            )
            if created:
                password = self._required_text(row, 'password', row_number)
                user.set_password(password)
            user.save()

            Profile.objects.update_or_create(
                user=user,
                defaults={
                    'access_level': access_level,
                    'state': state,
                }
            )

    def _process_car_import(self, df):
        required_cols = ['rego', 'rego_expiry_date', 'state', 'make', 'model', 'vin_number']
        optional_cols = ['manufacturing_year', 'color', 'body', 'assigned_user', 'current_odometer', 'service_odometer',
                        'purchase_date', 'purchase_price', 'service_interval_km', 'last_service_km']
        
        # Check if required columns exist
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ImportDataError(f'Missing required car columns: {", ".join(missing_cols)}.')

        success_count = 0
        error_count = 0
        
        for index, row in df.iterrows():
            try:
                row_number = index + 2
                rego = self._required_text(row, 'rego', row_number).upper()
                state = self._required_text(row, 'state', row_number).upper()
                if state not in {choice[0] for choice in Car.STATE_CHOICES}:
                    raise ImportDataError(
                        f'Row {row_number} has an unsupported car state. No rows were saved.'
                    )
                # Get assigned user if specified
                assigned_user = None
                if 'assigned_user' in df.columns and pd.notna(row['assigned_user']):
                    try:
                        assigned_user = User.objects.get(username=row['assigned_user'])
                    except User.DoesNotExist:
                        messages.warning(self.request, 
                            f"User {row['assigned_user']} not found for car {row['rego']}, importing without user assignment")

                # Prepare car data with required fields
                car_data = {
                    'rego_expiry_date': pd.to_datetime(row['rego_expiry_date']).date(),
                    'state': state,
                    'make': self._required_text(row, 'make', row_number),
                    'model': self._required_text(row, 'model', row_number),
                    'vin_number': self._required_text(row, 'vin_number', row_number),
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
                    rego=rego,
                    defaults=car_data
                )
                
                success_count += 1
                
            except ImportDataError:
                raise
            except Exception as e:
                error_count += 1
                logger.error(f"Car import error at row {index + 2}: {str(e)}")
        if error_count:
            raise ImportDataError(
                f'{error_count} car row(s) contained invalid data. No rows were saved.'
            )

    def _process_tool_import(self, df):
        required_cols = ['internal_number', 'tool_name', 'state']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ImportDataError(f'Missing required tool columns: {", ".join(missing_cols)}.')

        for index, row in df.iterrows():
            row_number = index + 2
            internal_number = self._required_text(row, 'internal_number', row_number)
            tool_data = {
                'tool_name': self._required_text(row, 'tool_name', row_number),
                'state': self._required_text(row, 'state', row_number).upper(),
                'store': 'other local stores',
            }
            if tool_data['state'] not in {choice[0] for choice in Car.STATE_CHOICES}:
                raise ImportDataError(
                    f'Row {row_number} has an unsupported tool state. No rows were saved.'
                )
            catalogue_item = ToolCatalogueItem.objects.filter(
                name__iexact=tool_data['tool_name'], active=True,
            ).first()
            if not catalogue_item:
                raise ImportDataError(
                    f'Row {row_number} has an unsupported tool name. No rows were saved.'
                )
            tool_data['tool_name'] = catalogue_item.name

            # Handle optional fields
            optional_fields = {
                'serial_number': str,
                'brand': str,
                'description': str,
                'size': str,
                'calibration_date': lambda x: pd.to_datetime(x).date(),
                'store': str,
                'quantity': int,
                'estimated_cost': float
            }

            for field, converter in optional_fields.items():
                if field in df.columns and pd.notna(row[field]):
                    tool_data[field] = converter(row[field])

            # Handle assigned user and car if present
            if 'assigned_user' in df.columns and pd.notna(row['assigned_user']):
                try:
                    tool_data['assigned_user'] = User.objects.get(
                        username=row['assigned_user'])
                except User.DoesNotExist:
                    messages.warning(self.request, 
                        f"User {row['assigned_user']} not found for tool {row['internal_number']}")

            if 'assigned_car' in df.columns and pd.notna(row['assigned_car']):
                try:
                    tool_data['assigned_car'] = Car.objects.get(
                        rego=row['assigned_car'])
                except Car.DoesNotExist:
                    messages.warning(self.request, 
                        f"Car {row['assigned_car']} not found for tool {row['internal_number']}")

            tool, created = Tool.objects.update_or_create(
                internal_number=internal_number,
                defaults=tool_data,
            )

# ----- Analytics and Report Views -----
class FleetAnalyticsView(LoginRequiredMixin, TemplateView):
    template_name = 'tracking/fleet_analytics.html'

    @staticmethod
    def _period_costs(cars, start_date, end_date):
        """Total maintenance, fuel, and accident cost for a period.

        Aggregates in the database instead of calling Car.get_total_costs() per
        vehicle, which issued three queries each. Each related total is summed
        in its own query so multiple joins cannot multiply rows.
        """
        zero = Decimal('0.00')
        maintenance = Maintenance.objects.filter(
            car__in=cars, service_date__gte=start_date, service_date__lte=end_date,
        ).aggregate(total=Sum('total_cost'))['total'] or zero
        fuel = FuelRecord.objects.filter(
            car__in=cars, date__gte=start_date, date__lte=end_date,
        ).aggregate(total=Sum('total_cost'))['total'] or zero
        accident = Accident.objects.filter(
            car__in=cars,
            accident_date__gte=start_date,
            accident_date__lte=end_date,
        ).aggregate(total=Sum('accident_excess'))['total'] or zero
        return {
            'maintenance_cost': maintenance,
            'fuel_cost': fuel,
            'accident_cost': accident,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        today = timezone.localdate()
        current_year = today.year
        
        # Filter cars based on access level and rego filter
        accessible_cars = visible_cars_for(user)
        cars = accessible_cars

        # Apply rego filter if provided
        rego = self.request.GET.get('rego')
        if rego:
            cars = cars.filter(rego__icontains=rego)

        # Add regos for filter dropdown
        context['regos'] = accessible_cars.values_list('rego', flat=True).distinct()
        context['total_cars'] = cars.count()
        # The template renders per-vehicle service and tire status, which read
        # these relations. Prefetching keeps that O(1) in queries instead of
        # O(vehicles).
        cars = cars.select_related('assigned_user').prefetch_related(
            'tire_records', 'odometer_readings',
        )
        context['cars'] = cars

        # Calculate statistics
        start_of_year = date(current_year, 1, 1)
        ytd_costs = self._period_costs(cars, start_of_year, today)
        ytd_maintenance_cost = ytd_costs['maintenance_cost']
        ytd_fuel_cost = ytd_costs['fuel_cost']
        ytd_accident_cost = ytd_costs['accident_cost']

        context['total_maintenance_cost'] = ytd_maintenance_cost
        context['total_fuel_cost'] = ytd_fuel_cost
        context['total_accident_cost'] = ytd_accident_cost
        context['total_fleet_cost'] = (
            ytd_maintenance_cost + ytd_fuel_cost + ytd_accident_cost
        )
        context['has_fuel_data'] = ytd_fuel_cost > 0
        context['service_due_cars'] = [car for car in cars if car.is_service_due() or car.is_service_due_by_km()]

        # Monthly costs
        monthly_maintenance_costs = []
        monthly_fuel_costs = []
        monthly_accident_costs = []
        for month in range(1, 13):
            month_start = date(current_year, month, 1)
            if month_start > today:
                monthly_maintenance_costs.append(0.0)
                monthly_fuel_costs.append(0.0)
                monthly_accident_costs.append(0.0)
                continue
            month_end = min(
                date(current_year, month, calendar.monthrange(current_year, month)[1]),
                today,
            )

            # One aggregate per month instead of three per vehicle per month.
            month_costs = self._period_costs(cars, month_start, month_end)

            monthly_maintenance_costs.append(float(month_costs['maintenance_cost']))
            monthly_fuel_costs.append(float(month_costs['fuel_cost']))
            monthly_accident_costs.append(float(month_costs['accident_cost']))

        context['monthly_maintenance_costs'] = json.dumps(monthly_maintenance_costs)
        context['monthly_fuel_costs'] = json.dumps(monthly_fuel_costs)
        context['monthly_accident_costs'] = json.dumps(monthly_accident_costs)

        # Cost per vehicle data. Each total is aggregated separately and joined
        # in Python by car id, so combining the three relations cannot inflate
        # the sums through a multi-join fan-out.
        def _totals_by_car(model, car_field, date_field, value_field):
            rows = (
                model.objects
                .filter(**{
                    f'{car_field}__in': cars,
                    f'{date_field}__gte': start_of_year,
                    f'{date_field}__lte': today,
                })
                .values(car_field)
                .annotate(total=Sum(value_field))
            )
            return {row[car_field]: row['total'] or Decimal('0.00') for row in rows}

        maintenance_by_car = _totals_by_car(
            Maintenance, 'car', 'service_date', 'total_cost')
        fuel_by_car = _totals_by_car(
            FuelRecord, 'car', 'date', 'total_cost')
        accident_by_car = _totals_by_car(
            Accident, 'car', 'accident_date', 'accident_excess')

        vehicle_costs = []
        vehicle_labels = []
        zero = Decimal('0.00')
        for car in cars:
            car_total = (
                maintenance_by_car.get(car.pk, zero)
                + fuel_by_car.get(car.pk, zero)
                + accident_by_car.get(car.pk, zero)
            )
            if car_total > 0:
                vehicle_costs.append(float(car_total))
                vehicle_labels.append(f"{car.rego} ({car.make} {car.model})")

        context['vehicle_costs'] = json.dumps(vehicle_costs)
        context['vehicle_labels'] = json.dumps(vehicle_labels)

        # Fuel efficiency analysis. Only vehicles that actually hold fuel
        # records can produce an efficiency figure, so the per-vehicle work is
        # limited to those instead of scanning the whole fleet.
        cars_fuel_data = []
        cars_by_id = {car.pk: car for car in cars}
        recent_fuel_by_car = {}
        for record in FuelRecord.objects.filter(
            car_id__in=cars_by_id, full_tank=True,
        ).order_by('car_id', '-date', '-pk'):
            records = recent_fuel_by_car.setdefault(record.car_id, [])
            if len(records) < 6:
                records.append(record)

        if recent_fuel_by_car:
            # The reporting window is the same for every vehicle; compute once.
            last_month_end = today.replace(day=1) - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            last_month_fuel = {
                row['car']: row['total'] or Decimal('0.00')
                for row in FuelRecord.objects
                .filter(
                    car_id__in=recent_fuel_by_car,
                    date__gte=last_month_start,
                    date__lte=last_month_end,
                )
                .values('car')
                .annotate(total=Sum('total_cost'))
            }

            for car_id, fuel_records in recent_fuel_by_car.items():
                car = cars_by_id[car_id]
                efficiency_data = Car.calculate_fuel_efficiency(
                    fuel_records, last_n_records=5
                )
                if not efficiency_data:
                    continue
                cars_fuel_data.append({
                    'rego': car.rego,
                    'current_efficiency': efficiency_data['current'],
                    'avg_efficiency': efficiency_data['average'],
                    'best_efficiency': efficiency_data['best'],
                    'monthly_fuel_cost': last_month_fuel.get(car.pk, Decimal('0.00')),
                    'previous_efficiency': efficiency_data['previous'],
                })

        context['cars_fuel_data'] = cars_fuel_data
        return context

class GenerateReportView(LoginRequiredMixin, View):
    @staticmethod
    def _totals_by_car(model, car_ids, date_field, value_field, start_date, end_date):
        rows = (
            model.objects
            .filter(**{
                'car_id__in': car_ids,
                f'{date_field}__gte': start_date,
                f'{date_field}__lte': end_date,
            })
            .values('car_id')
            .annotate(total=Sum(value_field))
        )
        return {row['car_id']: row['total'] or Decimal('0.00') for row in rows}

    def get(self, request, *args, **kwargs):
        user = request.user
        
        # Get cars based on user's access level
        if get_user_role(user) == 'admin':
            cars = Car.objects.all()
        elif get_user_role(user) == 'manager':
            cars = Car.objects.filter(state=get_user_state(user))
        else:
            cars = Car.objects.filter(assigned_user=user)

        report_type = request.GET.get('type', 'excel')
        report_period = request.GET.get('period', 'monthly')
        if report_type not in {'excel', 'csv'}:
            return HttpResponseBadRequest('Unsupported report format.')
        if report_period not in {'monthly', 'yearly'}:
            return HttpResponseBadRequest('Unsupported report period.')

        rego = request.GET.get('rego', '').strip()
        if rego:
            cars = cars.filter(rego__iexact=rego)
        
        # Calculate date range
        end_date = timezone.localdate()
        if report_period == 'yearly':
            start_date = date(end_date.year, 1, 1)
        else:
            start_date = end_date.replace(day=1)

        # Collect each report dimension in one query, then join the results in
        # memory. Report cost no longer grows by several queries per vehicle.
        cars = list(cars)
        car_ids = [car.pk for car in cars]
        zero = Decimal('0.00')
        maintenance_by_car = self._totals_by_car(
            Maintenance, car_ids, 'service_date', 'total_cost', start_date, end_date
        )
        fuel_by_car = self._totals_by_car(
            FuelRecord, car_ids, 'date', 'total_cost', start_date, end_date
        )
        accident_by_car = self._totals_by_car(
            Accident, car_ids, 'accident_date', 'accident_excess', start_date, end_date
        )

        last_service_by_car = {}
        for service in Maintenance.objects.filter(
            car_id__in=car_ids,
            service_date__range=[start_date, end_date],
            service_type='regular',
        ).order_by('car_id', '-service_date', '-pk'):
            last_service_by_car.setdefault(service.car_id, service)

        recent_fuel_by_car = {}
        for record in FuelRecord.objects.filter(
            car_id__in=car_ids, full_tank=True,
        ).order_by('car_id', '-date', '-pk'):
            records = recent_fuel_by_car.setdefault(record.car_id, [])
            if len(records) < 6:
                records.append(record)

        report_data = []
        total_maintenance_cost = sum(maintenance_by_car.values(), zero)
        total_fuel_cost = sum(fuel_by_car.values(), zero)
        total_accident_cost = sum(accident_by_car.values(), zero)

        for car in cars:
            maintenance_cost = maintenance_by_car.get(car.pk, zero)
            fuel_cost = fuel_by_car.get(car.pk, zero)
            accident_cost = accident_by_car.get(car.pk, zero)
            last_service = last_service_by_car.get(car.pk)
            efficiency_data = Car.calculate_fuel_efficiency(
                recent_fuel_by_car.get(car.pk, []), last_n_records=5
            )
            
            report_data.append({
                'rego': car.rego,
                'make_model': f"{car.make} {car.model}",
                'maintenance_cost': maintenance_cost,
                'fuel_cost': fuel_cost,
                'accident_cost': accident_cost,
                'total_cost': maintenance_cost + fuel_cost + accident_cost,
                'last_service': last_service,
                'fuel_efficiency': efficiency_data['current'] if efficiency_data else None
            })

        if report_type == 'excel':
            return self._generate_excel_report(report_data, start_date, end_date,
                                            total_maintenance_cost, total_fuel_cost, total_accident_cost)
        else:  # csv
            return self._generate_csv_report(report_data, start_date, end_date,
                                           total_maintenance_cost, total_fuel_cost, total_accident_cost)

    def _generate_excel_report(self, data, start_date, end_date, total_maintenance, total_fuel, total_accident):
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename=fleet_report_{start_date.strftime("%Y%m%d")}.xlsx'

        workbook = xlsxwriter.Workbook(response)
        worksheet = workbook.add_worksheet()
        bold = workbook.add_format({'bold': True})
        money_format = workbook.add_format({'num_format': '$#,##0.00'})

        # Write headers and summary
        worksheet.write('A1', 'Fleet Cost Report', bold)
        worksheet.write('A2', f'Period: {start_date.strftime("%Y-%m-%d")} to {end_date.strftime("%Y-%m-%d")}')
        worksheet.write('A3', f'Total Maintenance Cost: ${total_maintenance:,.2f}')
        worksheet.write('A4', f'Total Fuel Cost: ${total_fuel:,.2f}')
        worksheet.write('A5', f'Total Accident Cost: ${total_accident:,.2f}')
        worksheet.write('A6', f'Total Fleet Cost: ${(total_maintenance + total_fuel + total_accident):,.2f}')

        # Write data
        headers = ['Rego', 'Make/Model', 'Maintenance Cost', 'Fuel Cost', 'Accident Cost', 'Total Cost', 'Last Service', 'Fuel Efficiency']
        for col, header in enumerate(headers):
            worksheet.write(7, col, header, bold)

        for row, item in enumerate(data, start=8):
            worksheet.write(row, 0, item['rego'])
            worksheet.write(row, 1, item['make_model'])
            worksheet.write(row, 2, item['maintenance_cost'], money_format)
            worksheet.write(row, 3, item['fuel_cost'], money_format)
            worksheet.write(row, 4, item['accident_cost'], money_format)
            worksheet.write(row, 5, item['total_cost'], money_format)
            worksheet.write(row, 6, item['last_service'].service_date.strftime('%Y-%m-%d') if item['last_service'] else 'N/A')
            worksheet.write(row, 7, f"{item['fuel_efficiency']:.2f} L/100km" if item['fuel_efficiency'] else 'N/A')

        workbook.close()
        return response

    def _generate_csv_report(self, data, start_date, end_date, total_maintenance, total_fuel, total_accident):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename=fleet_report_{start_date.strftime("%Y%m%d")}.csv'

        writer = csv.writer(response)
        writer.writerow(['Fleet Cost Report'])
        writer.writerow([f'Period: {start_date.strftime("%Y-%m-%d")} to {end_date.strftime("%Y-%m-%d")}'])
        writer.writerow([f'Total Maintenance Cost: ${total_maintenance:,.2f}'])
        writer.writerow([f'Total Fuel Cost: ${total_fuel:,.2f}'])
        writer.writerow([f'Total Accident Cost: ${total_accident:,.2f}'])
        writer.writerow([f'Total Fleet Cost: ${(total_maintenance + total_fuel + total_accident):,.2f}'])
        writer.writerow([])

        # Write headers
        writer.writerow(['Rego', 'Make/Model', 'Maintenance Cost', 'Fuel Cost', 'Accident Cost', 'Total Cost', 'Last Service', 'Fuel Efficiency'])

        # Write data
        for item in data:
            writer.writerow([
                item['rego'],
                item['make_model'],
                f"${item['maintenance_cost']:,.2f}",
                f"${item['fuel_cost']:,.2f}",
                f"${item['accident_cost']:,.2f}",
                f"${item['total_cost']:,.2f}",
                item['last_service'].service_date.strftime('%Y-%m-%d') if item['last_service'] else 'N/A',
                f"{item['fuel_efficiency']:.2f} L/100km" if item['fuel_efficiency'] else 'N/A'
            ])

        return response


# ----- Accident Views -----
class AccidentListView(LoginRequiredMixin, ListView):
    model = Accident
    template_name = 'tracking/accident_list.html'
    context_object_name = 'accidents'
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset().filter(
            car__status=Car.STATUS_IN_SERVICE
        ).select_related('car', 'driver')
        user = self.request.user

        # Apply car filter
        car_rego = self.request.GET.get('car_rego')
        if car_rego:
            queryset = queryset.filter(car__rego__icontains=car_rego)

        # Apply user-level filtering
        if get_user_role(user) == 'admin':
            return queryset
        elif get_user_role(user) == 'manager':
            return queryset.filter(car__state=get_user_state(user))
        else:  # User level
            return queryset.filter(car__assigned_user=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['car_regos'] = visible_cars_for(self.request.user).values_list(
            'rego', flat=True
        ).distinct()
        # Total every accident matching the current filters, not just the rows
        # on the visible page, so pagination cannot understate the figure.
        context['total_accident_cost'] = self.get_queryset().aggregate(
            total=Sum('accident_excess')
        )['total'] or Decimal('0.00')
        return context


class AccidentCreateView(LoginRequiredMixin, CreateView):
    model = Accident
    form_class = AccidentForm
    template_name = 'tracking/accident_form.html'
    success_url = reverse_lazy('accident_list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        role = get_user_role(user)
        if role == 'admin':
            form.fields['car'].queryset = Car.objects.active()
            form.fields['driver'].queryset = User.objects.all()
        elif role == 'manager':
            form.fields['car'].queryset = Car.objects.active().filter(state=get_user_state(user))
            form.fields['driver'].queryset = visible_drivers_for_manager(user)
        else:
            form.fields['car'].queryset = Car.objects.active().filter(assigned_user=user)
            form.fields['driver'].queryset = User.objects.filter(pk=user.pk)
        return form

    def form_valid(self, form):
        if get_user_role(self.request.user) == 'user':
            form.instance.driver = self.request.user
        messages.success(self.request, 'Accident record created successfully.')
        return super().form_valid(form)


class AccidentUpdateView(LoginRequiredMixin, UpdateView):
    model = Accident
    form_class = AccidentForm
    template_name = 'tracking/accident_form.html'
    success_url = reverse_lazy('accident_list')

    def get_queryset(self):
        queryset = super().get_queryset().filter(car__status=Car.STATUS_IN_SERVICE)
        user = self.request.user
        role = get_user_role(user)
        if role == 'admin':
            return queryset
        if role == 'manager':
            return queryset.filter(car__state=get_user_state(user))
        return queryset.filter(car__assigned_user=user)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        user = self.request.user
        role = get_user_role(user)
        if role == 'admin':
            form.fields['car'].queryset = Car.objects.active()
            form.fields['driver'].queryset = User.objects.all()
        elif role == 'manager':
            form.fields['car'].queryset = Car.objects.active().filter(state=get_user_state(user))
            form.fields['driver'].queryset = visible_drivers_for_manager(user)
        else:
            form.fields['car'].queryset = Car.objects.active().filter(assigned_user=user)
            form.fields['driver'].queryset = User.objects.filter(pk=user.pk)
        return form

    def form_valid(self, form):
        if get_user_role(self.request.user) == 'user':
            form.instance.driver = self.request.user
        messages.success(self.request, 'Accident record updated successfully.')
        return super().form_valid(form)


class AccidentDeleteView(AdminManagerRequiredMixin, DeleteView):
    model = Accident
    template_name = 'tracking/accident_confirm_delete.html'
    success_url = reverse_lazy('accident_list')

    def get_queryset(self):
        queryset = super().get_queryset()
        if get_user_role(self.request.user) == 'admin':
            return queryset
        return queryset.filter(car__state=get_user_state(self.request.user))

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, 'Accident record deleted successfully.')
        return super().delete(request, *args, **kwargs)
