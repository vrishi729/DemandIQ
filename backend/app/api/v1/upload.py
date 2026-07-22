import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import UPLOAD_DIR
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.user import User
from app.schemas.upload import UploadResponse
from app.services.upload_service import ValidationError, detect_columns, parse_and_validate

router = APIRouter(prefix='/datasets', tags=['datasets'])


@router.get('/')
async def list_datasets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Dataset)
        .where(Dataset.user_id == current_user.id)
        .order_by(Dataset.created_at.desc())
    )
    datasets = result.scalars().all()
    return [
        {
            'id': str(ds.id),
            'original_filename': ds.original_filename,
            'row_count': ds.row_count,
            'file_size_bytes': ds.file_size_bytes,
            'status': ds.status,
            'created_at': ds.created_at.isoformat(),
        }
        for ds in datasets
    ]


@router.delete('/{dataset_id}')
async def delete_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
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

    file_path = UPLOAD_DIR / dataset.stored_filename
    if file_path.exists():
        file_path.unlink()

    from app.models.sales_record import SalesRecord
    await db.execute(SalesRecord.__table__.delete().where(SalesRecord.dataset_id == did))
    await db.delete(dataset)
    await db.flush()

    return {'status': 'deleted'}


@router.get('/{dataset_id}/download')
async def download_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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

    file_path = UPLOAD_DIR / dataset.stored_filename
    if not file_path.exists():
        raise HTTPException(status_code=400, detail='Uploaded file not found on disk')

    return FileResponse(str(file_path), filename=dataset.original_filename, media_type='text/csv')


@router.get('/{dataset_id}/columns')
async def get_dataset_columns(
    dataset_id: str,
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

    file_path = UPLOAD_DIR / dataset.stored_filename
    if not file_path.exists():
        raise HTTPException(status_code=400, detail='Uploaded file not found on disk')

    content = file_path.read_bytes()
    return detect_columns(content, dataset.original_filename)


@router.post('/upload', response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if file.filename is None:
        raise HTTPException(status_code=400, detail='Filename is required')

    content = await file.read()
    file_size = len(content)

    try:
        df, summary, stored_filename = parse_and_validate(content, file.filename, file_size)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.message) from e

    upload_path = UPLOAD_DIR / stored_filename
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    upload_path.write_bytes(content)

    dataset = Dataset(
        user_id=current_user.id,
        original_filename=file.filename,
        stored_filename=stored_filename,
        file_size_bytes=file_size,
        row_count=summary.total_rows,
        status='validated' if summary.is_valid else 'invalid',
        health_summary=summary.to_dict(),
    )
    db.add(dataset)
    await db.flush()

    return {
        'dataset_id': str(dataset.id),
        'filename': file.filename,
        'row_count': summary.total_rows,
        'is_valid': summary.is_valid,
        'health_summary': summary.to_dict() if not summary.is_valid else None,
    }
