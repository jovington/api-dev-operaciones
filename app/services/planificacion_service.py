import csv
import hashlib
import io
import re
import unicodedata
from datetime import datetime, timezone
from math import isfinite

from fastapi import HTTPException, UploadFile, status
from pymongo.database import Database

from app.db.planificacion_repo import list_planificaciones, upsert_planificaciones
from app.models.planificacion import PlanificacionImportada, PlanificacionRegistro


REQUIRED_COLUMNS = {'Tarea', 'ZONA', 'NIVEL', 'SUBNIVEL', 'ACTTYPE', 'CAMARA', 'PLANTA'}


def _normalized_header(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value.strip())
    return ''.join(character for character in normalized if not unicodedata.combining(character)).lower()


def _snake_case(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value.strip())
    ascii_value = ''.join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', ascii_value.lower())).strip('_')


def _clean_text(value: str | None) -> str:
    return (value or '').strip()


def _parse_european_float(value: str, row_number: int, header: str) -> float | None:
    cleaned = value.strip().replace(' ', '')
    if not cleaned:
        return None
    if ',' in cleaned:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'[+-]?\d{1,3}(?:\.\d{3})+', cleaned):
        cleaned = cleaned.replace('.', '')
    try:
        result = float(cleaned)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=f'Fila {row_number}: {header} debe ser numérico.',
        ) from error
    if not isfinite(result):
        raise HTTPException(status_code=400, detail=f'Fila {row_number}: {header} debe ser finito.')
    return result


def _parse_date(value: str, row_number: int) -> datetime:
    cleaned = value.strip()
    try:
        return datetime.strptime(cleaned, '%d/%m/%Y').replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    raise HTTPException(
        status_code=400,
        detail=f'Fila {row_number}: fecha debe tener formato DD/MM/YYYY.',
    )


def _normalize_level(value: str) -> str:
    cleaned = _clean_text(value)
    if re.fullmatch(r'[+-]?0*\d+', cleaned):
        sign = '-' if cleaned.startswith('-') else '+' if cleaned.startswith('+') else ''
        return f'{sign}{int(cleaned.lstrip("+-") or "0")}'
    return cleaned


def _area_component(value: str) -> str:
    cleaned = _clean_text(value)
    return '' if cleaned in {'.', '..', '_', '__'} else cleaned


def _area_nivel(row: dict[str, str]) -> str:
    zona = _clean_text(row['ZONA']).split('.', maxsplit=1)[-1]
    nivel = _normalize_level(row['NIVEL'])
    subnivel = _area_component(row['SUBNIVEL'])
    acttype = _area_component(row['ACTTYPE'])
    camara = _area_component(row['CAMARA'])
    if nivel.startswith('-') and subnivel == '0':
        subnivel = ''
    suffix = ''.join((subnivel, acttype, camara))
    if not subnivel:
        suffix = suffix.upper()
    area_nivel = f'{zona}{nivel}_{suffix}' if suffix else f'{zona}{nivel}'
    if not area_nivel:
        raise HTTPException(status_code=400, detail='Area_Nivel no puede estar vacío.')
    return area_nivel


def _read_csv_rows(upload: UploadFile) -> tuple[list[tuple[str, datetime]], list[str], list[dict[str, str]]]:
    try:
        content = upload.file.read()
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            text = content.decode('latin-1')
        except UnicodeDecodeError as error:
            raise HTTPException(status_code=400, detail='El CSV debe estar codificado en UTF-8 o Latin-1.') from error
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=';,\t')
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail='El CSV debe incluir cabeceras.')
    headers = [header.strip() for header in reader.fieldnames]
    if len(headers) != len(set(headers)):
        raise HTTPException(status_code=400, detail='El CSV contiene cabeceras duplicadas.')
    reader.fieldnames = headers
    missing_columns = REQUIRED_COLUMNS - set(headers)
    if missing_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan cabeceras obligatorias: {', '.join(sorted(missing_columns))}.",
        )
    rows = []
    expected_columns = len(headers)
    for row_number, row in enumerate(reader, start=2):
        if None in row or len(row) != expected_columns:
            raise HTTPException(status_code=400, detail=f'Fila {row_number}: número de columnas inválido.')
        rows.append({key: value or '' for key, value in row.items()})
    date_headers = []
    for header in headers:
        try:
            date_headers.append((header, _parse_date(header, 1)))
        except HTTPException:
            continue
    if not date_headers:
        raise HTTPException(
            status_code=400,
            detail='El CSV debe incluir al menos una cabecera de fecha DD/MM/YYYY.',
        )
    attribute_headers = [header for header in headers if header not in REQUIRED_COLUMNS and header not in {header for header, _ in date_headers}]
    return date_headers, attribute_headers, rows


def _row_values(row: dict[str, str], headers: list[str], row_number: int) -> tuple[dict[str, float], dict[str, str]]:
    values: dict[str, float] = {}
    attributes: dict[str, str] = {}
    for header in headers:
        value = _clean_text(row[header])
        if not value or value in {'-', '_', '__'}:
            continue
        try:
            parsed_value = _parse_european_float(value, row_number, header)
            if parsed_value is not None:
                values[_snake_case(header)] = parsed_value
        except HTTPException:
            attributes[_snake_case(header)] = value
    return values, attributes


def _build_document(
    row: dict[str, str],
    tipo: str,
    date_headers: list[tuple[str, datetime]],
    attribute_headers: list[str],
    row_number: int,
) -> dict | None:
    cronograma = []
    for header, fecha in date_headers:
        toneladas = _parse_european_float(row[header], row_number, header)
        cronograma.append({'fecha': fecha, 'toneladas': toneladas if toneladas is not None else 0.0})
    cronograma = [item for item in cronograma if item['toneladas'] is not None]
    cronograma.sort(key=lambda item: item['fecha'])
    valores, atributos = _row_values(row, attribute_headers, row_number)
    area_nivel = _area_nivel(row)
    atributos['id'] = _clean_text(row.get('ID'))
    atributos['name'] = _clean_text(row.get('Name'))
    relevant_content = repr((tipo, area_nivel, atributos.get('id'), valores, atributos, cronograma)).encode()
    return {
        'clave_importacion': hashlib.sha256(relevant_content).hexdigest(),
        'tipo': tipo,
        'fecha_importacion': datetime.now(timezone.utc),
        'Area_Nivel': area_nivel,
        'planta': _clean_text(row['PLANTA']),
        'tarea': _clean_text(row['Tarea']),
        'zona': _clean_text(row['ZONA']).split('.', maxsplit=1)[-1],
        'nivel': _normalize_level(row['NIVEL']),
        'subnivel': _area_component(row['SUBNIVEL']),
        'acttype': _area_component(row['ACTTYPE']),
        'camara': _area_component(row['CAMARA']),
        'valores': valores,
        'atributos': atributos,
        'cronograma': cronograma,
    }


def import_planificacion(
    database: Database, upload: UploadFile, tipo: str
) -> PlanificacionImportada:
    if upload.filename is None or not upload.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail='El archivo debe ser un CSV.')
    date_headers, attribute_headers, rows = _read_csv_rows(upload)
    documents = []
    discarded_rows = 0
    for row_number, row in enumerate(rows, start=2):
        document = _build_document(row, tipo, date_headers, attribute_headers, row_number)
        if document is None:
            discarded_rows += 1
        else:
            documents.append(document)
    inserted, updated = upsert_planificaciones(database, documents)
    return PlanificacionImportada(
        tipo=tipo,
        registrosImportados=inserted,
        registrosActualizados=updated,
        filasDescartadas=discarded_rows,
    )


def get_planificaciones(
    database: Database,
    tipo: str | None = None,
    fecha_desde: datetime | None = None,
    fecha_hasta: datetime | None = None,
    area_nivel: str | None = None,
    planta: str | None = None,
    tarea: str | None = None,
) -> list[PlanificacionRegistro]:
    return [
        PlanificacionRegistro(id=str(document['_id']), **{key: value for key, value in document.items() if key not in {'_id', 'clave_importacion'}})
        for document in list_planificaciones(
            database, tipo, fecha_desde, fecha_hasta, area_nivel, planta, tarea
        )
    ]