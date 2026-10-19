from datetime import datetime, time, timedelta

from pymongo import ASCENDING, DESCENDING, UpdateOne
from pymongo.database import Database


COLLECTION_NAME = 'Planificacion'


def ensure_planificacion_indexes(database: Database) -> None:
    database[COLLECTION_NAME].create_index(
        [('clave_importacion', ASCENDING)],
        unique=True,
        partialFilterExpression={'clave_importacion': {'$type': 'string'}},
        name='clave_importacion_unique',
    )
    database[COLLECTION_NAME].create_index(
        [('tipo', ASCENDING)], name='tipo'
    )
    database[COLLECTION_NAME].create_index([('Area_Nivel', ASCENDING)], name='area_nivel')
    database[COLLECTION_NAME].create_index([('planta', ASCENDING)], name='planta')
    database[COLLECTION_NAME].create_index([('tarea', ASCENDING)], name='tarea')
    database[COLLECTION_NAME].create_index([('cronograma.fecha', DESCENDING)], name='cronograma_fecha')


def upsert_planificaciones(database: Database, documents: list[dict]) -> tuple[int, int]:
    if not documents:
        return 0, 0
    inserted = 0
    updated = 0
    collection = database[COLLECTION_NAME]
    for start in range(0, len(documents), 500):
        batch = documents[start:start + 500]
        result = collection.bulk_write(
            [
                UpdateOne(
                    {'clave_importacion': document['clave_importacion']},
                    {
                        '$set': {
                            key: value
                            for key, value in document.items()
                            if key != 'fecha_importacion'
                        },
                        '$setOnInsert': {
                            'fecha_importacion': document['fecha_importacion']
                        },
                    },
                    upsert=True,
                )
                for document in batch
            ],
            ordered=False,
        )
        inserted += result.upserted_count
        updated += result.modified_count
    return inserted, updated


def list_planificaciones(
    database: Database,
    tipo: str | None = None,
    fecha_desde: datetime | None = None,
    fecha_hasta: datetime | None = None,
    area_nivel: str | None = None,
    planta: str | None = None,
    tarea: str | None = None,
) -> list[dict]:
    filters: dict = {}
    if tipo is not None:
        filters['tipo'] = tipo
    if area_nivel is not None:
        filters['Area_Nivel'] = area_nivel
    if planta is not None:
        filters['planta'] = planta
    if tarea is not None:
        filters['tarea'] = tarea
    if fecha_desde is not None or fecha_hasta is not None:
        date_filter: dict = {}
        if fecha_desde is not None:
            date_filter['$gte'] = datetime.combine(fecha_desde.date(), time.min)
        if fecha_hasta is not None:
            date_filter['$lt'] = datetime.combine(
                fecha_hasta.date() + timedelta(days=1), time.min
            )
        filters['cronograma'] = {'$elemMatch': {'fecha': date_filter}}
    return list(
        database[COLLECTION_NAME].find(filters).sort(
            [('cronograma.fecha', DESCENDING), ('_id', ASCENDING)]
        )
    )