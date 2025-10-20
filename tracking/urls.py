from django.urls import path
from django.shortcuts import redirect
from django.conf import settings
from django.contrib.auth import views as auth_views
from .views import (
    DashboardView, UserCarView, AdminCarView, CustomLoginView, ManagerToolListView,
    ManagerDashboardView, UserDashboardView, ToolListView, ToolCreateView, 
    ToolUpdateView, ToolDeleteView, CarListView, CarCreateView, CarUpdateView, 
    CarDeleteView, OdometerReadingListView, OdometerReadingCreateView, 
    OdometerReadingUpdateView, OdometerReadingDeleteView, OdometerUpdateView,
    MaintenanceRecordListView, MaintenanceRecordCreateView, MaintenanceRecordUpdateView, 
    MaintenanceRecordDeleteView, TransferListView, TransferCreateView, ImportView, 
    UserListView, UserCreateView, UserUpdateView, UserDeleteView, ManagerCarListView, 
    FleetAnalyticsView, GenerateReportView, AdminDashboardView
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
    path('tools/<str:pk>/edit/', ToolUpdateView.as_view(), name='tool_edit'),
    path('tools/<str:pk>/delete/', ToolDeleteView.as_view(), name='tool_delete'),

    # Cars
    path('cars/', CarListView.as_view(), name='car_list'),
    path('cars/add/', CarCreateView.as_view(), name='car_add'),
    path('cars/<int:pk>/edit/', CarUpdateView.as_view(), name='car_edit'),
    path('cars/<int:pk>/delete/', CarDeleteView.as_view(), name='car_delete'),
    path('cars/<int:pk>/odometer/', OdometerUpdateView.as_view(), name='car_odometer_update'),
    path('cars/<int:pk>/odometer/', OdometerUpdateView.as_view(), name='car_odometer_update'),

    # Import
    path('import/', ImportView.as_view(), name='import'),

    # Odometer
    path('odometer/', OdometerReadingListView.as_view(), name='odometer_list'),
    path('odometer/add/', OdometerReadingCreateView.as_view(), name='odometer_add'),
    path('odometer/<int:pk>/edit/', OdometerReadingUpdateView.as_view(), name='odometer_edit'),
    path('odometer/<int:pk>/delete/', OdometerReadingDeleteView.as_view(), name='odometer_delete'),

    # Maintenance
    path('maintenance/', MaintenanceRecordListView.as_view(), name='maintenance_list'),
    path('maintenance/add/', MaintenanceRecordCreateView.as_view(), name='maintenance_add'),
    path('maintenance/<int:pk>/edit/', MaintenanceRecordUpdateView.as_view(), name='maintenance_edit'),
    path('maintenance/<int:pk>/delete/', MaintenanceRecordDeleteView.as_view(), name='maintenance_delete'),

    # Transfer
    path('transfers/', TransferListView.as_view(), name='transfer_list'),
    path('transfers/add/', TransferCreateView.as_view(), name='transfer_add'),

    # Users
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/add/', UserCreateView.as_view(), name='user_add'),
    path('users/<int:pk>/edit/', UserUpdateView.as_view(), name='user_edit'),
    path('users/<int:pk>/delete/', UserDeleteView.as_view(), name='user_delete'),
   
    # User Password Change
    path('users/<int:pk>/password/', auth_views.PasswordChangeView.as_view(
        template_name='registration/password_change_form.html'), name='user_password_change'),

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
