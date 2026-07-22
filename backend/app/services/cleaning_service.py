from typing import Any

import pandas as pd


def _strip_currency(series: pd.Series) -> pd.Series:
    return series.astype(str).str.replace(r'[$,€£¥\s]', '', regex=True).str.strip()


def clean_dataframe(
    df: pd.DataFrame,
    header_map: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    report: dict[str, Any] = {
        'rows_before': len(df),
        'rows_after': 0,
        'duplicates_removed': 0,
        'rows_dropped_missing_date': 0,
        'rows_dropped_missing_product': 0,
        'rows_dropped_missing_quantity': 0,
        'rows_dropped_missing_price': 0,
        'categories_imputed': 0,
        'revenues_computed': 0,
        'product_names_normalized': 0,
    }

    mapped = df.rename(columns={v: k for k, v in header_map.items()})
    cols = list(header_map.keys())
    mapped = mapped[cols]

    before = len(mapped)
    mapped = mapped.drop_duplicates()
    report['duplicates_removed'] = before - len(mapped)

    if 'order_date' in mapped.columns:
        before = len(mapped)
        mapped = mapped.dropna(subset=['order_date'])
        report['rows_dropped_missing_date'] = before - len(mapped)

        mapped['order_date'] = pd.to_datetime(
            mapped['order_date'],
            errors='coerce',
        )
        before = len(mapped)
        mapped = mapped.dropna(subset=['order_date'])
        report['rows_dropped_missing_date'] += before - len(mapped)

    if 'product_name' in mapped.columns:
        before = len(mapped)
        mapped = mapped.dropna(subset=['product_name'])
        report['rows_dropped_missing_product'] = before - len(mapped)

        mapped['product_name'] = (
            mapped['product_name']
            .astype(str)
            .str.strip()
            .str.replace(r'\s+', ' ', regex=True)
            .str.title()
        )
        report['product_names_normalized'] = int((mapped['product_name'] != '').sum())

    if 'category' in mapped.columns:
        imputed = mapped['category'].isna().sum()
        mapped['category'] = mapped['category'].fillna('Uncategorized')
        mapped['category'] = mapped['category'].astype(str).str.strip().str.title()
        report['categories_imputed'] = int(imputed)

    if 'quantity_sold' in mapped.columns:
        before = len(mapped)
        mapped = mapped.dropna(subset=['quantity_sold'])
        report['rows_dropped_missing_quantity'] = before - len(mapped)

        mapped['quantity_sold'] = pd.to_numeric(
            _strip_currency(mapped['quantity_sold']),
            errors='coerce',
        )
        before = len(mapped)
        mask = (mapped['quantity_sold'] <= 0) | mapped['quantity_sold'].isna()
        mapped = mapped[~mask]
        report['rows_dropped_missing_quantity'] += before - len(mapped)
        mapped['quantity_sold'] = mapped['quantity_sold'].round().astype(int)

    if 'unit_price' in mapped.columns:
        before = len(mapped)
        mapped = mapped.dropna(subset=['unit_price'])
        report['rows_dropped_missing_price'] = before - len(mapped)

        mapped['unit_price'] = pd.to_numeric(_strip_currency(mapped['unit_price']), errors='coerce')
        before = len(mapped)
        mapped = mapped.dropna(subset=['unit_price'])
        report['rows_dropped_missing_price'] += before - len(mapped)

    has_quantity = 'quantity_sold' in mapped.columns
    has_unit_price = 'unit_price' in mapped.columns
    if has_quantity and has_unit_price:
        if 'revenue' not in mapped.columns:
            mapped['revenue'] = mapped['quantity_sold'] * mapped['unit_price']
            report['revenues_computed'] = int(len(mapped))
        else:
            mapped['revenue'] = pd.to_numeric(_strip_currency(mapped['revenue']), errors='coerce')
            has_revenue = mapped['revenue'].notna()
            missing_rev = (~has_revenue).sum()
            mapped.loc[~has_revenue, 'revenue'] = (
                mapped.loc[~has_revenue, 'quantity_sold'] * mapped.loc[~has_revenue, 'unit_price']
            )
            report['revenues_computed'] = int(missing_rev)

    report['rows_after'] = len(mapped)
    return mapped, report
