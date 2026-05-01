import re
from datetime import date as date_type
from decimal import Decimal, InvalidOperation

from actual_discord_bot.receipts.models import ParsedReceipt, ReceiptItem

# Main product line pattern: <name> <qty> x<unit_price> <total_price><vat>
PRODUCT_LINE_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<qty>[\d]+[.,]?\d*)\s*[x\N{MULTIPLICATION SIGN}*]\s*(?P<unit_price>-?[\d]+[.,]\d{2})\s+"
    r"(?P<total_price>-?[\d]+[.,]\d{2})\s*"
    r"(?P<vat>[A-Da-d])?\s*$",
)

# Alternative: T * price pattern (Pepco-style)
PRODUCT_LINE_ALT_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?:T|(?P<qty>[\d]+[.,]?\d*))\s*[*\N{MULTIPLICATION SIGN}x]\s*(?P<unit_price>-?[\d]+[.,]\d{2})\s+"
    r"(?P<total_price>-?[\d]+[.,]\d{2})\s*"
    r"(?P<vat>[A-Da-d])?\s*$",
)

# OCR-typical format: <name> <qty> szt [+*6x] <unit_price> = <total_price> <vat>
OCR_PRODUCT_LINE_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<qty>[\d]+[.,]?\d*)\s*(?:szt|sz[lt])?\s*[+*6x\N{MULTIPLICATION SIGN}]\s*"
    r"(?P<unit_price>-?[\d]+[.,]\d{2})\s*=\s*"
    r"(?P<total_price>-?[\d]+[.,]\d{2})\s*"
    r"(?P<vat>[A-Da-dUu])?\s*$",
    re.IGNORECASE,
)

# Weighted items: <name> x<weight>kg <total_price> <vat>
WEIGHTED_ITEM_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"[x\N{MULTIPLICATION SIGN}*]\s*(?P<qty>[\d]+[.,]\d+)\s*kg\s+"
    r"(?P<total_price>-?[\d]+[.,]\d{2})\s*"
    r"(?P<vat>[A-Da-d])?\s*$",
)

# OCR weighted: <qty> kg [+*x6k] <unit_price> = <total_price> <vat>
OCR_WEIGHTED_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<qty>[\d]+[.,]\d+)\s*kg\s*[+*6x\N{MULTIPLICATION SIGN}k]\s*"
    r"(?P<unit_price>-?[\d]+[.,]\d{2})\s*=\s*"
    r"(?P<total_price>-?[\d]+[.,]\d{2})\s*"
    r"(?P<vat>[A-Da-dUu])?\s*$",
    re.IGNORECASE,
)

# Total line (flexible for OCR variations)
TOTAL_RE = re.compile(
    r"(?:SUMA|RAZEM|Suma|SU[MN]A|SWĄ)\s*:?\s*(?:PLN?|PL[NI]?)?\s+(?P<total>[\d]+[.,]\d{2})",
    re.IGNORECASE,
)

# Tax summary line (used to detect end of product section)
TAX_SECTION_RE = re.compile(
    r"(?:SPRZEDA[ZŻ]|Sprzed)\s*\.?\s*(?:OPODATKOWANA|opod)|"
    r"PTU\s+[A-D]|"
    r"SUMA\s+PTU|"
    r"Kwota\s+PTU|"
    r"Podatek\s+%",
    re.IGNORECASE,
)

# Discount line patterns
DISCOUNT_LINE_RE = re.compile(
    r"^(?P<name>(?:OBNI[ZŻ]KA|RABAT|UPUST|Obni[zż]ka|Rabat|Upust).*?)\s+"
    r"(?P<total_price>-[\d]+[.,]\d{2})\s*(?P<vat>[A-D])?\s*$",
    re.IGNORECASE,
)

# Discount summary (skip line)
DISCOUNT_SUMMARY_RE = re.compile(r"[Ss]uma\s+obni[zż]ek", re.IGNORECASE)

# Date pattern in receipt footer (ISO format)
DATE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\s*(?P<time>\d{2}:\d{2})?")

# Date pattern: DD.MM.YYYY
DATE_DOT_RE = re.compile(
    r"(?:Data:?\s*)?(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})"
)

# Leading article code (8+ digits at start of line)
ARTICLE_CODE_RE = re.compile(r"^\d{8,}\s+")

# Receipt header markers
HEADER_RE = re.compile(r"PARAGON\s+FISKALNY|PARAGON|FISCAL", re.IGNORECASE)

# Price-only line (continuation from multi-line item)
PRICE_ONLY_RE = re.compile(
    r"^\s*(?P<qty>[\d]+[.,]?\d*)\s*[x\N{MULTIPLICATION SIGN}*]\s*(?P<unit_price>-?[\d]+[.,]\d{2})\s+"
    r"(?P<total_price>-?[\d]+[.,]\d{2})\s*"
    r"(?P<vat>[A-D])?\s*$",
)

# Standalone price line (used in PDF digital receipts)
STANDALONE_PRICE_RE = re.compile(r"^-?[\d]+[.,]\d{2}$")

# Digital receipt header detection
DIGITAL_RECEIPT_HEADER_RE = re.compile(r"Podsumowanie\s+zakup|Cena\s+w", re.IGNORECASE)


def _parse_decimal(value: str) -> Decimal:
    """Parse a decimal value from a string, handling both comma and dot separators."""
    normalized = value.replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return Decimal("0")


def _strip_article_code(name: str) -> str:
    """Remove leading article codes (8+ digit numbers) from product names."""
    return ARTICLE_CODE_RE.sub("", name).strip()


def _is_non_product_line(line: str) -> bool:
    """Check if a line is not a product (tax summary, discount summary, etc.)."""
    if TAX_SECTION_RE.search(line):
        return True
    return bool(DISCOUNT_SUMMARY_RE.search(line))


class ReceiptParser:
    """Parse receipt text into structured data."""

    def parse(self, text: str, source: str = "photo") -> ParsedReceipt:
        """Parse raw receipt text into a ParsedReceipt."""
        lines = text.strip().splitlines()

        # Detect digital receipt format (e.g., Kaufland PDF)
        if self._is_digital_receipt_format(lines):
            return self._parse_digital_receipt(lines, source)

        store_name = self._extract_store_name(lines)
        receipt_date = self._extract_date(lines)
        total = self._extract_total(lines)
        items = self._extract_items(lines)

        return ParsedReceipt(
            store_name=store_name,
            items=items,
            total=total,
            date=receipt_date,
            source=source,
        )

    def _is_digital_receipt_format(self, lines: list[str]) -> bool:
        """Detect if this is a digital receipt (price-before-name format)."""
        return any(DIGITAL_RECEIPT_HEADER_RE.search(line) for line in lines[:5])

    def _parse_digital_receipt(self, lines: list[str], source: str) -> ParsedReceipt:
        """Parse a digital receipt (Kaufland-style: price on one line, name on next)."""
        store_name = self._extract_digital_store_name(lines)
        items, total = self._parse_digital_items(lines)
        receipt_date = self._extract_date(lines)

        return ParsedReceipt(
            store_name=store_name,
            items=items,
            total=total,
            date=receipt_date,
            source=source,
        )

    def _extract_digital_store_name(self, lines: list[str]) -> str:
        """Extract store name from digital receipt header."""
        for line in lines:
            stripped = line.strip()
            if stripped and "Podsumowanie" not in stripped and "Cena" not in stripped:
                return stripped
        return "Unknown"

    def _parse_digital_items(
        self, lines: list[str]
    ) -> tuple[list[ReceiptItem], Decimal]:
        """Parse price-name pairs from digital receipt lines."""
        items: list[ReceiptItem] = []
        total = Decimal("0")
        i = 0
        in_items = False

        while i < len(lines):
            stripped = lines[i].strip()

            if "Cena" in stripped and not in_items:
                in_items = True
                i += 1
                continue

            if not in_items:
                i += 1
                continue

            if stripped.lower() == "suma":
                if items:
                    total = items.pop().total_price
                i += 1
                continue

            if _is_non_product_line(stripped):
                break

            if STANDALONE_PRICE_RE.match(stripped):
                price = _parse_decimal(stripped)
                result = self._try_consume_name(lines, i, price, items)
                if result is not None:
                    i, found_total = result
                    if found_total is not None:
                        total = found_total
                    continue
                i += 1
                continue

            i += 1

        return items, total

    def _try_consume_name(
        self,
        lines: list[str],
        i: int,
        price: Decimal,
        items: list[ReceiptItem],
    ) -> tuple[int, Decimal | None] | None:
        """Try to consume the name line following a price. Returns (next_i, total_if_found)."""
        if i + 1 >= len(lines):
            return None
        name = lines[i + 1].strip()
        if name.lower() == "suma":
            return (i + 2, price)
        if not STANDALONE_PRICE_RE.match(name) and name:
            items.append(
                ReceiptItem(
                    name=name,
                    quantity=Decimal("1"),
                    unit_price=price,
                    total_price=price,
                )
            )
            return (i + 2, None)
        return None

    def _extract_store_name(self, lines: list[str]) -> str:
        """Extract store name from receipt header (first non-empty line)."""
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("-"):
                return stripped
        return "Unknown"

    def _extract_date(self, lines: list[str]) -> date_type | None:
        """Extract transaction date from receipt text."""
        for line in lines:
            # Try ISO format first (YYYY-MM-DD)
            match = DATE_RE.search(line)
            if match:
                try:
                    return date_type.fromisoformat(match.group("date"))
                except ValueError:
                    pass

            # Try DD.MM.YYYY format
            match = DATE_DOT_RE.search(line)
            if match:
                try:
                    return date_type(
                        int(match.group("year")),
                        int(match.group("month")),
                        int(match.group("day")),
                    )
                except ValueError:
                    pass
        return None

    def _extract_total(self, lines: list[str]) -> Decimal:
        """Extract the total amount from the receipt."""
        for line in lines:
            match = TOTAL_RE.search(line)
            if match:
                return _parse_decimal(match.group("total"))
        return Decimal("0")

    def _extract_items(self, lines: list[str]) -> list[ReceiptItem]:
        """Extract product items from receipt text."""
        items: list[ReceiptItem] = []
        in_products_section = False
        buffered_name: str | None = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Detect start of products section
            if HEADER_RE.search(stripped):
                in_products_section = True
                continue

            # Detect end of products section
            if in_products_section and _is_non_product_line(stripped):
                break

            # Check for total line (also ends product section)
            if in_products_section and TOTAL_RE.search(stripped):
                break

            if not in_products_section:
                # If no header was found, try to parse items anyway
                item = self._try_parse_line(stripped, buffered_name)
                if item:
                    items.append(item)
                    buffered_name = None
                    in_products_section = True
                continue

            buffered_name = self._process_product_line(stripped, buffered_name, items)

        return items

    def _process_product_line(
        self,
        stripped: str,
        buffered_name: str | None,
        items: list[ReceiptItem],
    ) -> str | None:
        """Process a single line in the products section. Returns updated buffered_name."""
        # Try discount line
        discount_match = DISCOUNT_LINE_RE.match(stripped)
        if discount_match:
            items.append(
                ReceiptItem(
                    name=discount_match.group("name").strip(),
                    quantity=Decimal("1"),
                    unit_price=_parse_decimal(discount_match.group("total_price")),
                    total_price=_parse_decimal(discount_match.group("total_price")),
                    vat_category=discount_match.group("vat"),
                    is_discount=True,
                ),
            )
            return None

        # Try to parse as price-only line (multi-line item continuation)
        price_match = PRICE_ONLY_RE.match(stripped)
        if price_match and buffered_name:
            name = _strip_article_code(buffered_name)
            qty = _parse_decimal(price_match.group("qty"))
            unit_price = _parse_decimal(price_match.group("unit_price"))
            total_price = _parse_decimal(price_match.group("total_price"))
            items.append(
                ReceiptItem(
                    name=name,
                    quantity=qty,
                    unit_price=unit_price,
                    total_price=total_price,
                    vat_category=price_match.group("vat"),
                ),
            )
            return None

        # Try to parse a full product line
        item = self._try_parse_line(stripped, buffered_name)
        if item:
            items.append(item)
            return None

        # If line has no price, it might be a multi-line item name
        return stripped if not self._has_price_pattern(stripped) else None

    def _try_parse_line(
        self, line: str, _buffered_name: str | None = None
    ) -> ReceiptItem | None:
        """Try to parse a line as a product item."""
        # Skip non-product lines
        if _is_non_product_line(line):
            return None
        if DISCOUNT_SUMMARY_RE.search(line):
            return None

        # Try all product line patterns
        for pattern in (
            PRODUCT_LINE_RE,
            PRODUCT_LINE_ALT_RE,
            OCR_PRODUCT_LINE_RE,
            WEIGHTED_ITEM_RE,
            OCR_WEIGHTED_RE,
        ):
            match = pattern.match(line)
            if match:
                groups = match.groupdict()
                name = _strip_article_code(groups["name"])
                qty_str = groups.get("qty") or "1"
                qty = _parse_decimal(qty_str)
                unit_price = _parse_decimal(
                    groups.get("unit_price") or groups["total_price"]
                )
                total_price = _parse_decimal(groups["total_price"])
                is_discount = total_price < 0

                return ReceiptItem(
                    name=name,
                    quantity=qty,
                    unit_price=unit_price,
                    total_price=total_price,
                    vat_category=groups.get("vat"),
                    is_discount=is_discount,
                )

        return None

    def _has_price_pattern(self, line: str) -> bool:
        """Check if a line contains a price pattern."""
        return bool(re.search(r"\d+[.,]\d{2}\s*[A-D]?\s*$", line))
