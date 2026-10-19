from datetime import datetime

from pydantic import ValidationError
from pymongo.database import Database

from app.db.gravimetria_repo import list_gravimetria_predictions
from app.models.gravimetria import GravimetriaPredictionRecord


def get_gravimetria_predictions(
    database: Database,
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int,
) -> list[GravimetriaPredictionRecord]:
    predictions: list[GravimetriaPredictionRecord] = []
    for document in list_gravimetria_predictions(database, from_date, to_date, limit):
        try:
            predictions.append(GravimetriaPredictionRecord.model_validate(document))
        except ValidationError:
            continue
    return predictions