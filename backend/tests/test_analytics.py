import uuid
from datetime import date

import pytest

from app.analytics.engine import (
    get_category_performance,
    get_kpi_summary,
    get_sales_growth,
    get_sales_trends,
    get_top_products,
)
from app.models.sales_record import SalesRecord


@pytest.fixture
def sample_records() -> list[SalesRecord]:
    uid = uuid.uuid4()
    did = uuid.uuid4()
    return [
        SalesRecord(
            id=uuid.uuid4(),
            dataset_id=did,
            user_id=uid,
            order_date=date(2024, 1, 5),
            product_name='Coffee',
            category='Beverages',
            quantity_sold=15,
            unit_price=12.50,
            revenue=187.50,
        ),
        SalesRecord(
            id=uuid.uuid4(),
            dataset_id=did,
            user_id=uid,
            order_date=date(2024, 1, 6),
            product_name='Milk',
            category='Dairy',
            quantity_sold=30,
            unit_price=3.99,
            revenue=119.70,
        ),
        SalesRecord(
            id=uuid.uuid4(),
            dataset_id=did,
            user_id=uid,
            order_date=date(2024, 2, 5),
            product_name='Coffee',
            category='Beverages',
            quantity_sold=20,
            unit_price=12.50,
            revenue=250.00,
        ),
    ]


@pytest.mark.asyncio
async def test_kpi_summary(db_session, sample_records):
    db_session.add_all(sample_records)
    await db_session.commit()

    uid = sample_records[0].user_id
    kpi = await get_kpi_summary(db_session, uid)

    assert kpi['total_revenue'] == 557.20
    assert kpi['total_orders'] == 3
    assert kpi['total_quantity_sold'] == 65
    assert kpi['average_order_value'] == 185.73


@pytest.mark.asyncio
async def test_top_products(db_session, sample_records):
    db_session.add_all(sample_records)
    await db_session.commit()

    uid = sample_records[0].user_id
    top = await get_top_products(db_session, uid)

    assert len(top) == 2
    assert top[0]['product_name'] == 'Coffee'
    assert top[0]['total_quantity'] == 35
    assert top[1]['product_name'] == 'Milk'


@pytest.mark.asyncio
async def test_category_performance(db_session, sample_records):
    db_session.add_all(sample_records)
    await db_session.commit()

    uid = sample_records[0].user_id
    cats = await get_category_performance(db_session, uid)

    assert len(cats) == 2
    cat_map = {c['category']: c for c in cats}
    assert cat_map['Beverages']['total_revenue'] == 437.50
    assert cat_map['Dairy']['total_revenue'] == 119.70


@pytest.mark.asyncio
async def test_sales_trends(db_session, sample_records):
    db_session.add_all(sample_records)
    await db_session.commit()

    uid = sample_records[0].user_id
    trends = await get_sales_trends(db_session, uid, granularity='month')

    assert len(trends) == 2
    assert trends[0]['total_revenue'] == 307.20
    assert trends[1]['total_revenue'] == 250.00


@pytest.mark.asyncio
async def test_sales_growth(db_session, sample_records):
    db_session.add_all(sample_records)
    await db_session.commit()

    uid = sample_records[0].user_id
    growth = await get_sales_growth(db_session, uid)

    # Jan: 307.20, Feb: 250.00 -> decline
    assert growth['growth_rate'] < 0
    assert growth['previous_period_revenue'] > growth['current_period_revenue']
