from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass
class InvoiceItem:
    """A normalized line item extracted from an invoice."""

    description: str
    quantity: float = 1.0
    unit_cost: Decimal = Decimal("0.00")
    item_type: str = "parts"

    @property
    def total_cost(self):
        return Decimal(str(self.quantity)) * self.unit_cost


@dataclass
class InvoiceData:
    """Normalized invoice information returned by every format parser."""

    invoice_number: str
    date: date
    vehicle_rego: str = ""
    vehicle_vin: str = ""
    odometer_reading: int = 0
    service_provider: str = ""
    total_cost: Decimal = Decimal("0.00")
    items: Optional[List[InvoiceItem]] = None
    subtotal: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    confidence: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.items is None:
            self.items = []
