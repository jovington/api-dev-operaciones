from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_serializer


class MineralPackage(BaseModel):
    nombre: str
    cantidad: int | float
    matricula: str | None = None
    fecha_subida: datetime = Field(
        validation_alias='fechaSubida',
        serialization_alias='fechaSubida',
    )

    @field_serializer('fecha_subida')
    def serialize_fecha_subida(self, value: datetime) -> str:
        fecha_utc = value.replace(tzinfo=timezone.utc)
        return fecha_utc.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


class MineralSummary(BaseModel):
    mineral: str
    producto: str | None = None
    total: int | float
    fecha_subida: datetime | None = Field(
        default=None,
        serialization_alias='fechaSubida',
    )
    @field_serializer('fecha_subida', when_used='unless-none')
    def serialize_fecha_subida(self, value: datetime) -> str:
        fecha_utc = value.replace(tzinfo=timezone.utc)
        return fecha_utc.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


class MineralTotal(MineralSummary):
    paquetes: list[MineralPackage]