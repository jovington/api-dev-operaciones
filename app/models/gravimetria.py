from datetime import datetime, timezone
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class GravimetriaMetadata(BaseModel):
    model_config = ConfigDict(extra='ignore')

    camera_id: str
    granulometria: dict[str, int | float] | None = None


class GravimetriaPredictions(BaseModel):
    model_config = ConfigDict(extra='ignore')

    timestamp: datetime
    rocks_by_model_class: dict[str, int | float]
    total_objects_in_roi: int
    oversize_ratio_pct: int | float

    @field_validator('rocks_by_model_class')
    @classmethod
    def validate_rocks(cls, value: dict[str, int | float]) -> dict[str, int | float]:
        if not value or any(count < 0 for count in value.values()):
            raise ValueError('rocks_by_model_class debe contener conteos enteros no negativos.')
        return value

    @field_validator('total_objects_in_roi')
    @classmethod
    def validate_total(cls, value: int) -> int:
        if value <= 0:
            raise ValueError('total_objects_in_roi debe ser mayor que cero.')
        return value

    @field_validator('oversize_ratio_pct')
    @classmethod
    def validate_oversize_ratio(cls, value: int | float) -> int | float:
        if not isfinite(value):
            raise ValueError('oversize_ratio_pct debe ser finito.')
        return value

    @field_serializer('timestamp')
    def serialize_timestamp(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace(
            '+00:00', 'Z'
        )


class GravimetriaPredictionRecord(BaseModel):
    model_config = ConfigDict(extra='ignore')

    created_at: datetime
    metadata: GravimetriaMetadata = Field(default_factory=GravimetriaMetadata)
    predictions: GravimetriaPredictions

    @field_serializer('created_at')
    def serialize_created_at(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace(
            '+00:00', 'Z'
        )