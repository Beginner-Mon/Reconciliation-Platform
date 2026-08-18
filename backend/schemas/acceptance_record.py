from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .purchase_order import DOC_NUMBER_PATTERN, TAX_CODE_PATTERN


class AcceptedItem(BaseModel):
    item_name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0)
    unit: str | None = Field(default=None, max_length=20)


class AcceptanceRecord(BaseModel):
    document_type: Literal["acceptance_record"]
    record_number: str = Field(pattern=DOC_NUMBER_PATTERN)
    record_date: date
    vendor: str = Field(min_length=1, max_length=200)
    vendor_tax_code: str | None = Field(default=None, pattern=TAX_CODE_PATTERN)
    buyer: str | None = Field(default=None, max_length=200)
    po_number: str | None = Field(default=None, pattern=DOC_NUMBER_PATTERN)
    items: list[AcceptedItem] = Field(min_length=1)
    accepted_by: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)

    @property
    def total_quantity(self) -> int:
        return sum(i.quantity for i in self.items)
