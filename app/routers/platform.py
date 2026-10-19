from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.db.mongo_client import mongo_available

router = APIRouter(tags=['platform'])


@router.get('/')
def platform_info() -> dict[str, str]:
    return {'service': settings.app_name, 'version': settings.app_version}


@router.get('/health')
def health_check() -> dict[str, str]:
    if not mongo_available():
        raise HTTPException(status_code=503, detail='MongoDB no está disponible.')
    return {'status': 'ok', 'database': settings.mongodb_database}