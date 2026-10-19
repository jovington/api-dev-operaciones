# API Operaciones: contratos de producción v2

La API mantiene MongoDB como dependencia compartida y usa la base de datos configurada en `OPERACIONES_DATABASE` (por defecto, `Operaciones`). Los endpoints nuevos están registrados en `app/routers/operaciones.py`; los contratos de entrada viven en `app/models/operaciones.py` y la lógica de negocio en `app/services/`.

## Planta y autenticación

- `GET /planta/ultimo-dato`: sin parámetros conserva la respuesta histórica de una lectura PLC. `fecha_inicio` y `fecha_fin` aceptan fechas ISO (`YYYY-MM-DD` o ISO completo) y devuelven hasta 100 lecturas en `lecturas`. `historico=true` solicita los últimos 100 registros.
- `POST /planta/usuarios` y `GET /planta/usuarios`: alta/actualización por `N_Empleado` y listado. Las contraseñas se guardan como `sha256$<hash>` y el QR se genera si falta.
- `POST /planta/login`: `{ "n_empleado": 10, "password": "..." }`.
- `POST /planta/login-qr`: `{ "qr_token": "..." }`.

Ambos logins crean un registro en `sesiones` con un token aleatorio y `expires_at` a 12 horas.

## Partes y checklists

- `POST/GET /planta/partes` registra y lista partes.
- `POST /checklist/partes` sincroniza idempotentemente. El ID debe tener exactamente seis caracteres; los aliases auxiliares (`id_parte`, `id_partes`, `tipo_parte`, `fecha_creacion`, `items`) se normalizan antes de persistir.
- `GET/POST /checklist/vehiculos` inicializa el modelo `LV` y completa `qr_token` y `estado` en cada vehículo.
- `GET /checklist/templates` y `GET /checklist/templates/{tipo_parte}` consultan plantillas.

Las fotos aceptan los campos multipart `file`, `imagen`, `foto` o `archivo`, y las extensiones `.png`, `.jpg`, `.jpeg` y `.webp`. Se guardan en `/app/uploads/partes` y se sirven desde `/uploads/partes/{nombre_archivo}`. En Docker, `/app/uploads/partes` se enlaza con la carpeta `./imagenes` de la raíz del proyecto. El servicio queda publicado en el puerto `8000`.

## Báscula, blending y XRF

- `GET /mediciones?limit=100` consulta `Operaciones.bascula`, ordena por `Fecha` descendente y convierte `ObjectId` a texto y valores `NaN`/`Inf` a `null`.
- `GET /blending/historico?limit=500` solo acepta documentos cuyo `metadata.fecha_reporte` sea una fecha BSON y convierte fechas anidadas a ISO 8601.
- `GET /planta-xrf/hoy` y `/planta-xrf/ultimas?limite=25` consultan XRF.
- `PATCH /planta-xrf/{id_medicion}/desactivar` realiza la desactivación lógica.
- `GET /planta-xrf/exportarxrf?limite=5` excluye mediciones desactivadas, agrupa por ventanas de siete minutos y calcula Cu, As, Sb, Bi y recuperación de cobre.

Los límites están acotados para evitar consultas accidentales sin límite. Las excepciones de validación se devuelven como 4xx y las operaciones de infraestructura deben registrarse mediante el logging configurado por `app.core.logging`.