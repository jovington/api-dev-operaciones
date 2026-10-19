from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ParteOperacion(BaseModel):
    model_config = ConfigDict(extra='allow')

    Tipo_Parte: str
    ID: str | None = 'SIN_ID'
    Fecha: str | None = None
    Turno: str | None = None
    N_Empleado: int | None = None
    Nombre: str | None = None
    Ronda: int | None = None
    Relevo: str | None = None
    createdAt: datetime | None = None
    datos: list[dict[str, Any]] = Field(default_factory=list)


class ParteChecklist(BaseModel):
    model_config = ConfigDict(extra='allow', populate_by_name=True)

    ID: str | None = None
    id_parte: str | None = None
    id_partes: str | None = None
    Tipo_Parte: str | None = None
    tipo_parte: str | None = None
    createdAt: datetime | None = None
    fecha_creacion: str | None = None
    Fecha: str | None = None
    Turno: str | None = None
    N_Empleado: int | None = None
    Nombre: str | None = None
    Ronda: int | None = None
    Relevo: str | None = None
    cabecera: dict[str, Any] = Field(default_factory=dict)
    datos: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    fotos: list[str] = Field(default_factory=list)


class VehiculosTemplate(BaseModel):
    model_config = ConfigDict(extra='allow')

    titulo: str = 'Listado de vehiculos - Checklist'
    id: str = 'Listado de vehiculos'
    nombre: str = 'LV'
    version: str = '1.0'
    equipamiento: list[dict[str, Any]] = Field(default_factory=list)


class UsuarioPlanta(BaseModel):
    model_config = ConfigDict(extra='allow')

    N_Empleado: int
    Nombre: str
    Perfil: str
    Estado: str = 'Activo'
    password: str | None = None
    qr_token: str | None = None
    regenerar_qr: bool = False
    forzar_actualizacion_token: bool = False
    departamentos: list[str] = Field(default_factory=list)


class LoginRequest(BaseModel):
    n_empleado: int
    password: str


class LoginQrRequest(BaseModel):
    qr_token: str


class DesactivarMedicion(BaseModel):
    desactive_medicion: bool = True
