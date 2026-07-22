import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.engine import (
    get_category_performance,
    get_kpi_summary,
    get_product_growth,
    get_sales_growth,
    get_sales_trends,
    get_top_products,
)
from app.analytics.forecasting import get_or_run_forecast


async def generate_recommendations(
    db: AsyncSession,
    user_id: uuid.UUID,
    dataset_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []

    kpi = await get_kpi_summary(db, user_id, dataset_id)

    if kpi['total_orders'] == 0:
        recommendations.append({
            'type': 'info',
            'title': 'No data yet',
            'description': 'Upload a dataset to get business recommendations.',
        })
        return recommendations

    all_products = await get_top_products(db, user_id, dataset_id, limit=999)
    categories = await get_category_performance(db, user_id, dataset_id)
    trends = await get_sales_trends(db, user_id, dataset_id, 'month')
    growth = await get_sales_growth(db, user_id, dataset_id)
    prod_growth = await get_product_growth(db, user_id, dataset_id)

    for p in all_products:
        p['growth'] = prod_growth.get(p['product_name'], 0.0)

    total_rev = kpi['total_revenue']
    total_qty = sum(p['total_quantity'] for p in all_products) if all_products else 1
    avg_rev = total_rev / len(all_products) if all_products else 0
    avg_qty = total_qty / len(all_products) if all_products else 0

    product_analysis = {}
    for p in all_products:
        rev_pct = (p['total_revenue'] / total_rev * 100) if total_rev > 0 else 0
        qty_pct = (p['total_quantity'] / total_qty * 100) if total_qty > 0 else 0
        g = p.get('growth', 0)

        indicators = {
            'below_avg_revenue': p['total_revenue'] < avg_rev * 0.5,
            'below_avg_quantity': p['total_quantity'] < avg_qty * 0.5,
            'declining': g < -10,
            'low_rev_share': rev_pct < 2,
            'low_qty_share': qty_pct < 2,
        }
        poor_score = sum(1 for v in indicators.values() if v)
        is_slow = poor_score >= 3
        is_fast = g > 20 and rev_pct > 3 and qty_pct > 3
        is_declining = g < -15 and rev_pct > 1

        product_analysis[p['product_name']] = {
            'product': p,
            'rev_pct': rev_pct,
            'qty_pct': qty_pct,
            'growth': g,
            'is_slow_mover': is_slow,
            'is_fast_growing': is_fast,
            'is_declining': is_declining,
            'poor_score': poor_score,
        }

    # --- Revenue trend ---
    if growth['growth_rate'] > 0:
        recommendations.append({
            'type': 'positive',
            'title': 'Revenue on the rise',
            'description': (
                f'Revenue grew {growth["growth_rate"]:.1f}% from '
                f'{growth["previous_period"]} to {growth["current_period"]}. '
                'Continue the momentum by increasing inventory for your top performers '
                'and running targeted promotions in growing categories.'
            ),
        })
    elif growth['growth_rate'] < 0:
        severity = 'warning' if growth['growth_rate'] < -5 else 'info'
        recommendations.append({
            'type': severity,
            'title': 'Revenue decline detected',
            'description': (
                f'Revenue dropped {abs(growth["growth_rate"]):.1f}% from '
                f'{growth["previous_period"]} to {growth["current_period"]}. '
                'Review pricing, review underperforming product lines, and consider '
                'bundle deals to recover momentum.'
            ),
        })

    # --- Fast-growing products ---
    fast = [a for a in product_analysis.values() if a['is_fast_growing']]
    fast.sort(key=lambda x: x['growth'], reverse=True)
    for a in fast[:3]:
        p = a['product']
        recommendations.append({
            'type': 'positive',
            'title': f'{p["product_name"]} is gaining traction',
            'description': (
                f'Sales grew {a["growth"]:.1f}% year-over-year, contributing '
                f'{a["rev_pct"]:.1f}% of total revenue ({p["total_quantity"]} units). '
                'Consider allocating more shelf space and marketing budget to this product '
                'to capitalize on its momentum.'
            ),
        })

    # --- Declining products ---
    declining = [a for a in product_analysis.values() if a['is_declining']]
    declining.sort(key=lambda x: x['growth'])
    for a in declining[:3]:
        p = a['product']
        recommendations.append({
            'type': 'warning',
            'title': f'{p["product_name"]} demand is dropping',
            'description': (
                f'Sales declined {abs(a["growth"]):.1f}% year-over-year '
                f'({p["total_quantity"]} units, {a["rev_pct"]:.1f}% of revenue). '
                'Investigate root cause — competitor action, pricing issues, or changing '
                'customer preferences. Consider a campaign or bundling to revive demand.'
            ),
        })

    # --- Slow movers (multi-factor, not just unit count) ---
    slow = [a for a in product_analysis.values() if a['is_slow_mover']]
    slow.sort(key=lambda x: x['poor_score'], reverse=True)
    for a in slow[:3]:
        p = a['product']
        recommendations.append({
            'type': 'info',
            'title': f'{p["product_name"]} needs attention',
            'description': (
                f'{p["product_name"]} underperforms across multiple metrics — '
                f'{a["rev_pct"]:.1f}% revenue share, {a["qty_pct"]:.1f}% volume share, '
                f'growth {a["growth"]:+.1f}%. Review pricing strategy, consider '
                'bundling with top sellers, or run a clearance promotion.'
            ),
        })

    # --- Revenue concentration risk ---
    if all_products:
        top3 = sorted(all_products, key=lambda x: x['total_revenue'], reverse=True)[:3]
        top3_rev_share = sum(p['total_revenue'] for p in top3) / total_rev * 100
        if top3_rev_share > 60:
            recommendations.append({
                'type': 'warning',
                'title': 'Revenue concentration risk',
                'description': (
                    f'Top 3 products generate {top3_rev_share:.0f}% of total revenue. '
                    'This creates vulnerability if demand shifts. Consider diversifying '
                    'your product range and promoting mid-tail products to spread risk.'
                ),
            })

    # --- Bundling opportunities ---
    high_volume_low_rev = [p for p in all_products
                           if p['total_quantity'] > avg_qty and p['total_revenue'] < avg_rev]
    if high_volume_low_rev:
        top_bundle = max(high_volume_low_rev, key=lambda p: p['total_quantity'])
        top_sellers = sorted(all_products, key=lambda x: x['total_revenue'], reverse=True)[:3]
        if top_sellers:
            rec = {
                'type': 'action',
                'title': 'Bundling opportunity identified',
                'description': (
                    f'{top_bundle["product_name"]} sells '
                    f'({top_bundle["total_quantity"]} units) '
                    f'at ${top_bundle["total_revenue"] / top_bundle["total_quantity"]:.2f}/unit. '
                    f'Bundle it with top sellers like {top_sellers[0]["product_name"]} to '
                    'increase average order value while moving volume.'
                ),
            }
            recommendations.append(rec)

    # --- Seasonal pattern ---
    if len(trends) >= 12:
        from calendar import month_name
        month_revenues = defaultdict(list)
        for t in trends:
            month_label = t['period'][5:7]
            month_revenues[month_label].append(t['total_revenue'])
        month_avg = {m: sum(vs) / len(vs) for m, vs in month_revenues.items()}
        if month_avg:
            best_month_num = max(month_avg, key=month_avg.get)
            peak_avg = month_avg[best_month_num]
            overall_avg = sum(month_avg.values()) / len(month_avg)
            if overall_avg > 0 and peak_avg > overall_avg * 1.15:
                boost_pct = ((peak_avg / overall_avg) - 1) * 100
                num_years = max(1, len({t['period'][:4] for t in trends}))
                recommendations.append({
                    'type': 'info',
                    'title': f'{month_name[int(best_month_num)]} is your peak season',
                    'description': (
                        f'Over {num_years}y of data, {month_name[int(best_month_num)]} averages '
                        f'${peak_avg:,.0f} — {boost_pct:.0f}% above the yearly avg of '
                        f'${overall_avg:,.0f}. Build inventory 6-8 weeks ahead to maximize '
                        'this consistent seasonal pattern.'
                    ),
                })

    # --- Forecast-based restocking ---
    for p in all_products[:5]:
        forecast_result = {}
        if dataset_id is not None:
            try:
                forecast_result = await get_or_run_forecast(
                    db, user_id, dataset_id, p['product_name'], 'week',
                )
            except Exception:
                forecast_result = {}

        fd = forecast_result.get('forecast_data', {})
        fvals = [x['value'] for x in fd.get('forecast', [])]
        hist = fd.get('historical', [])

        if fvals and hist:
            avg_f = sum(fvals) / len(fvals)
            recent = hist[-min(len(hist), 8):]
            curr_weekly = sum(h['value'] for h in recent) / len(recent)

            if curr_weekly > 0 and avg_f > curr_weekly * 1.15:
                inc = ((avg_f - curr_weekly) / curr_weekly) * 100
                recommendations.append({
                    'type': 'action',
                    'title': f'Restock {p["product_name"]} ahead of demand',
                    'description': (
                        f'Forecast predicts ~{inc:.0f}% higher demand for '
                        f'{p["product_name"]} in the coming weeks. Increase order '
                        f'quantities by {max(10, int(inc / 10) * 10)}% to avoid stockouts.'
                    ),
                })

    # --- Category growth ---
    if len(categories) >= 2:
        cat_trends = []
        for cat in categories:
            cat_months = [t for t in trends if t.get('category') == cat['category']]
            if len(cat_months) >= 2:
                first = cat_months[0]['total_revenue']
                last = cat_months[-1]['total_revenue']
                if first > 0:
                    cat_growth = ((last - first) / first) * 100
                    cat_trends.append((cat['category'], cat_growth))
        if cat_trends:
            best_cat = max(cat_trends, key=lambda x: x[1])
            if best_cat[1] > 15:
                recommendations.append({
                    'type': 'positive',
                    'title': f'{best_cat[0]} category is growing steadily',
                    'description': (
                        f'The {best_cat[0]} category shows {best_cat[1]:.0f}% growth over '
                        'the observed period. Consider expanding your product range in '
                        'this category and allocating more marketing budget to capture demand.'
                    ),
                })

    # --- Top product spotlight ---
    if all_products:
        top = max(all_products, key=lambda x: x['total_revenue'])
        top_pct = (top['total_revenue'] / total_rev * 100) if total_rev > 0 else 0
        recommendations.append({
            'type': 'positive',
            'title': f'{top["product_name"]} leads revenue at {top_pct:.1f}%',
            'description': (
                f'{top["product_name"]} generated ${top["total_revenue"]:,.0f} '
                f'({top_pct:.1f}% of total) across {top["order_count"]} orders '
                f'({top["total_quantity"]} units). Ensure consistent stock levels '
                'and explore bundling it with slower-moving products to lift overall margins.'
            ),
        })

    # --- Priority ordering ---
    priority_map = {'warning': 0, 'positive': 1, 'action': 2, 'info': 3}
    for rec in recommendations:
        rec['priority'] = priority_map.get(rec.get('type', 'info'), 99)
    recommendations.sort(key=lambda r: (r['priority'], r.get('title', '')))

    return recommendations
