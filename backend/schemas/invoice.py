from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .purchase_order import DOC_NUMBER_PATTERN, TAX_CODE_PATTERN, LineItem


class Invoice(BaseModel):
    document_type: Literal["invoice"]
    invoice_number: str = Field(pattern=DOC_NUMBER_PATTERN)
    invoice_date: date
    vendor: str = Field(min_length=1, max_length=200)
    vendor_tax_code: str | None = Field(default=None, pattern=TAX_CODE_PATTERN)
    buyer: str | None = Field(default=None, max_length=200)
    currency: str
    po_number: str | None = Field(default=None, pattern=DOC_NUMBER_PATTERN)
    items: list[LineItem] = Field(min_length=1)
    subtotal: int | None = Field(default=None, gt=0)
    tax_rate: float | None = Field(default=None, ge=0, le=1)
    tax_amount: int | None = Field(default=None, ge=0)
    total_amount: int = Field(gt=0)
    payment_due_date: date | None = None

    @property
    def item_total(self) -> int:
        return sum(i.quantity * i.unit_price for i in self.items)

    @property
    def total_quantity(self) -> int:
        return sum(i.quantity for i in self.items)
