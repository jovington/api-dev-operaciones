from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pymongo import MongoClient

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.alimentacion_planta_repo import (
    ensure_alimentacion_planta_indexes,
    migrate_hour_cards_to_planned_tons,
    migrate_scoop_unloads_to_tons,
)
from app.db.consumos_acopio_repo import ensure_consumption_indexes
from app.db.gravimetria_repo import ensure_gravimetria_indexes
from app.db.mongo_client import close_mongo_client, ping_mongo, set_mongo_client
from app.db.planta_repo import ensure_plc_indexes
from app.db.planificacion_repo import ensure_planificacion_indexes
from app.routers import alimentacion_planta, acopio, bascula, gravimetria, operaciones, planificacion, planta, platform, users


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    client = MongoClient(settings.mongo_uri, tz_aware=True)
    set_mongo_client(client)
    ping_mongo()
    ensure_consumption_indexes(client[settings.mongodb_database])
    ensure_alimentacion_planta_indexes(client[settings.mongodb_database])
    migrate_scoop_unloads_to_tons(client[settings.mongodb_database])
    migrate_hour_cards_to_planned_tons(client[settings.mongodb_database])
    ensure_plc_indexes(client[settings.mongodb_database])
    ensure_gravimetria_indexes(client[settings.gravimetria_database])
    ensure_planificacion_indexes(client[settings.operaciones_database])
    yield
    close_mongo_client()


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    allow_headers=['Authorization', 'Content-Type'],
)

app.include_router(platform.router)
app.include_router(bascula.router)
app.include_router(acopio.router)
app.include_router(alimentacion_planta.router)
app.include_router(planificacion.router)
app.include_router(gravimetria.router)
app.include_router(planta.router)
app.include_router(planta.produccion_router)
app.include_router(users.router)
app.include_router(operaciones.router)
app.mount('/uploads', StaticFiles(directory='/app/uploads'), name='uploads')