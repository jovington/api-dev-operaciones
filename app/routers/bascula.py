from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.db.mongo_client import get_database
from app.models.bascula import MineralTotal
from app.services.bascula_service import get_mineral_totals

router = APIRouter(prefix='/bascula', tags=['bascula'])


@router.get('/total-por-mineral', response_model=list[MineralTotal])
def list_mineral_totals(
    database: Database = Depends(get_database),
) -> list[MineralTotal]:
    return get_mineral_totals(database)