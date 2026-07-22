import uuid
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import date_trunc
from app.models.forecast import Forecast
from app.models.sales_record import SalesRecord

HORIZON_MAP = {
    'day': ('day', 'D', 7),
    'week': ('week', 'W', 4),
    'month': ('month', 'ME', 3),
}


SEASONAL_PERIODS = {
    'day': 7,
    'week': 52,
    'month': 12,
}


def _holt_winters(series, steps, horizon='month'):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    seasonal_periods = SEASONAL_PERIODS.get(horizon, 12)
    if len(series) < seasonal_periods * 2:
        model = ExponentialSmoothing(
            series,
            trend='add',
            seasonal=None,
            initialization_method='estimated',
        )
    else:
        model = ExponentialSmoothing(
            series,
            trend='add',
            seasonal='add',
            seasonal_periods=seasonal_periods,
            initialization_method='estimated',
        )
    fitted = model.fit()
    forecast = fitted.forecast(steps)
    return fitted, forecast


async def get_product_sales(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID,
    product_name: str,
    granularity: str = 'day',
) -> pd.Series:
    period_col = date_trunc(granularity, SalesRecord.order_date)

    q = (
        select(
            period_col,
            func.sum(SalesRecord.quantity_sold).label('total_qty'),
        )
        .where(
            SalesRecord.user_id == user_id,
            SalesRecord.product_name.ilike(product_name),
        )
        .group_by(text('period'))
        .order_by(text('period'))
    )
    if dataset_id:
        q = q.where(SalesRecord.dataset_id == dataset_id)

    result = await db.execute(q)
    rows = result.all()

    if not rows:
        return pd.Series(dtype=float)

    dates = [r.period for r in rows]
    values = [float(r.total_qty) for r in rows]

    series = pd.Series(values, index=pd.DatetimeIndex(dates))
    series = series.asfreq(HORIZON_MAP[granularity][1])
    series = series.interpolate(method='linear').fillna(0)
    return series


def run_forecast(
    series: pd.Series,
    horizon: str,
    steps: int | None = None,
) -> dict[str, Any]:
    if len(series) < 4:
        return {
            'error': 'Not enough historical data. Need at least 4 data points.',
        }

    if steps is None:
        steps = HORIZON_MAP[horizon][2]

    try:
        fitted, forecast_values = _holt_winters(series, steps, horizon)

        historical = [
            {'date': str(k.date()), 'value': round(float(v), 2)} for k, v in series.items()
        ]

        forecast_dates = pd.date_range(
            start=series.index[-1] + pd.Timedelta(days=1),
            periods=steps,
            freq=HORIZON_MAP[horizon][1],
        )

        resid_std = float(np.std(fitted.resid)) if len(fitted.resid) > 0 else 0
        z_score = 1.96
        forecast_data = [
            {
                'date': str(d.date()),
                'value': max(0, round(float(v), 2)),
                'upper': max(0, round(float(v + z_score * resid_std * (1 + i / steps)), 2)),
                'lower': max(0, round(float(v - z_score * resid_std * (1 + i / steps)), 2)),
            }
            for i, (d, v) in enumerate(zip(forecast_dates, forecast_values, strict=False))
        ]

        mae = float(np.mean(np.abs(fitted.resid)))
        mape_val = float(np.nanmean(np.abs(fitted.resid / series.replace(0, np.nan)))) * 100
        cv = resid_std / (series.mean() + 1e-10)
        horizon_penalty = 1.0 / (1.0 + 0.05 * steps)
        confidence = max(0.0, min(1.0, (1.0 / (1.0 + cv)) * horizon_penalty))

        return {
            'historical': historical,
            'forecast': forecast_data,
            'confidence_score': round(float(confidence), 4),
            'mae': round(float(mae), 2),
            'mape': round(float(mape_val), 2),
            'model_used': 'Holt-Winters',
        }
    except Exception as e:
        return {
            'error': f'Forecasting failed: {e!s}',
        }


async def get_or_run_forecast(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID,
    product_name: str,
    horizon: str,
) -> dict[str, Any]:
    result = await db.execute(
        select(Forecast)
        .where(
            Forecast.user_id == user_id,
            Forecast.dataset_id == dataset_id,
            Forecast.product_name.ilike(product_name),
            Forecast.forecast_horizon == horizon,
        )
        .order_by(Forecast.created_at.desc())
        .limit(1),
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        return {
            'forecast_data': existing.forecast_data,
            'confidence_score': (
                float(existing.confidence_score) if existing.confidence_score is not None else None
            ),
            'model_used': existing.model_used,
            'cached': True,
        }

    series = await get_product_sales(db, user_id, dataset_id, product_name, horizon)
    result_data = run_forecast(series, horizon)

    if 'error' in result_data:
        return result_data

    forecast_record = Forecast(
        user_id=user_id,
        dataset_id=dataset_id,
        product_name=product_name,
        forecast_horizon=horizon,
        forecast_data=result_data,
        model_used=result_data.get('model_used'),
        confidence_score=result_data.get('confidence_score'),
    )
    db.add(forecast_record)
    await db.flush()

    return {
        'forecast_data': result_data,
        'confidence_score': result_data.get('confidence_score'),
        'model_used': result_data.get('model_used'),
        'cached': False,
    }
