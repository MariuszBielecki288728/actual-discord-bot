from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date


@dataclass
class ReceiptItem:
    name: str
    quantity: Decimal
    unit_price: Decimal
    total_price: Decimal
    vat_category: str | None = None
    is_discount: bool = False


@dataclass
class ParsedReceipt:
    store_name: str
    items: list[ReceiptItem] = field(default_factory=list)
    total: Decimal = Decimal("0")
    date: date | None = None
    source: str = "photo"
