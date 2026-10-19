from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


def _to_camel_case(value: str) -> str:
    first, *rest = value.split('_')
    return first + ''.join(part.capitalize() for part in rest)


class ConsumptionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mineral: str = Field(min_length=1)
    fecha: date
    peso_neto: int | float = Field(alias='pesoNeto', gt=0)


class ConsumptionCreated(ConsumptionCreate):
    id: str


class ConsumptionTotal(BaseModel):
    mineral: str
    producto: str | None = None
    fecha: date
    total: int | float
    fecha_subida: datetime | None = Field(
        default=None,
        validation_alias='fechaSubida',
        serialization_alias='fechaSubida',
    )

    @field_serializer('fecha_subida', when_used='unless-none')
    def serialize_fecha_subida(self, value: datetime) -> str:
        fecha_utc = value.replace(tzinfo=timezone.utc)
        return fecha_utc.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


class MineralStock(BaseModel):
    mineral: str
    producto: str | None = None
    entrado: int | float
    consumido: int | float
    disponible: int | float
    fecha_subida: datetime | None = Field(
        default=None,
        validation_alias='fechaSubida',
        serialization_alias='fechaSubida',
    )

    @field_serializer('fecha_subida', when_used='unless-none')
    def serialize_fecha_subida(self, value: datetime) -> str:
        fecha_utc = value.replace(tzinfo=timezone.utc)
        return fecha_utc.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


class AcopioGroup(BaseModel):
    id: str = Field(min_length=1)
    nombre: str = Field(min_length=1)
    tipo: Literal['mineral', 'baja_ley', 'esteril']
    fecha_asignacion: datetime = Field(
        validation_alias='fechaAsignacion',
        serialization_alias='fechaAsignacion',
    )

    @field_validator('fecha_asignacion')
    @classmethod
    def validate_fecha_asignacion_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError('fechaAsignacion debe incluir zona horaria UTC.')
        return value

    @field_serializer('fecha_asignacion')
    def serialize_fecha_asignacion(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace(
            '+00:00', 'Z'
        )


class AcopioMeasurement(BaseModel):
    id: str = Field(serialization_alias='_id')
    nombre: str
    cantidad: int | float
    matricula: str | None = None
    fecha_subida: datetime = Field(serialization_alias='fechaSubida')
    producto: str | None = None
    grupo: list[AcopioGroup] = Field(default_factory=list)

    @field_serializer('fecha_subida')
    def serialize_fecha_subida(self, value: datetime) -> str:
        fecha_utc = value.replace(tzinfo=timezone.utc)
        return fecha_utc.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


class AcopioMeasurementGroupsUpdate(BaseModel):
    grupo: list[AcopioGroup]


class AcopioMeasurementGroups(BaseModel):
    id: str = Field(serialization_alias='_id')
    grupo: list[AcopioGroup]


class AcopioMeasurementsRename(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel_case)

    medicion_ids: list[str] = Field(min_length=1)
    nombre: str

    @field_validator('medicion_ids')
    @classmethod
    def validate_medicion_ids(cls, value: list[str]) -> list[str]:
        cleaned_ids = [medicion_id.strip() for medicion_id in value]
        if any(not medicion_id for medicion_id in cleaned_ids):
            raise ValueError('medicionIds no puede contener valores vacíos.')
        if len(set(cleaned_ids)) != len(cleaned_ids):
            raise ValueError('medicionIds no puede contener valores duplicados.')
        return cleaned_ids

    @field_validator('nombre')
    @classmethod
    def validate_nombre(cls, value: str) -> str:
        cleaned_name = value.strip()
        if not cleaned_name:
            raise ValueError('nombre no puede estar vacío.')
        return cleaned_name


class AcopioMeasurementsRenamed(BaseModel):
    nombre: str
    medicion_ids: list[str] = Field(serialization_alias='medicionIds')


class AcopioMeasurementClassification(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    tipo: Literal['mineral', 'baja_ley', 'esteril']


class AcopioCardsMerge(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    origenMedicionIds: list[str] = Field(min_length=1)
    destinoMedicionIds: list[str] = Field(min_length=1)

    @field_validator('origenMedicionIds', 'destinoMedicionIds')
    @classmethod
    def validate_measurement_ids(cls, value: list[str]) -> list[str]:
        cleaned_ids = [medicion_id.strip() for medicion_id in value]
        if any(not medicion_id for medicion_id in cleaned_ids):
            raise ValueError('Los IDs de medición no pueden estar vacíos.')
        if len(set(cleaned_ids)) != len(cleaned_ids):
            raise ValueError('Los IDs de medición no pueden estar duplicados.')
        return cleaned_ids

    @field_validator('destinoMedicionIds')
    @classmethod
    def validate_disjoint_measurement_ids(cls, value: list[str], info) -> list[str]:
        origen_ids = info.data.get('origenMedicionIds', [])
        if set(value).intersection(origen_ids):
            raise ValueError('Origen y destino no pueden compartir mediciones.')
        return value


class AcopioCardsMerged(BaseModel):
    nombre: str
    medicion_ids: list[str] = Field(serialization_alias='medicionIds')
    total: int | float