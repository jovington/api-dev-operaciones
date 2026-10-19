from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.db.mongo_client import get_database
from app.models.users import UserSummary
from app.services.users_service import get_active_users

router = APIRouter(prefix='/users', tags=['users'])


@router.get('', response_model=list[UserSummary])
def list_users(database: Database = Depends(get_database)) -> list[UserSummary]:
    return get_active_users(database)