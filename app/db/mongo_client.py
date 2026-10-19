from fastapi import HTTPException, Request
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.core.config import settings

_client: MongoClient | None = None


def set_mongo_client(client: MongoClient) -> None:
    global _client
    _client = client


def get_database(_: Request) -> Database:
    if _client is None:
        raise HTTPException(status_code=503, detail='MongoDB no está disponible.')
    return _client[settings.mongodb_database]


def get_operaciones_database(_: Request) -> Database:
    if _client is None:
        raise HTTPException(status_code=503, detail='MongoDB no está disponible.')
    return _client[settings.operaciones_database]


def get_gravimetria_database(_: Request) -> Database:
    if _client is None:
        raise HTTPException(status_code=503, detail='MongoDB no está disponible.')
    return _client[settings.gravimetria_database]


def ping_mongo() -> None:
    if _client is None:
        raise RuntimeError('El cliente MongoDB no se ha inicializado.')
    _client.admin.command('ping')


def close_mongo_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None


def mongo_available() -> bool:
    try:
        ping_mongo()
        return True
    except PyMongoError:
        return False