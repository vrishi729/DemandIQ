import uuid
from typing import Any

import pandas as pd
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import UPLOAD_DIR
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.sales_record import SalesRecord
from app.models.user import User
from app.schemas.cleaning import CleaningResponse
from app.services.cleaning_service import clean_dataframe
from app.services.upload_service import _map_headers, read_file_to_dataframe

router = APIRouter(prefix='/datasets', tags=['datasets'])


class CleanRequest(BaseModel):
    column_mapping: dict[str, str] | None = None


@router.post('/{dataset_id}/clean', response_model=CleaningResponse)
async def clean_dataset(
    dataset_id: str,
    body: CleanRequest | None = Body(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    did = uuid.UUID(dataset_id)
    result = await db.execute(
        select(Dataset).where(
            Dataset.id == did,
            Dataset.user_id == current_user.id,
        ),
    )
    dataset = result.scalar_one_or_none()

    if dataset is None:
        raise HTTPException(status_code=404, detail='Dataset not found')

    if dataset.status in ('cleaned', 'processing'):
        raise HTTPException(
            status_code=409,
            detail=f'Dataset is already {dataset.status}',
        )

    file_path = UPLOAD_DIR / dataset.stored_filename
    if not file_path.exists():
        raise HTTPException(status_code=400, detail='Uploaded file not found on disk')

    content = file_path.read_bytes()
    df = read_file_to_dataframe(content, dataset.original_filename)

    if body and body.column_mapping:
        header_map = body.column_mapping
    else:
        header_map = _map_headers(list(df.columns))
    cleaned_df, cleaning_report = clean_dataframe(df, header_map)

    existing = await db.execute(
        select(SalesRecord)
        .where(
            SalesRecord.dataset_id == dataset.id,
            SalesRecord.user_id == current_user.id,
        )
        .limit(1),
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=409,
            detail='Cleaned records already exist for this dataset',
        )

    records = []
    for _, row in cleaned_df.iterrows():
        record = SalesRecord(
            dataset_id=dataset.id,
            user_id=current_user.id,
            order_date=row['order_date'].date()
            if hasattr(row['order_date'], 'date')
            else row['order_date'],
            product_name=str(row['product_name']),
            category=str(row['category'])
            if 'category' in row and pd.notna(row['category'])
            else None,
            quantity_sold=int(row['quantity_sold']),
            unit_price=float(row['unit_price']),
            revenue=float(row['revenue'])
            if 'revenue' in row and pd.notna(row['revenue'])
            else None,
        )
        records.append(record)

    db.add_all(records)
    dataset.status = 'cleaned'
    dataset.row_count = len(records)
    await db.flush()

    product_names = cleaned_df['product_name'].dropna().unique().tolist()
    category_col = (
        cleaned_df['category'] if 'category' in cleaned_df.columns else pd.Series(dtype=str)
    )
    categories = category_col.dropna().unique().tolist()
    date_col = cleaned_df['order_date']
    date_range = (
        f'{date_col.min().strftime("%b %Y")} – {date_col.max().strftime("%b %Y")}'
        if not date_col.empty and hasattr(date_col.min(), 'strftime')
        else None
    )

    return {
        'dataset_id': str(dataset.id),
        'cleaning_report': cleaning_report,
        'total_cleaned_records': len(records),
        'summary': {
            'products': len(product_names),
            'categories': len(categories),
            'date_range': date_range,
            'product_names': product_names[:5],
            'category_names': categories,
        },
    }
