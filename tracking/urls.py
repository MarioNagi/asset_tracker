from django.urls import path
from django.shortcuts import redirect
from django.conf import settings
from django.contrib.auth import views as auth_views
from .views import (
    DashboardView, UserCarView, AdminCarView, CustomLoginView, ManagerToolListView,
    ManagerDashboardView, UserDashboardView, ToolListView, ToolDetailView, ToolCreateView, 
    ToolUpdateView, ToolDeleteView, CarListView, CarCreateView, CarUpdateView, 
    CarDeleteView, OdometerReadingListView, OdometerReadingCreateView, 
    OdometerReadingUpdateView, OdometerReadingDeleteView, OdometerUpdateView,
    MaintenanceRecordListView, MaintenanceRecordDetailView,
    MaintenanceRecordCreateView, MaintenanceRecordUpdateView, 
    MaintenanceRecordDeleteView, TransferListView, TransferCreateView, ImportView, 
    UserListView, UserCreateView, UserUpdateView, UserDeleteView, ManagerCarListView, 
    FleetAnalyticsView, GenerateReportView, AdminDashboardView,
    AccidentListView, AccidentCreateView, AccidentUpdateView, AccidentDeleteView,
    AdminSetPasswordView, PDFInvoiceImportView, VehicleHistoryListView,
    CarDetailView, VehicleRetirementTaskUpdateView, TransferReverseView,
    TransferFollowUpTaskUpdateView,
    CompanyLocationListView, CompanyLocationDetailView,
    CompanyLocationCreateView, CompanyLocationUpdateView,
    AlertContactListView, AlertContactCreateView, AlertContactUpdateView,
    NotificationDeliveryListView, NotificationDeliveryRetryView,
    ToolCatalogueListView, ToolCatalogueCreateView, ToolCatalogueUpdateView,
    maintenance_document_download, car_photo_download,
    car_retirement_document_download, tool_photo_download,
    VehicleQRSubmissionView, OdometerReviewListView, OdometerReviewView,
    SpecialMaintenanceListView, SpecialMaintenanceCreateView,
    SpecialMaintenanceUpdateView, SpecialMaintenanceCompleteView,
    fuel_receipt_download, odometer_evidence_download,
    special_maintenance_document_download,
    vehicle_qr_code, VehicleQRLabelView,
)

urlpatterns = [
    # Redirect root to the dashboard if authenticated, otherwise go to login
    path('', DashboardView.as_view(), name='dashboard'),
    
    # Auth + Password Reset
    path('accounts/password_reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html'
    ), name='password_reset'),
    path('accounts/password_reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html'
    ), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html'
    ), name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html'
    ), name='password_reset_complete'),

    # Custom Login / Logout
    path('accounts/login/', CustomLoginView.as_view(), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(), name='logout'),

    # Dashboards
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('admin-dashboard/', AdminDashboardView.as_view(), name='admin_dashboard'),
    path('manager-dashboard/', ManagerDashboardView.as_view(), name='manager_dashboard'),
    path('user-dashboard/', UserDashboardView.as_view(), name='user_dashboard'),

    # Tools
    path('tools/', ToolListView.as_view(), name='tool_list'),
    path('tools/add/', ToolCreateView.as_view(), name='tool_add'),
    path('tools/catalogue/', ToolCatalogueListView.as_view(), name='tool_catalogue_list'),
    path('tools/catalogue/add/', ToolCatalogueCreateView.as_view(), name='tool_catalogue_add'),
    path('tools/catalogue/<int:pk>/edit/', ToolCatalogueUpdateView.as_view(), name='tool_catalogue_edit'),
    path('tools/locations/', CompanyLocationListView.as_view(), name='company_location_list'),
    path('tools/locations/add/', CompanyLocationCreateView.as_view(), name='company_location_add'),
    path('tools/locations/<int:pk>/', CompanyLocationDetailView.as_view(), name='company_location_detail'),
    path('tools/locations/<int:pk>/edit/', CompanyLocationUpdateView.as_view(), name='company_location_edit'),
    path('tools/<str:pk>/photo/', tool_photo_download, name='tool_photo'),
    path('tools/<str:pk>/', ToolDetailView.as_view(), name='tool_detail'),
    path('tools/<str:pk>/edit/', ToolUpdateView.as_view(), name='tool_edit'),
    path('tools/<str:pk>/delete/', ToolDeleteView.as_view(), name='tool_delete'),

    # Cars
    path('cars/', CarListView.as_view(), name='car_list'),
    path('cars/add/', CarCreateView.as_view(), name='car_add'),
    path('cars/history/', VehicleHistoryListView.as_view(), name='vehicle_history'),
    path('cars/retirement-tasks/<int:pk>/', VehicleRetirementTaskUpdateView.as_view(), name='vehicle_retirement_task_edit'),
    path('cars/<int:pk>/photo/', car_photo_download, name='car_photo'),
    path('cars/<int:pk>/retirement-document/', car_retirement_document_download, name='car_retirement_document'),
    path('cars/<int:pk>/qr.png', vehicle_qr_code, name='vehicle_qr_code'),
    path('cars/<int:pk>/qr-label/', VehicleQRLabelView.as_view(), name='vehicle_qr_label'),
    path('cars/<int:pk>/', CarDetailView.as_view(), name='car_detail'),
    path('cars/<int:pk>/edit/', CarUpdateView.as_view(), name='car_edit'),
    path('cars/<int:pk>/delete/', CarDeleteView.as_view(), name='car_delete'),
    path('cars/<int:pk>/odometer/', OdometerUpdateView.as_view(), name='car_odometer_update'),
    path('vehicle/<uuid:token>/update/', VehicleQRSubmissionView.as_view(), name='vehicle_qr_entry'),

    # Import
    path('import/', ImportView.as_view(), name='import'),

    # Odometer
    path('odometer/', OdometerReadingListView.as_view(), name='odometer_list'),
    path('odometer/add/', OdometerReadingCreateView.as_view(), name='odometer_add'),
    path('odometer/<int:pk>/edit/', OdometerReadingUpdateView.as_view(), name='odometer_edit'),
    path('odometer/<int:pk>/delete/', OdometerReadingDeleteView.as_view(), name='odometer_delete'),
    path('odometer/review/', OdometerReviewListView.as_view(), name='odometer_review_list'),
    path('odometer/review/<int:pk>/', OdometerReviewView.as_view(), name='odometer_review'),
    path('odometer/<int:pk>/evidence/', odometer_evidence_download, name='odometer_evidence'),
    path('fuel/<int:pk>/receipt/', fuel_receipt_download, name='fuel_receipt'),

    # Maintenance
    path('maintenance/', MaintenanceRecordListView.as_view(), name='maintenance_list'),
    path('maintenance/add/', MaintenanceRecordCreateView.as_view(), name='maintenance_add'),
    path('maintenance/import-pdf/', PDFInvoiceImportView.as_view(), name='pdf_invoice_import'),
    path('maintenance/<int:pk>/document/', maintenance_document_download, name='maintenance_document'),
    path('maintenance/<int:pk>/', MaintenanceRecordDetailView.as_view(), name='maintenance_detail'),
    path('maintenance/<int:pk>/edit/', MaintenanceRecordUpdateView.as_view(), name='maintenance_edit'),
    path('maintenance/<int:pk>/delete/', MaintenanceRecordDeleteView.as_view(), name='maintenance_delete'),
    path('maintenance/special/', SpecialMaintenanceListView.as_view(), name='special_maintenance_list'),
    path('maintenance/special/add/', SpecialMaintenanceCreateView.as_view(), name='special_maintenance_add'),
    path('maintenance/special/<int:pk>/edit/', SpecialMaintenanceUpdateView.as_view(), name='special_maintenance_edit'),
    path('maintenance/special/<int:pk>/complete/', SpecialMaintenanceCompleteView.as_view(), name='special_maintenance_complete'),
    path('maintenance/special/<int:pk>/document/', special_maintenance_document_download, name='special_maintenance_document'),

    # Accidents
    path('accidents/', AccidentListView.as_view(), name='accident_list'),
    path('accidents/add/', AccidentCreateView.as_view(), name='accident_add'),
    path('accidents/<int:pk>/edit/', AccidentUpdateView.as_view(), name='accident_edit'),
    path('accidents/<int:pk>/delete/', AccidentDeleteView.as_view(), name='accident_delete'),

    # Transfer
    path('transfers/', TransferListView.as_view(), name='transfer_list'),
    path('transfers/add/', TransferCreateView.as_view(), name='transfer_add'),
    path('transfers/<int:pk>/reverse/', TransferReverseView.as_view(), name='transfer_reverse'),
    path('transfers/tasks/<int:pk>/', TransferFollowUpTaskUpdateView.as_view(), name='transfer_follow_up_task_edit'),

    # Users
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/add/', UserCreateView.as_view(), name='user_add'),
    path('users/<int:pk>/edit/', UserUpdateView.as_view(), name='user_edit'),
    path('users/<int:pk>/delete/', UserDeleteView.as_view(), name='user_delete'),
    path('users/email-alerts/', AlertContactListView.as_view(), name='alert_contact_list'),
    path('users/email-alerts/add/', AlertContactCreateView.as_view(), name='alert_contact_add'),
    path('users/email-alerts/<int:pk>/edit/', AlertContactUpdateView.as_view(), name='alert_contact_edit'),
    path('users/email-alerts/history/', NotificationDeliveryListView.as_view(), name='notification_delivery_list'),
    path('users/email-alerts/history/<int:pk>/retry/', NotificationDeliveryRetryView.as_view(), name='notification_delivery_retry'),
   
    # User Password Change
    path('users/<int:pk>/password/', AdminSetPasswordView.as_view(), name='user_password_change'),

    # Car views by role
    path('user-cars/', UserCarView.as_view(), name='user_cars'),
    path('admin-cars/', AdminCarView.as_view(), name='admin_cars'),
    path('manager-cars/', ManagerCarListView.as_view(), name='manager_cars'),
    path('manager-tools/', ManagerToolListView.as_view(), name='manager_tools'),

    # Fleet Analytics
    path('analytics/', FleetAnalyticsView.as_view(), name='fleet_analytics'),

    # Reports
    path('reports/generate/', GenerateReportView.as_view(), name='generate_report'),
]
