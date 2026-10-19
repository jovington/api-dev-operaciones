from datetime import datetime, timezone
from math import isclose, isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


class AlimentacionPlantaCard(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    nombre: str
    producto: str
    tipo: Literal['mineral']

    @field_validator('nombre', 'producto')
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError('El campo no puede estar vacío.')
        return cleaned_value


class TarjetaRonda(AlimentacionPlantaCard):
    toneladasPlanificadas: int | float

    @field_validator('toneladasPlanificadas')
    @classmethod
    def validate_planned_tons(cls, value: int | float) -> int | float:
        if not isfinite(value) or value <= 0:
            raise ValueError('toneladasPlanificadas debe ser un número finito mayor que cero.')
        return value


class TarjetaHora(AlimentacionPlantaCard):
    entradasPorHora: int
    toneladasPlanificadas: int | float

    @field_validator('entradasPorHora')
    @classmethod
    def validate_entries_per_hour(cls, value: int) -> int:
        if value < 1:
            raise ValueError('entradasPorHora debe ser un entero mayor o igual que uno.')
        return value

    @field_validator('toneladasPlanificadas')
    @classmethod
    def validate_planned_tons(cls, value: int | float) -> int | float:
        if not isfinite(value) or value <= 0:
            raise ValueError('toneladasPlanificadas debe ser un número finito mayor que cero.')
        return value


class AlimentacionPlantaCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    codigo: str
    ronda: list[TarjetaRonda]
    hora: list[TarjetaHora]
    velocidadEstimadaTph: int | float
    ciclosAlimentacionHora: int
    cargaPalaEstimadaTon: int | float
    caudalEfectivoTph: int | float
    insertarDespuesDeId: str | None = None
    planificacionPadreId: str | None = None

    @field_validator('codigo')
    @classmethod
    def validate_codigo(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError('codigo no puede estar vacío.')
        return cleaned_value

    @field_validator('velocidadEstimadaTph')
    @classmethod
    def validate_estimated_speed(cls, value: int | float) -> int | float:
        if not isfinite(value) or value <= 0:
            raise ValueError('velocidadEstimadaTph debe ser un número finito mayor que cero.')
        return value

    @field_validator('ciclosAlimentacionHora')
    @classmethod
    def validate_feed_cycles(cls, value: int) -> int:
        if value < 1:
            raise ValueError('ciclosAlimentacionHora debe ser mayor o igual que uno.')
        return value

    @field_validator('cargaPalaEstimadaTon', 'caudalEfectivoTph')
    @classmethod
    def validate_positive_finite_value(cls, value: int | float) -> int | float:
        if not isfinite(value) or value <= 0:
            raise ValueError('El valor debe ser un número finito mayor que cero.')
        return value

    @field_validator('insertarDespuesDeId', 'planificacionPadreId')
    @classmethod
    def validate_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError('El identificador no puede estar vacío.')
        return cleaned_value

    @model_validator(mode='after')
    def validate_cards(self):
        cards = self.ronda + self.hora
        if not cards:
            raise ValueError('Debe incluir al menos una tarjeta.')
        if self.hora and not self.ronda:
            raise ValueError('Las tarjetas hora requieren una tarjeta ronda para calcular su duración nominal.')
        card_identities = [
            (card.nombre, card.producto, card.tipo)
            for card in cards
        ]
        if len(set(card_identities)) != len(card_identities):
            raise ValueError('Una tarjeta no puede repetirse entre ronda y hora.')
        expected_flow = self.ciclosAlimentacionHora * self.cargaPalaEstimadaTon
        if not isclose(self.caudalEfectivoTph, expected_flow, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(
                'caudalEfectivoTph debe ser igual a ciclosAlimentacionHora por cargaPalaEstimadaTon.'
            )
        return self


class AlimentacionPlanta(BaseModel):
    id: str
    codigo: str
    estado: Literal['pendiente', 'aprobada', 'activa', 'bloqueada', 'finalizada', 'cancelada']
    creadaEn: datetime
    aprobadaEn: datetime | None = None
    ronda: list[TarjetaRonda]
    hora: list[TarjetaHora]
    orden: int
    velocidadEstimadaTph: int | float = 0
    ciclosAlimentacionHora: int = 0
    cargaPalaEstimadaTon: int | float = 0
    caudalEfectivoTph: int | float = 0
    esSubplanificacion: bool = False
    planificacionPadreId: str | None = None
    activadaEn: datetime | None = None
    bloqueadaEn: datetime | None = None
    finalizadaEn: datetime | None = None
    canceladaEn: datetime | None = None
    observacionesCancelacion: str | None = None
    mineralLimitante: TarjetaRonda | None = None
    descargasPala: list['AlimentacionPlantaScoopUnloadRecord'] = Field(default_factory=list)
    progresoPorcentaje: int | float = 0

    @field_serializer(
        'creadaEn', 'aprobadaEn', 'activadaEn', 'bloqueadaEn', 'finalizadaEn',
        'canceladaEn', when_used='unless-none'
    )
    def serialize_utc_datetime(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace(
            '+00:00', 'Z'
        )


class AlimentacionPlantaApproved(BaseModel):
    id: str
    estado: Literal['aprobada']
    aprobadaEn: datetime

    @field_serializer('aprobadaEn')
    def serialize_utc_datetime(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace(
            '+00:00', 'Z'
        )


class AlimentacionesPlantaOrder(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    ids: list[str] = Field(min_length=1)

    @field_validator('ids')
    @classmethod
    def validate_ids(cls, value: list[str]) -> list[str]:
        cleaned_ids = [alimentacion_id.strip() for alimentacion_id in value]
        if any(not alimentacion_id for alimentacion_id in cleaned_ids):
            raise ValueError('ids no puede contener valores vacíos.')
        if len(set(cleaned_ids)) != len(cleaned_ids):
            raise ValueError('ids no puede contener valores duplicados.')
        return cleaned_ids


class AlimentacionesPlantaOrdered(BaseModel):
    ids: list[str]


class AlimentacionPlantaScoopUnload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    nombre: str
    producto: str
    toneladas: int | float

    @field_validator('nombre', 'producto')
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError('El campo no puede estar vacío.')
        return cleaned_value

    @field_validator('toneladas')
    @classmethod
    def validate_tons(cls, value: int | float) -> int | float:
        if not isfinite(value) or value <= 0:
            raise ValueError('toneladas debe ser un número finito mayor que cero.')
        return value


class AlimentacionPlantaScoopUnloadRecord(BaseModel):
    fecha: str
    nombre: str
    producto: str
    toneladas: int | float


class AlimentacionPlantaScoopUnloadCreated(BaseModel):
    alimentacionId: str
    nombre: str
    producto: str
    toneladas: int | float
    stockRestanteToneladas: int | float
    progresoPorcentaje: int | float
    alimentacionSiguienteActivadaId: str | None = None


class AlimentacionPlantaCopy(AlimentacionPlantaCreate):
    pass


class AlimentacionPlantaObservation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    observacion: str | None = None

    @field_validator('observacion')
    @classmethod
    def validate_observation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AlimentacionPlantaCancel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    observaciones: str

    @field_validator('observaciones')
    @classmethod
    def validate_observations(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError('observaciones no puede estar vacío.')
        return cleaned_value


class AlimentacionPlantaOperationalState(BaseModel):
    id: str
    estado: Literal['activa', 'bloqueada', 'finalizada', 'cancelada']
    alimentacionSiguienteActivadaId: str | None = None


class CircuitoAlimentacion(BaseModel):
    id: str
    codigo: str
    estado: Literal['activa', 'bloqueada']


class CircuitoMineralLimitante(BaseModel):
    nombre: str
    producto: str
    toneladasIniciales: int | float
    toneladasRestantes: int | float


class CircuitoActual(BaseModel):
    alimentacion: CircuitoAlimentacion
    mineralLimitante: CircuitoMineralLimitante
    velocidadEstimadaTph: int | float
    velocidadRealCinta4Tph: int | float
    duracionNominalHoras: int | float
    duracionRealEstimadaHoras: int | float
    progresoPorcentaje: int | float


class Cinta4Speed(BaseModel):
    toneladasHora: int | float
    fecha: datetime

    @field_serializer('fecha')
    def serialize_utc_datetime(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace(
            '+00:00', 'Z'
        )