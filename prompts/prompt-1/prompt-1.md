Actúa como un Arquitecto de Software Backend experto en Python, FastAPI y MongoDB (AsyncIOMotorClient). Tu objetivo es generar la versión definitiva de producción ("version 2 Api_operaciones") migrando y adaptando los endpoints de desarrollo (basados en main.py y api.py como guía orientativa) hacia la arquitectura modular oficial y estricta de producción.

REGLAS DE ORO DE ARQUITECTURA:
- NUNCA rompas la estructura modular de carpetas. Debes organizar el código rigurosamente en:
  * app/models/: Contratos Pydantic de entrada y salida.
  * app/db/: Capa de repositorios y conexión a MongoDB (Base de datos por defecto: "Operaciones").
  * app/services/: Lógica de negocio, algoritmos de cálculo y procesamiento de datos.
  * app/routers/: Endpoints HTTP organizados por dominio (planta, xrf, usuarios, checklists, bascula, blending).
- Los archivos `main.py` y `api.py` proporcionados previamente solo deben usarse como referencia de lógica; la arquitectura y esquemas limpios de producción son dominantes.
- Garantiza retrocompatibilidad total: los clientes existentes (como la app móvil) no deben verse afectados por los cambios.

---

REQUISITOS FUNCIONALES OBLIGATORIOS A IMPLEMENTAR:

1. GESTIÓN DE USUARIOS Y AUTENTICACIÓN:
   - Rutas de usuarios (`/planta/usuarios` GET/POST).
   - Sistema de login tradicional (`/planta/login`) y por código QR (`/planta/login-qr`) utilizando hash SHA-256 (`sha256$<hash>`) para contraseñas, generando tokens efímeros de sesión con expiración de 12 horas almacenados en la colección `sesiones`.

2. PARTES DE OPERACIÓN, CHECKLISTS Y VEHÍCULOS:
   - Registro y listado de partes de operación (`/planta/partes`).
   - Sincronización idempotente de partes de checklist (`/checklist/partes`) validando estrictamente IDs de 6 caracteres y limpiando metadatos auxiliares.
   - Listado y gestión de vehículos (`/checklist/vehiculos`) con inicialización automática del modelo "LV" y generación de tokens QR aleatorios si no existen.
   - Plantillas de checklists (`/checklist/templates`, `/checklist/templates/{tipo_parte}`).

3. GESTIÓN DE ARCHIVOS Y MULTIMEDIA:
   - Subida multipart flexible (`file`, `imagen`, `foto`, `archivo`) para fotos generales de partes (`/planta/partes/{id_parte}/fotos`) y de líneas específicas de ítems (`/planta/partes/{id_parte}/items/{item_id}/fotos`), validando extensiones (.png, .jpg, .jpeg, .webp), guardando con timestamp en `/app/uploads/partes` y actualizando MongoDB.
   - Servir archivos estáticos mediante FileResponse en `/uploads/partes/{nombre_archivo}` y montar `/uploads` globalmente.

4. MÓDULO PLANTA XRF Y EXPORTACIÓN:
   - Endpoints de consulta de mediciones (`/planta-xrf/hoy`, `/planta-xrf/ultimas`), desactivación lógica de mediciones (`/planta-xrf/{id_medicion}/desactivar`).
   - Endpoint de exportación a Excel (`/planta-xrf/exportarxrf`) con el algoritmo de agrupación por ventanas de tiempo de 7 minutos, exclusión de mediciones desactivadas y cálculos analíticos de concentraciones (Cu, As, Sb, Bi en % o ppm) junto con la fórmula de recuperación de cobre.

5. NUEVOS ENDPOINTS Y AMPLIACIONES EN PRODUCCIÓN:
   - **Ampliación Planta / Último Dato:** Extender el sistema de planta para que, reutilizando la lógica base de `/planta/ultimo-dato`, permita opcionalmente consultar datos filtrados por rango de fechas (`fecha_inicio`, `fecha_fin` en formato string flexible) o retornar los últimos 100 registros históricos si se requiere, manteniendo el comportamiento sin parámetros exactamente igual al original para no romper la app móvil.
   - **Nuevo Endpoint Báscula (`/mediciones`)**: 
     * Consultar la colección `mediciones` de la base de datos "Operaciones".
     * Ordenar por `Fecha` de forma descendente aplicando un límite configurable por parámetro (`limit: int = 100`).
     * Utilizar `jsonable_encoder` y un bucle de limpieza manual de seguridad para transformar ObjectIds a string y convertir floats fuera de rango (`NaN`, `Inf`) en `None` para evitar caídas de serialización JSON.
   - **Nuevo Endpoint Blending Histórico (`/blending/historico`)**:
     * Consultar la colección de blending filtrando estrictamente por documentos donde `metadata.fecha_reporte` sea de tipo fecha BSON válida (`{"metadata.fecha_reporte": {"$type": "date"}}`) para descartar registros antiguos basados en strings.
     * Ordenar por `metadata.fecha_reporte` descendente con un límite de seguridad (`limit: int = 500`).
     * Convertir dinámicamente los objetos `datetime` de Python dentro de `metadata` a formato de texto ISO (`isoformat()`) antes de devolver la respuesta.

6. DOCUMENTACIÓN Y REGISTROS:
   - Actualizar y generar la documentación técnica exhaustiva en la carpeta `/docs` (o Markdown integrado) detallando los nuevos esquemas, parámetros de consulta por fechas/límites, y contratos actualizados de la API.
   - Incluir manejo robusto de excepciones con bloques `try-except` detallados que registren trazas claras en los contenedores de Docker.

Por favor, entrega la estructura de archivos modular limpia, comentada y lista para producción.