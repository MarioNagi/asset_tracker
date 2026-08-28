from pathlib import Path

from django.core.management.base import BaseCommand
from openpyxl import Workbook

from tracking.models import Maintenance


SERVICE_TYPE_TITLES = {
    'regular': 'Regular Service',
    'repair': 'Repair',
    'inspection': 'Inspection',
    'accident': 'Accident Repair',
    'other': 'Other Maintenance',
}

HEADERS = [
    'Asset Tag ID',
    'Maintenance Title',
    'Maintenance Details',
    'Maintenance Due Date',
    'Maintenance By',
    'Maintenance Status',
    'Maintenance Completion Date',
    'Maintenance Cost',
    'Is Repeating',
    'Frequency',
    'Recur on every',
    'on (day or Weekday)',
]


class Command(BaseCommand):
    help = "Export Maintenance + MaintenanceItem rows into the ImportMaintenancesTemplate xlsx layout."

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            default='maintenance_export.xlsx',
            help='Path to write the xlsx file (default: maintenance_export.xlsx)',
        )
        parser.add_argument(
            '--rego',
            default=None,
            help='Optional rego filter (exports only maintenance rows for this car).',
        )

    def handle(self, *args, **options):
        output_path = Path(options['output']).resolve()
        rego_filter = options.get('rego')

        qs = (
            Maintenance.objects
            .select_related('car')
            .prefetch_related('items')
            .order_by('car__rego', 'service_date')
        )
        if rego_filter:
            qs = qs.filter(car__rego__iexact=rego_filter)

        wb = Workbook()
        ws = wb.active
        ws.title = 'Maintenance Template'
        ws.append(HEADERS)

        count = 0
        for m in qs:
            ws.append(self._build_row(m))
            count += 1

        wb.save(output_path)
        self.stdout.write(self.style.SUCCESS(
            f"Exported {count} maintenance row(s) to {output_path}"
        ))

    def _build_row(self, m):
        car = m.car
        asset_tag = car.rego if car else ''

        title = SERVICE_TYPE_TITLES.get(m.service_type, m.service_type.title() if m.service_type else 'Maintenance')
        if m.invoice_number:
            title = f"{title} - Inv {m.invoice_number}"

        details = self._build_details(m)

        date_str = m.service_date.strftime('%d/%m/%Y') if m.service_date else ''
        cost = f"{m.total_cost:.2f}" if m.total_cost is not None else '0.00'

        return [
            asset_tag,
            title,
            details,
            date_str,
            m.service_provider or '',
            'Completed',
            date_str,
            cost,
            'No',
            '',
            '',
            '',
        ]

    def _build_details(self, m):
        item_lines = []
        for it in m.items.all():
            qty = it.quantity
            qty_str = f"{qty:g}" if qty is not None else '1'
            unit = f"{it.unit_cost:.2f}" if it.unit_cost is not None else '0.00'
            item_lines.append(f"- {it.description} (x{qty_str} @ ${unit})")

        parts = []
        if m.description:
            parts.append(m.description.strip())
        if item_lines:
            parts.append('Items:\n' + '\n'.join(item_lines))
        if m.odometer_reading:
            parts.append(f"Odometer: {m.odometer_reading} km")

        return '\n\n'.join(p for p in parts if p)
