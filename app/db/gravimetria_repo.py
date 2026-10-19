from datetime import datetime

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from app.core.config import settings


def ensure_gravimetria_indexes(database: Database) -> None:
    database[settings.gravimetria_collection].create_index(
        [
            ('worker', ASCENDING),
            ('metadata.camera_id', ASCENDING),
            ('predictions.timestamp', DESCENDING),
        ],
        name='worker_camera_predictions_timestamp_desc',
    )


def list_gravimetria_predictions(
    database: Database,
    from_date: datetime | None,
    to_date: datetime | None,
    limit: int,
) -> list[dict]:
    valid_prediction: dict = {
        'worker': 'rocks',
        'created_at': {'$type': 'date'},
        'metadata.camera_id': {'$type': 'string'},
        'predictions.rocks_by_model_class': {'$type': 'object'},
        'predictions.total_objects_in_roi': {'$type': 'number', '$gt': 0},
        'predictions.oversize_ratio_pct': {'$type': 'number'},
    }
    pipeline: list[dict] = [
        {'$match': valid_prediction},
        {'$set': {
            '_measurement_time': {
                '$convert': {
                    'input': '$predictions.timestamp',
                    'to': 'date',
                    'onError': '$created_at',
                    'onNull': '$created_at',
                },
            },
        }},
    ]
    time_filter: dict = {}
    if from_date is not None:
        time_filter['$gte'] = from_date
    if to_date is not None:
        time_filter['$lte'] = to_date
    if time_filter:
        pipeline.append({'$match': {'_measurement_time': time_filter}})
    pipeline.extend([
        {'$setWindowFields': {
            'partitionBy': '$metadata.camera_id',
            'sortBy': {'_measurement_time': DESCENDING},
            'output': {'_camera_rank': {'$documentNumber': {}}},
        }},
        {'$match': {'_camera_rank': {'$lte': limit}}},
        {'$sort': {'_measurement_time': DESCENDING, '_id': DESCENDING}},
        {'$project': {
            '_id': 0,
            'created_at': 1,
            'metadata.camera_id': 1,
            'metadata.granulometria': 1,
            'predictions.rocks_by_model_class': 1,
            'predictions.total_objects_in_roi': 1,
            'predictions.oversize_ratio_pct': 1,
            'predictions.timestamp': '$_measurement_time',
        }},
    ])
    return list(database[settings.gravimetria_collection].aggregate(pipeline))