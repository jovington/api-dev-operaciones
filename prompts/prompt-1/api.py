from fastapi import FastAPI, HTTPException, Body, Query, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import os
import json
import math # <--- IMPORTANTE: Asegúrate de tenerlo arriba
from datetime import datetime, timedelta
from pydantic import BaseModel, Field
from bson import ObjectId
from typing import Dict, Any, Optional, List

app = FastAPI(title="API Control de Báscula - Planta Oro")
router = APIRouter()

# --- CONFIGURACIÓN DE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modelo de entrada para el formulario
class ZonaMinaInput(BaseModel):
    mina: str           # "01" o "02"
    zona: str           # "SB", "AR", etc.
    nivel: str          # "120", "+120", "-050"
    subnivel: str       # "0" a "7"
    acttype: str        # "GL", "SP", "AC", "RV", "RB"
    camara: Optional[str] = "."
    panel: Optional[str] = ".."
    parent_id: Optional[str] = None
    nivel_jerarquico: int = 1  # 1=Raíz, 2=Hijo, 3=Nieto, 4=Bisnieto
    importado_planif: bool = False
    es_raiz: bool = False
    lado: Optional[str] = None # "derecha" o "izquierda"

# --- MODELO PYDANTIC PARA VALIDACIÓN DEL HISTÓRICO ---
class ParteDiarioMuestras(BaseModel):
    fecha: str = Field(..., description="Fecha del parte en formato YYYY-MM-DD")
    relevo: str = Field(..., description="Turno de trabajo: 1P, 2P o N")
    areas: list
    observaciones_generales: Optional[str] = ""
    material_de_baja: Optional[str] = ""
    firmas_y_validacion: Dict[str, Any]



# --- CARGA DE VARIABLES CON FAILSAFE ---
MONGO_USER = os.getenv("MONGO_USER", "root")
MONGO_PASS = os.getenv("MONGO_PASSWORD", "P3lopicopata")
MONGO_HOST = os.getenv("MONGO_HOST", "192.168.100.151")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")
MONGO_DB   = os.getenv("MONGO_DB", "bascula_pl")

# Construcción de la URI
MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASS}@{MONGO_HOST}:{MONGO_PORT}/"
#mongodb://root:P3lopicopata@192.168.100.151:27017/

# --- CONEXIÓN A BBDD (CORREGIDO EL ORDEN) ---
try:
    # 1. Iniciamos el cliente
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    
    # 2. Definimos las bases de datos (Báscula y Planta)
    db = client[MONGO_DB]
    db_planta = client["PlantaOperaciones"] 
    col_blending = db_planta["HistoricoBlending"]
    col_geologia = db_planta["HistoricoGeologia"]
    col_control = db_planta["HistoricoControl"]
   
    # Definición de la base de datos de Recursos Humanos/Control
    db_hrac = client["hrac_control"]
    col_operaciones = db_hrac["hrac_control_operation"]
    col_personal = db_hrac["hrac_personal"]
    col_terminales = db_hrac["hrac_terminales"]

# Definición de la base de datos de Operaciones Mina
    db_mina = client[os.getenv("MONGO_DB_MINA", "MinaOperaciones")]
    col_mina_config = db_mina[os.getenv("MONGO_DB_MINA_COL_CONFIG", "mop_config")]
    col_mina_data = db_mina[os.getenv("MONGO_DB_MINA_COL_DATA", "mop_data")]

# Definición de la base de datos de Operaciones planta partes 
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Base de datos específica de PlantaOperaciones
    db_planta = client["PlantaOperaciones"]        
    # NUEVAS COLECCIONES ASIGNADAS SEGÚN TUS REQUISITOS
    col_pdm_data = db_planta["pdm_data"]           # Contiene la plantilla de configuración
    col_pdm_historico = db_planta["pdm_historico"] # Contiene los partes diarios completados

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Base de datos específica de PlantaOperaciones
    db_planta = client["PlantaOperaciones"] 
    
    # NUEVAS COLECCIONES ASIGNADAS SEGÚN TUS REQUISITOS
    col_pdm_data = db_planta["pdm_data"]           # Contiene la plantilla de configuración
    col_pdm_historico = db_planta["pdm_historico"] # Contiene los partes diarios completados

    # Test de conexión
    client.admin.command('ping')
    print(f"INFO: Conectado a MongoDB en {MONGO_HOST}:{MONGO_PORT}")
except Exception as e:
    print(f"ERROR CRÍTICO: No se pudo conectar a MongoDB: {e}")

# hrac_personal to hrac_personal
# --- ENDPOINTS ---

# @app.get("/mediciones")
# async def get_mediciones(limit: int = 100):
#     """
#     Retorna las últimas mediciones ordenadas por Fecha descendente.
#     Usa el campo 'Fecha' para asegurar que lo más nuevo salga primero.
#     """
#     try:
#         # CORRECCIÓN: Ordenamos por "Fecha" (Case Sensitive) para ver lo de HOY primero
#         cursor = db["mediciones"].find().sort("Fecha", -1).limit(limit)
#         data = []
#         for doc in cursor:
#             # Convertimos el ObjectId de Mongo a string para que FastAPI pueda serializarlo
#             doc["_id"] = str(doc["_id"])
#             data.append(doc)
#         return data
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error consultando mediciones: {e}")

from fastapi.encoders import jsonable_encoder
import math

@app.get("/mediciones")
async def get_mediciones(limit: int = 100):
    try:
        # Consultamos a la colección
        cursor = db["mediciones"].find().sort("Fecha", -1).limit(limit)
        
        # El jsonable_encoder se encarga de convertir ObjectIds, fechas 
        # y de manejar errores de floats fuera de rango convirtiéndolos en null.
        raw_data = list(cursor)
        
        for doc in raw_data:
            doc["_id"] = str(doc["_id"])
            # Limpieza manual por si acaso el encoder se salta algo
            for k, v in doc.items():
                if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
                    doc[k] = None

        return jsonable_encoder(raw_data)

    except Exception as e:
        print(f"Error detectado: {e}") # Esto saldrá en tu terminal de docker
        raise HTTPException(status_code=500, detail="Error al procesar los datos de báscula")

@app.get("/config")
async def get_worker_config():
    try:
        cfg = db["mediciones_control"].find_one({"id": "config_worker"}, {"_id": 0})
        return cfg or {"message": "Configuración no inicializada aún"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/status")
async def get_status():
    """Endpoint de salud del sistema."""
    return {
        "status": "online",
        "mongo_host": MONGO_HOST,
        "database": MONGO_DB,
        "database_planta": "Planta_Operaciones",
        "server_time": datetime.now()
    }

# --- NUEVOS ENDPOINTS PARA GEOLOGÍA ---

@app.get("/config/geologia")
async def get_opciones_geologia():
    """Retorna las opciones de clasificación (Mineral, Baja Ley, Esteril) desde la DB."""
    try:
        cfg = db["config_parametros"].find_one({"proceso": "clasificacion_geologia"}, {"_id": 0})
        if not cfg:
            return []
        return cfg["opciones"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- NUEVOS ENDPOINTS PARA HISTÓRICO GEOLOGÍA ---

@app.get("/geologia/muestras")
async def get_muestras_geologia(
    limit: int = 100, 
    block: str = None, 
    days: int = None
):
    """
    Retorna el histórico de geología.
    Permite filtrar por bloque específico y por ventana de días hacia atrás.
    """
    try:
        query = {}

        # 1. Filtro por Bloque (opcional)
        if block:
            query["Nomenclatura.Block"] = block

        # 2. Filtro por Ventana de Días (opcional)
        if days:
            fecha_limite = datetime.now() - timedelta(days=days)
            query["Varios.Fecha"] = {"$gte": fecha_limite}

        # Ejecutamos la consulta ordenando por fecha de toma de muestra (más reciente primero)
        cursor = col_geologia.find(query).sort("Varios.Fecha", -1).limit(limit)
        
        data = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            
            # Serializamos la fecha de 'Varios' si existe
            if "Varios" in doc and isinstance(doc["Varios"].get("Fecha"), datetime):
                doc["Varios"]["Fecha"] = doc["Varios"]["Fecha"].isoformat()
            
            # Serializamos la fecha de 'Laboratorio'
            if "Laboratorio" in doc and isinstance(doc["Laboratorio"].get("Fecha_Importacion"), datetime):
                doc["Laboratorio"]["Fecha_Importacion"] = doc["Laboratorio"]["Fecha_Importacion"].isoformat()
            
            data.append(doc)
            
        return data

    except Exception as e:
        print(f"Error en API Geología: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/validar_material")
async def validar_material(payload: dict = Body(...)):
    """
    Actualiza una medición existente con la clasificación de Geología.
    Se espera: {"id_registro": "...", "clasificacion": "..."}
    """
    try:
        id_registro = payload.get("id_registro")
        clasificacion = payload.get("clasificacion")
        
        if not id_registro or not clasificacion:
            raise HTTPException(status_code=400, detail="Faltan campos id_registro o clasificacion")

        result = db["mediciones"].update_one(
            {"_id": ObjectId(id_registro)},
            {"$set": {
                "Clasificacion_Geologia": clasificacion,
                "Fecha_Validacion": datetime.now(),
                "Estado_Material": "Validado",
                "Validado_Por": "Jefe Relevos"
            }}
        )

        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="No se encontró la medición con ese ID")

        return {"status": "success", "message": f"Material clasificado como {clasificacion}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- NUEVOS ENDPOINTS BASCULA V0.2 ---

@app.get("/producto_planta")
async def get_producto_planta(
    limit: int = 500, 
    producto: str = None, 
    fecha_inicio: str = None, 
    fecha_fin: str = None
):
    """Retorna listado de mediciones filtrado por nombre de producto y rango de fechas."""
    try:
        query = {}
        if producto:
            query["Producto"] = producto
        
        # Filtro de rango de fechas para sincronizar con el calendario del HTML
        if fecha_inicio or fecha_fin:
            query["Fecha"] = {}
            if fecha_inicio:
                query["Fecha"]["$gte"] = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            if fecha_fin:
                query["Fecha"]["$lte"] = datetime.strptime(fecha_fin, "%Y-%m-%d") + timedelta(days=1)
        
        cursor = db["mediciones"].find(query).sort("Fecha", -1).limit(limit)
        data = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            data.append(doc)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en producto_planta: {e}")

@app.get("/stats/balance_mineral")
async def get_balance_mineral(fecha_inicio: str = None, fecha_fin: str = None):
    """
    Calcula totales de toneladas filtrado por rango de fechas del calendario.
    Si no hay fechas, filtra por el día de hoy.
    """
    try:
        query = {}
        
        if fecha_inicio or fecha_fin:
            query["Fecha"] = {}
            if fecha_inicio:
                query["Fecha"]["$gte"] = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            if fecha_fin:
                query["Fecha"]["$lte"] = datetime.strptime(fecha_fin, "%Y-%m-%d") + timedelta(days=1)
        else:
            # Filtro por defecto para el día actual
            hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            query["Fecha"] = {"$gte": hoy}

        # Pipeline de agregación sumando por Producto
        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": "$Producto",
                    "total_tn": {"$sum": {"$divide": ["$Peso_Neto", 1000]}}
                }
            }
        ]
        
        cursor = db["mediciones"].aggregate(pipeline)
        
        balance = {
            "Boinás": 0,
            "Carlés": 0
        }
        
        for doc in cursor:
            nombre = doc["_id"]
            if not nombre:
                continue
            
            toneladas = round(doc["total_tn"], 2)
            
            # Busqueda por contenido del string exacto que nos da la DB
            if "Boinás" in str(nombre) or "BOINA" in str(nombre).upper():
                balance["Boinás"] += toneladas
            elif "Carlés" in nombre or "CARLE" in str(nombre).upper():
                balance["Carlés"] += toneladas
                
        return balance
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en balance: {e}")



# --- ENDPOINT PARA EL DASHBOARD DE CONTROL ---

@app.get("/control/conciliacion")
async def get_control_conciliacion():
    try:
        # CAMBIO 1: Quitamos el filtro restrictivo para ver TODO por ahora
        # O ajustamos al nombre real de tu campo: "Bascula.Total"
        cursor = col_control.find({}) 
        
        data = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            
            # CAMBIO 2: Aseguramos que los nombres coincidan con tu JSON real
            # Si tu JSON usa "Bascula", no inventes "Bascula_Data" aquí.
            
            # Agregamos lógica de semáforo por si no existe
            if "Semaforo" not in doc:
                doc["Semaforo"] = "verde"
                
            data.append(doc)
            
        return data
    except Exception as e:
        print(f"ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/control/zona/{zona_id}")
@app.get("/control/zona/{zona_id}")
async def get_detalle_zona(zona_id: str):
    """Retorna el detalle completo de una zona específica con limpieza de ObjectIds."""
    try:
        doc = col_control.find_one({"Zona_ID": zona_id})
        
        if not doc:
            raise HTTPException(status_code=404, detail="Zona no encontrada")
        
        # 1. Convertir el ID principal
        doc["_id"] = str(doc["_id"])
        
        # 2. Formatear la fecha si existe para evitar errores de serialización
        if "Ultima_Actualizacion" in doc and isinstance(doc["Ultima_Actualizacion"], datetime):
            doc["Ultima_Actualizacion"] = doc["Ultima_Actualizacion"].isoformat()

        # 3. LIMPIEZA CLAVE: Recorrer los paquetes de geología y convertir sus IDs
        if "Geologia_Data" in doc and "Paquetes_Activos" in doc["Geologia_Data"]:
            for paquete in doc["Geologia_Data"]["Paquetes_Activos"]:
                if "id_muestra" in paquete:
                    # Convertimos el ObjectId de cada muestra a String
                    paquete["id_muestra"] = str(paquete["id_muestra"])
        
        return doc
        
    except Exception as e:
        print(f"Error en detalle_zona: {e}")
        raise HTTPException(status_code=500, detail=str(e))

###### FIN

##### CONTROL DASHBOARD ###

@app.get("/control/dashboard")
async def get_dashboard_conciliacion():
    pipeline = [
        {
            "$project": {
                "Area_Nivel_ID": 1,
                "Nombre_Display": 1,
                "Ultima_Sincronizacion": 1,
                "Datos_Geologia": 1,
                "Datos_Bascula": 1,
                "Total_Geo": {"$sum": "$Datos_Geologia.toneladas_declaradas"},
                "Total_Bas": {"$sum": "$Datos_Bascula.peso_neto_tn"},
                # Calculamos Ley Ponderada Au
                "Ley_P_Au": { "$avg": "$Datos_Geologia.leyes.au" } 
            }
        },
        {"$sort": {"Ultima_Sincronizacion": -1}}
    ]
    
    resultados = list(col_control.aggregate(pipeline))
    
    # Limpieza de ObjectIds para JSON
    for res in resultados:
        res["_id"] = str(res["_id"])
        for g in res.get("Datos_Geologia", []):
            g["geologia_id"] = str(g["geologia_id"])
            g["fecha_declaracion"] = g["fecha_declaracion"].isoformat()
        for b in res.get("Datos_Bascula", []):
            b["bascula_id"] = str(b["bascula_id"])
            b["fecha_pesaje"] = b["fecha_pesaje"].isoformat()
            
    return resultados


# --- NUEVO ENDPOINT PARA BLENDING (PLANTA OPERACIONES) ---

@app.get("/blending/historico")
async def get_historico_blending(limit: int = 500): # Subimos a 500 para mayor seguridad
    """
    Retorna los datos del histórico filtrando por registros con ISODate válido.
    """
    try:
        # 1. FILTRO DE CONSISTENCIA
        # Solo traemos documentos donde metadata.fecha_reporte sea de tipo 'date' (tipo 9 en BSON)
        # Esto ignora automáticamente los registros viejos que eran String.
        query = {"metadata.fecha_reporte": {"$type": "date"}}
        
        # 2. ORDENACIÓN
        cursor = col_blending.find({"metadata.fecha_reporte": {"$type": "date"}}).sort("metadata.fecha_reporte", -1).limit(500)        
        data = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            
            if "metadata" in doc:
                # Convertimos a lista para evitar errores de mutación durante el loop
                for k, v in list(doc["metadata"].items()):
                    if isinstance(v, datetime):
                        # Convertimos el objeto datetime a string ISO para el JSON
                        doc["metadata"][k] = v.isoformat()
            
            data.append(doc)
            
        return data
    except Exception as e:
        print(f"Error en API Blending: {e}")
        raise HTTPException(status_code=500, detail=str(e))


#------- ENDPOINTS PARA CONTROL ACCESOS -------

# ------- ENDPOINTS PARA CONTROL ACCESOS -------


@app.get("/control/accesos/vinculados")
async def get_accesos_vinculados(
    fecha_inicio: str = None, 
    fecha_fin: str = None, 
    limit: int = 10000
):
    try:
        query = {}
        # 1. Gestión de Rango de Fechas
        if fecha_inicio and fecha_fin:
            inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            fin = datetime.strptime(fecha_fin, "%Y-%m-%d") + timedelta(days=1)
            query["fecha"] = {"$gte": inicio, "$lt": fin}
        elif fecha_inicio:
            inicio = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            fin = inicio + timedelta(days=1)
            query["fecha"] = {"$gte": inicio, "$lt": fin}
        else:
            hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            query["fecha"] = {"$gte": hoy}

        # 2. Pipeline de Agregación
        pipeline = [
            {"$match": query},
            {
                "$lookup": {
                    "from": "hrac_personal",
                    "localField": "idper",
                    "foreignField": "id",
                    "as": "personal_info"
                }
            },
            {"$unwind": "$personal_info"},
            {
                "$lookup": {
                    "from": "hrac_terminales",
                    "localField": "terminal",
                    "foreignField": "id_terminal",
                    "as": "terminal_info"
                }
            },
            {"$unwind": "$terminal_info"},
            {
                "$project": {
                    "_id": 0,
                    "id": "$personal_info.id",
                    "id_empleado": "$personal_info.id_empleado",
                    "colaborador": { "$concat": ["$personal_info.Datos.apellidos", ", ", "$personal_info.Datos.nombre"] },
                    "puesto": "$personal_info.Datos.DefPuesto",
                    "actividad_funcional": "$personal_info.Datos.actividad funcional",
                    "unidad_operativa": "$personal_info.Datos.unidad operativa",
                    "puesto_generico": "$personal_info.Datos.puesto genérico",
                    "ubicacion_puesto": "$personal_info.Datos.UbicacionPuesto",
                    "fecha_operacion": "$fecha",
                    # --- CAMBIO CRÍTICO AQUÍ ---
                    "id_terminal": "$terminal_info.id_terminal", 
                    # ---------------------------
                    "ubicacion_nieto": "$terminal_info.jerarquia.nieto",
                    "tipo_dispositivo": "$terminal_info.tipo_dispositivo",
                    "color_sede": "$terminal_info.visualizacion.color_sede",
                    "ruta_completa": "$terminal_info.visualizacion.ruta_completa"
                }
            },
            {"$sort": {"fecha_operacion": -1}},
            {"$limit": limit}
        ]

        # 3. Ejecución y Limpieza de datos
        resultados = list(col_operaciones.aggregate(pipeline))
        
        for res in resultados:
            if isinstance(res.get("fecha_operacion"), datetime):
                res["fecha_operacion"] = res["fecha_operacion"].isoformat()
            
            for campo, valor in res.items():
                if isinstance(valor, float):
                    if math.isnan(valor) or math.isinf(valor):
                        res[campo] = None
                
        return resultados

    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")
    



@app.get("/control/terminales/status")
async def get_terminales_status():
    """Retorna el estado de salud de todos los terminales configurados."""
    try:
        cursor = col_terminales.find({}, {"_id": 0})
        return list(cursor)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
########################## GEOFENCING DASHBOARD ##########################

# Asegúrate de usar el objeto 'client' que ya tienes creado arriba en tu api.py
@app.get("/control/geofencing/master")
def get_geofencing_master():
    try:
        # Usamos la conexión síncrona de pymongo
        db = client["hrac_control"]
        
        # Buscamos el documento por nombre
        config = db["hrac_control_date"].find_one(
            {"nombre": "Zonas Estándar Orovalle"}
        )
        
        if not config:
            raise HTTPException(status_code=404, detail="Configuración 'Zonas Estándar Orovalle' no encontrada")
        
        # IMPORTANTE: Convertir el ObjectId a string para que FastAPI pueda enviarlo como JSON
        config["_id"] = str(config["_id"])
        
        return config
        
    except Exception as e:
        print(f"Error en el endpoint master: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/control/geofencing/master/update")
async def update_geofencing_structure(payload: dict = Body(...)):
    """Actualiza el JSON maestro de estructura de zonas (el que lee el index.html)."""
    try:
        db_aux = client["hrac_control"]
        result = db_aux["hrac_control_date"].update_one(
            {"nombre": "Zonas Estándar Orovalle"},
            {"$set": {
                "sedes": payload.get("sedes"),
                "ultima_actualizacion": datetime.now()
            }}
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

###########################################################################


@app.get("/control/protocolo/mina")
async def get_protocolo_mina():
    try:
        # 1. Diagnóstico de conexión: listamos las colecciones para ver qué está pasando
        # Si usas pymongo, esto nos dirá si realmente estamos viendo la base de datos
        db_names = client.list_database_names()
        print(f"Bases de datos disponibles: {db_names}")
        
        # Accedemos a la base de datos específica (ajusta el nombre si es distinto a 'hrac_control_date')
        # Si tu base de datos se llama 'hrac_control_date' y la colección también:
        database = client["hrac_control"]
        coleccion = database["hrac_control_date"]
        
        print(f"Buscando en BD: hrac_control | Colección: hrac_control_date")
        
        # 2. Búsqueda sin await
        protocolo = coleccion.find_one({"id_version": "protocolo_acceso_mina_v1"})
        
        if not protocolo:
            # Si no lo encuentra, intentamos traer cualquiera para ver si hay datos
            protocolo = coleccion.find_one({})
            if protocolo:
                print("Se encontró un documento, pero no coincidía el id_version.")
            else:
                print("La colección parece estar vacía.")
                raise HTTPException(status_code=404, detail="Colección hrac_control_date vacía")

        # 3. Limpieza de ObjectId
        protocolo["_id"] = str(protocolo["_id"])
        return protocolo

    except Exception as e:
        print(f"--- DETALLE DEL ERROR ---")
        import traceback
        traceback.print_exc() # Esto sacará el error real en la terminal (ej: Auth failed, o Database error)
        raise HTTPException(status_code=500, detail=str(e))
    
# ---- HISTORICO DE ACCESOS VINCULADOS CON INFORMACIÓN DE PERSONAL Y TERMINALES ----
# --- ENDPOINT PARA EL BUSCADOR DE PERSONAL ---
import math # Importa esto al inicio de tu api.py

@app.get("/control/hrac_personal")
async def get_lista_personal():
    try:
        db = client['hrac_control'] 
        
        cursor = db.hrac_personal.find(
            {"activo": True}, 
            {"_id": 0, "id_empleado": 1, "id": 1, "Datos.nombre": 1, "Datos.apellidos": 1}
        )
        
        lista_formateada = []
        for p in cursor:
            # 1. Extraer IDs con validación básica
            id_emp = p.get("id_empleado")
            id_real = p.get("id")
            
            # 2. Limpieza de valores JSON no compatibles (NaN o Inf)
            # Si id_emp no es un número finito, lo ponemos como None o 0
            if isinstance(id_emp, float) and not math.isfinite(id_emp):
                id_emp = 0
            if isinstance(id_real, float) and not math.isfinite(id_real):
                id_real = 0

            # 3. Formatear nombre
            datos = p.get("Datos", {})
            nombre_completo = f"{datos.get('nombre', '')} {datos.get('apellidos', '')}".strip()
            
            # Solo añadimos si tiene los datos mínimos
            lista_formateada.append({
                "id_empleado": id_emp,
                "id": id_real,
                "colaborador": nombre_completo if nombre_completo else "SIN NOMBRE"
            })
            
        return sorted(lista_formateada, key=lambda x: x['colaborador'])
    except Exception as e:
        print(f"Error en hrac_personal: {e}") # Para verlo en el log de uvicorn
        raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINT PARA EL HISTÓRICO PLANO ---

@app.get("/control/historico/movimientos")
async def get_historico_movimientos(inicio: str, fin: str, id_empleado: Optional[int] = None):
    try:
        db = client['hrac_control']
        coleccion = db['hrac_control_operation'] 

        # 1. Convertimos a datetime para filtrar el ISODate de la DB
        f_inicio = datetime.strptime(f"{inicio} 00:00:00", "%Y-%m-%d %H:%M:%S")
        f_fin = datetime.strptime(f"{fin} 23:59:59", "%Y-%m-%d %H:%M:%S")

        # 2. Filtro exacto por el campo 'fecha'
        filtro = {"fecha": {"$gte": f_inicio, "$lte": f_fin}}

        # 3. Filtro por 'idper' si viene el parámetro
        if id_empleado is not None:
            try:
                # Forzamos que sea un entero por si acaso
                id_numerico = int(id_empleado)
                filtro["idper"] = id_numerico
                print(f"DEBUG: Aplicando filtro numérico: {filtro}")
            except ValueError:
                print(f"ERROR: id_empleado '{id_empleado}' no se pudo convertir a número")

        cursor = coleccion.find(filtro).sort("fecha", -1)
        
        res = []
        for m in cursor:
            res.append({
                "fecha": m["fecha"].strftime("%Y-%m-%d %H:%M:%S"),
                "idper": m.get("idper"),
                "terminal": m.get("terminal"),
                "lector": m.get("lector")
            })
            
        print(f"DEBUG: Buscando idper {id_empleado}. Encontrados: {len(res)}")
        return res

    except Exception as e:
        print(f"ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
# --- CRUD TERMINALES ---

@app.post("/control/terminales")
async def update_terminal(payload: dict = Body(...)):
    # Extraemos usando EXACTAMENTE los nombres que pusimos en el JS (payload)
    id_t = payload.get("id_terminal")
    tipo = payload.get("tipo_web") # <--- ESTE ES EL NOMBRE QUE VIENE DEL HTML
    p = payload.get("padre")
    h = payload.get("hijo")
    n = payload.get("nieto")

    # Mapa de colores para evitar el null en color_sede
    color_map = {"BOINÁS": "#D5F5E3", "BEGEGA": "#FADBD8", "CARLÉS": "#FCF3CF"}
    color_hex = color_map.get(p.upper() if p else "", "#E5E7EB")

    # Construimos el objeto final para MongoDB
    nuevo_doc = {
        "id_terminal": id_t,
        "tipo_dispositivo": tipo,  # <--- YA NO SERÁ NULL
        "jerarquia": {
            "abuelo": "Orovalle",
            "padre": p,
            "hijo": h,
            "nieto": n,
            "ancestros": ["Orovalle", p, h, n]
        },
        "visualizacion": {
            "color_sede": color_hex,
            "ruta_completa": f"Orovalle > {p} > {h} > {n}"
        },
        "status": {
            "activo": True,
            "marcado_rfid": True if tipo == "Presencia" else False
        },
        "ultima_modificacion": datetime.utcnow()
    }

    db.hrac_terminales.update_one(
        {"id_terminal": id_t}, 
        {"$set": nuevo_doc}, 
        upsert=True
    )
    return {"status": "success"}

@app.delete("/control/terminales/{id_terminal}")
async def eliminar_terminal(id_terminal: str):
    """Elimina un terminal de la configuración."""
    try:
        result = col_terminales.delete_one({"id_terminal": id_terminal})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Terminal no encontrado")
        return {"status": "success", "message": "Terminal eliminado"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))    
    
# --- DETALLE USUARIO ---

@app.get("/control/hrac_personal/{id_interno}")
async def get_detalle_usuario(id_interno: int):
    """Retorna toda la información de un colaborador específico."""
    try:
        user = col_personal.find_one({"id": id_interno}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return user
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/control/hrac_personal/update")
async def actualizar_datos_personales(payload: dict = Body(...)):
    """Actualiza la Unidad Operativa o Puesto de un trabajador."""
    try:
        id_interno = payload.get("id")
        result = col_personal.update_one(
            {"id": id_interno},
            {"$set": {
                "Datos.unidad operativa": payload.get("unidad_operativa"),
                "Datos.DefPuesto": payload.get("puesto"),
                "Datos.UbicacionPuesto": payload.get("ubicacion"),
                "modificado_el": datetime.now()
            }}
        )
        return {"status": "success", "updated": result.modified_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- NUEVOS ENDPOINTS PARA NORMALIZACIÓN DE DATOS ---

# --- ENDPOINTS DE NORMALIZACIÓN (Añadir al final de api.py) ---

# --- ENDPOINTS PARA NORMALIZACIÓN ---

def json_safe(obj):
    """Convierte recursivamente objetos no serializables (NaN, Inf, Listas) en strings o None."""
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [json_safe(i) for i in obj]
    elif isinstance(obj, float):
        if not math.isfinite(obj):
            return ""  # Cambia NaN/Inf por string vacío
        return obj
    return obj

@app.get("/control/personal/busqueda")
async def buscar_personal_completo(
    nombre: Optional[str] = Query(None),
    apellidos: Optional[str] = Query(None),
    actividad: Optional[str] = Query(None),
    ubicacion: Optional[str] = Query(None),
    puesto: Optional[str] = Query(None),
    unidad: Optional[str] = Query(None)
):
    try:
        filtro = {}
        if nombre: filtro["Datos.nombre"] = {"$regex": nombre, "$options": "i"}
        if apellidos: filtro["Datos.apellidos"] = {"$regex": apellidos, "$options": "i"}
        if actividad: filtro["Datos.actividad funcional"] = {"$regex": actividad, "$options": "i"}
        if ubicacion: filtro["Datos.UbicacionPuesto"] = {"$regex": ubicacion, "$options": "i"}
        if puesto: filtro["Datos.DefPuesto"] = {"$regex": puesto, "$options": "i"}
        if unidad: filtro["Datos.unidad operativa"] = {"$regex": unidad, "$options": "i"}

        cursor = col_personal.find(filtro).sort("id_empleado", 1).limit(300)
        
        resultados = []
        for p in cursor:
            p["_id"] = str(p["_id"])
            # Aplicamos la limpieza profunda a TODO el objeto antes de enviarlo
            p_limpio = json_safe(p)
            
            # Preparamos los datos de visualización (para que el HTML no falle)
            d = p_limpio.get("Datos", {})
            p_limpio["Datos_Display"] = {
                "nombre": str(d.get("nombre") or ""),
                "apellidos": str(d.get("apellidos") or ""),
                "actividad": str(d.get("actividad funcional") or ""),
                "ubicacion": str(d.get("UbicacionPuesto") or ""),
                "puesto": str(d.get("DefPuesto") or ""),
                "unidad": str(d.get("unidad operativa") or "")
            }
            resultados.append(p_limpio)
            
        return resultados
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/control/hrac_personal/update_full")
async def actualizar_personal_normalizado(payload: dict = Body(...)):
    try:
        id_interno = payload.get("id")
        update_data = {}
        campos_mapeo = {
            "nombre": "Datos.nombre",
            "apellidos": "Datos.apellidos",
            "actividad": "Datos.actividad funcional",
            "ubicacion": "Datos.UbicacionPuesto",
            "puesto": "Datos.DefPuesto",
            "unidad": "Datos.unidad operativa"
        }

        for key, mongo_path in campos_mapeo.items():
            if key in payload:
                val = payload[key]
                # Normalizamos a mayúsculas y quitamos espacios
                update_data[mongo_path] = val.upper().strip() if isinstance(val, str) else val

        result = col_personal.update_one({"id": id_interno}, {"$set": update_data})
        return {"status": "success", "updated": result.modified_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

###### INSPECCIONAR TIPOS DE DATOS ######

@app.get("/control/personal/inspeccionar_tipos")
async def inspeccionar_tipos():
    try:
        # Tomamos una muestra de 500 documentos para analizar
        muestra = col_personal.find().limit(500)
        analisis = {}

        for doc in muestra:
            datos = doc.get("Datos", {})
            for campo, valor in datos.items():
                tipo = type(valor).__name__
                if campo not in analisis:
                    analisis[campo] = set()
                analisis[campo].add(tipo)

        # Convertimos los sets a listas para que sea JSON serializable
        resultado = {k: list(v) for k, v in analisis.items()}
        return {
            "mensaje": "Tipos encontrados en el objeto 'Datos'",
            "tipos_por_campo": resultado
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

#########################################################################################################################################
####################################### ENDPOINTS DE PLANTA ###############################################################################
#########################################################################################################################################

# --- ENDPOINT 1: OBTENER U OPTIMIZAR LA PLANTILLA BASE DE FORMULARIO ---
@app.get("/api/planta/pdm-config", tags=["Partes de Muestras Diario"])
async def obtener_configuracion_formulario():
    """
    Recupera el JSON maestro desde pdm_data que define las áreas, nomenclaturas 
    y campos del formulario para pintarlo de forma dinámica en el HTML.
    """
    try:
        config = col_pdm_data.find_one({"identificador": "config_muestras_planta"}, {"_id": 0})
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="La plantilla 'config_muestras_planta' no se encuentra en la colección pdm_data."
            )
        return config
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- ENDPOINT 2: GUARDAR EL PARTE DIARIO RELLENADO (HISTÓRICO) ---
@app.post("/api/planta/pdm-guardar", tags=["Partes de Muestras Diario"])
async def guardar_historico_parte(parte: ParteDiarioMuestras):
    """
    Recibe los datos completados desde la interfaz web, construye el identificador único 
    combinando [FECHA] + [RELEVO] (ej. '2026-05-18_1P') y lo almacena en pdm_historico.
    """
    try:
        # 1. Normalizar fecha y relevo para crear el nombre/identificador compuesto
        fecha_str = parte.fecha.strip()
        relevo_str = parte.relevo.strip().upper() # Asegura mayúsculas (1P, 2P)
        
        id_compuesto = f"{fecha_str}_{relevo_str}"
        
        # 2. Transformar el modelo Pydantic a diccionario para MongoDB
        documento_historico = parte.dict()
        
        # 3. Inyectar el ID personalizado de negocio, estado inicial y metadatos de auditoría en formato String ISO
        documento_historico["_id"] = id_compuesto
        documento_historico["identificador_parte"] = id_compuesto
        
        # CORRECCIÓN AQUÍ: Convertimos el datetime a string ISO para evitar problemas de serialización
        documento_historico["fecha_insercion_servidor"] = datetime.utcnow().isoformat()
        
        # Agregar estado inicial del flujo de trabajo
        documento_historico["estado"] = "pendiente"
        
        # 4. Upsert (Guardar si es nuevo o actualizar si corrigen datos del mismo turno)
        result = col_pdm_historico.update_one(
            {"_id": id_compuesto},
            {"$set": documento_historico},
            upsert=True
        )
        
        if result.upserted_id:
            mensaje = f"Parte diario creado con éxito bajo el identificador: {id_compuesto}"
        else:
            mensaje = f"Parte diario actualizado con éxito para el identificador: {id_compuesto}"
            
        return {
            "status": "success",
            "identificador_pdm": id_compuesto,
            "message": mensaje
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Error en la persistencia de datos: {str(e)}"
        )

### ENDPOINT 3: CONSULTAR UN PARTE DIARIO GUARDADO (HISTÓRICO) POR FECHA Y RELEVO ---

### ENDPOINT 3: CONSULTAR UN PARTE DIARIO GUARDADO (HISTÓRICO) POR FECHA Y RELEVO ---

@app.get("/api/planta/pdm-consultar", tags=["Partes de Muestras Diario"])
def consultar_pdm_historico(
    fecha: Optional[str] = Query(None, description="Fecha en formato YYYY-MM-DD", example="2026-05-18"),
    relevo: Optional[str] = Query(None, description="Código del relevo", example="1P")
):
    try:
        # CASO 1: Si NO se envían parámetros, traemos TODOS los partes (los 8 registros o los que haya)
        if not fecha and not relevo:
            cursor = col_pdm_historico.find({})
            lista_partes = []
            for documento in cursor:
                # Convertimos el ObjectId si fuera necesario (aunque tus IDs son strings)
                if "_id" in documento and not isinstance(documento["_id"], str):
                    documento["_id"] = str(documento["_id"])
                lista_partes.append(documento)
            return lista_partes

        # CASO 2: Si falta uno de los dos parámetros para la búsqueda exacta
        if not fecha or not relevo:
            raise HTTPException(
                status_code=400,
                detail="Para una búsqueda exacta debe proporcionar tanto 'fecha' como 'relevo'. De lo contrario, no envíe ningún parámetro."
            )

        # CASO 3: Búsqueda exacta (Tu lógica actual)
        id_buscado = f"{fecha}_{relevo}"
        documento = col_pdm_historico.find_one({"_id": id_buscado})
        
        if not documento:
            raise HTTPException(
                status_code=404, 
                detail=f"No se encontró ningún parte diario de muestras para el ID: {id_buscado}"
            )
        
        return documento

    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")





#########################################################################################################################################
####################################### ENDPOINTS DE MINA ###############################################################################
#########################################################################################################################################


####### POST MINA CONFIGURACIÓN #######


@app.get("/mina/configuracion")
def get_mina_config():
    try:
        # Usamos la colección definida en la conexión
        configs = list(col_mina_config.find({"activa": True}, {"_id": 0}))
        return {"status": "success", "data": configs}
    except Exception as e:
        logging.error(f"Error en GET config mina: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/mina/listado")
def get_mina_listado(mina: str):
    try:
        # Buscamos todas las zonas de la mina especificada
        zonas = list(col_mina_data.find({"nomenclatura.mina": mina}))
        # Convertimos ObjectId a string para que JSON sea feliz
        for z in zonas:
            z["_id"] = str(z["_id"])
        return zonas
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/mina/actualizar-estado/{id_zona}")
def actualizar_zona(id_zona: str, campo: str, valor: bool):
    try:
        # campo puede ser "control.activo" o "control.favorito"
        from bson import ObjectId
        result = col_mina_data.update_one(
            {"_id": ObjectId(id_zona)},
            {"$set": {f"control.{campo}": valor}}
        )
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/mina/crear-zona")
def crear_zona(datos: ZonaMinaInput):
    """Genera el código de 18 caracteres y guarda con jerarquía completa"""
    try:
        # 1. FORMATEO Y NORMALIZACIÓN
        mina = datos.mina.zfill(2)
        zona = datos.zona.upper()
        
        # Normalizar nivel (+120, -050)
        nivel_num = datos.nivel.replace("+", "").replace("-", "").zfill(3)
        signo = "-" if "-" in datos.nivel else "+"
        nivel = f"{signo}{nivel_num}"
        
        # 2. LÓGICA DE RELLENO (Padding de 18 caracteres)
        # Aseguramos char_camara (1) y chars_panel (2)
        char_camara = (datos.camara or ".").strip()[:1] or "."
        chars_panel = (datos.panel or "..").strip().ljust(2, ".")[:2]
        seccion_final = f"{datos.acttype.upper()}{char_camara}{chars_panel}"
        
        codigo_18 = f"{mina}.{zona}.{nivel}.{datos.subnivel}.{seccion_final}"
        
        # Validación de longitud crítica
        if len(codigo_18) != 18:
            raise HTTPException(status_code=400, detail=f"Código inválido: {codigo_18}")

        # 3. VALIDACIÓN DE DUPLICADOS
        if col_mina_data.find_one({"codigo_18": codigo_18}):
            raise HTTPException(status_code=400, detail=f"La zona {codigo_18} ya existe.")

        # 4. CONSTRUCCIÓN DEL DOCUMENTO FINAL (Estructura MOP_DATA)
        nuevo_registro = {
            "codigo_18": codigo_18,
            "nomenclatura": {
                "mina": mina,
                "zona": zona,
                "nivel": nivel,
                "subnivel": datos.subnivel,
                "acttype": datos.acttype.upper(),
                "camara": char_camara,
                "panel": chars_panel
            },
            "jerarquia": {
                "parent_id": datos.parent_id,        # Código del padre o None
                "nivel_jerarquico": datos.nivel_jerarquico, # 1, 2, 3 o 4
                "es_raiz": datos.es_raiz            # True si nivel_jerarquico es 1
            },
            "control": {
                "activo": True,                     # Alta lógica por defecto
                "favorito": False,                  # Iniciamos siempre en falso
                "importado_planif": datos.importado_planif, 
                "fecha_creacion": datetime.now()
            }
        }
        
        # 5. INSERCIÓN
        result = col_mina_data.insert_one(nuevo_registro)
        
        return {
            "status": "success",
            "codigo": codigo_18,
            "mongo_id": str(result.inserted_id),
            "nivel": datos.nivel_jerarquico
        }

    except Exception as e:
        logging.error(f"Error creando zona: {e}")
        raise HTTPException(status_code=500, detail=str(e))