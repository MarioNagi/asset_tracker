import base64
import hashlib
import hmac
import json
import struct
import tempfile
import time
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from django.core import mail
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from allauth.mfa.models import Authenticator
from allauth.mfa.utils import encrypt
from openpyxl import load_workbook
from pypdf import PdfWriter

from .maintenance_service import MaintenanceInvoiceService
from .models import (
    Accident, Car, FuelRecord, Maintenance, MaintenanceItem, OdometerReading, Tool, Transfer,
    VehicleRetirementTask, CustodyLocation, TransferBatch, TransferLedgerEntry,
    TransferFollowUpTask, AlertContact, NotificationDelivery, ToolCatalogueItem,
    SpecialMaintenanceRequirement,
)
from .pdf_invoice_parser import PDFInvoiceParser, InvoiceData, InvoiceItem
from .tasks import (
    send_calibration_reminders, send_retirement_task_reminders,
    send_transfer_follow_up_reminders,
    send_special_maintenance_reminders, send_weekly_odometer_reminders,
)
from .views import AccidentListView
from .notification_service import (
    alert_recipient_emails, primary_state_manager_email,
    send_tracked_notification,
)


class ApplicationTestCase(TestCase):
    def setUp(self):
        super().setUp()
        # Workflow tests focus on their own permissions. Mandatory enrollment
        # is covered independently in MFAAuthenticationTests below.
        self._mfa_override = self.settings(ASSET_TRACKER_MFA_REQUIRED_ROLES=set())
        self._mfa_override.enable()

    def tearDown(self):
        self._mfa_override.disable()
        super().tearDown()

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user('admin_user', password='Admin-pass-123')
        cls.admin.profile.access_level = 'Admin'
        cls.admin.profile.state = 'NSW-Wireless'
        cls.admin.profile.save()

        cls.manager = User.objects.create_user('manager_user', password='Manager-pass-123')
        cls.manager.profile.access_level = 'Manager'
        cls.manager.profile.state = 'NSW-Wireless'
        cls.manager.profile.save()

        cls.user = User.objects.create_user('regular_user', password='User-pass-123')
        cls.user.profile.access_level = 'User'
        cls.user.profile.state = 'NSW-Wireless'
        cls.user.profile.save()

        cls.other_user = User.objects.create_user('other_user', password='Other-pass-123')
        cls.other_user.profile.access_level = 'User'
        cls.other_user.profile.state = 'VIC'
        cls.other_user.profile.save()

        cls.car = Car.objects.create(
            rego='TEST01',
            rego_expiry_date=date(2030, 1, 1),
            state='NSW',
            assigned_user=cls.user,
            make='Test',
            model='Vehicle',
            vin_number='VIN-TEST-01',
        )
        cls.other_car = Car.objects.create(
            rego='TEST02',
            rego_expiry_date=date(2030, 1, 1),
            state='VIC',
            assigned_user=cls.other_user,
            make='Other',
            model='Vehicle',
            vin_number='VIN-TEST-02',
        )
        cls.odometer = OdometerReading.objects.create(
            car=cls.car,
            reading_date=date(2026, 1, 1),
            reading_value=1000,
        )
        cls.other_odometer = OdometerReading.objects.create(
            car=cls.other_car,
            reading_date=date(2026, 1, 1),
            reading_value=2000,
        )
        cls.accident = Accident.objects.create(car=cls.car, driver=cls.user)
        cls.other_accident = Accident.objects.create(car=cls.other_car, driver=cls.other_user)
        cls.maintenance = Maintenance.objects.create(
            car=cls.car,
            service_date=date(2026, 1, 1),
            service_type='repair',
            service_provider='Test Provider',
        )
        cls.other_maintenance = Maintenance.objects.create(
            car=cls.other_car,
            service_date=date(2026, 1, 1),
            service_type='repair',
            service_provider='Other Provider',
        )
        cls.tool = Tool.objects.create(
            internal_number='KE-TEST',
            tool_name='radman',
            store='Online',
            state='NSW',
            assigned_user=cls.user,
        )
        cls.other_tool = Tool.objects.create(
            internal_number='KE-OTHER',
            tool_name='other tool',
            store='Online',
            state='VIC',
            brand='Other Brand',
            assigned_user=cls.other_user,
        )


class NavigationTests(ApplicationTestCase):
    def test_all_current_route_names_reverse(self):
        routes = [
            ('manager_cars', ()),
            ('manager_tools', ()),
            ('odometer_add', ()),
            ('odometer_edit', (self.odometer.pk,)),
            ('odometer_delete', (self.odometer.pk,)),
            ('odometer_list', ()),
            ('tool_edit', (self.tool.pk,)),
            ('tool_delete', (self.tool.pk,)),
            ('tool_list', ()),
            ('user_list', ()),
        ]
        for name, args in routes:
            with self.subTest(name=name):
                self.assertTrue(reverse(name, args=args))

    def test_manager_dashboard_renders_with_nsw_subdivision(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('manager_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.car, response.context['cars'])

    def test_maintenance_delete_confirmation_exists(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('maintenance_delete', args=[self.maintenance.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.car.rego)

    def test_admin_dashboard_renders_an_unassigned_car(self):
        Car.objects.create(
            rego='UNASSIGNED',
            rego_expiry_date=date(2030, 1, 1),
            state='NSW',
            make='Test',
            model='Unassigned',
            vin_number='VIN-UNASSIGNED',
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Unassigned')


@override_settings(ASSET_TRACKER_MFA_REQUIRED_ROLES={'admin', 'manager'})
class MFAAuthenticationTests(TestCase):
    @staticmethod
    def _activate_totp(user, secret):
        return Authenticator.objects.create(
            user=user,
            type=Authenticator.Type.TOTP,
            data={'secret': encrypt(secret)},
        )

    def setUp(self):
        self.admin = User.objects.create_user(
            'mfa_admin', password='Admin-pass-123', email='admin@example.com'
        )
        self.admin.profile.access_level = 'Admin'
        self.admin.profile.save()

        self.manager = User.objects.create_user(
            'mfa_manager', password='Manager-pass-123', email='manager@example.com'
        )
        self.manager.profile.access_level = 'Manager'
        self.manager.profile.state = 'NSW-Wireless'
        self.manager.profile.save()

        self.user = User.objects.create_user(
            'mfa_user', password='User-pass-123', email='user@example.com'
        )
        self.user.profile.access_level = 'User'
        self.user.profile.save()

    def test_admin_without_mfa_is_redirected_to_enrollment(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertRedirects(
            response,
            reverse('mfa_activate_totp'),
            fetch_redirect_response=False,
        )

    def test_activation_page_uses_application_security_layout(self):
        self.client.post(reverse('login'), {
            'login': self.admin.username,
            'password': 'Admin-pass-123',
        })
        response = self.client.get(reverse('mfa_activate_totp'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Koinonia Asset Tracker')
        self.assertContains(response, 'class="mfa-qr"', html=False)
        self.assertContains(response, 'Manual setup key')
        self.assertContains(response, '/static/css/mfa.css')

    def test_invalid_totp_activation_keeps_the_same_enrollment_secret(self):
        self.client.post(reverse('login'), {
            'login': self.admin.username,
            'password': 'Admin-pass-123',
        })
        response = self.client.get(reverse('mfa_activate_totp'))
        original_secret = response.context['form'].secret

        response = self.client.post(
            reverse('mfa_activate_totp'),
            {'code': 'not-a-valid-code'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].secret, original_secret)
        self.assertFalse(
            Authenticator.objects.filter(
                user=self.admin,
                type=Authenticator.Type.TOTP,
            ).exists()
        )

    def test_totp_activation_refresh_keeps_pending_enrollment_secret(self):
        self.client.post(reverse('login'), {
            'login': self.admin.username,
            'password': 'Admin-pass-123',
        })
        first_response = self.client.get(reverse('mfa_activate_totp'))
        first_secret = first_response.context['form'].secret

        second_response = self.client.get(reverse('mfa_activate_totp'))

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.context['form'].secret, first_secret)

    def test_valid_totp_activation_saves_authenticator_before_redirect(self):
        self.client.post(reverse('login'), {
            'login': self.admin.username,
            'password': 'Admin-pass-123',
        })
        response = self.client.get(reverse('mfa_activate_totp'))
        secret = response.context['form'].secret

        response = self.client.post(
            reverse('mfa_activate_totp'),
            {'code': self._current_totp_code(secret)},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Authenticator.objects.filter(
                user=self.admin,
                type=Authenticator.Type.TOTP,
            ).exists()
        )

    def test_regular_user_can_opt_in_without_forced_enrollment(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('mfa_index'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Two-Factor Authentication')
        self.assertContains(response, 'class="mfa-shell"', html=False)
        self.assertContains(response, 'Account Security')

    def test_enrolled_admin_can_access_operational_pages(self):
        self._activate_totp(self.admin, 'JBSWY3DPEHPK3PXP')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_password_login_for_enrolled_account_requires_second_factor(self):
        self._activate_totp(self.admin, 'JBSWY3DPEHPK3PXP')
        response = self.client.post(reverse('login'), {
            'login': self.admin.username,
            'password': 'Admin-pass-123',
        })
        self.assertRedirects(
            response,
            reverse('mfa_authenticate'),
            fetch_redirect_response=False,
        )

        response = self.client.get(reverse('mfa_authenticate'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'mfa-auth-card')
        self.assertContains(response, 'Verify and continue')
        self.assertContains(response, 'Koinonia Asset Tracker')

    @staticmethod
    def _current_totp_code(secret):
        key = base64.b32decode(secret)
        counter = int(time.time()) // 30
        digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        value = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return f'{value % 1_000_000:06d}'

    def test_enrolled_privileged_accounts_reach_their_dashboard_after_mfa(self):
        secret = 'JBSWY3DPEHPK3PXP'
        accounts = (
            (self.admin, 'Admin-pass-123', reverse('admin_dashboard')),
            (self.manager, 'Manager-pass-123', reverse('manager_dashboard')),
        )

        for account, password, expected_dashboard in accounts:
            with self.subTest(account=account.username):
                self._activate_totp(account, secret)
                response = self.client.post(reverse('login'), {
                    'login': account.username,
                    'password': password,
                })
                self.assertRedirects(
                    response,
                    reverse('mfa_authenticate'),
                    fetch_redirect_response=False,
                )
                response = self.client.post(
                    reverse('mfa_authenticate'),
                    {'code': self._current_totp_code(secret)},
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.request['PATH_INFO'], expected_dashboard)
                self.client.logout()


class AccountRegistrationTests(TestCase):
    def test_public_signup_page_is_closed(self):
        response = self.client.get(reverse('account_signup'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<form', html=False)
        self.assertContains(response, 'Sign Up Closed')

    def test_public_signup_post_cannot_create_an_account(self):
        response = self.client.post(reverse('account_signup'), {
            'username': 'public_signup',
            'email': 'public@example.com',
            'password1': 'Public-pass-123',
            'password2': 'Public-pass-123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='public_signup').exists())


class UserAdministrationTests(ApplicationTestCase):
    def test_admin_can_create_user_with_role_state_and_password(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('user_add'), {
            'username': 'created_user',
            'email': 'created@example.com',
            'first_name': 'Created',
            'last_name': 'User',
            'access_level': 'Manager',
            'state': 'VIC',
            'password1': 'Created-pass-123',
            'password2': 'Created-pass-123',
        })
        self.assertRedirects(response, reverse('user_list'))
        created = User.objects.get(username='created_user')
        self.assertTrue(created.check_password('Created-pass-123'))
        self.assertEqual(created.profile.access_level, 'Manager')
        self.assertEqual(created.profile.state, 'VIC')

    def test_admin_sets_target_password_without_changing_own(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('user_password_change', args=[self.user.pk]), {
            'new_password1': 'Replacement-pass-123',
            'new_password2': 'Replacement-pass-123',
        })
        self.assertRedirects(response, reverse('user_list'))
        self.user.refresh_from_db()
        self.admin.refresh_from_db()
        self.assertTrue(self.user.check_password('Replacement-pass-123'))
        self.assertTrue(self.admin.check_password('Admin-pass-123'))

    def test_regular_user_cannot_manage_users(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('user_list')).status_code, 403)
        self.assertEqual(
            self.client.get(reverse('user_password_change', args=[self.other_user.pk])).status_code,
            403,
        )


class AccessControlTests(ApplicationTestCase):
    def test_regular_user_cannot_manage_core_inventory(self):
        self.client.force_login(self.user)
        protected_routes = [
            reverse('tool_add'),
            reverse('tool_delete', args=[self.tool.pk]),
            reverse('car_add'),
            reverse('car_delete', args=[self.car.pk]),
            reverse('maintenance_add'),
            reverse('maintenance_delete', args=[self.maintenance.pk]),
        ]
        for url in protected_routes:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_manager_can_edit_but_not_delete_core_inventory(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('tool_edit', args=[self.tool.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('car_edit', args=[self.car.pk])).status_code, 200)
        self.assertEqual(
            self.client.get(reverse('maintenance_edit', args=[self.maintenance.pk])).status_code,
            200,
        )
        self.assertEqual(self.client.get(reverse('tool_delete', args=[self.tool.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('car_delete', args=[self.car.pk])).status_code, 403)

    def test_user_cannot_edit_another_users_odometer(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('odometer_edit', args=[self.other_odometer.pk]))
        self.assertEqual(response.status_code, 404)

    def test_user_cannot_edit_another_users_accident(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accident_edit', args=[self.other_accident.pk]))
        self.assertEqual(response.status_code, 404)

    def test_user_can_report_and_edit_accident_for_assigned_car(self):
        self.client.force_login(self.user)
        add_response = self.client.get(reverse('accident_add'))
        edit_response = self.client.get(reverse('accident_edit', args=[self.accident.pk]))
        self.assertEqual(add_response.status_code, 200)
        self.assertEqual(edit_response.status_code, 200)
        self.assertQuerySetEqual(
            add_response.context['form'].fields['car'].queryset,
            [self.car],
        )

    def test_regular_user_filter_choices_do_not_reveal_other_fleet_data(self):
        self.client.force_login(self.user)

        tool_response = self.client.get(reverse('tool_list'))
        self.assertEqual(list(tool_response.context['states']), ['NSW'])
        self.assertNotIn('Other Brand', list(tool_response.context['brands']))
        self.assertNotIn(
            self.other_car.rego,
            [car['rego'] for car in tool_response.context['cars']],
        )

        car_response = self.client.get(reverse('car_list'))
        self.assertEqual(list(car_response.context['regos']), [self.car.rego])

        maintenance_response = self.client.get(reverse('maintenance_list'))
        self.assertEqual(list(maintenance_response.context['regos']), [self.car.rego])
        self.assertEqual(
            list(maintenance_response.context['service_providers']),
            ['Test Provider'],
        )

        accident_response = self.client.get(reverse('accident_list'))
        self.assertEqual(list(accident_response.context['car_regos']), [self.car.rego])

        analytics_response = self.client.get(reverse('fleet_analytics'))
        self.assertEqual(list(analytics_response.context['regos']), [self.car.rego])


class VehicleLifecycleTests(ApplicationTestCase):
    def test_new_vehicle_is_active_by_default(self):
        self.assertEqual(self.car.status, Car.STATUS_IN_SERVICE)
        self.assertTrue(self.car.is_active)

    def test_retirement_form_requires_complete_financial_record(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('car_delete', args=[self.car.pk]), {
            'status': Car.STATUS_SOLD,
            'confirm_retirement': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.car.refresh_from_db()
        self.assertTrue(self.car.is_active)
        self.assertFormError(response.context['form'], 'final_value', 'Final amount received is required.')

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        FLEET_MANAGER_EMAIL='fleet@example.com',
    )
    def test_admin_retires_vehicle_without_deleting_history(self):
        self.tool.assigned_car = self.car
        self.tool.save(update_fields=['assigned_car'])
        self.client.force_login(self.admin)
        response = self.client.post(reverse('car_delete', args=[self.car.pk]), {
            'status': Car.STATUS_WRITTEN_OFF,
            'retired_at': '2026-08-12',
            'final_odometer': '1500',
            'final_value': '12500.00',
            'final_payment_date': '2026-08-12',
            'final_payment_source': 'Insurance company',
            'final_payment_reference': 'CLAIM-123',
            'retirement_notes': 'Insurer confirmed total loss and payment.',
            'confirm_retirement': 'on',
        })

        self.assertRedirects(response, reverse('car_list'))
        self.car.refresh_from_db()
        self.tool.refresh_from_db()
        self.assertEqual(self.car.status, Car.STATUS_WRITTEN_OFF)
        self.assertIsNone(self.car.assigned_user)
        self.assertIsNone(self.tool.assigned_car)
        self.assertTrue(Maintenance.objects.filter(pk=self.maintenance.pk).exists())
        self.assertTrue(Accident.objects.filter(pk=self.accident.pk).exists())
        self.assertEqual(
            VehicleRetirementTask.objects.filter(car=self.car).count(),
            len(VehicleRetirementTask.TASK_CHOICES),
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('fleet@example.com', mail.outbox[0].to)

    def test_retired_vehicle_moves_from_active_list_to_history(self):
        self.car.status = Car.STATUS_SOLD
        self.car.retired_at = date(2026, 8, 12)
        self.car.final_odometer = 1000
        self.car.final_value = Decimal('10000.00')
        self.car.final_payment_date = date(2026, 8, 12)
        self.car.final_payment_source = 'Buyer'
        self.car.retirement_notes = 'Sold after replacement.'
        self.car.assigned_user = None
        self.car.save()

        self.client.force_login(self.admin)
        active_response = self.client.get(reverse('car_list'))
        history_response = self.client.get(reverse('vehicle_history'))
        self.assertNotContains(active_response, self.car.rego)
        self.assertContains(history_response, self.car.rego)

    def test_manager_only_sees_retired_vehicles_in_their_state(self):
        for car in (self.car, self.other_car):
            car.status = Car.STATUS_SOLD
            car.assigned_user = None
            car.save(update_fields=['status', 'assigned_user'])
        self.client.force_login(self.manager)
        response = self.client.get(reverse('vehicle_history'))
        self.assertContains(response, self.car.rego)
        self.assertNotContains(response, self.other_car.rego)

    def test_completing_retirement_task_records_actor_and_time(self):
        self.car.status = Car.STATUS_SOLD
        self.car.assigned_user = None
        self.car.save(update_fields=['status', 'assigned_user'])
        task = VehicleRetirementTask.objects.create(
            car=self.car, task_type='rego_refund'
        )
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse('vehicle_retirement_task_edit', args=[task.pk]),
            {'completed': 'on', 'notes': 'Refund submitted.'},
        )
        self.assertRedirects(response, reverse('car_detail', args=[self.car.pk]))
        task.refresh_from_db()
        self.assertTrue(task.completed)
        self.assertEqual(task.completed_by, self.manager)
        self.assertIsNotNone(task.completed_at)


class AdditionalAccessControlTests(ApplicationTestCase):

    def test_manager_filter_choices_are_limited_to_their_state(self):
        self.client.force_login(self.manager)

        tool_response = self.client.get(reverse('tool_list'))
        self.assertNotIn('VIC', list(tool_response.context['states']))

        car_response = self.client.get(reverse('car_list'))
        self.assertIn(self.car.rego, list(car_response.context['regos']))
        self.assertNotIn(self.other_car.rego, list(car_response.context['regos']))

        maintenance_response = self.client.get(reverse('maintenance_list'))
        self.assertNotIn(
            'Other Provider',
            list(maintenance_response.context['service_providers']),
        )

    def test_admin_dashboard_falls_back_to_username_for_assignment(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertContains(response, self.user.username)

    def test_manager_dashboard_falls_back_to_username_for_assignment(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('manager_dashboard'))
        self.assertContains(response, self.user.username)

    def test_manager_inventory_uses_username_and_hides_delete_action(self):
        self.client.force_login(self.manager)
        tool_response = self.client.get(reverse('manager_tools'))
        car_response = self.client.get(reverse('manager_cars'))
        self.assertContains(tool_response, self.user.username)
        self.assertNotContains(tool_response, reverse('tool_delete', args=[self.tool.pk]))
        self.assertContains(car_response, self.user.username)


class TransferLedgerTests(ApplicationTestCase):
    def setUp(self):
        super().setUp()
        self.second_tool = Tool.objects.create(
            internal_number='KE-SECOND', tool_name='radman', store='Online',
            state='NSW', assigned_user=self.user,
        )

    def test_admin_can_transfer_multiple_tools_in_one_immutable_batch(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('transfer_add'), {
            'from_user': self.user.pk,
            'to_user': self.manager.pk,
            'tools': [self.tool.pk, self.second_tool.pk],
            'date_of_transfer': '2026-08-12',
            'notes': 'Employee is going on leave.',
        })
        self.assertRedirects(response, reverse('transfer_list'))
        batch = TransferBatch.objects.get()
        self.assertEqual(batch.entries.count(), 2)
        self.tool.refresh_from_db()
        self.second_tool.refresh_from_db()
        self.assertEqual(self.tool.assigned_user, self.manager)
        self.assertEqual(self.second_tool.assigned_user, self.manager)
        entry = batch.entries.first()
        entry.asset_identifier = 'CHANGED'
        with self.assertRaises(ValidationError):
            entry.save()
        batch.notes = 'CHANGED'
        with self.assertRaises(ValidationError):
            batch.save()

    def test_loading_employee_assets_ignores_blank_warehouse_value(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('transfer_add'), {
            'from_user': self.user.pk,
            'from_location': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['source_user'], self.user)
        self.assertIsNone(response.context['source_location'])
        self.assertQuerySetEqual(
            response.context['form'].fields['tools'].queryset,
            [self.tool, self.second_tool],
            ordered=False,
        )

    def test_loading_source_rejects_malformed_ids_without_server_error(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('transfer_add'), {
            'from_user': 'not-a-number',
            'from_location': 'also-not-a-number',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['source_user'])
        self.assertIsNone(response.context['source_location'])

    def test_all_tools_can_move_to_a_real_warehouse(self):
        warehouse = CustodyLocation.objects.create(name='Sydney Warehouse', state='NSW')
        self.client.force_login(self.admin)
        response = self.client.post(reverse('transfer_add'), {
            'from_user': self.user.pk,
            'to_location': warehouse.pk,
            'transfer_all_tools': 'on',
            'date_of_transfer': '2026-08-12',
        })
        self.assertRedirects(response, reverse('transfer_list'))
        self.tool.refresh_from_db()
        self.second_tool.refresh_from_db()
        self.assertIsNone(self.tool.assigned_user)
        self.assertEqual(self.tool.custody_location, warehouse)
        self.assertEqual(self.second_tool.custody_location, warehouse)

    def test_reversal_creates_a_new_ledger_batch(self):
        warehouse = CustodyLocation.objects.create(name='Leave Warehouse', state='NSW')
        self.client.force_login(self.admin)
        self.client.post(reverse('transfer_add'), {
            'from_user': self.user.pk,
            'to_location': warehouse.pk,
            'tools': [self.tool.pk],
            'date_of_transfer': '2026-08-12',
        })
        original = TransferBatch.objects.get()
        response = self.client.post(reverse('transfer_reverse', args=[original.pk]))
        self.assertRedirects(response, reverse('transfer_list'))
        self.tool.refresh_from_db()
        self.assertEqual(self.tool.assigned_user, self.user)
        self.assertIsNone(self.tool.custody_location)
        self.assertEqual(TransferBatch.objects.count(), 2)
        self.assertEqual(original.reversal.entries.count(), 1)

    def test_destination_employee_cannot_receive_a_second_active_car(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('transfer_add'), {
            'from_user': self.user.pk,
            'to_user': self.other_user.pk,
            'car': self.car.pk,
            'date_of_transfer': '2026-08-12',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'to_user',
            'This employee already has an active vehicle.',
        )
        self.assertFalse(TransferBatch.objects.exists())

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        FLEET_MANAGER_EMAIL='fleet@example.com',
    )
    def test_cross_state_car_transfer_creates_tasks_and_email(self):
        vic_driver = User.objects.create_user(
            'vic_driver', password='Driver-pass-123', email='driver@example.com'
        )
        vic_driver.profile.state = 'VIC'
        vic_driver.profile.save()
        self.client.force_login(self.admin)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('transfer_add'), {
                'from_user': self.user.pk,
                'to_user': vic_driver.pk,
                'car': self.car.pk,
                'date_of_transfer': '2026-08-12',
            })
        self.assertRedirects(response, reverse('transfer_list'))
        self.car.refresh_from_db()
        self.assertEqual(self.car.assigned_user, vic_driver)
        self.assertEqual(self.car.state, 'VIC')
        self.assertTrue(TransferFollowUpTask.objects.filter(car=self.car, state='VIC').exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('fleet@example.com', mail.outbox[0].to)
        task = TransferFollowUpTask.objects.filter(car=self.car, state='VIC').first()
        task_response = self.client.post(
            reverse('transfer_follow_up_task_edit', args=[task.pk]),
            {'completed': 'on'},
        )
        self.assertRedirects(task_response, reverse('transfer_list'))
        task.refresh_from_db()
        self.assertTrue(task.completed)
        self.assertEqual(task.completed_by, self.admin)
        self.assertIsNotNone(task.completed_at)


class CompanyLocationTests(ApplicationTestCase):
    def setUp(self):
        super().setUp()
        self.location = CustodyLocation.objects.create(
            name='Sydney Office',
            location_type=CustodyLocation.TYPE_OFFICE,
            state='NSW',
            address='1 Test Street, Sydney',
            responsible_manager=self.manager,
        )

    def test_admin_can_create_warehouse(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('company_location_add'), {
            'name': 'Melbourne Warehouse',
            'location_type': CustodyLocation.TYPE_WAREHOUSE,
            'state': 'VIC',
            'address': '2 Warehouse Road, Melbourne',
            'responsible_manager': '',
            'active': 'on',
            'notes': 'Field tools storage.',
        })
        self.assertRedirects(response, reverse('company_location_list'))
        location = CustodyLocation.objects.get(name='Melbourne Warehouse')
        self.assertEqual(location.location_type, CustodyLocation.TYPE_WAREHOUSE)
        self.assertTrue(location.active)

    def test_manager_can_view_only_locations_in_their_state(self):
        CustodyLocation.objects.create(
            name='Melbourne Office', location_type='office', state='VIC'
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse('company_location_list'), {'status': 'all'})
        self.assertContains(response, self.location.name)
        self.assertNotContains(response, 'Melbourne Office')
        self.assertEqual(
            self.client.get(reverse('company_location_add')).status_code, 403
        )

    def test_location_profile_shows_current_assets_and_transfer_history(self):
        self.tool.assigned_user = None
        self.tool.custody_location = self.location
        self.tool.save(update_fields=['assigned_user', 'custody_location'])
        batch = TransferBatch.objects.create(
            from_user=self.user, to_location=self.location,
            date_of_transfer=date(2026, 8, 12), created_by=self.admin,
        )
        TransferLedgerEntry.objects.create(
            batch=batch, asset_type=TransferLedgerEntry.ASSET_TOOL,
            tool=self.tool, asset_identifier=self.tool.pk,
            from_user=self.user, to_location=self.location,
        )
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse('company_location_detail', args=[self.location.pk])
        )
        self.assertContains(response, self.tool.pk)
        self.assertContains(response, 'Recent custody movements')

    def test_location_with_assets_cannot_be_deactivated(self):
        self.tool.assigned_user = None
        self.tool.custody_location = self.location
        self.tool.save(update_fields=['assigned_user', 'custody_location'])
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('company_location_edit', args=[self.location.pk]),
            {
                'name': self.location.name,
                'location_type': self.location.location_type,
                'state': self.location.state,
                'address': self.location.address,
                'responsible_manager': self.manager.pk,
                'notes': '',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'active',
            'Transfer all active vehicles and tools before deactivating this location.',
        )
        self.location.refresh_from_db()
        self.assertTrue(self.location.active)

    def test_location_without_assets_can_be_deactivated(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('company_location_edit', args=[self.location.pk]),
            {
                'name': self.location.name,
                'location_type': self.location.location_type,
                'state': self.location.state,
                'address': self.location.address,
                'responsible_manager': self.manager.pk,
                'notes': '',
            },
        )
        self.assertRedirects(
            response, reverse('company_location_detail', args=[self.location.pk])
        )
        self.location.refresh_from_db()
        self.assertFalse(self.location.active)


class EmailAlertConfigurationTests(ApplicationTestCase):
    def _contact_data(self, **overrides):
        data = {
            'name': 'NSW State Alerts',
            'email': 'nsw.alerts@example.com',
            'responsibility': AlertContact.ROLE_STATE_MANAGER,
            'state': 'NSW',
            'is_primary': 'on',
            'categories': [
                AlertContact.CATEGORY_CALIBRATION,
                AlertContact.CATEGORY_CONTROLLED_TRANSFER,
            ],
            'linked_user': self.manager.pk,
            'enabled': 'on',
        }
        data.update(overrides)
        return data

    def test_admin_creates_audited_primary_state_mailbox(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('alert_contact_add'), self._contact_data()
        )
        self.assertRedirects(response, reverse('alert_contact_list'))
        contact = AlertContact.objects.get()
        self.assertEqual(contact.created_by, self.admin)
        self.assertEqual(contact.updated_by, self.admin)
        self.assertTrue(contact.is_primary)
        self.assertEqual(
            primary_state_manager_email(
                'NSW', AlertContact.CATEGORY_CONTROLLED_TRANSFER
            ),
            'nsw.alerts@example.com',
        )

    def test_manager_cannot_access_alert_configuration(self):
        self.client.force_login(self.manager)
        for route in ('alert_contact_list', 'alert_contact_add', 'notification_delivery_list'):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_second_primary_contact_for_state_is_rejected(self):
        AlertContact.objects.create(
            name='First NSW Manager', email='first@example.com',
            responsibility=AlertContact.ROLE_STATE_MANAGER, state='NSW',
            is_primary=True,
            categories=[AlertContact.CATEGORY_CONTROLLED_TRANSFER],
        )
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('alert_contact_add'),
            self._contact_data(email='second@example.com'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(AlertContact.objects.count(), 1)

    def test_non_state_contact_cannot_have_state_or_primary_flag(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('alert_contact_add'),
            self._contact_data(
                responsibility=AlertContact.ROLE_FLEET_MANAGER,
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'state',
            'State is only used for State Manager contacts.',
        )

    def test_category_and_enabled_status_control_recipient_resolution(self):
        AlertContact.objects.create(
            name='Fleet', email='fleet@example.com',
            responsibility=AlertContact.ROLE_FLEET_MANAGER,
            categories=[AlertContact.CATEGORY_VEHICLE_SERVICE], enabled=True,
        )
        AlertContact.objects.create(
            name='Disabled', email='disabled@example.com',
            responsibility=AlertContact.ROLE_FLEET_MANAGER,
            categories=[AlertContact.CATEGORY_VEHICLE_SERVICE], enabled=False,
        )
        self.assertEqual(
            alert_recipient_emails(
                AlertContact.ROLE_FLEET_MANAGER,
                AlertContact.CATEGORY_VEHICLE_SERVICE,
            ),
            ['fleet@example.com'],
        )
        self.assertEqual(
            alert_recipient_emails(
                AlertContact.ROLE_FLEET_MANAGER,
                AlertContact.CATEGORY_CALIBRATION,
            ),
            [],
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_delivery_history_sends_once_for_deduplication_key(self):
        delivery, sent = send_tracked_notification(
            event_type=AlertContact.CATEGORY_VEHICLE_SERVICE,
            related_object='TEST01', recipients=['Fleet@Example.com'],
            subject='Test service reminder', message='Test only',
            deduplication_key='service:TEST01:2026-08-12',
        )
        duplicate, duplicate_sent = send_tracked_notification(
            event_type=AlertContact.CATEGORY_VEHICLE_SERVICE,
            related_object='TEST01', recipients=['fleet@example.com'],
            subject='Test service reminder', message='Test only',
            deduplication_key='service:TEST01:2026-08-12',
        )
        delivery.refresh_from_db()
        self.assertTrue(sent)
        self.assertFalse(duplicate_sent)
        self.assertEqual(duplicate.pk, delivery.pk)
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_SENT)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_failed_delivery_is_visible_and_can_be_retried(self):
        with patch('tracking.notification_service.send_mail', side_effect=RuntimeError('SMTP unavailable')):
            delivery, sent = send_tracked_notification(
                event_type=AlertContact.CATEGORY_CALIBRATION,
                related_object='KE-TEST', recipients=['fleet@example.com'],
                subject='Calibration test', message='Test only',
                deduplication_key='calibration:KE-TEST:2026-08-12',
            )
        delivery.refresh_from_db()
        self.assertFalse(sent)
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_FAILED)
        self.assertIn('SMTP unavailable', delivery.failure_reason)

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('notification_delivery_retry', args=[delivery.pk])
        )
        self.assertRedirects(response, reverse('notification_delivery_list'))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.STATUS_SENT)
        self.assertEqual(delivery.attempt_count, 2)


class ControlledDeviceTests(ApplicationTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.location = CustodyLocation.objects.create(
            name='NSW Controlled Devices Office',
            location_type=CustodyLocation.TYPE_OFFICE,
            state='NSW',
        )

    def _controlled_tool(self, **overrides):
        values = {
            'internal_number': 'KE-CONTROLLED',
            'serial_number': 'SERIAL-CONTROLLED',
            'tool_name': 'otdr + charger + bag + port protector',
            'store': 'Online',
            'state': 'NSW',
            'is_controlled': True,
            'condition': Tool.CONDITION_GOOD,
            'photo': 'tool_photos/controlled-device.jpg',
            'assigned_user': self.user,
        }
        values.update(overrides)
        return Tool(**values)

    def test_existing_tools_remain_ordinary_with_safe_defaults(self):
        self.tool.refresh_from_db()
        self.assertFalse(self.tool.is_controlled)
        self.assertEqual(self.tool.condition, Tool.CONDITION_GOOD)
        self.assertFalse(self.tool.calibration_required)

    def test_controlled_device_requires_serial_photo_and_calibration_due_date(self):
        tool = self._controlled_tool(
            serial_number=None,
            photo=None,
            calibration_required=True,
            calibration_date=None,
        )
        with self.assertRaises(ValidationError) as raised:
            tool.full_clean()
        self.assertIn('serial_number', raised.exception.message_dict)
        self.assertIn('photo', raised.exception.message_dict)
        self.assertIn('calibration_date', raised.exception.message_dict)

    def test_valid_controlled_device_can_be_held_by_employee_or_location(self):
        employee_tool = self._controlled_tool()
        employee_tool.full_clean()
        location_tool = self._controlled_tool(
            internal_number='KE-CONTROLLED-2',
            serial_number='SERIAL-CONTROLLED-2',
            assigned_user=None,
            custody_location=self.location,
        )
        location_tool.full_clean()

    def test_tool_cannot_have_two_current_custodians(self):
        tool = self._controlled_tool(custody_location=self.location)
        with self.assertRaises(ValidationError) as raised:
            tool.full_clean()
        self.assertIn('__all__', raised.exception.message_dict)

    def test_only_admin_can_change_controlled_classification(self):
        self.client.force_login(self.manager)
        manager_response = self.client.get(reverse('tool_add'))
        self.assertTrue(manager_response.context['form'].fields['is_controlled'].disabled)
        self.assertQuerySetEqual(
            manager_response.context['form'].fields['custody_location'].queryset,
            [self.location],
        )
        self.client.force_login(self.admin)
        admin_response = self.client.get(reverse('tool_add'))
        self.assertFalse(admin_response.context['form'].fields['is_controlled'].disabled)

    def test_controlled_filter_and_badge_distinguish_devices(self):
        Tool.objects.create(
            internal_number='KE-CONTROLLED-LIST',
            serial_number='SERIAL-CONTROLLED-LIST',
            tool_name='radman', store='Online', state='NSW',
            is_controlled=True, assigned_user=self.user,
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('tool_list'), {'controlled': 'yes'})
        self.assertContains(response, 'KE-CONTROLLED-LIST')
        self.assertContains(response, 'Controlled')
        self.assertNotContains(response, self.tool.internal_number)


class ToolCatalogueTests(ApplicationTestCase):
    def test_existing_approved_choice_is_seeded(self):
        self.assertTrue(ToolCatalogueItem.objects.filter(name='radman').exists())

    def test_tool_form_uses_searchable_catalogue_input(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('tool_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'list="tool-catalogue-options"')
        self.assertContains(response, 'Start typing, for example PIM, OTDR, drill, or tool bag')
        self.assertContains(response, '<datalist id="tool-catalogue-options">')

    def test_admin_can_add_audited_catalogue_item(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('tool_catalogue_add'), {
            'name': 'PIM tester',
            'suggested_controlled': 'on',
            'suggested_calibration_required': 'on',
            'notes': 'Shared specialist device',
            'active': 'on',
        })
        self.assertRedirects(response, reverse('tool_catalogue_list'))
        item = ToolCatalogueItem.objects.get(name='PIM tester')
        self.assertEqual(item.created_by, self.admin)
        self.assertEqual(item.updated_by, self.admin)
        self.assertTrue(item.suggested_controlled)

    def test_case_and_spacing_duplicate_is_rejected(self):
        ToolCatalogueItem.objects.create(name='PIM tester')
        self.client.force_login(self.admin)
        response = self.client.post(reverse('tool_catalogue_add'), {
            'name': '  pim   TESTER  ', 'active': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertNotContains(response, 'Enter a tool or device type.')
        self.assertEqual(
            ToolCatalogueItem.objects.filter(name__iexact='PIM tester').count(), 1
        )

    def test_manager_cannot_manage_catalogue(self):
        self.client.force_login(self.manager)
        for route in ('tool_catalogue_list', 'tool_catalogue_add'):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(reverse(route)).status_code, 403)

    def test_inactive_catalogue_item_cannot_be_selected_for_new_tool(self):
        ToolCatalogueItem.objects.filter(name='radman').update(active=False)
        self.client.force_login(self.admin)
        response = self.client.post(reverse('tool_add'), {
            'internal_number': 'KE-INACTIVE-CATALOGUE',
            'tool_name': 'radman', 'brand': 'Test', 'store': 'Online',
            'state': 'NSW', 'quantity': 1,
            'condition': Tool.CONDITION_GOOD,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a valid choice')
        self.assertFalse(Tool.objects.filter(pk='KE-INACTIVE-CATALOGUE').exists())


class ToolProfileTests(ApplicationTestCase):
    def test_assigned_user_can_view_tool_profile_but_other_user_cannot(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('tool_detail', args=[self.tool.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.tool.internal_number)
        self.client.force_login(self.other_user)
        self.assertEqual(
            self.client.get(reverse('tool_detail', args=[self.tool.pk])).status_code,
            404,
        )

    def test_tool_profile_shows_controlled_identity_calibration_and_ledger(self):
        self.tool.is_controlled = True
        self.tool.serial_number = 'SERIAL-PROFILE'
        self.tool.calibration_required = True
        self.tool.calibration_date = date.today()
        self.tool.save(update_fields=[
            'is_controlled', 'serial_number', 'calibration_required',
            'calibration_date',
        ])
        batch = TransferBatch.objects.create(
            from_user=self.user, to_user=self.manager,
            date_of_transfer=date.today(), created_by=self.admin,
        )
        TransferLedgerEntry.objects.create(
            batch=batch, asset_type=TransferLedgerEntry.ASSET_TOOL,
            tool=self.tool, asset_identifier=self.tool.pk,
            from_user=self.user, to_user=self.manager,
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('tool_detail', args=[self.tool.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Controlled device')
        self.assertContains(response, 'SERIAL-PROFILE')
        self.assertContains(response, 'Due soon')
        self.assertContains(response, batch.source_label)
        self.assertContains(response, batch.destination_label)
        self.assertContains(response, str(batch.reference)[:8])


class MaintenanceWorkspaceTests(ApplicationTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.maintenance.invoice_number = 'INV-WORKSPACE'
        cls.maintenance.description = 'Replace worn brake pads and complete inspection.'
        cls.maintenance.odometer_reading = 12500
        cls.maintenance.total_cost = Decimal('275.50')
        cls.maintenance.save()
        cls.item = MaintenanceItem.objects.create(
            maintenance=cls.maintenance,
            item_type='parts',
            description='Brake pads',
            quantity=2,
            unit_cost=Decimal('100.00'),
        )

    def test_role_scoped_maintenance_profile_shows_summary_items_and_car_link(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('maintenance_detail', args=[self.maintenance.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.car.rego)
        self.assertContains(response, 'INV-WORKSPACE')
        self.assertContains(response, 'Brake pads')
        self.assertContains(response, '$200.00')
        self.assertContains(response, reverse('car_detail', args=[self.car.pk]))

        self.client.force_login(self.other_user)
        self.assertEqual(
            self.client.get(
                reverse('maintenance_detail', args=[self.maintenance.pk])
            ).status_code,
            404,
        )

    def test_maintenance_workspace_summary_and_filters_cover_full_queryset(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('maintenance_list'), {
            'rego': self.car.rego,
            'service_type': 'repair',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['maintenance_summary']['record_count'], 1)
        self.assertEqual(
            response.context['maintenance_summary']['total_cost'],
            Decimal('275.50'),
        )
        self.assertEqual(response.context['maintenance_summary']['invoice_count'], 1)
        self.assertContains(
            response, reverse('maintenance_detail', args=[self.maintenance.pk])
        )

    def test_car_profile_has_compact_linked_maintenance_summary(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('car_detail', args=[self.car.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['maintenance_record_count'], 1)
        self.assertEqual(response.context['maintenance_total_cost'], Decimal('275.50'))
        self.assertContains(response, 'Replace worn brake pads')
        self.assertContains(
            response, reverse('maintenance_detail', args=[self.maintenance.pk])
        )
        self.assertContains(
            response, f'{reverse("maintenance_list")}?rego={self.car.rego}'
        )

    def test_maintenance_list_queries_stay_flat_when_rows_have_items(self):
        self.client.force_login(self.admin)
        with CaptureQueriesContext(connection) as baseline:
            self.client.get(reverse('maintenance_list'))

        for index in range(5):
            record = Maintenance.objects.create(
                car=self.car,
                service_date=date(2026, 7, index + 1),
                service_type='repair',
                service_provider='Scaling Provider',
                description=f'Scaling record {index}',
                total_cost=Decimal('10.00'),
            )
            MaintenanceItem.objects.create(
                maintenance=record,
                item_type='parts',
                description=f'Part {index}',
                quantity=1,
                unit_cost=Decimal('10.00'),
            )

        with CaptureQueriesContext(connection) as scaled:
            self.client.get(reverse('maintenance_list'))

        self.assertLessEqual(len(scaled), len(baseline) + 1)

    def test_maintenance_documents_require_login_and_object_permission(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(
            MEDIA_ROOT=media_root
        ):
            self.maintenance.documents = SimpleUploadedFile(
                'invoice.pdf', b'%PDF-private-test', content_type='application/pdf'
            )
            self.maintenance.save(update_fields=['documents'])
            url = reverse('maintenance_document', args=[self.maintenance.pk])

            anonymous = self.client.get(url)
            self.assertEqual(anonymous.status_code, 302)

            self.client.force_login(self.other_user)
            self.assertEqual(self.client.get(url).status_code, 404)

            self.client.force_login(self.admin)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertIn('attachment', response['Content-Disposition'])
            response.close()


class BusinessWorkflowTests(ApplicationTestCase):
    def test_web_tool_import_creates_a_tool(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile(
            'tools.csv',
            b'internal_number,tool_name,state,store\nKE-IMPORTED,radman,NSW,Online\n',
            content_type='text/csv',
        )
        response = self.client.post(reverse('import'), {
            'file': upload,
            'type': 'Tool',
            'format': 'csv',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))
        imported = Tool.objects.get(pk='KE-IMPORTED')
        self.assertEqual(imported.state, 'NSW')
        self.assertEqual(imported.store, 'Online')

    def test_import_rejects_extension_format_mismatch(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile(
            'tools.xlsx',
            b'internal_number,tool_name,state\nKE-WRONG,radman,NSW\n',
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response = self.client.post(reverse('import'), {
            'file': upload,
            'type': 'Tool',
            'format': 'csv',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'requires a .csv file')
        self.assertFalse(Tool.objects.filter(pk='KE-WRONG').exists())

    def test_tool_import_rolls_back_every_row_when_one_row_is_invalid(self):
        self.client.force_login(self.admin)
        upload = SimpleUploadedFile(
            'tools.csv',
            (
                b'internal_number,tool_name,state,store\n'
                b'KE-ROLLBACK,radman,NSW,Online\n'
                b'KE-INVALID,radman,INVALID,Online\n'
            ),
            content_type='text/csv',
        )
        response = self.client.post(reverse('import'), {
            'file': upload,
            'type': 'Tool',
            'format': 'csv',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No rows were saved')
        self.assertFalse(Tool.objects.filter(pk='KE-ROLLBACK').exists())
        self.assertFalse(Tool.objects.filter(pk='KE-INVALID').exists())

    def test_only_admin_can_create_transfers(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse('transfer_add'), {
            'from_user': self.user.pk,
            'to_user': self.manager.pk,
            'tools': [self.tool.pk],
            'date_of_transfer': '2026-01-02',
        })
        self.assertEqual(response.status_code, 403)
        self.tool.refresh_from_db()
        self.assertEqual(self.tool.assigned_user, self.user)

    def test_maintenance_item_total_uses_decimal_arithmetic(self):
        item = MaintenanceItem(
            maintenance=self.maintenance,
            description='Oil',
            quantity=1.5,
            unit_cost=Decimal('20.00'),
        )
        self.assertEqual(item.total_cost, Decimal('30.000'))

    def test_regular_service_advances_vehicle_service_state(self):
        Maintenance.objects.create(
            car=self.car,
            service_date=date(2026, 2, 1),
            odometer_reading=12000,
            service_type='regular',
            service_provider='Test Provider',
        )
        self.car.refresh_from_db()
        self.assertEqual(self.car.current_odometer, 12000)
        self.assertEqual(self.car.last_service_km, 12000)
        self.assertEqual(self.car.service_odometer, 22000)

    def test_maintenance_formset_deletes_existing_item(self):
        item = MaintenanceItem.objects.create(
            maintenance=self.maintenance,
            description='Remove me',
            quantity=1,
            unit_cost=Decimal('10.00'),
        )
        self.client.force_login(self.manager)
        response = self.client.post(reverse('maintenance_edit', args=[self.maintenance.pk]), {
            'car': self.car.pk,
            'service_date': '2026-01-01',
            'odometer_reading': 0,
            'service_type': 'repair',
            'invoice_number': '',
            'service_provider': 'Test Provider',
            'description': 'Test maintenance record',
            'total_cost': '0.00',
            'items-TOTAL_FORMS': '1',
            'items-INITIAL_FORMS': '1',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
            'items-0-id': str(item.pk),
            'items-0-maintenance': str(self.maintenance.pk),
            'items-0-description': item.description,
            'items-0-item_type': 'parts',
            'items-0-quantity': '1',
            'items-0-unit_cost': '10.00',
            'items-0-DELETE': 'on',
        })
        if response.status_code != 302:
            self.fail(
                f"Maintenance form errors: {response.context['form'].errors}; "
                f"formset errors: {response.context['item_formset'].errors}; "
                f"non-form errors: {response.context['item_formset'].non_form_errors()}"
            )
        self.assertRedirects(response, reverse('maintenance_list'))
        self.assertFalse(MaintenanceItem.objects.filter(pk=item.pk).exists())

    def test_pdf_auto_create_uses_current_car_fields(self):
        invoice = InvoiceData(
            invoice_number='INV-TEST',
            date=date(2026, 1, 1),
            vehicle_rego='PDF001',
            vehicle_vin='VIN-PDF-001',
            items=[InvoiceItem(description='Service')],
        )
        service = MaintenanceInvoiceService()
        car = service._get_or_create_car(invoice, auto_create=True)
        self.assertEqual(car.rego, 'PDF001')

    def test_pdf_brake_and_tire_items_map_to_valid_service_type(self):
        service = MaintenanceInvoiceService()
        for description in ('Brake replacement', 'New tyre'):
            with self.subTest(description=description):
                invoice = InvoiceData(
                    invoice_number='INV-TYPE',
                    date=date(2026, 1, 1),
                    items=[InvoiceItem(description=description)],
                )
                self.assertEqual(service._determine_service_type(invoice), 'repair')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_calibration_reminder_uses_tool_name_and_skips_missing_email(self):
        self.user.email = 'regular@example.com'
        self.user.save()
        self.tool.calibration_date = date.today()
        self.tool.save()
        send_calibration_reminders()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.tool.tool_name, mail.outbox[0].subject)


class ScheduledReminderReliabilityTests(ApplicationTestCase):
    """A failing recipient must not stop the rest of a scheduled batch."""

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_calibration_batch_continues_after_a_failing_recipient(self):
        self.user.email = 'regular@example.com'
        self.user.save()
        self.tool.calibration_date = date.today()
        self.tool.save()

        second_holder = User.objects.create_user(
            username='second-holder', password='pw', email='second@example.com',
        )
        second_holder.profile.access_level = 'User'
        second_holder.profile.state = 'NSW'
        second_holder.profile.save()
        Tool.objects.create(
            internal_number='KE-REMINDER-2',
            tool_name='Second Tester',
            store='Online',
            state='NSW',
            calibration_date=date.today(),
            assigned_user=second_holder,
        )

        # Fail only the first send; the task must still deliver the second.
        with patch('tracking.tasks.send_mail') as send_mail_mock:
            send_mail_mock.side_effect = [OSError('smtp refused'), None]
            result = send_calibration_reminders()

        self.assertEqual(send_mail_mock.call_count, 2)
        self.assertEqual(result, {'sent': 1, 'failed': 1})

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_maintenance_schedule_flags_due_by_date_and_by_distance(self):
        from .tasks import check_maintenance_schedule

        self.user.email = 'regular@example.com'
        self.user.save()

        # Due by distance travelled since the last service.
        self.car.assigned_user = self.user
        self.car.next_service_date = None
        self.car.last_service_km = 1000
        self.car.service_interval_km = 5000
        self.car.save()
        OdometerReading.objects.create(
            car=self.car, reading_date=date.today(), reading_value=9000,
        )

        result = check_maintenance_schedule()

        self.assertEqual(result['due'], 1)
        self.assertEqual(result['sent'], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.car.rego, mail.outbox[0].subject)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_maintenance_schedule_ignores_vehicle_that_is_not_due(self):
        from .tasks import check_maintenance_schedule

        self.user.email = 'regular@example.com'
        self.user.save()
        self.car.assigned_user = self.user
        self.car.next_service_date = date.today() + timedelta(days=90)
        self.car.last_service_km = 1000
        self.car.service_interval_km = 5000
        self.car.save()
        OdometerReading.objects.create(
            car=self.car, reading_date=date.today(), reading_value=1200,
        )

        result = check_maintenance_schedule()

        self.assertEqual(result['due'], 0)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_retirement_reminder_is_tracked_and_deduplicated_daily(self):
        AlertContact.objects.create(
            name='Fleet', email='fleet@example.com',
            responsibility=AlertContact.ROLE_FLEET_MANAGER,
            categories=[AlertContact.CATEGORY_RETIREMENT], enabled=True,
        )
        self.car.status = Car.STATUS_SOLD
        self.car.assigned_user = None
        self.car.save(update_fields=['status', 'assigned_user'])
        VehicleRetirementTask.objects.create(
            car=self.car, task_type='rego_refund'
        )

        first = send_retirement_task_reminders()
        second = send_retirement_task_reminders()

        self.assertEqual(first['sent'], 1)
        self.assertEqual(second['sent'], 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            NotificationDelivery.objects.filter(
                event_type=AlertContact.CATEGORY_RETIREMENT
            ).count(),
            1,
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_transfer_follow_up_reminder_uses_tracked_delivery(self):
        AlertContact.objects.create(
            name='Fleet', email='fleet@example.com',
            responsibility=AlertContact.ROLE_FLEET_MANAGER,
            categories=[AlertContact.CATEGORY_CONTROLLED_TRANSFER], enabled=True,
        )
        batch = TransferBatch.objects.create(
            from_user=self.user, to_user=self.other_user,
            date_of_transfer=date.today(), created_by=self.admin,
        )
        TransferFollowUpTask.objects.create(
            batch=batch, car=self.car, state='VIC',
            description='Change registration to VIC.',
        )

        result = send_transfer_follow_up_reminders()

        self.assertEqual(result['tasks'], 1)
        self.assertEqual(result['sent'], 1)
        self.assertEqual(len(mail.outbox), 1)


class AnalyticsAndAccidentValidationTests(ApplicationTestCase):
    TODAY = date(2026, 8, 11)

    def setUp(self):
        super().setUp()
        Maintenance.objects.create(
            car=self.car,
            service_date=date(2026, 8, 5),
            service_type='repair',
            service_provider='August Provider',
            total_cost=Decimal('100.00'),
        )
        Maintenance.objects.create(
            car=self.car,
            service_date=date(2026, 7, 20),
            service_type='repair',
            service_provider='July Provider',
            total_cost=Decimal('50.00'),
        )
        Maintenance.objects.create(
            car=self.car,
            service_date=date(2026, 8, 20),
            service_type='repair',
            service_provider='Future Provider',
            total_cost=Decimal('999.00'),
        )
        Accident.objects.create(
            car=self.car,
            driver=self.user,
            accident_date=date(2026, 8, 6),
            accident_excess=Decimal('25.00'),
            via_insurance=False,
        )
        Accident.objects.create(
            car=self.car,
            driver=self.user,
            accident_date=date(2026, 7, 21),
            accident_excess=Decimal('10.00'),
            via_insurance=False,
        )
        Accident.objects.create(
            car=self.car,
            driver=self.user,
            accident_date=date(2026, 8, 20),
            accident_excess=Decimal('999.00'),
            via_insurance=False,
        )

    @patch('tracking.views.timezone.localdate', return_value=TODAY)
    def test_analytics_uses_calendar_ytd_and_excludes_future_records(self, _):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('fleet_analytics'), {'rego': self.car.rego})
        self.assertEqual(response.context['total_maintenance_cost'], Decimal('150.00'))
        self.assertEqual(response.context['total_accident_cost'], Decimal('35.00'))
        self.assertEqual(response.context['total_fleet_cost'], Decimal('185.00'))

        maintenance = json.loads(response.context['monthly_maintenance_costs'])
        accidents = json.loads(response.context['monthly_accident_costs'])
        self.assertEqual(maintenance[6], 50.0)
        self.assertEqual(maintenance[7], 100.0)
        self.assertEqual(accidents[6], 10.0)
        self.assertEqual(accidents[7], 25.0)
        self.assertEqual(maintenance[8:], [0.0, 0.0, 0.0, 0.0])
        self.assertContains(response, 'Accident Cost (YTD)')
        self.assertNotContains(response, 'Fuel Cost (YTD)')

    @patch('tracking.views.timezone.localdate', return_value=TODAY)
    def test_analytics_totals_are_correct_across_multiple_vehicles(self, _):
        """Aggregation must sum the whole visible fleet, not just one vehicle."""
        Maintenance.objects.create(
            car=self.other_car,
            service_date=date(2026, 8, 6),
            service_type='repair',
            service_provider='Second Vehicle Provider',
            total_cost=Decimal('40.00'),
        )
        Accident.objects.create(
            car=self.other_car,
            driver=self.user,
            accident_date=date(2026, 8, 6),
            accident_excess=Decimal('5.00'),
            via_insurance=False,
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('fleet_analytics'))

        # self.car contributes 150 + 35; other_car contributes 40 + 5.
        self.assertEqual(response.context['total_maintenance_cost'], Decimal('190.00'))
        self.assertEqual(response.context['total_accident_cost'], Decimal('40.00'))
        self.assertEqual(response.context['total_fleet_cost'], Decimal('230.00'))

    @patch('tracking.views.timezone.localdate', return_value=TODAY)
    def test_analytics_query_count_does_not_grow_with_fleet_size(self, _):
        """Analytics must aggregate in the database rather than per vehicle."""
        self.client.force_login(self.admin)

        with CaptureQueriesContext(connection) as baseline:
            self.client.get(reverse('fleet_analytics'))
        baseline_count = len(baseline)

        # Add more vehicles with their own cost records.
        for index in range(5):
            extra_car = Car.objects.create(
                rego=f'QRY{index:03d}',
                rego_expiry_date=date(2027, 1, 1),
                state='NSW',
                make='Toyota',
                model='Hilux',
                vin_number=f'VINQUERY{index:03d}',
            )
            Maintenance.objects.create(
                car=extra_car,
                service_date=date(2026, 8, 6),
                service_type='repair',
                service_provider='Bulk Provider',
                total_cost=Decimal('10.00'),
            )

        with CaptureQueriesContext(connection) as scaled:
            self.client.get(reverse('fleet_analytics'))

        # Five extra vehicles previously added dozens of queries via
        # per-vehicle get_total_costs() calls. Aggregation keeps it flat.
        self.assertLessEqual(len(scaled), baseline_count + 2)

    @patch('tracking.views.timezone.localdate', return_value=TODAY)
    def test_report_query_count_does_not_grow_with_fleet_size(self, _):
        self.client.force_login(self.admin)
        report_url = reverse('generate_report')
        params = {'type': 'csv', 'period': 'monthly'}

        with CaptureQueriesContext(connection) as baseline:
            self.client.get(report_url, params)

        for index in range(5):
            extra_car = Car.objects.create(
                rego=f'RPT{index:03d}',
                rego_expiry_date=date(2027, 1, 1),
                state='NSW',
                make='Ford',
                model='Ranger',
                vin_number=f'VINREPORT{index:03d}',
            )
            Maintenance.objects.create(
                car=extra_car,
                service_date=date(2026, 8, 6),
                service_type='regular',
                service_provider='Report Provider',
                total_cost=Decimal('10.00'),
            )
            FuelRecord.objects.create(
                car=extra_car, date=date(2026, 8, 1), odometer=1000,
                liters=Decimal('40.00'), cost_per_liter=Decimal('2.00'),
                total_cost=Decimal('0.00'), fuel_type='diesel', full_tank=True,
            )
            FuelRecord.objects.create(
                car=extra_car, date=date(2026, 8, 8), odometer=1500,
                liters=Decimal('45.00'), cost_per_liter=Decimal('2.00'),
                total_cost=Decimal('0.00'), fuel_type='diesel', full_tank=True,
            )

        with CaptureQueriesContext(connection) as scaled:
            response = self.client.get(report_url, params)

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(scaled), len(baseline) + 1)

    def test_car_fuel_efficiency_uses_one_query_and_previous_fill(self):
        FuelRecord.objects.create(
            car=self.car, date=date(2026, 7, 1), odometer=1000,
            liters=Decimal('40.00'), cost_per_liter=Decimal('2.00'),
            total_cost=Decimal('0.00'), fuel_type='diesel', full_tank=True,
        )
        FuelRecord.objects.create(
            car=self.car, date=date(2026, 7, 8), odometer=1500,
            liters=Decimal('45.00'), cost_per_liter=Decimal('2.00'),
            total_cost=Decimal('0.00'), fuel_type='diesel', full_tank=True,
        )
        FuelRecord.objects.create(
            car=self.car, date=date(2026, 7, 15), odometer=2000,
            liters=Decimal('50.00'), cost_per_liter=Decimal('2.00'),
            total_cost=Decimal('0.00'), fuel_type='diesel', full_tank=True,
        )

        with CaptureQueriesContext(connection) as queries:
            efficiency = self.car.get_fuel_efficiency(last_n_records=5)

        self.assertEqual(len(queries), 1)
        self.assertEqual(efficiency['current'], Decimal('10.00'))
        self.assertEqual(efficiency['previous'], Decimal('9.00'))

    @patch('tracking.views.timezone.localdate', return_value=TODAY)
    def test_monthly_csv_matches_dashboard_period_and_vehicle_filter(self, _):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('generate_report'), {
            'type': 'csv', 'period': 'monthly', 'rego': self.car.rego,
        })
        content = response.content.decode('utf-8')
        self.assertIn('Period: 2026-08-01 to 2026-08-11', content)
        self.assertIn('Total Maintenance Cost: $100.00', content)
        self.assertIn('Total Accident Cost: $25.00', content)
        self.assertIn('Total Fleet Cost: $125.00', content)
        self.assertIn(self.car.rego, content)
        self.assertNotIn(self.other_car.rego, content)
        self.assertNotIn('$999.00', content)

    @patch('tracking.views.timezone.localdate', return_value=TODAY)
    def test_yearly_excel_matches_calendar_year_totals(self, _):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('generate_report'), {
            'type': 'excel', 'period': 'yearly', 'rego': self.car.rego,
        })
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        worksheet = workbook.active
        self.assertEqual(worksheet['A2'].value, 'Period: 2026-01-01 to 2026-08-11')
        self.assertEqual(worksheet['A3'].value, 'Total Maintenance Cost: $150.00')
        self.assertEqual(worksheet['A5'].value, 'Total Accident Cost: $35.00')
        self.assertEqual(worksheet['A6'].value, 'Total Fleet Cost: $185.00')

    def test_report_rejects_unknown_format_and_period(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse('generate_report'), {'type': 'pdf'}).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                reverse('generate_report'), {'type': 'csv', 'period': 'decade'}
            ).status_code,
            400,
        )

    @patch('tracking.forms.timezone.localdate', return_value=TODAY)
    def test_accident_form_rejects_future_negative_and_inconsistent_values(self, _):
        from tracking.forms import AccidentForm

        future_form = AccidentForm(data={
            'car': self.car.pk,
            'accident_date': '2026-08-12',
            'driver': self.user.pk,
            'accident_excess': '-1.00',
            'via_insurance': 'on',
            'insurance_company': '',
            'claim_number': '',
            'description': '',
            'location': '',
        })
        self.assertFalse(future_form.is_valid())
        self.assertIn('accident_date', future_form.errors)
        self.assertIn('accident_excess', future_form.errors)
        self.assertIn('insurance_company', future_form.errors)

        contradictory_form = AccidentForm(data={
            'car': self.car.pk,
            'accident_date': '2026-08-10',
            'driver': self.user.pk,
            'accident_excess': '25.00',
            'insurance_company': 'Should be cleared',
            'claim_number': 'CLAIM-1',
            'description': '',
            'location': '',
        })
        self.assertFalse(contradictory_form.is_valid())
        self.assertIn('via_insurance', contradictory_form.errors)

    @patch('tracking.forms.timezone.localdate', return_value=TODAY)
    def test_regular_user_is_recorded_as_driver(self, _):
        self.client.force_login(self.user)
        response = self.client.post(reverse('accident_add'), {
            'car': self.car.pk,
            'accident_date': '2026-08-10',
            'driver': '',
            'accident_excess': '40.00',
            'description': 'User report',
            'location': 'Depot',
            'insurance_company': '',
            'claim_number': '',
        })
        self.assertRedirects(response, reverse('accident_list'))
        created = Accident.objects.get(description='User report')
        self.assertEqual(created.driver, self.user)

    def test_nsw_manager_can_select_driver_from_another_nsw_subdivision(self):
        nsw_special = User.objects.create_user('nsw_special')
        nsw_special.profile.state = 'NSW-Special'
        nsw_special.profile.save()
        self.client.force_login(self.manager)
        response = self.client.get(reverse('accident_add'))
        self.assertIn(nsw_special, response.context['form'].fields['driver'].queryset)

    def test_accident_list_shows_filtered_recorded_cost(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('accident_list'))
        self.assertEqual(response.context['total_accident_cost'], Decimal('1034.00'))

    def test_accident_total_covers_every_page_not_just_the_visible_one(self):
        """The recorded total must not shrink once the list paginates."""
        page_size = AccidentListView.paginate_by
        baseline = Accident.objects.filter(car__assigned_user=self.user).aggregate(
            total=Sum('accident_excess')
        )['total'] or Decimal('0.00')

        # Push the list past a single page.
        for _ in range(page_size):
            Accident.objects.create(
                car=self.car,
                driver=self.user,
                accident_date=date(2026, 8, 1),
                accident_excess=Decimal('1.00'),
                via_insurance=False,
            )
        expected = baseline + Decimal(page_size)

        self.client.force_login(self.user)
        response = self.client.get(reverse('accident_list'))

        self.assertTrue(response.context['is_paginated'])
        self.assertEqual(len(response.context['accidents']), page_size)
        self.assertEqual(response.context['total_accident_cost'], expected)


class LegacyCarImportTests(TestCase):
    def test_invalid_optional_purchase_fields_are_reported_and_omitted(self):
        dataframe = pd.DataFrame([{
            'Rego': 'LEGACY01',
            'state': 'NSW',
            'vin': 'VIN-LEGACY-01',
            'Description of vehicle': 'Toyota Corolla',
            'inv. date': 'not-a-date',
            'purchase price': 'not-a-price',
        }])
        output = StringIO()

        with tempfile.NamedTemporaryFile(suffix='.xlsx') as import_file:
            with (
                patch(
                    'tracking.management.commands.import_koinonia_cars.pd.read_excel',
                    return_value=dataframe,
                ),
                patch('builtins.input', return_value='y'),
            ):
                call_command(
                    'import_koinonia_cars', import_file.name, stdout=output
                )

        car = Car.objects.get(rego='LEGACY01')
        self.assertIsNone(car.purchase_date)
        self.assertIsNone(car.purchase_price)
        self.assertIn('invalid purchase date', output.getvalue())
        self.assertIn('invalid purchase price', output.getvalue())

    def test_fallback_partial_name_match_assigns_the_only_user(self):
        driver = User.objects.create_user(
            'legacy_driver', first_name='Alexandra', last_name='Miller'
        )

        from tracking.management.commands.import_koinonia_cars import Command

        self.assertEqual(Command().find_user('xand'), driver)


class PDFInvoiceImportWorkflowTests(ApplicationTestCase):
    def setUp(self):
        super().setUp()
        self._media_directory = tempfile.TemporaryDirectory()
        self._media_override = override_settings(
            MEDIA_ROOT=self._media_directory.name
        )
        self._media_override.enable()

    def tearDown(self):
        self._media_override.disable()
        self._media_directory.cleanup()
        super().tearDown()

    @staticmethod
    def _pdf_upload(name='invoice.pdf'):
        stream = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.write(stream)
        return SimpleUploadedFile(
            name, stream.getvalue(), content_type='application/pdf'
        )

    def _invoice(self, **overrides):
        values = {
            'invoice_number': 'PDF-100',
            'date': date(2026, 8, 1),
            'vehicle_rego': self.car.rego,
            'vehicle_vin': self.car.vin_number,
            'odometer_reading': 12500,
            'service_provider': 'Example Auto Pty Ltd',
            'subtotal': Decimal('100.00'),
            'tax_amount': Decimal('10.00'),
            'total_cost': Decimal('110.00'),
            'items': [InvoiceItem(
                description='Scheduled service',
                quantity=1,
                unit_cost=Decimal('100.00'),
                item_type='labor',
            )],
            'confidence': {
                'invoice_number': 'high', 'date': 'high', 'vehicle': 'high',
                'odometer': 'high', 'service_provider': 'high', 'items': 'high',
                'subtotal': 'high', 'tax': 'high', 'total': 'high',
            },
        }
        values.update(overrides)
        return InvoiceData(**values)

    def _preview(self, invoice=None):
        with patch.object(
            PDFInvoiceParser, 'parse_pdf', return_value=invoice or self._invoice()
        ):
            return self.client.post(reverse('pdf_invoice_import'), {
                'action': 'preview',
                'invoice_file': self._pdf_upload(),
            })

    def test_regular_user_cannot_access_pdf_invoice_import(self):
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.get(reverse('pdf_invoice_import')).status_code, 403
        )

    def test_non_pdf_upload_is_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('pdf_invoice_import'), {
            'action': 'preview',
            'invoice_file': SimpleUploadedFile(
                'invoice.pdf', b'not a pdf', content_type='application/pdf'
            ),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not a valid PDF document')
        self.assertFalse(Maintenance.objects.filter(invoice_number='PDF-100').exists())

    def test_preview_shows_financial_details_without_saving(self):
        self.client.force_login(self.admin)
        response = self._preview()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PDF-100')
        self.assertContains(response, 'Example Auto Pty Ltd')
        self.assertContains(response, '$110.00')
        self.assertContains(response, '$10.00')
        self.assertNotContains(
            response,
            'The extracted line items do not add up to the invoice subtotal.',
        )
        self.assertFalse(Maintenance.objects.filter(invoice_number='PDF-100').exists())

    def test_confirm_creates_transactional_record_items_and_document(self):
        self.client.force_login(self.admin)
        invoice = self._invoice()
        with patch.object(PDFInvoiceParser, 'parse_pdf', return_value=invoice):
            preview = self.client.post(reverse('pdf_invoice_import'), {
                'action': 'preview',
                'invoice_file': self._pdf_upload(),
            })
            token = preview.context['confirm_form'].initial['pending_token']
            response = self.client.post(reverse('pdf_invoice_import'), {
                'action': 'confirm',
                'pending_token': token,
                'confirm_details': 'on',
            })

        self.assertRedirects(response, reverse('maintenance_list'))
        maintenance = Maintenance.objects.get(invoice_number='PDF-100')
        self.assertEqual(maintenance.car, self.car)
        self.assertEqual(maintenance.total_cost, Decimal('110.00'))
        self.assertEqual(maintenance.items.count(), 1)
        self.assertTrue(maintenance.documents.name.endswith('.pdf'))
        self.assertNotIn(
            'pending_pdf_invoice_import', self.client.session
        )

    def test_duplicate_invoice_is_blocked_during_preview(self):
        Maintenance.objects.create(
            car=self.car,
            invoice_number='PDF-100',
            service_provider='Existing',
        )
        self.client.force_login(self.admin)
        response = self._preview()
        self.assertContains(response, 'has already been imported')
        self.assertFalse(response.context['can_confirm'])
        self.assertEqual(Maintenance.objects.filter(invoice_number='PDF-100').count(), 1)

    def test_tampered_confirmation_token_cannot_save(self):
        self.client.force_login(self.admin)
        self._preview()
        with patch.object(PDFInvoiceParser, 'parse_pdf', return_value=self._invoice()):
            response = self.client.post(reverse('pdf_invoice_import'), {
                'action': 'confirm',
                'pending_token': 'tampered-token',
                'confirm_details': 'on',
            })
        self.assertRedirects(response, reverse('pdf_invoice_import'))
        self.assertFalse(Maintenance.objects.filter(invoice_number='PDF-100').exists())

    def test_manager_cannot_import_invoice_for_another_state(self):
        self.client.force_login(self.manager)
        response = self._preview(self._invoice(
            vehicle_rego=self.other_car.rego,
            vehicle_vin=self.other_car.vin_number,
        ))
        self.assertContains(
            response, 'was not found among the vehicles you can manage'
        )
        self.assertFalse(response.context['can_confirm'])

    def test_financial_summary_does_not_confuse_subtotal_with_total(self):
        invoice = self._invoice(total_cost=Decimal('321.40'))
        text = 'Subtotal $321.40\nGST $32.14\nTotal $353.54'
        result = PDFInvoiceParser()._add_preview_metadata(invoice, text)
        self.assertEqual(result.subtotal, Decimal('321.40'))
        self.assertEqual(result.tax_amount, Decimal('32.14'))
        self.assertEqual(result.total_cost, Decimal('353.54'))


class VehicleMonitoringAndSpecialMaintenanceTests(ApplicationTestCase):
    PNG = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
    )

    def setUp(self):
        super().setUp()
        self.car.current_odometer = 1000
        self.car.save(update_fields=['current_odometer'])

    def _image(self, name='evidence.png'):
        return SimpleUploadedFile(name, self.PNG, content_type='image/png')

    def test_any_employee_can_use_exact_vehicle_qr_without_changing_custody(self):
        self.client.force_login(self.other_user)
        response = self.client.post(reverse('vehicle_qr_entry', args=[self.car.qr_token]), {
            'odometer': 1100,
            'confirm_vehicle': 'on',
        })
        self.assertRedirects(response, reverse('user_dashboard'))
        reading = OdometerReading.objects.get(
            car=self.car, reading_value=1100, source=OdometerReading.SOURCE_QR
        )
        self.assertEqual(reading.submitted_by, self.other_user)
        self.assertEqual(reading.review_status, OdometerReading.STATUS_ACCEPTED)
        self.car.refresh_from_db()
        self.assertEqual(self.car.current_odometer, 1100)
        self.assertEqual(self.car.assigned_user, self.user)

    def test_qr_label_is_role_scoped_and_returns_a_png(self):
        self.client.force_login(self.manager)
        label = self.client.get(reverse('vehicle_qr_label', args=[self.car.pk]))
        image = self.client.get(reverse('vehicle_qr_code', args=[self.car.pk]))
        self.assertEqual(label.status_code, 200)
        self.assertContains(label, str(self.car.qr_token))
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image['Content-Type'], 'image/png')
        self.assertTrue(image.content.startswith(b'\x89PNG'))

        self.client.force_login(self.other_user)
        self.assertEqual(
            self.client.get(reverse('vehicle_qr_code', args=[self.car.pk])).status_code,
            404,
        )

    def test_fuel_requires_receipt_and_creates_linked_record(self):
        self.client.force_login(self.user)
        url = reverse('vehicle_qr_entry', args=[self.car.qr_token])
        data = {
            'odometer': 1100, 'confirm_vehicle': 'on', 'include_fuel': 'on',
            'liters': '20.00', 'cost_per_liter': '2.00',
            'fuel_type': 'diesel', 'full_tank': 'on',
        }
        response = self.client.post(url, data)
        self.assertContains(response, 'required for a fuel purchase')
        self.assertFalse(FuelRecord.objects.filter(car=self.car).exists())
        data['receipt'] = self._image('receipt.png')
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse('user_dashboard'))
        fuel = FuelRecord.objects.get(car=self.car)
        self.assertEqual(fuel.submitted_by, self.user)
        self.assertIsNotNone(fuel.odometer_reading)
        self.assertTrue(fuel.receipt.name.startswith('fuel_receipts/'))
        self.assertTrue(fuel.receipt.name.endswith('.jpg'))
        duplicate = self.client.post(url, {
            **{key: value for key, value in data.items() if key != 'receipt'},
            'receipt': self._image('second-receipt.png'),
        })
        self.assertContains(duplicate, 'appears to duplicate a fuel entry')
        self.assertEqual(FuelRecord.objects.filter(car=self.car).count(), 1)

    def test_suspicious_reading_requires_photo_and_review_before_car_update(self):
        self.client.force_login(self.user)
        url = reverse('vehicle_qr_entry', args=[self.car.qr_token])
        response = self.client.post(url, {
            'odometer': 7001, 'confirm_vehicle': 'on'
        })
        self.assertContains(response, 'Add a dashboard photograph for review')
        self.assertFalse(OdometerReading.objects.filter(reading_value=7001).exists())
        response = self.client.post(url, {
            'odometer': 7001, 'confirm_vehicle': 'on',
            'odometer_photo': self._image(),
        })
        self.assertRedirects(response, reverse('user_dashboard'))
        reading = OdometerReading.objects.get(reading_value=7001)
        self.assertEqual(reading.review_status, OdometerReading.STATUS_PENDING)
        self.car.refresh_from_db()
        self.assertEqual(self.car.current_odometer, 1000)

        self.client.force_login(self.manager)
        response = self.client.post(reverse('odometer_review', args=[reading.pk]), {
            'decision': 'accept', 'review_notes': 'Photo confirmed',
        })
        self.assertRedirects(response, reverse('odometer_review_list'))
        self.car.refresh_from_db()
        self.assertEqual(self.car.current_odometer, 7001)

    def test_special_maintenance_completion_creates_recurrence(self):
        requirement = SpecialMaintenanceRequirement.objects.create(
            car=self.car, title='Timing belt', due_odometer=5000,
            recurrence_km=50000, created_by=self.admin,
        )
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse('special_maintenance_complete', args=[requirement.pk]),
            {'completed_odometer': 4500, 'completion_notes': 'Invoice checked'},
        )
        self.assertRedirects(response, reverse('special_maintenance_list'))
        requirement.refresh_from_db()
        self.assertFalse(requirement.active)
        next_item = SpecialMaintenanceRequirement.objects.get(
            car=self.car, title='Timing belt', active=True
        )
        self.assertEqual(next_item.due_odometer, 54500)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_special_and_weekly_reminders_are_tracked_and_deduplicated(self):
        self.user.email = 'driver@example.com'
        self.user.save(update_fields=['email'])
        AlertContact.objects.create(
            name='Fleet', email='fleet@example.com',
            responsibility=AlertContact.ROLE_FLEET_MANAGER,
            categories=[
                AlertContact.CATEGORY_SPECIAL_MAINTENANCE,
                AlertContact.CATEGORY_ODOMETER,
            ], created_by=self.admin, updated_by=self.admin,
        )
        SpecialMaintenanceRequirement.objects.create(
            car=self.car, title='Timing belt', due_date=date.today(),
            created_by=self.admin,
        )
        OdometerReading.objects.filter(car=self.car).update(
            reading_date=date.today() - timedelta(days=15)
        )
        first = send_special_maintenance_reminders()
        second = send_special_maintenance_reminders()
        weekly = send_weekly_odometer_reminders()
        self.assertEqual((first['sent'], second['sent'], weekly['sent']), (1, 0, 2))
        self.assertEqual(NotificationDelivery.objects.filter(
            event_type=AlertContact.CATEGORY_SPECIAL_MAINTENANCE
        ).count(), 1)


class PDFInvoiceParserRegressionTests(TestCase):
    def test_anonymized_mechanicdesk_layout_extracts_complete_invoice(self):
        fixture = (
            Path(__file__).with_name('test_fixtures') / 'mechanicdesk_invoice.txt'
        ).read_text(encoding='utf-8')

        parser = PDFInvoiceParser()
        result = parser._add_preview_metadata(
            parser._extract_data_from_text(fixture), fixture
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.invoice_number, 'TEST-1001')
        self.assertEqual(result.date, date(2025, 4, 15))
        self.assertEqual(result.vehicle_rego, 'ZZ00ZZ')
        self.assertEqual(result.odometer_reading, 231580)
        self.assertEqual(
            result.service_provider,
            'EXAMPLE MOTOR SERVICES & MECHANICAL REPAIRS',
        )
        self.assertEqual(result.subtotal, Decimal('321.40'))
        self.assertEqual(result.tax_amount, Decimal('32.14'))
        self.assertEqual(result.total_cost, Decimal('353.54'))
        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.items[0].description, 'Labour')
        self.assertEqual(result.items[0].item_type, 'labor')
        self.assertEqual(Decimal(str(result.items[0].quantity)), Decimal('0.3'))
        self.assertEqual(result.items[0].total_cost, Decimal('42.000'))
        self.assertEqual(result.confidence['odometer'], 'high')
