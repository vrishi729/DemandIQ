import io
import os
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings

UPLOAD_DIR = Path('uploads')

CANONICAL_COLUMNS = {
    'order_date': [
        'order date',
        'order_date',
        'date',
        'transaction date',
        'transaction_date',
    ],
    'product_name': [
        'product name',
        'product_name',
        'product',
        'item',
        'item name',
        'item_name',
    ],
    'category': [
        'category',
        'product category',
        'product_category',
        'item category',
        'item_category',
    ],
    'quantity_sold': [
        'quantity sold',
        'quantity_sold',
        'quantity',
        'qty',
        'units sold',
        'units_sold',
    ],
    'unit_price': [
        'unit price',
        'unit_price',
        'unit price inr',
        'unit_price_inr',
        'price',
        'price per unit',
        'price_per_unit',
    ],
    'revenue': [
        'revenue',
        'revenue inr',
        'revenue_inr',
        'total revenue',
        'total_revenue',
        'sales',
        'total sales',
        'total_sales',
        'amount',
    ],
}

REQUIRED_COLUMNS = ['order_date', 'product_name', 'quantity_sold', 'unit_price']

ALLOWED_EXTENSIONS = {'.csv', '.xlsx', '.xls'}

CANONICAL_DISPLAY = {
    'order_date': 'Order Date',
    'product_name': 'Product Name',
    'category': 'Category',
    'quantity_sold': 'Quantity Sold',
    'unit_price': 'Unit Price',
    'revenue': 'Revenue',
}


def detect_columns(content: bytes, filename: str) -> dict[str, Any]:
    df = read_file_to_dataframe(content, filename)
    headers = list(df.columns)
    auto_map = _map_headers(headers)
    samples: list[dict[str, str]] = []
    for _, row in df.head(5).iterrows():
        samples.append({h: str(row[h]) for h in headers})
    return {
        'detected_columns': headers,
        'sample_rows': samples,
        'auto_mapping': auto_map,
        'canonical_fields': list(CANONICAL_COLUMNS.keys()),
        'canonical_labels': CANONICAL_DISPLAY,
        'required_fields': REQUIRED_COLUMNS,
    }


def _normalize_header(header: str) -> str:
    return header.strip().lower()


def _map_headers(raw_headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    normalized = {h: _normalize_header(h) for h in raw_headers}

    for canonical, variants in CANONICAL_COLUMNS.items():
        for raw, norm in zip(raw_headers, [normalized[h] for h in raw_headers], strict=False):
            if norm in variants or norm == canonical:
                mapping[canonical] = raw
                break

    return mapping


class ValidationError(Exception):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class HealthSummary:
    def __init__(self) -> None:
        self.total_rows: int = 0
        self.missing_required_columns: list[str] = []
        self.missing_optional_columns: list[str] = []
        self.duplicate_rows: int = 0
        self.invalid_dates: int = 0
        self.negative_quantities: int = 0
        self.missing_values: dict[str, int] = {}
        self.empty_columns: list[str] = []
        self.type_errors: dict[str, list[str]] = {}
        self.is_valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            'total_rows': self.total_rows,
            'missing_required_columns': self.missing_required_columns,
            'missing_optional_columns': self.missing_optional_columns,
            'duplicate_rows': self.duplicate_rows,
            'invalid_dates': self.invalid_dates,
            'negative_quantities': self.negative_quantities,
            'missing_values': self.missing_values,
            'empty_columns': self.empty_columns,
            'type_errors': self.type_errors,
            'is_valid': self.is_valid,
        }


def validate_file_extension(filename: str) -> None:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f'Unsupported file type "{ext}". Allowed: {", ".join(ALLOWED_EXTENSIONS)}',
        )


def validate_file_size(file_size: int) -> None:
    max_bytes = settings.upload_max_size_bytes
    if file_size > max_bytes:
        raise ValidationError(
            f'File size {file_size / 1024 / 1024:.1f} MB exceeds the maximum '
            f'of {settings.upload_max_size_mb} MB',
        )


def read_file_to_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    ext = os.path.splitext(filename)[1].lower()
    try:
        if ext == '.csv':
            try:
                return pd.read_csv(
                    io.BytesIO(content), encoding='utf-8-sig',
                    dtype_backend='numpy_nullable',
                )
            except (UnicodeDecodeError, pd.errors.ParserError):
                return pd.read_csv(
                    io.BytesIO(content), encoding='latin-1',
                    sep=None, engine='python',
                    dtype_backend='numpy_nullable',
                )
        else:
            return pd.read_excel(io.BytesIO(content), dtype_backend='numpy_nullable')
    except Exception as e:
        raise ValidationError(f'Failed to parse file: {e!s}') from e


def validate_and_summarize(df: pd.DataFrame) -> HealthSummary:
    summary = HealthSummary()
    summary.total_rows = len(df)
    original_columns = list(df.columns)

    if not original_columns:
        summary.is_valid = False
        summary.missing_required_columns = list(REQUIRED_COLUMNS)
        return summary

    header_map = _map_headers(original_columns)

    for col in REQUIRED_COLUMNS:
        if col not in header_map:
            summary.missing_required_columns.append(col)
            summary.is_valid = False

    for col in ['category', 'revenue']:
        if col not in header_map:
            summary.missing_optional_columns.append(col)

    if not summary.is_valid:
        return summary

    mapped_df = df.rename(columns={v: k for k, v in header_map.items()})
    mapped_df = mapped_df[list(header_map.keys())]

    for col in mapped_df.columns:
        missing_count = int(mapped_df[col].isna().sum())
        if missing_count > 0:
            summary.missing_values[col] = missing_count

        if mapped_df[col].dropna().empty:
            summary.empty_columns.append(col)

    duplicate_count = int(mapped_df.duplicated().sum())
    summary.duplicate_rows = duplicate_count

    if 'order_date' in mapped_df.columns:
        parsed_dates = pd.to_datetime(
            mapped_df['order_date'], errors='coerce',
        )
        invalid_date_count = int(parsed_dates.isna().sum())
        summary.invalid_dates = invalid_date_count

    if 'quantity_sold' in mapped_df.columns:
        qty = mapped_df['quantity_sold']
        try:
            qty_num = pd.to_numeric(qty, errors='coerce')
            neg_mask = (qty_num < 0) & qty_num.notna()
            summary.negative_quantities = int(neg_mask.sum())
        except (ValueError, TypeError):
            summary.type_errors.setdefault('quantity_sold', [])
            summary.type_errors['quantity_sold'].append('Could not convert to numeric')

    return summary


def parse_and_validate(
    content: bytes,
    filename: str,
    file_size: int,
) -> tuple[pd.DataFrame, HealthSummary, str]:
    validate_file_extension(filename)
    validate_file_size(file_size)

    df = read_file_to_dataframe(content, filename)
    summary = validate_and_summarize(df)

    stored_filename = f'{uuid.uuid4().hex}{os.path.splitext(filename)[1]}'
    return df, summary, stored_filename
