# Receipt Photo Parsing — Implementation Plan

## Overview

Parse Polish shopping receipts sent to a dedicated Discord channel — either as **photos** (OCR) or **digital PDF receipts** (text extraction) — extract individual product line items, and create **split transactions** in Actual Budget where each product is a sub-transaction.

## Data Flow

```
┌──────────────┐      ┌──────────────┐      ┌──────────────────────┐      ┌──────────────┐
│ Phone camera │─────▶│              │      │ Image → OCR pipeline  │      │              │
│ (photo)      │      │              │─────▶│         or            │─────▶│ Actual Budget│
│ Shop app     │─────▶│ Discord      │      │ PDF → text extraction │      │ (split txn)  │
│ (PDF)        │      │ #receipts    │      │         ↓             │      │              │
└──────────────┘      └──────────────┘      │   Receipt parser      │      └──────────────┘
                                            └──────────────────────┘
```

1. User posts a receipt to the `#receipts` Discord channel (photo or PDF from a shop app)
2. Bot detects the attachment type:
   - **Image** (jpg/png/webp) → download, preprocess, OCR
   - **PDF** → download, extract text directly (no OCR needed)
3. Extracted text is parsed to identify product line items, discounts, and total
4. Bot creates a split transaction in Actual Budget via actualpy
5. Bot reacts to the message with success/failure and replies with a summary

## Phase 1: OCR Pipeline

### 1.1 Image Download & Preprocessing

- Download image from Discord attachment URL (`message.attachments[0].url`)
- Use **Pillow** for preprocessing:
  - Convert to grayscale
  - Apply adaptive thresholding (for varying lighting)
  - Deskew if needed (using projection profile or Hough transform)
  - Optional: crop to receipt boundaries

### 1.2 OCR Provider Abstraction

The OCR layer is designed behind an abstract interface so the backend can be swapped between local Tesseract and cloud providers via configuration.

Do not implement cloud providers in Phase 1 — just the abstraction, classes and Tesseract implementation.

```python
from abc import ABC, abstractmethod
from PIL import Image


class OCRProvider(ABC):
    """Abstract base for OCR backends."""

    @abstractmethod
    def extract_text(self, image: Image.Image) -> str:
        """Return raw OCR text from a preprocessed image."""
        ...


class TesseractProvider(OCRProvider):
    """Local Tesseract-based OCR (default, free)."""

    def extract_text(self, image: Image.Image) -> str:
        import pytesseract
        return pytesseract.image_to_string(image, lang="pol", config="--psm 6")


class AmazonTextractProvider(OCRProvider):
    """AWS Textract cloud OCR (paid, higher accuracy)."""

    def extract_text(self, image: Image.Image) -> str:
        # Uses boto3 to call Textract AnalyzeExpense or DetectDocumentText
        ...


class GoogleCloudVisionProvider(OCRProvider):
    """Google Cloud Vision OCR (paid, higher accuracy)."""

    def extract_text(self, image: Image.Image) -> str:
        # Uses google-cloud-vision client
        ...
```

**Provider selection** is driven by a config variable:

```python
@environ.config(prefix="OCR")
class OCRConfig:
    provider: str = environ.var(default="tesseract")  # tesseract | textract | google_vision
    # Cloud-specific settings (ignored when provider=tesseract)
    aws_region: str = environ.var(default="eu-central-1")
    google_credentials_path: str = environ.var(default="")
```

A factory function instantiates the configured provider:

```python
def create_ocr_provider(config: OCRConfig) -> OCRProvider:
    match config.provider:
        case "tesseract":
            return TesseractProvider()
        case "textract":
            return AmazonTextractProvider(config)
        case "google_vision":
            return GoogleCloudVisionProvider(config)
        case _:
            raise ValueError(f"Unknown OCR provider: {config.provider}")
```

This allows switching to a paid cloud service for better accuracy without changing any parsing or integration code.

### 1.3 Local Tesseract Setup

- Use **pytesseract** (Python binding for Tesseract)
- Configure for Polish language: `lang='pol'`
- Use `--psm 6` (assume a single uniform block of text) or `--psm 4` (single column)
- Return raw text output for parsing

### 1.4 Dependencies

```toml
# pyproject.toml additions
pytesseract = "^0.3"
Pillow = "^11.0"
pdfplumber = "^0.11"

# Optional cloud provider dependencies (extras)
# [tool.poetry.extras]
# ocr-textract = ["boto3"]
# ocr-google = ["google-cloud-vision"]
```

Docker: install `tesseract-ocr` and `tesseract-ocr-pol` in the builder stage (only needed when using local provider).

## Phase 2: Receipt Text Parser

### 2.1 Input Categories

Receipt parsing is divided into two distinct pipelines based on the input source:

#### 2.1.1 Paper Receipt Photos (OCR-based)

Traditional paper receipts photographed by the user. These go through the OCR pipeline (Phase 1) and then text parsing. Subject to image quality issues, OCR misreads, and format ambiguity.

#### 2.1.2 Online/Digital Receipt PDFs

Many Polish shops (e.g., Kaufland, Lidl, Żabka) offer digital receipts via their mobile apps. These are typically well-structured PDFs with clean text that can be extracted directly (via `pdfplumber` or `PyPDF2`) without OCR — resulting in much higher accuracy.

**Advantages of digital receipts:**
- No OCR errors — text is already digital
- Consistent, machine-readable formatting
- Often include structured metadata (date, NIP, transaction ID)
- Items are clearly separated with no multi-line ambiguity

**Detection:** The bot should detect the attachment type (image vs. PDF) and route accordingly:
- Image attachments → OCR pipeline → text parser
- PDF attachments → PDF text extraction → text parser (or structured parser if format is known)

**Dependencies:**
```toml
pdfplumber = "^0.11"
```

### 2.2 Polish Receipt Structure & Real-World Examples

Based on analysis of actual receipts from various Polish stores, the following structures and variations have been identified:

#### 2.2.1 General Structure

```
[Store name / logo]
[Address]
[NIP: tax number]
──────────────────────────
PARAGON FISKALNY    nr: XXXXX
[Product lines section]
──────────────────────────
[Tax summary section]
SUMA PLN            XX,XX
[Payment section]
[Date, transaction ID, etc.]
```

#### 2.2.2 Product Line Formats (Observed Variations)

**Format A — Single-line items (most common):**
```
Pierogi ruskie 330g    1 x26,70 26,70B
Kompot 250 ml          1 x17,30 17,30B
```
Pattern: `<name> <qty> x<unit_price> <total_price><vat>`

**Format B — Multi-line items (price on second line):**
```
Barszcz z uszkami z podgrzybków 480 ml
                       1 x25,50 25,50B
```
The product name is too long to fit on one line, so quantity and price appear on the next line.

**Format C — Items with article codes (Pepco, Kaufland):**
```
63338001 t-shirt mes kr/r str_S
                       T * 30,00 30,00 A
32531301 torbanazakupymałaDKT_ON 1 * 0,90 0,90 A
```
Pattern: `<article_code> <name>` on first line, price may be on same or next line. Uses `*` instead of `x` as multiplier.

**Format D — Fuel stations (Orlen):**
```
EFECTA DIESEL CN27102011D(8) (B) 30*7.79     233,70B
OBNIŻKA                                       -2,40B
```
Contains technical product codes and uses dot as decimal in unit price but comma in total.

**Format E — Weighted/measured items:**
```
Banany  x1.234kg  8,72 A
```

#### 2.2.3 Discounts & Negative Amounts

Discounts appear in multiple forms:

1. **Per-item discount line** — a separate line immediately after the product with a negative amount:
   ```
   EFECTA DIESEL ...    233,70B
   OBNIŻKA              -2,40B
   ```

2. **Discount summary line** — an aggregate of all per-item discounts:
   ```
   Suma obniżek:         2,40
   ```
   This is informational only (not an item) and should be skipped during parsing.

3. **Promotions/coupons** — may appear as a negative line anywhere in the items section or after the subtotal.

**Parsing rule:** Negative amounts should be treated as discount items attached to the preceding product, or as standalone discount sub-transactions if they cannot be associated with a specific item.
The wording may also vary (e.g., "OBNIŻKA", "RABAT", "UPUST") — the parser should use a regex pattern to detect these.

#### 2.2.4 Tax Summary Section

Between the last product and `SUMA`, receipts include a tax breakdown:
```
SPRZEDAŻ OPODATKOWANA A           4,99
SPRZEDAŻ OPODATKOWANA B         104,90
PTU A 23%                         0,93
PTU B 8%                          7,77
SUMA PTU                          8,70
```
or:
```
Sprzed. opod. PTU A              30,90
Kwota PTU A 23,00%                5,78
SUMA PTU                          5,78
```

**These lines must NOT be parsed as product items.** The parser must detect the tax summary section (starts with `SPRZEDAŻ OPODATKOWANA` / `Sprzed. opod.` / `PTU` / `SUMA PTU`) and stop parsing products before it.

#### 2.2.5 Date Extraction

Receipts typically include a date in the footer area in various formats:
- `2026-04-24 14:38`
- `2026-04-18 18:50`
- `2026-04-30` with time separately

**Date usage for transaction matching:**
- If a date is successfully extracted from the receipt, use it as the transaction date
- If OCR fails to read the date, fall back to the Discord message timestamp
- For deduplication matching (§3.1), use a tolerance of ±1 day from the receipt/message date

### 2.3 Parsing Challenges & Strategies

| Challenge | Example | Strategy |
|-----------|---------|----------|
| Multi-line items | Long product name wraps to next line | If a line has no price, concatenate with the next line that does |
| Negative amounts (discounts) | `OBNIŻKA -2,40B` | Detect minus sign; attach to preceding item or keep as separate line item |
| Discount summary lines | `Suma obniżek: 2,40` | Skip — detect by keyword pattern, do not include in items |
| Tax summary section | `SPRZEDAŻ OPODATKOWANA...` | End product parsing when tax keywords are detected |
| Varying multiplier symbols | `x`, `*`, `×` | Regex alternation for all known symbols |
| Decimal separators | Comma in totals, dot in unit prices (Orlen) | Accept both `,` and `.` as decimal separators |
| Article codes as prefixes | `63338001 t-shirt...` | Strip leading numeric codes (8+ digits) from product names |
| OCR misreads of Polish characters | `ż` → `z`, `ł` → `l` | Fuzzy matching for keywords (SUMA, RAZEM, etc.) |
| Crumpled/torn receipts | Missing sections | Graceful degradation — parse what's available, flag incomplete |
| `T *` quantity notation | Pepco uses `T` for quantity 1 | Handle `T` as quantity indicator |

### 2.4 Parser Design

```python
@dataclass
class ReceiptItem:
    name: str
    quantity: Decimal
    unit_price: Decimal
    total_price: Decimal  # quantity * unit_price (negative for discounts)
    vat_category: str | None
    is_discount: bool = False  # True for OBNIŻKA lines

@dataclass
class ParsedReceipt:
    store_name: str
    items: list[ReceiptItem]
    total: Decimal
    date: date | None  # extracted from receipt text or Discord message timestamp
    source: str  # "photo" or "pdf"
```

Parsing strategy:
1. **Detect input type:** image → OCR text, PDF → extracted text
2. **Identify the product section:** between `PARAGON FISKALNY` header and tax summary / `SUMA` line
3. **Handle multi-line items:** if a line contains no price pattern, buffer it and prepend to the next line
4. **For each line in the product section, extract:**
   - Product name (strip leading article codes if present)
   - Quantity (look for `<qty> x|*|× <unit_price>` or `x<qty><unit>` patterns)
   - Total price (rightmost decimal number, possibly preceded by minus for discounts)
   - VAT category letter (A/B/C/D at end of line)
5. **Detect and skip non-item lines:** tax summaries, discount aggregates (`Suma obniżek`)
6. **Extract date** from footer area
7. **Validate:** sum of item prices should ≈ total (within rounding tolerance)

### 2.5 Regex Patterns

```python
# Main product line pattern (handles x and * multipliers, negative prices)
PRODUCT_LINE_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?:(?P<qty>[\d]+)\s*[x*×]\s*(?P<unit_price>[\d]+[.,]\d{2})\s+)?"
    r"(?P<price>-?[\d]+[.,]\d{2})\s*"
    r"(?P<vat>[A-D])?\s*$"
)

# Alternative: price with quantity after name (Pepco-style: T * 30,00 30,00 A)
PRODUCT_LINE_ALT_RE = re.compile(
    r"^(?P<name>.+?)\s+"
    r"(?P<qty_indicator>[T\d]+)\s*\*\s*(?P<unit_price>[\d]+[.,]\d{2})\s+"
    r"(?P<price>-?[\d]+[.,]\d{2})\s*"
    r"(?P<vat>[A-D])?\s*$"
)

# Total line
TOTAL_RE = re.compile(r"(?:SUMA|RAZEM)\s*:?\s*(?:PLN\s+)?(?P<total>[\d]+[.,]\d{2})")

# Tax summary line (used to detect end of product section)
TAX_SECTION_RE = re.compile(
    r"(?:SPRZEDA[ZŻ]|Sprzed)\s*\.?\s*(?:OPODATKOWANA|opod)|"
    r"PTU\s+[A-D]|"
    r"SUMA\s+PTU|"
    r"Kwota\s+PTU"
)

# Discount summary (skip line)
DISCOUNT_SUMMARY_RE = re.compile(r"[Ss]uma\s+obni[zż]ek")

# Date pattern in receipt footer
DATE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})\s*(?P<time>\d{2}:\d{2})?")

# Leading article code (8+ digits at start of line)
ARTICLE_CODE_RE = re.compile(r"^\d{8,}\s+")
```

## Phase 3: Actual Budget Integration

### 3.1 Transaction Deduplication & Reconciliation

Receipts and bank notifications can both create transactions for the same purchase. The system must handle all cases:

**Scenario A: Receipt arrives first (no matching bank transaction yet)**
- Bot creates a new split transaction with a unique `imported_id` derived from the receipt (e.g., `receipt:<store>:<date>:<total>:<hash>`).
- When the bank notification later arrives, the bank-notification handler must check for an existing transaction matching (amount, date ±1 day, payee) before creating a new one.
- If a match is found, the bank-notification handler marks the existing transaction as cleared/reconciled instead of creating a duplicate.

**Scenario B: Bank transaction already exists (notification arrived first)**
- Before creating a new transaction, the receipt handler searches for an existing uncleared transaction matching (amount, date ±1 day, payee).
- If found, convert the existing simple transaction into a split transaction by attaching the parsed line items as sub-transactions.
- The parent transaction keeps the same `id` — no duplicate is created.

**Scenario C: Neither exists yet**
- Bot creates the split transaction as normal (see §3.2).

**Matching logic:**

```python
def find_matching_transaction(
    actual: Actual,
    account_name: str,
    amount_cents: int,
    date: date,
    payee_name: str,
    date_tolerance_days: int = 1,
) -> Transaction | None:
    """Find an existing transaction that likely represents the same purchase."""
    # Search by amount and date range; optionally fuzzy-match payee
    ...
```

**Bank-notification side changes:**
- The existing bank-notification handler must also call `find_matching_transaction` before creating.
- If a receipt-created transaction already exists, it should link/reconcile rather than duplicate.

### 3.2 Split Transaction Creation

Using actualpy's split transaction API:

```python
from actual import Actual
from actual.queries import create_transaction, create_splits

def create_receipt_transaction(
    actual: Actual,
    receipt: ParsedReceipt,
    account_name: str,
) -> None:
    amount_cents = -int(receipt.total * 100)
    txn_date = receipt.date or date.today()

    # Check for existing transaction (bank notification may have arrived first)
    existing = find_matching_transaction(
        actual, account_name, amount_cents, txn_date, receipt.store_name
    )

    with actual.session() as s:
        if existing:
            parent = existing
        else:
            parent = create_transaction(
                s,
                date=txn_date,
                account=account_name,
                amount=amount_cents,
                imported_payee=receipt.store_name,
                imported_id=_receipt_imported_id(receipt),
            )

        splits = [
            {"amount": -int(item.total_price * 100), "notes": item.name}
            for item in receipt.items
        ]
        create_splits(s, parent, splits)
```

### 3.3 Handling Sum Mismatches

When the sum of parsed item prices does not equal the receipt total, the bot enters an **interactive correction flow**:

1. **Calculate discrepancy:** `diff = receipt.total - sum(item.total_price for item in items)`
2. **If abs(diff) ≤ threshold (e.g., 0.02 PLN):** silently add a rounding adjustment sub-transaction labeled "Zaokrąglenie" (rounding).
3. **If abs(diff) > threshold:** bot replies to the Discord message with:
   - The parsed items and their prices
   - The expected total vs. parsed total
   - Instructions for the user:
     - **Reply** with a corrected item list (same format) for the bot to re-process
     - **React with ✅** to accept as-is — bot adds an "Inne / Others" sub-transaction for the difference
     - **React with ❌** to abort entirely

**Discord interaction flow:**

```
Bot: ⚠️ Parsed 5 items totaling 24,69 PLN but receipt says 26,18 PLN (diff: 1,49 PLN).
     Items found:
       • Mleko UHT 3.2% — 3,49
       • Chleb tostowy — 5,98
       • Masło extra — 7,99
       • Banany — 8,72

     Reply with corrected items, react ✅ to commit with "Inne" adjustment,
     or react ❌ to cancel.
```

**Implementation notes:**
- Bot listens for reactions and replies on the original message (with a timeout, e.g., 24h).
- The "Inne / Others" adjustment sub-transaction uses a configurable category (or uncategorized).
- If user replies with corrected data, bot re-parses and retries the flow.

### 3.4 Category Assignment (Plugin System — Future Enhancement)

Category assignment is designed as a pluggable pipeline that can be added later without modifying core parsing logic.

```python
from abc import ABC, abstractmethod


class CategoryAssigner(ABC):
    """Base class for category assignment strategies."""

    @abstractmethod
    def assign(self, item_name: str, store_name: str) -> str | None:
        """Return a category name or None if this assigner cannot decide."""
        ...


class KeywordCategoryAssigner(CategoryAssigner):
    """Assign categories based on keyword mappings from a config file."""
    # e.g., {"mleko": "Groceries: Dairy", "chleb": "Groceries: Bakery"}
    ...


class LearningCategoryAssigner(CategoryAssigner):
    """Learn from user corrections in Actual Budget over time."""
    ...
```

**Pipeline execution:** assigners are tried in order; first non-None result wins. If all return None, the split is left uncategorized.

```python
def assign_category(item_name: str, store_name: str, assigners: list[CategoryAssigner]) -> str | None:
    for assigner in assigners:
        result = assigner.assign(item_name, store_name)
        if result is not None:
            return result
    return None
```

Initially the assigners list is empty (all items uncategorized). Users can enable keyword-based assignment by providing a mapping file.

### 3.5 Item Name Expansion (Plugin System — Future Enhancement)

Polish receipts frequently use abbreviated/shortened product names (e.g., "ML.UHT 3.2" → "Mleko UHT 3.2%", "M.EXTRA 200G" → "Masło extra 200g"). A pluggable name transformer pipeline normalizes these before display and storage.

```python
from abc import ABC, abstractmethod


class ItemNameTransformer(ABC):
    """Base class for item name normalization/expansion."""

    @abstractmethod
    def transform(self, raw_name: str, store_name: str) -> str:
        """Return the expanded/cleaned name, or the input unchanged."""
        ...


class AbbreviationDictTransformer(ItemNameTransformer):
    """Expand known abbreviations from a user-provided dictionary file."""
    # e.g., {"ML.": "Mleko", "M.EXTRA": "Masło extra", "CH.TOST": "Chleb tostowy"}
    ...


class FuzzyMatchTransformer(ItemNameTransformer):
    """Match abbreviated names against a known product database using fuzzy matching."""
    ...
```

**Pipeline execution:** transformers are applied sequentially (each receives the output of the previous).

```python
def expand_item_name(raw_name: str, store_name: str, transformers: list[ItemNameTransformer]) -> str:
    name = raw_name
    for transformer in transformers:
        name = transformer.transform(name, store_name)
    return name
```

This runs after OCR parsing and before category assignment, so categories can match on clean names.

## Phase 4: Discord Integration

### 4.1 Configuration

```python
@environ.config(prefix="DISCORD")
class DiscordConfig:
    token: str = environ.var()
    bank_notification_channel: str = environ.var()
    receipt_channel: str = environ.var()  # NEW
```

### 4.2 Message Handler

```python
async def on_message(self, message: discord.Message):
    if message.channel.name == self.config.receipt_channel:
        if message.attachments:
            await self.handle_receipt(message)
    elif message.channel.name == self.config.bank_notification_channel:
        await self.handle_message(message)
```

### 4.3 Error Handling & Feedback

- On success: react with ✅ and reply with summary (e.g., "Created split transaction: CARREFOUR, 5 items, 26,18 PLN")
- On OCR failure: react with ❌ and reply with "Could not read receipt. Try a clearer photo."
- On partial parse: react with ⚠️ and reply with what was parsed + what failed

## Phase 5: Docker Setup

### 5.1 Dockerfile Changes

```dockerfile
FROM python-base AS builder-base

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
    curl \
    build-essential \
    tesseract-ocr \
    tesseract-ocr-pol \
    libleptonica-dev \
    libtesseract-dev
```

### 5.2 Test Data & Testing Strategy

Receipt parsing must be thoroughly tested at every layer — from OCR output through parsing logic to end-to-end transaction creation. The test suite uses real receipt photos stored in `tests/receipts/` as ground-truth fixtures.

#### 5.2.1 Test Data Organization

```
tests/receipts/
├── images/
│   ├── folgujemy_01.jpg          # Restaurant receipt (Format A, single-line items)
│   ├── pepco_01.jpg              # Retail receipt (Format C, article codes)
│   ├── orlen_01.jpg              # Fuel station receipt (Format D, discount line)
│   ├── bar_pierozek_01.jpg       # Restaurant receipt (Format A+B, multi-line items)
│   ├── biedronka_01.jpg          # Supermarket (discounts, many items)
│   ├── lidl_01.jpg               # Supermarket (weighted items, Format E)
│   ├── kaufland_01.jpg           # Supermarket (article codes + discounts)
│   └── blurry_unreadable.jpg     # Intentionally poor quality for error handling tests
├── pdfs/
│   ├── kaufland_digital_01.pdf   # Digital receipt from Kaufland app
│   ├── lidl_digital_01.pdf       # Digital receipt from Lidl Plus app
│   └── zabka_digital_01.pdf      # Digital receipt from Żappka app
├── ocr_outputs/
│   ├── folgujemy_01.txt          # Raw OCR text output for folgujemy_01.jpg
│   ├── pepco_01.txt              # Raw OCR text output for pepco_01.jpg
│   ├── orlen_01.txt              # Raw OCR text output for orlen_01.jpg
│   ├── bar_pierozek_01.txt       # Raw OCR text output for bar_pierozek_01.jpg
│   └── ...                       # One per image
└── expected/
    ├── folgujemy_01.json         # Expected ParsedReceipt as JSON
    ├── pepco_01.json
    ├── orlen_01.json
    ├── bar_pierozek_01.json
    └── ...                       # One per receipt (image or PDF)
```

**Ground-truth expected JSON format:**

```json
{
  "store_name": "Folgujemy",
  "date": "2026-04-18",
  "total": 164.00,
  "items": [
    {"name": "Keto Bostock (na wynos)", "quantity": 1, "unit_price": 41.00, "total_price": 41.00, "vat_class": "B"},
    {"name": "Fettuccine ze szparagami (na miejscu)", "quantity": 1, "unit_price": 52.00, "total_price": 52.00, "vat_class": "B"},
    {"name": "Jajecznica na chalce (na miejscu)", "quantity": 1, "unit_price": 29.00, "total_price": 29.00, "vat_class": "B"},
    {"name": "Lemoniada (Rabarbarowa)", "quantity": 1, "unit_price": 18.00, "total_price": 18.00, "vat_class": "B"},
    {"name": "Kombu Espresso (na miejscu)", "quantity": 1, "unit_price": 24.00, "total_price": 24.00, "vat_class": "A"}
  ]
}
```

The `ocr_outputs/` directory contains manually verified OCR text outputs. This allows the text parser to be tested independently of the OCR engine, and also serves as a regression baseline — if OCR output changes after a Tesseract upgrade, the diff is immediately visible.

#### 5.2.2 Unit Tests

Unit tests cover individual components in isolation, using mocked inputs. They run without Tesseract, Docker, or Actual Budget.

**Test file structure:**

```
tests/unit_tests/
├── test_receipt_parser.py        # Text parsing logic
├── test_ocr_provider.py          # OCR provider abstraction
├── test_image_preprocessing.py   # Image preprocessing pipeline
├── test_pdf_extractor.py         # PDF text extraction
├── test_receipt_dataclasses.py   # Data model validation
└── test_receipt_bot_handler.py   # Discord handler logic (mocked)
```

**`test_receipt_parser.py` — Receipt text parsing:**

```python
import json
from pathlib import Path

import pytest

RECEIPTS_DIR = Path(__file__).parent.parent / "receipts"


class TestReceiptLineParser:
    """Test individual line parsing patterns."""

    @pytest.mark.parametrize(
        "line,expected_name,expected_qty,expected_price",
        [
            ("Pierogi ruskie 330g    1 x26,70 26,70B", "Pierogi ruskie 330g", 1, 26.70),
            ("Kompot 250 ml          1 x17,30 17,30B", "Kompot 250 ml", 1, 17.30),
            ("torbanazakupymałaDKT_ON 1 * 0,90 0,90 A", "torbanazakupymałaDKT_ON", 1, 0.90),
            ("Banany  x1.234kg  8,72 A", "Banany", 1.234, 8.72),
        ],
    )
    def test_parse_single_line_item(self, line, expected_name, expected_qty, expected_price):
        ...

    def test_parse_multi_line_item(self):
        """Format B: product name on first line, price on second."""
        ...

    def test_parse_item_with_article_code(self):
        """Format C: article code prefix (Pepco, Kaufland)."""
        ...

    def test_parse_fuel_station_format(self):
        """Format D: technical product codes with dot decimal in unit price."""
        ...

    def test_parse_discount_line(self):
        """Negative amount lines (OBNIŻKA, RABAT, UPUST)."""
        ...

    def test_discount_attached_to_preceding_item(self):
        """Discount line should be associated with the item above it."""
        ...


class TestReceiptTextParser:
    """Test full receipt text → ParsedReceipt conversion."""

    @pytest.mark.parametrize("receipt_name", [
        "folgujemy_01",
        "pepco_01",
        "orlen_01",
        "bar_pierozek_01",
    ])
    def test_parse_from_ocr_output(self, receipt_name):
        """Parse stored OCR text and compare against expected JSON fixture."""
        ocr_text = (RECEIPTS_DIR / "ocr_outputs" / f"{receipt_name}.txt").read_text()
        expected = json.loads((RECEIPTS_DIR / "expected" / f"{receipt_name}.json").read_text())

        result = parse_receipt_text(ocr_text)

        assert result.store_name == expected["store_name"]
        assert result.total == pytest.approx(expected["total"], abs=0.01)
        assert len(result.items) == len(expected["items"])
        for parsed_item, expected_item in zip(result.items, expected["items"]):
            assert parsed_item.name == expected_item["name"]
            assert parsed_item.total_price == pytest.approx(expected_item["total_price"], abs=0.01)

    def test_tax_section_filtered_out(self):
        """Lines like 'SPRZEDAŻ OPODATKOWANA' and 'PTU' should not appear as items."""
        ...

    def test_suma_line_extracted_as_total(self):
        """'SUMA PLN' line should set the receipt total, not be parsed as an item."""
        ...

    def test_empty_text_raises_parse_error(self):
        ...

    def test_no_items_found_raises_parse_error(self):
        ...


class TestDateExtraction:
    """Test date parsing from various receipt formats."""

    @pytest.mark.parametrize("text,expected_date", [
        ("2026-04-18 18:50", "2026-04-18"),
        ("2026-04-30  20:15", "2026-04-30"),
        ("00050 #001 KIEROWNIK    2026-04-24 14:38", "2026-04-24"),
    ])
    def test_extract_date(self, text, expected_date):
        ...


class TestTotalValidation:
    """Test sum of items vs. declared total."""

    def test_items_sum_matches_total(self):
        ...

    def test_items_sum_mismatch_flagged(self):
        ...

    def test_discount_items_reduce_sum(self):
        ...
```

**`test_ocr_provider.py` — Provider abstraction:**

```python
class TestOCRProviderFactory:
    def test_create_tesseract_provider(self):
        ...

    def test_create_unknown_provider_raises(self):
        ...

    def test_provider_interface_contract(self):
        """All providers must implement the extract_text method."""
        ...
```

**`test_image_preprocessing.py` — Pillow pipeline:**

```python
from PIL import Image

class TestImagePreprocessing:
    def test_converts_to_grayscale(self):
        ...

    def test_output_dimensions_within_bounds(self):
        """Preprocessing should resize very large images."""
        ...

    def test_handles_rotated_image(self):
        ...

    def test_handles_various_input_formats(self):
        """Should accept jpg, png, webp."""
        ...
```

**`test_pdf_extractor.py` — PDF text extraction:**

```python
class TestPDFExtractor:
    @pytest.mark.parametrize("pdf_name", [
        "kaufland_digital_01",
        "lidl_digital_01",
        "zabka_digital_01",
    ])
    def test_extract_text_from_pdf(self, pdf_name):
        """Extract text from a real PDF and verify it contains expected content."""
        ...

    def test_corrupted_pdf_raises_error(self):
        ...

    def test_empty_pdf_raises_error(self):
        ...
```

**`test_receipt_bot_handler.py` — Discord handler (mocked):**

```python
from unittest.mock import AsyncMock, MagicMock

class TestReceiptMessageHandler:
    def test_image_attachment_triggers_ocr_flow(self):
        ...

    def test_pdf_attachment_triggers_pdf_flow(self):
        ...

    def test_no_attachment_ignored(self):
        ...

    def test_success_reacts_with_checkmark(self):
        ...

    def test_ocr_failure_reacts_with_x(self):
        ...

    def test_partial_parse_reacts_with_warning(self):
        ...
```

#### 5.2.3 Integration Tests

Integration tests verify the full pipeline with real dependencies — Tesseract OCR engine, Actual Budget server, and the real receipt images. These run inside Docker (same as existing integration tests).

**Test file structure:**

```
tests/integration_tests/
├── test_actual_connector.py       # Existing
├── test_ocr_pipeline.py           # OCR on real images
├── test_receipt_end_to_end.py     # Full flow: image → parsed receipt → Actual Budget
└── conftest.py                    # Shared fixtures (Actual connection, test images)
```

**`test_ocr_pipeline.py` — Real OCR on receipt photos:**

These tests require Tesseract to be installed (run inside Docker or a CI environment with `tesseract-ocr-pol`).

```python
import json
from pathlib import Path

import pytest
from PIL import Image

RECEIPTS_DIR = Path(__file__).parent.parent / "receipts"
IMAGES_DIR = RECEIPTS_DIR / "images"
EXPECTED_DIR = RECEIPTS_DIR / "expected"


@pytest.fixture
def ocr_provider():
    """Create a real TesseractProvider for integration testing."""
    ...


class TestTesseractOCR:
    """Integration tests: real images through Tesseract OCR."""

    @pytest.mark.parametrize("image_name,expected_fixture", [
        ("folgujemy_01.jpg", "folgujemy_01.json"),
        ("pepco_01.jpg", "pepco_01.json"),
        ("orlen_01.jpg", "orlen_01.json"),
        ("bar_pierozek_01.jpg", "bar_pierozek_01.json"),
    ])
    def test_ocr_produces_parseable_text(self, ocr_provider, image_name, expected_fixture):
        """OCR output from a real image should be parseable into the expected receipt."""
        image = Image.open(IMAGES_DIR / image_name)
        ocr_text = ocr_provider.extract_text(image)

        # Verify OCR output is non-empty and contains key markers
        assert len(ocr_text) > 50
        assert "PARAGON" in ocr_text.upper() or "FISKALNY" in ocr_text.upper()

    @pytest.mark.parametrize("image_name,expected_fixture", [
        ("folgujemy_01.jpg", "folgujemy_01.json"),
        ("pepco_01.jpg", "pepco_01.json"),
        ("orlen_01.jpg", "orlen_01.json"),
        ("bar_pierozek_01.jpg", "bar_pierozek_01.json"),
    ])
    def test_full_ocr_to_parsed_receipt(self, ocr_provider, image_name, expected_fixture):
        """End-to-end: real image → OCR → parser → verify against expected fixture."""
        image = Image.open(IMAGES_DIR / image_name)
        expected = json.loads((EXPECTED_DIR / expected_fixture).read_text())

        ocr_text = ocr_provider.extract_text(image)
        result = parse_receipt_text(ocr_text)

        # Store name should match (may have minor OCR differences — use fuzzy or exact)
        assert result.store_name.lower() == expected["store_name"].lower()
        # Total must match exactly
        assert result.total == pytest.approx(expected["total"], abs=0.01)
        # Item count should match
        assert len(result.items) == len(expected["items"])
        # Each item's total_price should match within tolerance
        for parsed_item, expected_item in zip(result.items, expected["items"]):
            assert parsed_item.total_price == pytest.approx(
                expected_item["total_price"], abs=0.01
            )

    def test_blurry_image_raises_ocr_error(self, ocr_provider):
        """An intentionally unreadable image should raise a clear error."""
        image = Image.open(IMAGES_DIR / "blurry_unreadable.jpg")
        with pytest.raises(OCRError):
            ocr_provider.extract_text(image)

    def test_preprocessing_improves_ocr_accuracy(self, ocr_provider):
        """Preprocessing a receipt image should produce equal or better OCR results."""
        raw_image = Image.open(IMAGES_DIR / "folgujemy_01.jpg")
        preprocessed = preprocess_image(raw_image)

        raw_text = ocr_provider.extract_text(raw_image)
        preprocessed_text = ocr_provider.extract_text(preprocessed)

        # Preprocessed should contain at least as many recognized items
        raw_items = count_parseable_items(raw_text)
        preprocessed_items = count_parseable_items(preprocessed_text)
        assert preprocessed_items >= raw_items


class TestOCRRegression:
    """Regression tests: OCR output should not degrade after Tesseract/preprocessing changes."""

    @pytest.mark.parametrize("image_name", [
        "folgujemy_01",
        "pepco_01",
        "orlen_01",
        "bar_pierozek_01",
    ])
    def test_ocr_output_matches_baseline(self, ocr_provider, image_name):
        """Compare current OCR output against stored baseline text.

        If OCR output changes (e.g., after Tesseract upgrade), update the baseline
        files in tests/receipts/ocr_outputs/ after verifying the new output is correct.
        """
        image = Image.open(IMAGES_DIR / f"{image_name}.jpg")
        baseline_text = (RECEIPTS_DIR / "ocr_outputs" / f"{image_name}.txt").read_text()

        current_text = ocr_provider.extract_text(preprocess_image(image))

        # Use similarity ratio rather than exact match (minor whitespace differences OK)
        from difflib import SequenceMatcher
        similarity = SequenceMatcher(None, baseline_text, current_text).ratio()
        assert similarity > 0.90, (
            f"OCR output for {image_name} drifted significantly from baseline "
            f"(similarity: {similarity:.2%}). Review and update baseline if correct."
        )
```

**`test_receipt_end_to_end.py` — Full flow to Actual Budget:**

```python
import json
from pathlib import Path

import pytest
from PIL import Image

RECEIPTS_DIR = Path(__file__).parent.parent / "receipts"


class TestReceiptToActualBudget:
    """End-to-end: receipt image → OCR → parse → split transaction in Actual Budget."""

    @pytest.fixture
    def actual_with_account(self, actual):
        """Provide an Actual Budget instance with a test account."""
        ...

    @pytest.mark.parametrize("image_name,expected_fixture", [
        ("folgujemy_01.jpg", "folgujemy_01.json"),
        ("bar_pierozek_01.jpg", "bar_pierozek_01.json"),
    ])
    def test_receipt_creates_split_transaction(
        self, actual_with_account, ocr_provider, image_name, expected_fixture
    ):
        """A receipt image should produce a correctly structured split transaction."""
        image = Image.open(RECEIPTS_DIR / "images" / image_name)
        expected = json.loads((RECEIPTS_DIR / "expected" / expected_fixture).read_text())

        # Process receipt
        ocr_text = ocr_provider.extract_text(preprocess_image(image))
        parsed_receipt = parse_receipt_text(ocr_text)

        # Create transaction in Actual Budget
        transaction = create_split_transaction(actual_with_account, parsed_receipt)

        # Verify transaction structure
        assert transaction.payee == parsed_receipt.store_name
        assert transaction.amount == pytest.approx(-expected["total"] * 100)  # cents
        assert len(transaction.splits) == len(expected["items"])

    def test_duplicate_receipt_not_created_twice(self, actual_with_account, ocr_provider):
        """Processing the same receipt twice should not create duplicate transactions."""
        image = Image.open(RECEIPTS_DIR / "images" / "folgujemy_01.jpg")

        ocr_text = ocr_provider.extract_text(preprocess_image(image))
        parsed_receipt = parse_receipt_text(ocr_text)

        create_split_transaction(actual_with_account, parsed_receipt)
        # Second attempt should detect duplicate
        result = create_split_transaction(actual_with_account, parsed_receipt)
        assert result.is_duplicate

    def test_receipt_with_discount_creates_correct_splits(
        self, actual_with_account, ocr_provider
    ):
        """Receipts with discount lines should include them as negative sub-transactions."""
        image = Image.open(RECEIPTS_DIR / "images" / "orlen_01.jpg")

        ocr_text = ocr_provider.extract_text(preprocess_image(image))
        parsed_receipt = parse_receipt_text(ocr_text)

        transaction = create_split_transaction(actual_with_account, parsed_receipt)

        # Should have a negative split for the discount
        discount_splits = [s for s in transaction.splits if s.amount > 0]  # positive = reduces expense
        assert len(discount_splits) >= 1
```

#### 5.2.4 Test Configuration & CI

**Docker setup for integration tests:**

The integration test Docker service must include Tesseract with the Polish language pack:

```dockerfile
# docker-compose.yml — testing service additions
integration_tests:
  build:
    context: .
    dockerfile: Dockerfile.test
  environment:
    - ACTUAL_TEST_URL=http://actual-server:5006
  depends_on:
    - actual-server
  volumes:
    - ./tests/receipts:/app/tests/receipts
```

```dockerfile
# Dockerfile.test additions
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-pol \
    && rm -rf /var/lib/apt/lists/*
```

**pytest markers for selective test execution:**

```python
# conftest.py (root or integration_tests/)
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "ocr: tests requiring Tesseract OCR engine")
    config.addinivalue_line("markers", "slow: tests that take >5s (e.g., full OCR pipeline)")
```

```ini
# pyproject.toml additions
[tool.pytest.ini_options]
markers = [
    "ocr: tests requiring Tesseract OCR engine",
    "slow: tests that take >5s (full OCR pipeline)",
]
```

This allows running fast unit tests separately: `pytest -m "not ocr"` for quick feedback during development, and the full suite (including OCR integration tests) in CI/Docker.

#### 5.2.5 Coverage Requirements

| Component | Minimum Coverage Target |
|-----------|------------------------|
| Receipt text parser (`receipt_parser.py`) | 95% |
| Image preprocessing pipeline | 80% |
| OCR provider abstraction | 90% |
| PDF text extraction | 90% |
| Discord handler (receipt flow) | 85% |
| Transaction creation logic | 90% |

#### 5.2.6 Test Data Maintenance

- **Adding new stores:** When a new receipt format is encountered, add the photo to `tests/receipts/images/`, run OCR to generate the baseline text file, manually create the expected JSON fixture, and add parametrized test cases.
- **Updating baselines:** After a Tesseract upgrade or preprocessing change, re-run OCR on all test images and review diffs. Update `ocr_outputs/*.txt` baselines only after verifying correctness.
- **Receipt privacy:** All test receipts should be from the project maintainer's own purchases. Blur or remove any personal information (names on cards, loyalty numbers) before committing.

## Implementation Order

| Phase | Task | Priority | Effort |
|-------|------|----------|--------|
| 1.1 | Image download from Discord | High | Small |
| 1.2 | OCR provider abstraction + Tesseract impl | High | Medium |
| 1.3 | Image preprocessing pipeline | High | Medium |
| 1.4 | PDF text extraction pipeline | High | Small |
| 2.1 | Attachment type detection & routing (image vs PDF) | High | Small |
| 2.2 | Receipt line parser (regex, multi-line handling) | High | Large |
| 2.3 | Discount/negative amount handling | High | Medium |
| 2.4 | Tax section detection & filtering | High | Small |
| 2.5 | Date extraction from receipt text | Medium | Small |
| 2.6 | Total validation | Medium | Small |
| 3.1 | Transaction deduplication & matching logic | High | Medium |
| 3.2 | Split transaction creation (with reconciliation) | High | Medium |
| 3.3 | Sum mismatch interactive flow | Medium | Medium |
| 4.1 | Discord channel config + handler | High | Small |
| 4.2 | Error handling + user feedback | Medium | Small |
| 4.3 | Bank-notification handler dedup check | High | Small |
| 5.1 | Docker Tesseract installation | High | Small |
| 5.2 | Test data collection + fixtures | High | Medium |
| 5.3 | Unit tests (parser, preprocessing, PDF, handler) | High | Medium |
| 5.4 | Integration tests (OCR pipeline on real images) | High | Medium |
| 5.5 | End-to-end tests (image → Actual Budget) | High | Medium |
| 5.6 | OCR regression baseline tests | Medium | Small |
| 6.1 | Item name transformer plugin system | Low | Small |
| 6.2 | Category assigner plugin system | Low | Small |
| 6.3 | Cloud OCR provider (Textract or Vision) | Low | Small |

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Poor OCR quality on phone photos | High | Image preprocessing; user guidance on photo quality; option to switch to cloud OCR |
| Varying receipt formats across stores | High | Start with top 3-5 stores; make parser configurable |
| Polish diacritics misread by OCR | Medium | Use pol language pack; fuzzy matching for known products; item name transformers |
| Split amounts don't sum to total | Medium | Interactive correction flow; user can accept with adjustment or provide corrections |
| Duplicate transactions (receipt + bank notification) | High | Deduplication matching by amount/date/payee before creating |
| Large images slow down bot | Low | Resize before OCR; process asynchronously |
| Cloud OCR costs | Low | Local Tesseract as default; cloud is opt-in via config |

## Success Criteria

1. Bot can parse a clear receipt photo from Carrefour, Biedronka, or Lidl with >90% item accuracy
2. Split transaction appears correctly in Actual Budget with store name as payee
3. No duplicate transactions when both receipt and bank notification arrive for the same purchase
4. Sum mismatches are handled interactively — user always has control over the final transaction
5. OCR provider can be switched via a single config variable without code changes
6. Processing time < 10 seconds per receipt (local Tesseract)
7. Graceful failure with helpful user feedback on unparseable receipts
