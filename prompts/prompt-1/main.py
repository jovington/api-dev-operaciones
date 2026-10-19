import os
import secrets
import hashlib
import shutil
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, status, Request, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from bson import ObjectId

app = FastAPI(
    title="API DEV Partes de Operación y XRF",
    version="1.0.4"
)

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite peticiones desde cualquier origen
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cargar configuración desde el entorno (Base de datos por defecto: Operaciones)
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DATABASE_NAME", "Operaciones")

# Inicializar cliente de MongoDB
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]

# Nombres de colecciones unificados
COLECCION_PARTES = "PartesOperacionPlanta"
COLECCION_USUARIOS = "UsuariosPlanta"
COLECCION_PLANTA_XRF = "PlantaXrf"
COLECCION_TEMPLATES = "PartesOperacionPlantaTemplate"

# ==========================================
# GESTIÓN DE ARCHIVOS Y MULTIMEDIA (VOLUMEN)
# ==========================================
CARPETA_UPLOAD = "/app/uploads/partes"
os.makedirs(CARPETA_UPLOAD, exist_ok=True)

# Montar la carpeta de subidas para servir archivos estáticos públicamente a la Web y App
app.mount("/uploads", StaticFiles(directory="/app/uploads"), name="uploads")


# ==========================================
# MODELOS PYDANTIC
# ==========================================
class ParteOperacionSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    Tipo_Parte: str
    createdAt: Optional[datetime] = None
    ID: Optional[str] = "SIN_ID"
    Fecha: str
    Turno: str
    N_Empleado: Optional[int] = None
    Nombre: Optional[str] = None
    Ronda: Optional[int] = None
    Relevo: Optional[str] = None
    datos: List[Dict[str, Any]] = []


class UsuarioSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    N_Empleado: int
    Nombre: str
    Perfil: str  # Ej: "Operario", "Jefe de relevo", "Jefe de planta", "Dirección"
    Estado: Optional[str] = "Activo"  # "Activo" o "Inactivo"
    password: Optional[str] = None
    qr_token: Optional[str] = None
    regenerar_qr: Optional[bool] = False
    forzar_actualizacion_token: Optional[bool] = False
    departamentos: List[str] = Field(default_factory=list)
    createdAt: Optional[datetime] = None


class ParteSubmit(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ID: Optional[str] = None
    id_parte: Optional[str] = None
    id_partes: Optional[str] = None
    Tipo_Parte: Optional[str] = None
    tipo_parte: Optional[str] = None
    createdAt: Optional[datetime] = None
    fecha_creacion: Optional[str] = None
    Fecha: Optional[str] = None
    Turno: Optional[str] = None
    N_Empleado: Optional[int] = None
    Nombre: Optional[str] = None
    Ronda: Optional[int] = None
    Relevo: Optional[str] = None
    sincronizado: bool = True
    cabecera: Dict[str, Any] = Field(default_factory=dict)
    datos: List[Dict[str, Any]] = Field(default_factory=list)
    items: List[Dict[str, Any]] = Field(default_factory=list)
    observaciones_general: Optional[str] = None
    fotos: List[str] = Field(default_factory=list)


class VehiculosSubmitSchema(BaseModel):
    model_config = ConfigDict(extra="allow")
    titulo: Optional[str] = "Listado de vehiculos - Checklist"
    id: Optional[str] = "Listado de vehiculos"
    nombre: Optional[str] = "LV"
    version: Optional[str] = "1.0"
    equipamiento: List[Dict[str, Any]] = Field(default_factory=list)

class DesactivarMedicionSchema(BaseModel):
    desactive_medicion: bool = True

# ==========================================
# ENDPOINTS - SISTEMA Y ESTADO
# ==========================================
@app.get("/", tags=["Sistema"])
async def root():
    """Verifica la conexión actual con la base de datos MongoDB."""
    try:
        await client.admin.command('ping')
        return {
            "estado": "Conexión exitosa",
            "base_de_datos": DB_NAME,
            "mensaje": "FastAPI conectado correctamente a la base de datos Operaciones en MongoDB."
        }
    except Exception as e:
        return {"estado": "Error de conexión", "detalles": str(e)}


# ==========================================
# ENDPOINTS - PLANTA XRF
# ==========================================
@app.get("/planta-xrf/hoy", tags=["Planta XRF"])
async def listar_mediciones_hoy():
    """Obtiene las mediciones de las últimas 24 horas para cubrir correctamente los turnos cruzados."""
    try:
        hace_24h = datetime.utcnow() - timedelta(hours=24)

        cursor = db[COLECCION_PLANTA_XRF].find({
            "createdAt": {"$gte": hace_24h}
        }).sort("createdAt", -1)

        documentos = await cursor.to_list(length=None)
        
        if not documentos:
            cursor = db[COLECCION_PLANTA_XRF].find({}).sort("createdAt", -1).limit(50)
            documentos = await cursor.to_list(length=None)

        mediciones_formateadas = []
        for doc in documentos:
            mediciones_formateadas.append({
                "ID": doc.get("ID"),
                "Fecha": doc.get("Fecha"),
                "Turno": doc.get("Turno"),
                "product_name": doc.get("product_name"),
                "profile_name": doc.get("profile_name"),
                "reading_number": doc.get("reading_number"),
                "desactive_medicion": doc.get("desactive_medicion", False),
                "resultados_analiticos": [
                    {
                        "element": item.get("element"),
                        "result_ppm": item.get("result_ppm")
                    }
                    for item in doc.get("resultados_analiticos", [])
                ]
            })

        return {
            "total": len(mediciones_formateadas),
            "mediciones": mediciones_formateadas
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar las mediciones: {str(e)}")


@app.get("/planta-xrf/ultimas", tags=["Planta XRF"])
async def listar_ultimas_mediciones(limite: int = 25):
    """Obtiene las últimas mediciones registradas en la colección 'Planta Xrf'."""
    try:
        cursor = db[COLECCION_PLANTA_XRF].find({}).sort("createdAt", -1).limit(limite)
        documentos = await cursor.to_list(length=limite)

        mediciones_formateadas = []
        for doc in documentos:
            product_name = doc.get("product_name")
            profile_name = doc.get("profile_name")
            turno = doc.get("Turno")

            resultados_raw = doc.get("resultados_analiticos", [])
            resultados_analiticos = [
                {
                    "element": item.get("element"),
                    "result_ppm": item.get("result_ppm")
                }
                for item in resultados_raw
            ]

            mediciones_formateadas.append({
                "ID": doc.get("ID"),
                "Fecha": doc.get("Fecha"),
                "Turno": turno,
                "product_name": product_name,
                "profile_name": profile_name,
                "reading_number": doc.get("reading_number"),
                "desactive_medicion": doc.get("desactive_medicion", False),
                "resultados_analiticos": resultados_analiticos
            })

        return {
            "total": len(mediciones_formateadas),
            "mediciones": mediciones_formateadas
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar las últimas mediciones: {str(e)}")


@app.patch("/planta-xrf/{id_medicion}/desactivar", tags=["Planta XRF"])
async def desactivar_medicion_xrf(id_medicion: str, payload: DesactivarMedicionSchema):
    """Marca o desmarca una medición XRF como desactivada (anulada para los cálculos de recuperación)."""
    try:
        filtro = {"ID": id_medicion}
        if ObjectId.is_valid(id_medicion):
            filtro = {"$or": [{"ID": id_medicion}, {"_id": ObjectId(id_medicion)}]}

        resultado = await db[COLECCION_PLANTA_XRF].update_one(
            filtro,
            {"$set": {"desactive_medicion": payload.desactive_medicion}}
        )

        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="Medición XRF no encontrada")

        return {
            "status": "success",
            "message": f"Medición {id_medicion} actualizada correctamente.",
            "desactive_medicion": payload.desactive_medicion
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar la medición: {str(e)}")

@app.get("/planta-xrf/exportarxrf", tags=["Planta XRF"])
async def exportar_datos_excel(limite: int = Query(5, description="Número de filas o conjuntos completos a exportar")):
    """Endpoint GET para alimentar un excel agrupando por ventanas de tiempo. 
    'limite' ahora controla directamente la cantidad de filas/conjuntos completos devueltos."""
    try:
        # Consultamos un lote amplio de documentos crudos para garantizar que cubrimos los 'limite' grupos solicitados
        cursor = db[COLECCION_PLANTA_XRF].find({}).sort("createdAt", -1).limit(max(200, limite * 10))
        documentos = await cursor.to_list(length=None)

        # IMPORTANTE: Filtrar y excluir estrictamente las mediciones anuladas
        mediciones_activas = [doc for doc in documentos if not doc.get("desactive_medicion", False)]

        def parsear_fecha_py(fecha_str):
            if not fecha_str:
                return 0
            try:
                partes = fecha_str.split(' ')
                if len(partes) < 2:
                    return datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S").timestamp() * 1000
                fecha_partes = partes[0].split('/')
                hora_partes = partes[1].split(':')
                if len(fecha_partes) < 3:
                    return datetime.now().timestamp() * 1000
                anio = int(fecha_partes[2])
                mes = int(fecha_partes[1])
                dia = int(fecha_partes[0])
                hora = int(hora_partes[0]) if len(hora_partes) > 0 else 0
                minuto = int(hora_partes[1]) if len(hora_partes) > 1 else 0
                segundo = int(hora_partes[2]) if len(hora_partes) > 2 else 0
                return datetime(anio, mes, dia, hora, minuto, segundo).timestamp() * 1000
            except Exception:
                return 0

        # Ordenar cronológicamente para agrupar por ventana de tiempo
        mediciones_activas.sort(key=lambda x: parsear_fecha_py(x.get("Fecha")))

        # Agrupar por ventana de 7 minutos (igual que el frontend)
        grupos = []
        grupo_actual = None
        ventana_ms = 7 * 60 * 1000

        for m in mediciones_activas:
            tiempo_m = parsear_fecha_py(m.get("Fecha"))
            if not grupo_actual:
                grupo_actual = {"tiempoInicio": tiempo_m, "tiempoFin": tiempo_m, "items": [m]}
            else:
                if (tiempo_m - grupo_actual["tiempoInicio"]) <= ventana_ms:
                    grupo_actual["items"].append(m)
                    grupo_actual["tiempoFin"] = max(grupo_actual["tiempoFin"], tiempo_m)
                else:
                    grupos.append(grupo_actual)
                    grupo_actual = {"tiempoInicio": tiempo_m, "tiempoFin": tiempo_m, "items": [m]}
        if grupo_actual:
            grupos.append(grupo_actual)

        # Invertir para mostrar lo más reciente primero
        grupos.sort(key=lambda x: x["tiempoInicio"], reverse=True)

        # Aplicar el límite estrictamente sobre el número de grupos/filas completas
        grupos = grupos[:limite]

        resultado_filas = []
        for grupo in grupos:
            items = grupo["items"]
            turno_val = "-"
            cf_item = None
            rc_ac_item = None
            rc_item = None
            ac_item = None

            ids_detalle = []
            for m in items:
                if m.get("Turno") and turno_val == "-":
                    turno_val = m.get("Turno")
                
                perfil = (m.get("profile_name") or "").upper()
                if "CF" in perfil:
                    cf_item = m
                elif "RC" in perfil and "AC" in perfil:
                    rc_ac_item = m
                elif "RC" in perfil:
                    rc_item = m
                elif "AC" in perfil:
                    ac_item = m

                # Extraer resultados analíticos ordenados y formateados con 2 decimales
                resultados_raw = m.get("resultados_analiticos", [])
                resultados_raw_sorted = sorted(resultados_raw, key=lambda x: (x.get("element") or ""))
                
                valores_filtrados = []
                for r in resultados_raw_sorted:
                    el = (r.get("element") or "").upper()
                    val_ppm = r.get("result_ppm", 0) or 0
                    if "CF" in perfil:
                        if el in ["CU", "AS"]:
                            val_fmt = f"{val_ppm / 10000:.2f}%"
                            valores_filtrados.append({"elemento": f"{el}(%)", "valor": val_fmt})
                        elif el in ["SB", "BI"]:
                            val_fmt = f"{val_ppm:.2f} ppm"
                            valores_filtrados.append({"elemento": f"{el}(ppm)", "valor": val_fmt})
                    elif "RC" in perfil or "AC" in perfil:
                        if el == "CU":
                            val_fmt = f"{val_ppm:.2f} ppm"
                            valores_filtrados.append({"elemento": "Cu(ppm)", "valor": val_fmt})

                ids_detalle.append({
                    "ID": m.get("ID"),
                    "Perfil": m.get("profile_name"),
                    "N_Medicion": m.get("reading_number"),
                    "Valores": valores_filtrados
                })

            primer_fecha = items[0].get("Fecha", "") if items else ""

            def obtener_ppm_val(res, elem):
                if not res:
                    return 0
                item = next((r for r in res if (r.get("element") or "").upper() == elem.upper()), None)
                return item.get("result_ppm", 0) if item else 0

            cf_res = cf_item.get("resultados_analiticos") if cf_item else None
            rc_source = rc_ac_item or rc_item
            ac_source = rc_ac_item or ac_item
            rc_res = rc_source.get("resultados_analiticos") if rc_source else None
            ac_res = ac_source.get("resultados_analiticos") if ac_source else None

            cu_cf = f"{obtener_ppm_val(cf_res, 'Cu') / 10000:.2f}" if cf_res else "-"
            as_cf = f"{obtener_ppm_val(cf_res, 'As') / 10000:.2f}" if cf_res else "-"
            sb_cf = f"{obtener_ppm_val(cf_res, 'Sb'):.2f}" if cf_res else "-"
            bi_cf = f"{obtener_ppm_val(cf_res, 'Bi'):.2f}" if cf_res else "-"

            cu_rc_val = obtener_ppm_val(rc_res, 'Cu') if rc_res else 0
            cu_ac_val = obtener_ppm_val(ac_res, 'Cu') if ac_res else 0

            cu_rc = f"{cu_rc_val:.2f}" if rc_res else "-"
            cu_ac = f"{cu_ac_val:.2f}" if rc_res else "-"

            rec_cu = "-"
            if rc_res and cu_rc_val > 0 and cu_ac_val > 0:
                rec = ((cu_rc_val - cu_ac_val) / cu_rc_val) * 100
                rec_cu = f"{rec:.2f}%"

            resultado_filas.append({
                "Dia_Hora": primer_fecha,
                "Turno": turno_val,
                "Ids_Detalle": ids_detalle,
                "Resumen_Calculado": {
                    "Cu_CF_Pct": cu_cf,
                    "As_CF_Pct": as_cf,
                    "Sb_CF_Ppm": sb_cf,
                    "Bi_CF_Ppm": bi_cf,
                    "Cu_RC_Ppm": cu_rc,
                    "Cu_AC_Ppm": cu_ac,
                    "Recuperacion_Cu": rec_cu
                }
            })

        return {
            "status": "success",
            "total_filas": len(resultado_filas),
            "filas": resultado_filas
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar datos para Excel: {str(e)}")

# ==========================================
# ENDPOINTS - PARTES DE OPERACIÓN
# ==========================================
@app.post("/planta/partes", status_code=201, tags=["Partes de Operación"])
async def crear_parte_operacion(parte: ParteOperacionSchema):
    """Registra un nuevo parte de operación en la base de datos."""
    try:
        if hasattr(parte, "model_dump"):
            parte_dict = parte.model_dump()
        else:
            parte_dict = parte.dict()

        if not parte_dict.get("createdAt"):
            parte_dict["createdAt"] = datetime.utcnow()

        resultado = await db[COLECCION_PARTES].insert_one(parte_dict)

        return {
            "mensaje": "Parte de operación guardado correctamente en MongoDB",
            "base_de_datos": DB_NAME,
            "coleccion": COLECCION_PARTES,
            "id_documento_mongo": str(resultado.inserted_id),
            "Tipo_Parte": parte.Tipo_Parte,
            "ID_Parte": parte.ID
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar el parte: {str(e)}")


@app.get("/planta/partes", tags=["Partes de Operación"])
async def listar_partes_operacion(tipo_parte: Optional[str] = None, turno: Optional[str] = None, fecha: Optional[str] = None):
    """Obtiene el listado de partes registrados con filtros opcionales."""
    try:
        filtro = {}
        if tipo_parte:
            filtro["Tipo_Parte"] = tipo_parte
        if turno:
            filtro["Turno"] = turno
        if fecha:
            filtro["Fecha"] = fecha

        cursor = db[COLECCION_PARTES].find(filtro, {"_id": 0})
        partes = await cursor.to_list(length=1000)
        return {
            "total": len(partes),
            "partes": partes
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar los partes: {str(e)}")


# ==========================================
# ENDPOINTS - CHECKLISTS Y PLANTILLAS
# ==========================================
@app.get("/checklist/vehiculos", tags=["Checklists y Plantillas"])
async def obtener_listado_vehiculos():
    """Devuelve el listado completo de vehículos y su equipamiento estructurado para los checklists."""
    try:
        doc = await db[COLECCION_TEMPLATES].find_one({"nombre": "LV"})
        if not doc:
            doc = await db[COLECCION_TEMPLATES].find_one({"id": {"$regex": "vehiculos"}})
        
        if not doc:
            doc = {
                "titulo": "Listado de vehiculos - Checklist",
                "id": "Listado de vehiculos",
                "nombre": "LV",
                "version": "1.0",
                "equipamiento": [
                    {
                        "nombre": "PALA PRINCIPAL",
                        "numero_interno": "#1",
                        "matricula_identificacion": None,
                        "tipo": "Pala",
                        "marca": "KOMATSU",
                        "modelo": "WA-480-8",
                        "propiedad": "Renting",
                        "departamento": "Planta",
                        "ubicacion": "Planta",
                        "responsable": "",
                        "qr_token": secrets.token_hex(16)
                    },
                    {
                        "nombre": "PALA BACKUP",
                        "numero_interno": "#2",
                        "matricula_identificacion": None,
                        "tipo": "Pala",
                        "marca": "KOMATSU",
                        "modelo": "WA-480",
                        "departamento": "Planta",
                        "propiedad": "Orovalle",
                        "ubicacion": "Planta",
                        "responsable": "",
                        "qr_token": secrets.token_hex(16)
                    },
                    {
                        "nombre": "PICKUP DE OPERACIÓN",
                        "numero_interno": None,
                        "matricula_identificacion": "6270-HFW",
                        "tipo": "Pickup",
                        "marca": "TOYOTA",
                        "modelo": "HILUX Dc 2.5 Td 4x4",
                        "departamento": "Planta",
                        "propiedad": "Orovalle",
                        "ubicacion": "Planta",
                        "responsable": "",
                        "qr_token": secrets.token_hex(16)
                    },
                    {
                        "nombre": "PICKUP MANTENIMIENTO",
                        "numero_interno": None,
                        "matricula_identificacion": "1521-JCF",
                        "tipo": "Pickup",
                        "marca": "TOYOTA",
                        "modelo": "HILUX Dc 2.5 Td 4x4",
                        "departamento": "Planta",
                        "propiedad": "Orovalle",
                        "ubicacion": "Planta",
                        "departamento": "Mantenimiento electrico Planta",
                        "responsable": "",
                        "qr_token": secrets.token_hex(16)
                    },
                    {
                        "nombre": "CARRETILLA ELEVADORA",
                        "numero_interno": "#1",
                        "matricula_identificacion": None,
                        "tipo": "Carretilla",
                        "marca": "Manitou",
                        "modelo": "MH 25-4T",
                        "departamento": "Planta",
                        "propiedad": "Orovalle",
                        "ubicacion": "Planta",
                        "responsable": "",
                        "qr_token": secrets.token_hex(16)
                    },
                    {
                        "nombre": "Retroexcavadora",
                        "numero_interno": "#17",
                        "matricula_identificacion": None,
                        "tipo": "Retro",
                        "marca": "YANMAR",
                        "modelo": "SV-100",
                        "departamento": "Planta",
                        "propiedad": "Orovalle",
                        "ubicacion": "Planta",
                        "responsable": "",
                        "qr_token": secrets.token_hex(16)
                    },
                    {
                        "nombre": "Retroexcavadora",
                        "numero_interno": "#14",
                        "matricula_identificacion": None,
                        "tipo": "Retro",
                        "marca": "YANMAR",
                        "modelo": "SV-100",
                        "departamento": "Planta",
                        "propiedad": "Orovalle",
                        "ubicacion": "Planta",
                        "responsable": "",
                        "qr_token": secrets.token_hex(16)
                    },
                    {
                        "nombre": "Retroexcavadora",
                        "numero_interno": "#3",
                        "matricula_identificacion": None,
                        "tipo": "Retro",
                        "marca": "LIEBHERR",
                        "modelo": None,
                        "departamento": "Planta",
                        "propiedad": "Orovalle",
                        "ubicacion": "Planta",
                        "responsable": "",
                        "qr_token": secrets.token_hex(16)
                    }
                ]
            }
            await db[COLECCION_TEMPLATES].insert_one(doc.copy())
        
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
            
        return doc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener el listado de vehículos: {str(e)}")


@app.post("/checklist/vehiculos", tags=["Checklists y Plantillas"])
async def guardar_o_actualizar_vehiculos(payload: VehiculosSubmitSchema):
    """Crea o actualiza el listado global de vehículos y su equipamiento en la base de datos."""
    try:
        if hasattr(payload, "model_dump"):
            data_dict = payload.model_dump(by_alias=True)
        else:
            data_dict = payload.dict()
        
        for vehiculo in data_dict.get("equipamiento", []):
            if not vehiculo.get("qr_token"):
                vehiculo["qr_token"] = secrets.token_hex(16)
            if not vehiculo.get("estado"):
                vehiculo["estado"] = "Activo"

        nombre_clave = data_dict.get("nombre", "LV")
        filtro = {"nombre": nombre_clave}
        
        resultado = await db[COLECCION_TEMPLATES].update_one(
            filtro,
            {"$set": data_dict},
            upsert=True
        )
        
        return {
            "status": "success",
            "message": "Listado de vehículos actualizado y sincronizado correctamente en MongoDB",
            "matched_count": resultado.matched_count,
            "modified_count": resultado.modified_count,
            "upserted_id": str(resultado.upserted_id) if resultado.upserted_id else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar el listado de vehículos: {str(e)}")


@app.get("/checklist/templates", tags=["Checklists y Plantillas"])
async def listar_plantillas(departamento: Optional[str] = Query(None, description="Filtrar por departamento")):
    """Devuelve todas las plantillas de checklist disponibles."""
    query = {}
    if departamento:
        query["departamentos"] = departamento
    
    cursor = db[COLECCION_TEMPLATES].find(query, {"_id": 0})
    templates = await cursor.to_list(length=100)
    return {"status": "success", "total": len(templates), "data": templates}


@app.get("/checklist/templates/{tipo_parte}", tags=["Checklists y Plantillas"])
async def obtener_plantilla_por_tipo(tipo_parte: str):
    """Devuelve la estructura de esqueleto para un tipo de checklist específico."""
    template = await db[COLECCION_TEMPLATES].find_one({"tipo_parte": tipo_parte}, {"_id": 0})
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plantilla con tipo '{tipo_parte}' no encontrada"
        )
    return template


@app.post("/checklist/partes", tags=["Checklists y Plantillas"])
async def sincronizar_parte_checklist(parte: ParteSubmit):
    """Recibe el parte de operación rellenado desde la app Android de forma idempotente."""
    id_parte = parte.ID or parte.id_parte or parte.id_partes
    tipo_parte = parte.Tipo_Parte or parte.tipo_parte

    if not id_parte:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El campo ID es obligatorio"
        )

    if not tipo_parte:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El campo Tipo_Parte es obligatorio"
        )

    if len(id_parte) != 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El campo ID debe tener exactamente 6 caracteres"
        )

    existente = await db[COLECCION_PARTES].find_one({"ID": id_parte}, {"_id": 1})
    if existente:
        return {
            "status": "ok",
            "message": "El parte ya había sido sincronizado previamente.",
            "ID": id_parte,
            "id_parte": id_parte
        }
    
    if hasattr(parte, "model_dump"):
        parte_dict = parte.model_dump()
    else:
        parte_dict = parte.dict()

    parte_dict["ID"] = id_parte
    parte_dict["Tipo_Parte"] = tipo_parte
    parte_dict["createdAt"] = parte_dict.get("createdAt") or datetime.utcnow()
    parte_dict["Fecha"] = parte_dict.get("Fecha") or parte_dict.get("fecha_creacion")
    parte_dict["Turno"] = parte_dict.get("Turno") or parte_dict.get("cabecera", {}).get("Turno")
    parte_dict["N_Empleado"] = parte_dict.get("N_Empleado") or parte_dict.get("cabecera", {}).get("N_Empleado")
    parte_dict["Nombre"] = parte_dict.get("Nombre") or parte_dict.get("cabecera", {}).get("Nombre")
    parte_dict["Ronda"] = parte_dict.get("Ronda")
    parte_dict["Relevo"] = parte_dict.get("Relevo") or parte_dict.get("cabecera", {}).get("Relevo")
    parte_dict["datos"] = parte_dict.get("datos") or [{"titulo": "Checklist", "items": parte_dict.get("items", [])}]
    
    # Limpieza de campos redundantes auxiliares recibidos del cliente
    parte_dict.pop("id_parte", None)
    parte_dict.pop("id_partes", None)
    parte_dict.pop("tipo_parte", None)
    parte_dict.pop("fecha_creacion", None)
    parte_dict.pop("items", None)

    if isinstance(parte_dict.get("cabecera"), dict):
        parte_dict["cabecera"]["ID"] = id_parte
        parte_dict["cabecera"]["Tipo_Parte"] = tipo_parte
        parte_dict["cabecera"].pop("id_parte", None)
        parte_dict["cabecera"].pop("id_partes", None)
        parte_dict["cabecera"].pop("tipo_parte", None)
        
    await db[COLECCION_PARTES].insert_one(parte_dict)
    
    return {
        "status": "success",
        "message": "Parte sincronizado correctamente en el servidor",
        "ID": id_parte,
        "id_parte": id_parte
    }


# ==========================================
# ENDPOINTS - SUBIDA Y SERVICIO DE FOTOGRAFÍAS
# ==========================================
@app.post("/planta/partes/{id_parte}/fotos", tags=["Partes de Operación"])
async def subir_foto_general_checklist(id_parte: str, request: Request):
    """Sube una fotografía adjunta general asociada a un ID de parte de operación de forma flexible."""
    try:
        form = await request.form()
        file = form.get("file") or form.get("imagen") or form.get("foto") or form.get("archivo")

        if not file or not hasattr(file, "filename"):
            raise HTTPException(status_code=422, detail="No se ha encontrado ningún archivo válido en la petición multipart.")

        if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            raise HTTPException(status_code=400, detail="Formato de archivo no válido. Solo se permiten imágenes.")

        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"general_{id_parte}_{timestamp_str}_{file.filename.replace(' ', '_')}"
        file_path = os.path.join(CARPETA_UPLOAD, nombre_archivo)

        contents = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(contents)

        url_relativa = f"/uploads/partes/{nombre_archivo}"

        resultado = await db[COLECCION_PARTES].update_one(
            {"ID": id_parte},
            {"$push": {"fotos": url_relativa}}
        )

        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="No se encontró el parte especificado para asociar la foto general.")

        return {
            "status": "success",
            "message": "Fotografía general subida y asociada correctamente",
            "ID": id_parte,
            "url_foto": url_relativa
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar la subida de la imagen: {str(e)}")


@app.post("/planta/partes/{id_parte}/items/{item_id}/fotos", tags=["Partes de Operación"])
async def subir_foto_item_checklist(id_parte: str, item_id: str, request: Request):
    """Sube una fotografía adjunta directamente a una línea específica del checklist."""
    try:
        form = await request.form()
        file = form.get("file") or form.get("imagen") or form.get("foto") or form.get("archivo")

        if not file or not hasattr(file, "filename"):
            raise HTTPException(status_code=422, detail="No se ha encontrado ningún archivo válido en la petición multipart.")

        if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            raise HTTPException(status_code=400, detail="Formato de archivo no válido. Solo se permiten imágenes.")

        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"item_{id_parte}_linea{item_id}_{timestamp_str}_{file.filename.replace(' ', '_')}"
        file_path = os.path.join(CARPETA_UPLOAD, nombre_archivo)

        contents = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(contents)

        url_relativa = f"/uploads/partes/{nombre_archivo}"

        valores_busqueda = [item_id]
        try:
            if "." in item_id:
                val_float = float(item_id)
                valores_busqueda.append(val_float)
                if val_float.is_integer():
                    valores_busqueda.append(int(val_float))
            else:
                val_int = int(item_id)
                valores_busqueda.append(val_int)
                valores_busqueda.append(float(val_int))
        except ValueError:
            pass

        resultado = await db[COLECCION_PARTES].update_one(
            {"ID": id_parte, "datos.items.id": {"$in": valores_busqueda}},
            {"$push": {"datos.$[seccion].items.$[item].fotos": url_relativa}},
            array_filters=[
                {"seccion.items.id": {"$in": valores_busqueda}}, 
                {"item.id": {"$in": valores_busqueda}}
            ]
        )

        if resultado.matched_count == 0:
            raise HTTPException(status_code=404, detail="No se encontró el parte o el ID de ítem del checklist especificado.")

        return {
            "status": "success",
            "message": "Fotografía de línea de checklist guardada correctamente",
            "ID": id_parte,
            "item_id": item_id,
            "url_foto": url_relativa
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al procesar la subida de imagen para el ítem: {str(e)}")


@app.get("/uploads/partes/{nombre_archivo}", tags=["Partes de Operación"])
async def obtener_foto_parte(nombre_archivo: str):
    """Endpoint GET explícito para servir las fotografías almacenadas y evitar errores 404 en la web."""
    file_path = os.path.join(CARPETA_UPLOAD, nombre_archivo)
    
    if os.path.exists(file_path):
        return FileResponse(file_path)
    
    raise HTTPException(status_code=404, detail="La imagen solicitada no existe en el servidor.")


# ==========================================
# ENDPOINTS - GESTIÓN DE USUARIOS
# ==========================================
@app.post("/planta/usuarios", status_code=201, tags=["Gestión de Usuarios"])
async def guardar_usuario(usuario: UsuarioSchema):
    """Crea un nuevo usuario o actualiza uno existente si el N_Empleado ya está registrado."""
    try:
        if hasattr(usuario, "model_dump"):
            usuario_dict = usuario.model_dump()
        else:
            usuario_dict = usuario.dict()

        existente = await db[COLECCION_USUARIOS].find_one({"N_Empleado": usuario.N_Empleado})
        
        if usuario_dict.get("password"):
            pwd = usuario_dict["password"]
            if not pwd.startswith("sha256$"):
                usuario_dict["password"] = "sha256$" + hashlib.sha256(pwd.encode()).hexdigest()
        elif existente and "password" in existente:
            usuario_dict["password"] = existente["password"]

        if not usuario_dict.get("departamentos") and existente and existente.get("departamentos"):
            usuario_dict["departamentos"] = existente["departamentos"]

        if usuario_dict.get("regenerar_qr") or usuario_dict.get("forzar_actualizacion_token") or not usuario_dict.get("qr_token"):
            if usuario_dict.get("qr_token") and not usuario_dict.get("regenerar_qr"):
                pass
            else:
                usuario_dict["qr_token"] = secrets.token_hex(16)
        else:
            if existente and existente.get("qr_token"):
                usuario_dict["qr_token"] = existente["qr_token"]

        usuario_dict.pop("regenerar_qr", None)
        usuario_dict.pop("forzar_actualizacion_token", None)

        if existente:
            if "createdAt" in existente and not usuario_dict.get("createdAt"):
                usuario_dict["createdAt"] = existente["createdAt"]

            await db[COLECCION_USUARIOS].update_one(
                {"N_Empleado": usuario.N_Empleado},
                {"$set": usuario_dict}
            )
            return {
                "mensaje": "Usuario actualizado correctamente",
                "N_Empleado": usuario.N_Empleado,
                "Nombre": usuario.Nombre,
                "Perfil": usuario.Perfil,
                "Estado": usuario.Estado,
                "qr_token": usuario_dict["qr_token"]
            }
        else:
            if not usuario_dict.get("createdAt"):
                usuario_dict["createdAt"] = datetime.utcnow()

            resultado = await db[COLECCION_USUARIOS].insert_one(usuario_dict)
            return {
                "mensaje": "Usuario creado correctamente",
                "id_documento_mongo": str(resultado.inserted_id),
                "N_Empleado": usuario.N_Empleado,
                "Nombre": usuario.Nombre,
                "Perfil": usuario.Perfil,
                "Estado": usuario.Estado,
                "qr_token": usuario_dict["qr_token"]
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar usuario: {str(e)}")


@app.get("/planta/usuarios", tags=["Gestión de Usuarios"])
async def listar_usuarios():
    """Obtiene la lista completa de usuarios registrados en el sistema."""
    try:
        cursor = db[COLECCION_USUARIOS].find({}, {"_id": 0})
        usuarios = await cursor.to_list(length=500)
        return {
            "total": len(usuarios),
            "usuarios": usuarios
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al listar usuarios: {str(e)}")
    
# ==========================================
# GESTIÓN DE SESIONES Y TOKENS EFÍMEROS
# ==========================================
COLECCION_SESIONES = "sesiones"

class LoginRequest(BaseModel):
    n_empleado: int
    password: str

class LoginQrRequest(BaseModel):
    qr_token: str

@app.post("/planta/login", tags=["Gestión de Usuarios"])
async def login_tradicional(credenciales: LoginRequest):
    """Autentica al usuario por Nº de Empleado y Contraseña."""
    try:
        user = await db[COLECCION_USUARIOS].find_one({"N_Empleado": credenciales.n_empleado})
        if not user:
            raise HTTPException(status_code=401, detail="Número de empleado no encontrado")

        if user.get("Estado", "Activo") != "Activo":
            raise HTTPException(status_code=401, detail="El usuario se encuentra inactivo")

        pass_input = credenciales.password
        hash_hex = hashlib.sha256(pass_input.encode()).hexdigest()
        password_formateada = "sha256$" + hash_hex

        stored_pass = user.get("password")
        if stored_pass != password_formateada and stored_pass != pass_input:
            raise HTTPException(status_code=401, detail="Contraseña incorrecta")

        token_efimero = secrets.token_hex(32)
        expiracion = datetime.utcnow() + timedelta(hours=12)

        await db[COLECCION_SESIONES].insert_one({
            "token": token_efimero,
            "n_empleado": user["N_Empleado"],
            "createdAt": datetime.utcnow(),
            "expires_at": expiracion
        })

        return {
            "status": "success",
            "token_sesion": token_efimero,
            "operador": {
                "nombre": user.get("Nombre"),
                "n_empleado": user.get("N_Empleado"),
                "Perfil": user.get("Perfil"),
                "departamentos": user.get("departamentos", [])
            }
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el servidor: {str(e)}")


@app.post("/planta/login-qr", tags=["Gestión de Usuarios"])
async def login_por_qr(datos: LoginQrRequest):
    """Autentica al operario mediante el escaneo de su QR único."""
    try:
        user = await db[COLECCION_USUARIOS].find_one({"qr_token": datos.qr_token})
        if not user:
            raise HTTPException(status_code=401, detail="Código QR de operario no válido")

        if user.get("Estado", "Activo") != "Activo":
            raise HTTPException(status_code=401, detail="El operario se encuentra inactivo")

        token_efimero = secrets.token_hex(32)
        expiracion = datetime.utcnow() + timedelta(hours=12)

        await db[COLECCION_SESIONES].insert_one({
            "token": token_efimero,
            "n_empleado": user["N_Empleado"],
            "createdAt": datetime.utcnow(),
            "expires_at": expiracion
        })

        return {
            "status": "success",
            "token_sesion": token_efimero,
            "operador": {
                "nombre": user.get("Nombre"),
                "n_empleado": user.get("N_Empleado"),
                "Perfil": user.get("Perfil"),
                "departamentos": user.get("departamentos", [])
            }
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el servidor: {str(e)}")