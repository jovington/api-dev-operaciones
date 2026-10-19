from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class PlanificacionImportada(BaseModel):
    tipo: Literal['mensual', 'semanal']
    registrosImportados: int
    registrosActualizados: int
    filasDescartadas: int


class PlanificacionCronograma(BaseModel):
    fecha: datetime
    toneladas: float

    @field_serializer('fecha')
    def serialize_date(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace(
            '+00:00', 'Z'
        )


class PlanificacionRegistro(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    tipo: Literal['mensual', 'semanal']
    fecha_importacion: datetime
    Area_Nivel: str
    planta: str | None = None
    tarea: str | None = None
    zona: str
    nivel: str
    subnivel: str
    acttype: str
    camara: str
    valores: dict[str, float] = Field(default_factory=dict)
    atributos: dict[str, str] = Field(default_factory=dict)
    cronograma: list[PlanificacionCronograma] = Field(default_factory=list)

    @field_serializer('fecha_importacion')
    def serialize_import_date(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace(
            '+00:00', 'Z'
        )