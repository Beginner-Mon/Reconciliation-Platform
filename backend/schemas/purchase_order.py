from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

CURRENCIES = {"VND", "USD", "EUR", "JPY", "SGD"}
DOC_NUMBER_PATTERN = r"^[A-Z0-9][A-Z0-9\-/ ]{2,50}$"
TAX_CODE_PATTERN = r"^\d{10,13}$"


class LineItem(BaseModel):
    item_name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0)
    unit: str | None = Field(default=None, max_length=20)
    unit_price: int = Field(gt=0)


class PurchaseOrder(BaseModel):
    document_type: Literal["purchase_order"]
    po_number: str = Field(pattern=DOC_NUMBER_PATTERN)
    po_date: date
    vendor: str = Field(min_length=1, max_length=200)
    vendor_tax_code: str | None = Field(default=None, pattern=TAX_CODE_PATTERN)
    buyer: str | None = Field(default=None, max_length=200)
    currency: str
    items: list[LineItem] = Field(min_length=1)
    total_amount: int = Field(gt=0)
    delivery_date: date | None = None
    payment_terms: str | None = Field(default=None, max_length=100)

    @property
    def item_total(self) -> int:
        return sum(i.quantity * i.unit_price for i in self.items)

    @property
    def total_quantity(self) -> int:
        return sum(i.quantity for i in self.items)
