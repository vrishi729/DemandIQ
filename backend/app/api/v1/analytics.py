import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.engine import get_full_analytics
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.sales_record import SalesRecord
from app.models.user import User

router = APIRouter(prefix='/analytics', tags=['analytics'])


PERIOD_MAP = {'1m': 1, '6m': 6, '12m': 12, 'all': None}


@router.get('/overview')
async def analytics_overview(
    dataset_id: str | None = Query(None),
    period: str = Query('all'),
    year: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    did = uuid.UUID(dataset_id) if dataset_id else None
    months_back = PERIOD_MAP.get(period)

    years_q = (
        select(func.strftime('%Y', SalesRecord.order_date))
        .where(
            SalesRecord.user_id == current_user.id,
        )
        .distinct()
        .order_by(func.strftime('%Y', SalesRecord.order_date))
    )
    if did is not None:
        years_q = years_q.where(SalesRecord.dataset_id == did)
    years_result = await db.execute(years_q)
    available_years = [r[0] for r in years_result.all() if r[0]]

    result = await get_full_analytics(db, current_user.id, did, months_back=months_back, year=year)
    result['available_years'] = available_years
    return result
