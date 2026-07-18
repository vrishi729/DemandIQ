# DemandIQ - Sales Analytics & Demand Forecasting Platform

A full-stack web application for uploading sales data, cleaning and processing it, viewing analytics dashboards, forecasting product demand, and receiving data-driven business insights.

---

## Features

- User authentication with JWT tokens
- Upload CSV and Excel files with automatic column detection and mapping
- Data cleaning pipeline with date parsing, deduplication, and normalization
- Analytics dashboard with KPIs, revenue trends, category breakdown, and product tables
- Product-level demand forecasting using Holt-Winters exponential smoothing
- Data-driven business insights including growth alerts, product flags, and seasonal pattern detection
- Dataset management with download and delete capabilities

---

## Tech Stack

### Backend

| Layer | Technology |
|---|---|
| Framework | FastAPI (Python) |
| ORM | SQLAlchemy with Alembic migrations |
| Database | SQLite / PostgreSQL |
| Auth | JWT access and refresh tokens |
| Data processing | Pandas, NumPy |
| Forecasting | Statsmodels |

### Frontend

| Layer | Technology |
|---|---|
| Framework | React, TypeScript |
| Build tool | Vite |
| Routing | React Router |
| State management | Zustand, TanStack Query |
| Charts | Recharts |
| Styling | Tailwind CSS |

---

## Setup

### Backend

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## API Overview

| Method | Path | Description |
|---|---|---|
| POST | /api/v1/auth/register | Create account |
| POST | /api/v1/auth/login | Log in |
| GET | /api/v1/auth/me | Get current user |
| GET | /api/v1/datasets/ | List datasets |
| POST | /api/v1/datasets/upload | Upload file |
| POST | /api/v1/datasets/{id}/clean | Process dataset |
| GET | /api/v1/analytics/overview | Get dashboard data |
| GET | /api/v1/forecast/run | Run product forecast |
| GET | /api/v1/recommendations/ | Get business insights |

---

## Supported File Formats

- CSV (.csv)
- Excel (.xlsx, .xls)
- Max file size: 10 MB
- Required columns: Order Date, Product Name, Quantity Sold, Unit Price
- Optional columns: Category, Revenue

---

## License

MIT
