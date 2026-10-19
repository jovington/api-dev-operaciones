# version 2 Api_operaciones

### Contexto de la Arquitectura del Proyecto:
Sigue estrictamente la estructura modular existente:
- app/routers/: Endpoints HTTP organizados por dominio.
- app/services/: Lógica de negocio.
- app/db/: Repositorios de MongoDB.
- app/models/: Contratos Pydantic de entrada y salida.

## Descipción 

Instertar los nuevos endpoints de dev en prod teniendo en cuenta la arquitectura y esquema de PROD como dominante (Ver contexto de la arquitectura del proyecto). 

## Ampliación 

### nuevos endpoint api Producción

Reutilizando el ulitimo codigo del endpoint /planta/ultimo-dato necesito crear en planta un nuevo endpoint con los mismos datos pero que pueda
obtener datos entre fechas o los ultimos 100 datos 

## Nuevo endpoint Báscula

```txt
Este es el que utilizamos en DEV y tenemos que pasar a PROD con la ARQUITECTURA DE PROD
la base de datos es PROD y la base de datos se llama Operaciones y la coleccion bascula 

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

```

## Nuevo endpoint Blendig

```txt
Este es el endpoint que utilizamos para blending html y sus datos 


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

```

## Origen  - API DEV 

``` txt
Actúa como un Arquitecto de Software Backend experto en Python y FastAPI. Necesito que recrees completamente el código fuente proporcionado en main_3.py bajo la estructura de la api de produccion, pero manteniendo idénticas todas las funcionalidades, rutas, nombres de colecciones en MongoDB y contratos de datos.

A continuación, se detallan los requisitos funcionales obligatorios que deben cumplirse sin excepciones:

1. CONFIGURACIÓN Y CONexión:
   - Mantener el uso de Motor (AsyncIOMotorClient) para MongoDB asíncrono utilizando variables de entorno (`MONGO_URI`, `DATABASE_NAME` por defecto "Operaciones").
   - Colecciones exactas a respetar: `PartesOperacionPlanta`, `UsuariosPlanta`, `PlantaXrf`, `PartesOperacionPlantaTemplate`, y `sesiones`.
   - Habilitar CORS completo (`allow_origins=["*"]`) y montar la carpeta estática `/uploads` en `/app/uploads` para servir las imágenes correctamente.

2. ENDPOINTS DE SISTEMA Y XRF:
   - Ruta GET `/`: Ping a la base de datos MongoDB.
   - Rutas XRF (`/planta-xrf/hoy`, `/planta-xrf/ultimas`, `/planta-xrf/{id_medicion}/desactivar` y `/planta-xrf/exportarxrf`): Mantener la lógica de filtrado de 24 horas, límites de registros, manejo del campo `desactive_medicion`, y el algoritmo de agrupación temporal de 7 minutos con cálculos analíticos de concentraciones (Cu, As, Sb, Bi en porcentajes o ppm) y fórmula de recuperación de cobre exactamente como están en el script original.

3. ENDPOINTS DE PARTES DE OPERACIÓN Y CHECKLISTS:
   - Registro y consulta de partes (`/planta/partes` en métodos GET y POST).
   - Listado de vehículos (`/checklist/vehiculos` en GET y POST con inicialización automática por defecto del modelo LV y tokens QR aleatorios si no existen).
   - Gestión de plantillas de checklists (`/checklist/templates` y `/checklist/templates/{tipo_parte}`).
   - Sincronización robusta e idempotente de partes de checklist (`/checklist/partes`) validando IDs de exactamente 6 caracteres y limpiando campos auxiliares.

4. GESTIÓN DE ARCHIVOS Y FOTOGRAFÍAS:
   - Subida de fotos generales de parte (`/planta/partes/{id_parte}/fotos`) y de líneas específicas de ítems (`/planta/partes/{id_parte}/items/{item_id}/fotos`). Ambas deben admitir subidas multipart flexibles (`file`, `imagen`, `foto`, `archivo`), validar extensiones de imagen (`.png`, `.jpg`, `.jpeg`, `.webp`), guardarlas con marca de tiempo en la carpeta de uploads y actualizar el array de fotos en MongoDB.
   - Endpoint GET `/uploads/partes/{nombre_archivo}` utilizando `FileResponse`.

5. GESTIÓN DE USUARIOS Y AUTENTICACIÓN:
   - Registro y actualización de usuarios (`/planta/usuarios` en GET y POST) con hash de contraseñas mediante SHA-256 (`sha256$<hash>`) y generación/mantenimiento automático de tokens QR (`qr_token`).
   - Sistema de login tradicional por número de empleado y contraseña (`/planta/login`) y login por código QR (`/planta/login-qr`), ambos generando tokens de sesión efímeros de 12 horas almacenados en la colección `sesiones`.

Por favor, entrega la nueva estructura de archivos limpia, comentada y lista para producción, asegurando que ningún endpoint pierda compatibilidad con el frontend o app móvil existente.


```

Te ajunto dos archivos 
api.py - donde estan la informacion de hasta ahora de los endpoints de báscula y blending 
main.py -  donde estan los endpoint ahora mismo en desarrollo para hacer el paso a produccion

Solo usarlos como guia SIEMPROE RESPETA LA ESTRUCTURA DE PRODUCCION

Genera la documentacion de esta nueva version en /docs de los nuevo endpoints y actualiza las antiguas de ser necesario
Respeta la estructura: Le indica explícitamente dónde ubicar cada archivo (routers, services, db, models) basándose en tu README.md.

Mantiene la lógica previa: Asegura que si la aplicación móvil (o cualquier cliente) llama al endpoint sin parámetros, se siga comportando exactamente igual que el /planta/ultimo-dato actual.

Maneja los tipos flexibles: Al pedirle que acepte cadenas de texto opcionales para las fechas (fecha_inicio y fecha_fin), evita los problemas de parseo estricto y permite que la app móvil mande el string cómodamente.