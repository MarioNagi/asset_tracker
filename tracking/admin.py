from django.contrib import admin
from .models import (
    Profile, Tool, Car, OdometerReading, Maintenance, Transfer, Accident,
    VehicleRetirementTask, CustodyLocation, TransferBatch, TransferLedgerEntry,
    TransferFollowUpTask,
    AlertContact, NotificationDelivery, ToolCatalogueItem,
)
from django.utils.html import format_html


# --------- Profile Admin ---------
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'access_level', 'state', 'display_photo')
    list_filter = ('access_level', 'state')
    search_fields = ('user__username', 'user__email')

    def display_photo(self, obj):
        if obj.photo:
            return format_html('<img src="{}" width="50" height="50" />', obj.photo.url)
        return "No Photo"
    display_photo.short_description = 'Photo'


# --------- Tool Admin ---------
@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    list_display = ('tool_name', 'brand', 'description', 'size', 'store', 'state', 'quantity', 'assigned_user')
    list_filter = ('tool_name', 'brand', 'state', 'assigned_user')
    search_fields = ('tool_name', 'brand', 'assigned_user__username')


@admin.register(ToolCatalogueItem)
class ToolCatalogueItemAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'suggested_controlled',
        'suggested_calibration_required', 'active', 'updated_at',
    )
    list_filter = ('suggested_controlled', 'suggested_calibration_required', 'active')
    search_fields = ('name', 'notes')
    readonly_fields = ('created_by', 'updated_by', 'created_at', 'updated_at')


# --------- Car Admin ---------
@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = (
        'rego', 'make', 'model', 'state', 'purchase_date', 'purchase_price',
        'assigned_user', 'status', 'rego_expiry_date', 'current_odometer', 'service_odometer', 'is_service_due'
    )
    list_filter = ('status', 'make', 'model', 'state', 'assigned_user')
    search_fields = ('rego', 'vin_number', 'make', 'model')

    def is_service_due(self, obj):
        return obj.is_service_due_by_km()
    is_service_due.boolean = True
    is_service_due.short_description = 'Service Due'


@admin.register(VehicleRetirementTask)
class VehicleRetirementTaskAdmin(admin.ModelAdmin):
    list_display = ('car', 'task_type', 'completed', 'completed_by', 'completed_at')
    list_filter = ('completed', 'task_type', 'car__state')
    search_fields = ('car__rego', 'notes')


@admin.register(CustodyLocation)
class CustodyLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'location_type', 'state', 'responsible_manager', 'active')
    list_filter = ('location_type', 'state', 'active')
    search_fields = ('name', 'address')


@admin.register(TransferBatch)
class TransferBatchAdmin(admin.ModelAdmin):
    list_display = ('reference', 'date_of_transfer', 'source_label', 'destination_label', 'created_by')
    readonly_fields = [field.name for field in TransferBatch._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TransferLedgerEntry)
class TransferLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('batch', 'asset_type', 'asset_identifier', 'recorded_at')
    readonly_fields = [field.name for field in TransferLedgerEntry._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TransferFollowUpTask)
class TransferFollowUpTaskAdmin(admin.ModelAdmin):
    list_display = ('description', 'state', 'assigned_to', 'completed', 'created_at')
    list_filter = ('completed', 'state')


@admin.register(AlertContact)
class AlertContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'responsibility', 'state', 'is_primary', 'enabled')
    list_filter = ('responsibility', 'state', 'is_primary', 'enabled')
    search_fields = ('name', 'email')
    readonly_fields = ('created_by', 'updated_by', 'created_at', 'updated_at')


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'subject', 'status', 'attempt_count', 'created_at', 'sent_at')
    list_filter = ('event_type', 'status')
    search_fields = ('subject', 'related_object', 'deduplication_key')
    readonly_fields = [field.name for field in NotificationDelivery._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# --------- Maintenance Admin ---------
@admin.register(Maintenance)
class MaintenanceAdmin(admin.ModelAdmin):
    list_display = (
        'car', 'service_date', 'service_type', 'service_provider',
        'total_cost', 'odometer_reading'
    )
    list_filter = ('car', 'service_date', 'service_type', 'service_provider')
    search_fields = ('car__rego', 'service_provider', 'description', 'invoice_number')


# --------- Odometer Reading Admin ---------
@admin.register(OdometerReading)
class OdometerReadingAdmin(admin.ModelAdmin):
    list_display = ('car', 'reading_date', 'reading_value')
    list_filter = ('car', 'reading_date')
    search_fields = ('car__rego',)


# --------- Transfer Admin ---------
@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ('transfer_type', 'item_id', 'from_user', 'to_user', 'date_of_transfer')
    list_filter = ('transfer_type', 'date_of_transfer')
    search_fields = ('from_user__username', 'to_user__username')


# --------- Accident Admin ---------
@admin.register(Accident)
class AccidentAdmin(admin.ModelAdmin):
    list_display = (
        'car', 'accident_date', 'driver', 'accident_excess', 
        'via_insurance', 'insurance_company'
    )
    list_filter = ('accident_date', 'via_insurance', 'car', 'driver')
    search_fields = ('car__rego', 'driver__username', 'insurance_company', 'claim_number')
