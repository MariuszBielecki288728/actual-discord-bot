# Future improvements

This document is the single home for ideas that are intentionally not yet
implemented. It describes possible directions, not commitments or current
behavior. Current behavior is documented in [Architecture](ARCHITECTURE.md).

## Receipt correction workflow

Receipts whose item sum differs from the declared total by more than PLN 0.02
are currently rejected with a warning. A future interactive workflow could show
the parsed merchant, date, items, and difference, then let the user correct or
confirm the data before anything is saved.

Any design should preserve these properties:

- no transaction is written before explicit confirmation;
- corrections are tied to the original Discord message and expire;
- concurrent users cannot alter one another's pending receipt;
- retries remain idempotent; and
- raw receipt data and internal errors are not exposed outside the configured
  private channel.

## Product-name normalization

A post-parse transformer could expand store abbreviations and normalize noisy
OCR names before split transactions are created. This should be an injected
interface with a no-op default so dictionaries or fuzzy matching can be added
without coupling them to `ReceiptParser` or Discord.

Useful first steps include collecting representative abbreviations, defining
deterministic precedence for global and store-specific rules, and measuring
false expansions against the receipt fixtures.

## Automatic category assignment

Receipt items currently become uncategorized splits. A separate injected
category assigner could map normalized item names to Actual Budget category IDs.
Potential implementations include a local rules file, learned mappings from
past transactions, or an external classifier.

The integration needs a defined fallback for unknown items and a safe response
when configured category IDs no longer exist. Category assignment should remain
independent of text extraction and parsing.

## Cloud OCR backends

`AmazonTextractProvider` and `GoogleCloudVisionProvider` exist as placeholders
and raise `NotImplementedError`. Implementing either backend requires:

- optional dependencies and provider-specific configuration;
- credential validation without logging secrets;
- request timeouts, retry policy, and actionable error translation;
- an explicit privacy and cost model for uploaded receipts; and
- parity tests against the `OCRProvider` contract.

Local Tesseract should remain the default and cloud upload must be opt-in.

## Additional banks

The notification parser accepts an injected `BaseNotification` subtype, but the
application always selects `PekaoNotification`. Supporting more banks requires
bank-specific fixtures and parsers plus a configuration-driven selection or
dispatch mechanism. Ambiguous messages must never be imported by more than one
parser.

## Broader receipt-format support

The parser covers the formats represented by the current fixtures but receipt
layouts vary by retailer, point-of-sale software, and OCR quality. Improvements
could include store-specific parsing strategies, better deskewing and receipt
boundary detection, safe downscaling of large images before OCR, scanned-PDF OCR
fallback, and more robust handling of weighted items or damaged receipts.

Changes in this area should add anonymized fixtures and regression tests. Parser
accuracy and processing-time targets should be measured on a documented corpus
rather than stated as assumptions.
