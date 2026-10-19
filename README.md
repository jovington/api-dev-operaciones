# Orovalle Platform API

API principal de la plataforma, organizada por dominios para incorporar usuarios, roles, autenticación y APIs de negocio sin hacer crecer `app/main.py`.

## Estructura

```text
app/
	core/        Configuración, logging y seguridad común.
	db/          Cliente MongoDB y repositorios por dominio.
	models/      Contratos Pydantic de entrada y salida.
	routers/     Endpoints HTTP agrupados por dominio.
	services/    Lógica de negocio.
	main.py      Arranque, ciclo de vida y registro de routers.
```

El cliente de MongoDB se crea una sola vez al arrancar la API y se reutiliza durante toda su vida. Los repositorios obtienen la base de datos compartida mediante una dependencia de FastAPI. Se mantiene la configuración por defecto del driver porque aún no hay datos de concurrencia ni carga suficientes para justificar límites de pool concretos.

## Desarrollo con Docker

Desde esta carpeta:

```powershell
docker compose up --build
```

Servicios:

- API: `http://localhost:8000`
- Documentación OpenAPI: `http://localhost:8000/docs`
- Salud: `http://localhost:8000/health`
- MongoDB: `localhost:27017`

El servicio `api` monta esta carpeta como volumen y arranca Uvicorn con `--reload`. Al modificar y guardar cualquier archivo de `app/`, la aplicación se reinicia automáticamente dentro del contenedor.

## Variables

Las configuraciones iniciales están en `.env`. Copia `.env.example` si vas a crear una instalación nueva y cambia, como mínimo, `MONGO_INITDB_ROOT_PASSWORD` y el valor equivalente en `MONGODB_URI`.

`MONGODB_URI` usa el host `mongodb` porque FastAPI se conecta mediante la red interna de Docker Compose. Si ejecutas FastAPI fuera de Docker, usa `localhost` en esa URL.

## Separación futura

La carpeta no depende del frontend: se puede mover a otro repositorio conservando sus archivos. La integración del frontend debe usar la URL publicada de esta API cuando se implementen login y autorización.

La especificación vigente para que el frontend gestione los grupos de las mediciones de Acopio está en [docs/acopio-mediciones-grupos.md](docs/acopio-mediciones-grupos.md).

La especificación para persistir planificaciones de Alimentación Planta está en [docs/alimentacion-planta.md](docs/alimentacion-planta.md).

## Rutas iniciales

- `GET /`: metadatos de la API.
- `GET /health`: disponibilidad de MongoDB.
- `GET /bascula/total-por-mineral`: suma `Peso_Neto` de la colección `bascula`, agrupada por `Area_Nivel`; incluye `producto` y los paquetes con `matricula`, cantidad y fecha de subida.
- `GET /acopio/total-por-mineral`: entradas de acopio por mineral, incluido su `producto`.
- `GET /acopio/stock-por-mineral`: entradas, consumos, stock disponible y `producto` por mineral.
- `GET /acopio/mediciones`: mediciones individuales de origen con sus grupos de Acopio.
- `GET /acopio/mediciones/{medicion_id}`: detalle de una medición y sus grupos.
- `PUT`, `POST` y `DELETE /acopio/mediciones/{medicion_id}/grupo`: reemplazo, alta y baja de los grupos de una medición. Consulta el contrato en la documentación de Acopio.
- `PATCH /acopio/mediciones/renombrar`: renombra de forma atómica una tarjeta de Acopio y sus mediciones seleccionadas.
- `GET`, `POST`, aprobación y reordenado de `/alimentacion-planta/alimentaciones`: persistencia de planificaciones de Alimentación Planta.
- `POST /consumos-acopio`: registra un consumo diario con `mineral`, `fecha` y `pesoNeto`.
- `GET /consumos-acopio`: consumos sumados por mineral y día, incluido su `producto`; acepta `mineral`, `fechaDesde` y `fechaHasta`.
- `GET /planta/ultimo-dato`: última lectura del PLC de planta, ordenada por `payload.timestamp`.
- `GET /users`: lista de usuarios activos sin datos sensibles. La colección puede permanecer vacía hasta implementar el alta de usuarios y autenticación.