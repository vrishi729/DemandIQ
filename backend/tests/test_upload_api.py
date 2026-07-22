import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_upload_requires_auth(client: AsyncClient):
    resp = await client.post(
        '/api/v1/datasets/upload',
        files={'file': ('test.csv', b'a,b\n1,2', 'text/csv')},
    )
    assert resp.status_code == 401


async def test_upload_valid_csv(client: AsyncClient, auth_headers: dict[str, str]):
    csv_content = (
        b'Order Date,Product Name,Category,Quantity Sold,Unit Price\n'
        b'2024-01-05,Coffee, Beverages,15,12.50\n'
    )
    resp = await client.post(
        '/api/v1/datasets/upload',
        files={'file': ('sales.csv', csv_content, 'text/csv')},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data['is_valid']
    assert data['row_count'] == 1
    assert 'dataset_id' in data


async def test_upload_missing_columns(client: AsyncClient, auth_headers: dict[str, str]):
    csv_content = b'Name,Qty\nCoffee,15\n'
    resp = await client.post(
        '/api/v1/datasets/upload',
        files={'file': ('bad.csv', csv_content, 'text/csv')},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert not data['is_valid']
    assert 'order_date' in data['health_summary']['missing_required_columns']


async def test_upload_wrong_extension(client: AsyncClient, auth_headers: dict[str, str]):
    resp = await client.post(
        '/api/v1/datasets/upload',
        files={'file': ('data.pdf', b'fake', 'application/pdf')},
        headers=auth_headers,
    )
    assert resp.status_code == 400


async def test_upload_file_too_large(client: AsyncClient, auth_headers: dict[str, str]):
    large = b'x' * (11 * 1024 * 1024)
    resp = await client.post(
        '/api/v1/datasets/upload',
        files={'file': ('big.csv', large, 'text/csv')},
        headers=auth_headers,
    )
    assert resp.status_code == 400
