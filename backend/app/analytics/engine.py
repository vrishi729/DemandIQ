import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Select

from app.core.db_utils import date_trunc as date_trunc_fn
from app.models.sales_record import SalesRecord


def _filtered_query(
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Select[tuple[SalesRecord]]:
    q = select(SalesRecord).where(SalesRecord.user_id == user_id)
    if dataset_id is not None:
        q = q.where(SalesRecord.dataset_id == dataset_id)
    if start_date is not None:
        q = q.where(SalesRecord.order_date >= start_date)
    if end_date is not None:
        q = q.where(SalesRecord.order_date <= end_date)
    return q


async def get_kpi_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    base = _filtered_query(user_id, dataset_id, start_date, end_date)

    count_q = select(func.count()).select_from(base.subquery())
    result = await db.execute(count_q)
    total_orders: int = result.scalar_one() or 0

    revenue_q = select(func.coalesce(func.sum(SalesRecord.revenue), 0)).where(
        SalesRecord.user_id == user_id,
    )
    if dataset_id is not None:
        revenue_q = revenue_q.where(SalesRecord.dataset_id == dataset_id)
    if start_date is not None:
        revenue_q = revenue_q.where(SalesRecord.order_date >= start_date)
    if end_date is not None:
        revenue_q = revenue_q.where(SalesRecord.order_date <= end_date)

    result = await db.execute(revenue_q)
    total_revenue: float = float(result.scalar_one() or 0)

    qty_q = select(func.coalesce(func.sum(SalesRecord.quantity_sold), 0)).where(
        SalesRecord.user_id == user_id,
    )
    if dataset_id is not None:
        qty_q = qty_q.where(SalesRecord.dataset_id == dataset_id)
    if start_date is not None:
        qty_q = qty_q.where(SalesRecord.order_date >= start_date)
    if end_date is not None:
        qty_q = qty_q.where(SalesRecord.order_date <= end_date)

    result = await db.execute(qty_q)
    total_quantity: int = int(result.scalar_one() or 0)

    avg_order_value = round(total_revenue / total_orders, 2) if total_orders > 0 else 0.0

    return {
        'total_revenue': round(total_revenue, 2),
        'total_orders': total_orders,
        'total_quantity_sold': total_quantity,
        'average_order_value': avg_order_value,
    }


async def get_top_products(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
    limit: int = 10,
    order: str = 'desc',
    start_date: date | None = None,
    year: str | None = None,
) -> list[dict[str, Any]]:
    q = (
        select(
            SalesRecord.product_name,
            func.sum(SalesRecord.quantity_sold).label('total_quantity'),
            func.sum(SalesRecord.revenue).label('total_revenue'),
            func.count().label('order_count'),
        )
        .where(SalesRecord.user_id == user_id)
        .group_by(SalesRecord.product_name)
    )
    if dataset_id is not None:
        q = q.where(SalesRecord.dataset_id == dataset_id)
    if start_date is not None:
        q = q.where(SalesRecord.order_date >= start_date)
    if year is not None:
        q = q.where(func.strftime('%Y', SalesRecord.order_date) == year)

    order_func = (
        func.sum(SalesRecord.revenue).desc()
        if order == 'desc'
        else func.sum(SalesRecord.revenue)
    )
    q = q.order_by(order_func).limit(limit)

    result = await db.execute(q)
    rows = result.all()

    return [
        {
            'product_name': row.product_name,
            'total_quantity': int(row.total_quantity),
            'total_revenue': round(float(row.total_revenue or 0), 2),
            'order_count': int(row.order_count),
        }
        for row in rows
    ]


async def get_category_performance(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    q = (
        select(
            SalesRecord.category,
            func.sum(SalesRecord.quantity_sold).label('total_quantity'),
            func.sum(SalesRecord.revenue).label('total_revenue'),
            func.count().label('order_count'),
        )
        .where(SalesRecord.user_id == user_id)
        .group_by(SalesRecord.category)
        .order_by(func.sum(SalesRecord.revenue).desc())
    )
    if dataset_id is not None:
        q = q.where(SalesRecord.dataset_id == dataset_id)

    result = await db.execute(q)
    rows = result.all()

    return [
        {
            'category': row.category or 'Uncategorized',
            'total_quantity': int(row.total_quantity),
            'total_revenue': round(float(row.total_revenue or 0), 2),
            'order_count': int(row.order_count),
        }
        for row in rows
    ]


async def get_sales_trends(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
    granularity: str = 'month',
) -> list[dict[str, Any]]:
    date_trunc = date_trunc_fn(granularity, SalesRecord.order_date)

    q = (
        select(
            date_trunc,
            func.sum(SalesRecord.quantity_sold).label('total_quantity'),
            func.sum(SalesRecord.revenue).label('total_revenue'),
            func.count().label('order_count'),
        )
        .where(SalesRecord.user_id == user_id)
        .group_by(text('period'))
        .order_by(text('period'))
    )
    if dataset_id is not None:
        q = q.where(SalesRecord.dataset_id == dataset_id)

    result = await db.execute(q)
    rows = result.all()

    trends = []
    for row in rows:
        period_val = row.period
        if isinstance(period_val, datetime):
            period_str = period_val.strftime('%Y-%m-%d')
        else:
            period_str = str(period_val)

        trends.append(
            {
                'period': period_str,
                'total_quantity': int(row.total_quantity),
                'total_revenue': round(float(row.total_revenue or 0), 2),
                'order_count': int(row.order_count),
            }
        )

    return trends


async def get_sales_growth(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    trends = await get_sales_trends(db, user_id, dataset_id, 'month')

    if len(trends) < 2:
        return {'growth_rate': 0.0, 'current_period_revenue': 0.0, 'previous_period_revenue': 0.0}

    current_year = trends[-1]['period'][:4]
    previous_year = str(int(current_year) - 1)

    curr_rev = sum(t['total_revenue'] for t in trends if t['period'].startswith(current_year))
    prev_rev = sum(t['total_revenue'] for t in trends if t['period'].startswith(previous_year))

    if prev_rev > 0:
        growth_rate = round(((curr_rev - prev_rev) / prev_rev) * 100, 2)
        return {
            'growth_rate': growth_rate,
            'current_period_revenue': round(curr_rev, 2),
            'previous_period_revenue': round(prev_rev, 2),
            'current_period': current_year,
            'previous_period': previous_year,
        }

    return {'growth_rate': 0.0, 'current_period_revenue': 0.0, 'previous_period_revenue': 0.0,
            'current_period': current_year, 'previous_period': previous_year}


async def get_product_growth(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
) -> dict[str, float]:
    date_trunc = date_trunc_fn('month', SalesRecord.order_date)
    q = (
        select(
            SalesRecord.product_name,
            date_trunc,
            func.sum(SalesRecord.revenue).label('revenue'),
        )
        .where(SalesRecord.user_id == user_id)
        .group_by(SalesRecord.product_name, text('period'))
        .order_by(SalesRecord.product_name, text('period'))
    )
    if dataset_id is not None:
        q = q.where(SalesRecord.dataset_id == dataset_id)

    result = await db.execute(q)
    rows = result.all()

    product_months: dict[str, list[tuple[str, float]]] = {}
    for row in rows:
        name = row.product_name
        period = str(row.period)
        rev = float(row.revenue or 0)
        product_months.setdefault(name, []).append((period, rev))

    growth: dict[str, float] = {}
    for name, months in product_months.items():
        curr_year = months[-1][0][:4]
        prev_year = str(int(curr_year) - 1)

        curr_rev = sum(m[1] for m in months if m[0].startswith(curr_year))
        prev_rev = sum(m[1] for m in months if m[0].startswith(prev_year))

        if prev_rev > 0:
            growth[name] = round(((curr_rev - prev_rev) / prev_rev) * 100, 1)
        else:
            growth[name] = 0.0

    return growth


async def _compute_start_date(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None,
    months_back: int,
    year: str | None = None,
) -> date | None:
    from dateutil.relativedelta import relativedelta

    max_q = select(func.max(SalesRecord.order_date)).where(SalesRecord.user_id == user_id)
    if dataset_id is not None:
        max_q = max_q.where(SalesRecord.dataset_id == dataset_id)
    if year is not None:
        max_q = max_q.where(func.strftime('%Y', SalesRecord.order_date) == year)
    result = await db.execute(max_q)
    max_date = result.scalar()
    if max_date is None:
        return None
    max_dt = max_date if isinstance(max_date, date) else date.fromisoformat(str(max_date))

    return max_dt - relativedelta(months=months_back)


async def get_full_analytics(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
    months_back: int | None = None,
    year: str | None = None,
) -> dict[str, Any]:
    start = (
        await _compute_start_date(db, user_id, dataset_id, months_back, year)
        if months_back is not None else None
    )
    kpi = await get_kpi_summary(db, user_id, dataset_id)
    top_products = await get_top_products(db, user_id, dataset_id, start_date=start, year=year)
    all_products = await get_top_products(
        db, user_id, dataset_id, limit=999, start_date=start, year=year,
    )
    category_perf = await get_category_performance(db, user_id, dataset_id)
    monthly_trends = await get_sales_trends(db, user_id, dataset_id, 'month')
    growth = await get_sales_growth(db, user_id, dataset_id)
    prod_growth = await get_product_growth(db, user_id, dataset_id)

    for p in top_products:
        p['growth'] = prod_growth.get(p['product_name'], 0.0)
    for p in all_products:
        p['growth'] = prod_growth.get(p['product_name'], 0.0)

    # -- Extended summary --
    date_range_q = select(
        func.min(SalesRecord.order_date),
        func.max(SalesRecord.order_date),
    ).where(SalesRecord.user_id == user_id)
    if dataset_id is not None:
        date_range_q = date_range_q.where(SalesRecord.dataset_id == dataset_id)
    dr_result = await db.execute(date_range_q)
    min_date, max_date = dr_result.one()
    date_range = f'{min_date} – {max_date}' if min_date and max_date else None

    avg_monthly_rev = 0.0
    if monthly_trends:
        total = sum(t['total_revenue'] for t in monthly_trends)
        avg_monthly_rev = round(total / len(monthly_trends), 2)

    highest_rev_product = (
        max(all_products, key=lambda p: p['total_revenue'])['product_name']
        if all_products else None
    )
    lowest_rev_product = (
        min(all_products, key=lambda p: p['total_revenue'])['product_name']
        if all_products else None
    )

    avg_monthly_growth = 0.0
    if len(monthly_trends) >= 2:
        positive = [t['total_revenue'] for t in monthly_trends if t['total_revenue'] > 0]
        if len(positive) >= 2:
            cagr = (positive[-1] / positive[0]) ** (1 / (len(positive) - 1)) - 1
            avg_monthly_growth = round(cagr * 100, 2)

    return {
        'kpi': kpi,
        'top_products': top_products,
        'products': all_products,
        'category_performance': category_perf,
        'sales_trends': monthly_trends,
        'sales_growth': growth,
        'dataset_summary': {
            'date_range': date_range,
            'avg_monthly_revenue': avg_monthly_rev,
            'highest_revenue_product': highest_rev_product,
            'lowest_revenue_product': lowest_rev_product,
            'avg_monthly_growth': avg_monthly_growth,
        },
    }
