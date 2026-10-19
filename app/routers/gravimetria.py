from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pymongo.database import Database

from app.db.mongo_client import get_gravimetria_database
from app.models.gravimetria import GravimetriaPredictionRecord
from app.services.gravimetria_service import get_gravimetria_predictions


router = APIRouter(prefix='/gravimetria', tags=['gravimetria'])


@router.get('/predicciones', response_model=list[GravimetriaPredictionRecord])
def list_predictions(
    from_date: datetime | None = Query(default=None, alias='from'),
    to_date: datetime | None = Query(default=None, alias='to'),
    limit: int = Query(default=500, ge=1, le=2000),
    database: Database = Depends(get_gravimetria_database),
) -> list[GravimetriaPredictionRecord]:
    return get_gravimetria_predictions(database, from_date, to_date, limit)