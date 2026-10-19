# Grupos de mediciones de Acopio

## Estado

Implementado el 7 de agosto de 2026.

La funcionalidad pertenece al dominio de Acopio. Los endpoints existentes de Báscula y su integración con sistemas externos no se han modificado.

Las mediciones se leen de la colección MongoDB existente `bascula`. Acopio escribe únicamente `grupo` o, mediante el endpoint de renombrado, el campo de origen `Area_Nivel` expuesto como `nombre`. No crea copias de mediciones, documentos de stock ni colecciones de auditoría. El renombrado y la fusión registran su auditoría en el array `auditoria_acopio` del documento de origen actualizado.

Solo se exponen y se pueden gestionar mediciones válidas para Acopio:

- `Area_Nivel` debe ser un string no vacío.
- `Peso_Neto` debe ser numérico.
- `Fecha` debe ser una fecha válida de MongoDB.

Los documentos externos incompletos o con valores no válidos, por ejemplo `Area_Nivel: NaN`, no aparecen en `GET /acopio/mediciones`. Consultarlos o modificarlos mediante estos endpoints responde `404`.

## Contrato de medición

Las respuestas de medición exponen este formato público:

```json
{
  "_id": "uuid-o-objectid",
  "nombre": "Mineral Carles",
  "cantidad": 5000,
  "matricula": "1234ABC",
  "fechaSubida": "2026-08-07T09:30:00.000Z",
  "producto": "Mineral de Carles",
  "grupo": []
}
```

`grupo` siempre está presente como array. Las mediciones anteriores a esta funcionalidad, que no tienen el campo persistido, devuelven `grupo: []`.

El identificador `_id` se devuelve siempre como texto, tanto si el origen usa `ObjectId` como si usa una cadena o UUID.

## Contrato de grupo

```json
{
  "id": "grupo-acopio-001",
  "nombre": "Acopio Carles Norte",
  "tipo": "mineral",
  "fechaAsignacion": "2026-08-07T10:00:00.000Z"
}
```

Reglas de validación:

- `id`: string obligatorio y no vacío.
- `nombre`: string obligatorio y no vacío.
- `tipo`: uno de `mineral`, `baja_ley` o `esteril`.
- `fechaAsignacion`: fecha ISO 8601 con zona UTC. Se acepta el sufijo `Z` o un desplazamiento `+00:00`; la respuesta se normaliza con `Z`.

Los bodies que no cumplan estas reglas responden `422`.

## Estados operativos

El frontend calcula las tarjetas agrupando las mediciones por `nombre`. No existen documentos de tarjeta ni de stock separados.

- Una medición con `grupo: []` está en `Picking / A definir` y no está verificada.
- Una medición que contenga `estado-stock` con tipo `mineral` o `baja_ley` está en `Stock`.
- Una medición que contenga `estado-esteril` con tipo `esteril` está en `Esteril`.
- El grupo `origen-balizado` es un marcador de trazabilidad. El frontend debe usarlo para pintar el indicador naranja del paquete fusionado.

Los grupos operativos creados por la API son:

```json
{
  "id": "estado-stock",
  "nombre": "Stock",
  "tipo": "mineral",
  "fechaAsignacion": "2026-08-10T10:00:00.000Z"
}
```

Para baja ley, `id` y `nombre` se mantienen y `tipo` es `baja_ley`. Para estéril se utiliza `id: "estado-esteril"`, `nombre: "Esteril"` y `tipo: "esteril"`.

## Endpoints

### Listar mediciones

`GET /acopio/mediciones`

Devuelve `200` y un array de mediciones completas. La lista se ordena por la fecha de origen más reciente primero.

### Consultar una medición

`GET /acopio/mediciones/{medicion_id}`

Devuelve `200` con una medición completa y su array `grupo`. Si la medición no existe devuelve `404`.

### Tipificar y verificar una medición

`PUT /acopio/mediciones/{medicion_id}/clasificacion`

Body:

```json
{
  "tipo": "mineral"
}
```

`tipo` solo admite `mineral`, `baja_ley` o `esteril`. La respuesta `200` contiene exclusivamente `_id` y `grupo`.

La operación reemplaza el estado operativo previo por el estado indicado y conserva cualquier `origen-balizado` ya asignado. No modifica nombre, cantidad, matrícula, fecha ni producto. Una medición inexistente o no válida para Acopio devuelve `404`; un body no válido devuelve `422`.

### Fusionar tarjetas

`POST /acopio/tarjetas/fusionar`

Body:

```json
{
  "origenMedicionIds": ["id-balizado-1", "id-balizado-2"],
  "destinoMedicionIds": ["id-mineral-1", "id-mineral-2"]
}
```

Respuesta `200`:

```json
{
  "nombre": "BE_160-75",
  "medicionIds": [
    "id-balizado-1",
    "id-balizado-2",
    "id-mineral-1",
    "id-mineral-2"
  ],
  "total": 18500
}
```

No se acepta nombre de destino en el body: se obtiene de las mediciones de destino. Origen y destino deben contener IDs no vacíos, únicos y sin solapamiento; cada conjunto debe pertenecer a una única tarjeta con el mismo nombre, producto y estado operativo. El destino debe estar clasificado como `mineral` o `baja_ley`, nunca como `esteril`.

El origen debe terminar en un sufijo que empiece por `_Bal` o por espacio seguido de `bal`, sin importar mayúsculas/minúsculas, o estar marcado con `origen-balizado`. Se aceptan, entre otros, `_Bal`, `_Balizado`, `_Balizar`, `_Ballizar` y sufijos con espacio seguido de `bal`. Para comparar tarjetas se elimina ese sufijo final completo; por ejemplo, `BE_160-75_Ballizar` es compatible con `BE_160-75`.

En una fusión correcta, cada medición de origen adopta el nombre de la tarjeta destino, recibe el estado de Stock compatible con el destino y conserva o recibe `origen-balizado`. Las mediciones de destino no se modifican. La respuesta incluye el total de `cantidad` de todas las mediciones de ambas tarjetas.

Después de validar todas las mediciones, la API ejecuta una única operación `update_many` sobre los IDs origen. Su filtro incluye IDs, nombre, producto, estado operativo y validez de Acopio, evitando sobrescribir un cambio concurrente. Cada documento origen actualizado recibe atómicamente nombre, grupos y auditoría embebida; no se usa una transacción, replica set ni una colección de auditoría independiente.

MongoDB standalone no puede garantizar atomicidad entre documentos. Si una modificación concurrente reduce los documentos coincidentes o modificados, la API registra un aviso de consistencia y responde `409`; no realiza una segunda escritura ni una compensación automática. Los errores son `404` cuando falta una medición o no es válida para Acopio, y `409` para conflictos de negocio o concurrencia. Este endpoint no devuelve `503` por falta de transacciones.

La auditoría de una fusión satisfactoria se añade al array `auditoria_acopio` de cada documento origen. Los destinos no reciben auditoría ni se modifican:

```json
{
  "accion": "fusionar_tarjetas",
  "fecha": "2026-08-10T10:15:00.000Z",
  "nombreOrigen": "BE_160-75_Balizado",
  "nombreDestino": "BE_160-75",
  "origenMedicionIds": ["id-balizado-1", "id-balizado-2"],
  "destinoMedicionIds": ["id-mineral-1", "id-mineral-2"]
}
```

### Renombrar una tarjeta y sus mediciones

`PATCH /acopio/mediciones/renombrar`

Body:

```json
{
  "medicionIds": [
    "id-medicion-1",
    "id-medicion-2",
    "id-medicion-3"
  ],
  "nombre": "BE_160-75"
}
```

Responde `200`:

```json
{
  "nombre": "BE_160-75",
  "medicionIds": [
    "id-medicion-1",
    "id-medicion-2",
    "id-medicion-3"
  ]
}
```

`nombre` se limpia con trim y debe conservar contenido; los IDs también se limpian, deben ser únicos y no pueden estar vacíos. Los bodies que incumplan estas reglas responden `422`.

Todas las mediciones indicadas deben existir y pertenecer a la misma tarjeta actual. Si falta alguna, la respuesta es `404` y no se modifica ninguna. Si pertenecen a tarjetas distintas, responde `422` y no se modifica ninguna.

La operación cambia únicamente el campo de origen `Area_Nivel`, expuesto por la API como `nombre`. No modifica cantidad, matrícula, fecha, producto ni `grupo`.

Después de validar todos los IDs y que pertenecen a la misma tarjeta, la API ejecuta una única operación `update_many` sobre `bascula`. El filtro incluye los IDs solicitados, el nombre anterior y la validez de la medición. Cada documento actualizado recibe de forma atómica su nuevo nombre y la siguiente entrada en su array `auditoria_acopio`; no se usa una colección de auditoría independiente ni una transacción MongoDB.

```json
{
  "accion": "renombrar_medicion",
  "fecha": "2026-08-10T12:00:00.000Z",
  "nombreAnterior": "ZV_295.2 Balizar",
  "nombreNuevo": "ZV_295.2"
}
```

Si otro proceso modifica una medición entre la validación y la actualización y el número de documentos modificados no coincide con los IDs solicitados, la API responde `409` y registra un aviso de consistencia. No realiza una segunda actualización ni una operación destructiva.

### Reemplazar grupos

`PUT /acopio/mediciones/{medicion_id}/grupo`

Body:

```json
{
  "grupo": [
    {
      "id": "grupo-acopio-001",
      "nombre": "Acopio Carles Norte",
      "tipo": "mineral",
      "fechaAsignacion": "2026-08-07T10:00:00Z"
    }
  ]
}
```

Reemplaza exclusivamente el array `grupo`. Responde `200`:

```json
{
  "_id": "uuid-o-objectid",
  "grupo": []
}
```

Un array vacío es válido y elimina todas las asignaciones de grupo. Si la medición no existe devuelve `404`.

### Añadir un grupo

`POST /acopio/mediciones/{medicion_id}/grupo`

El body es directamente un objeto de grupo. Añade el objeto al final del array existente sin reemplazarlo. Responde `200` con `_id` y el array `grupo` completo.

La API no deduplica por `id`; el frontend debe evitar enviar dos veces el mismo grupo si esa no es la intención de negocio. Si la medición no existe devuelve `404`.

### Eliminar un grupo

`DELETE /acopio/mediciones/{medicion_id}/grupo/{grupo_id}`

Elimina todos los elementos cuyo campo `id` sea igual a `grupo_id`, sin modificar el resto de la medición. Responde `204` sin body.

Si la medición existe pero no hay coincidencia de `grupo_id`, también responde `204`: el estado deseado (el grupo ya no está) se cumple. Si la medición no existe responde `404`.

## Límites de propiedad

El frontend no puede modificar `cantidad`, `matricula`, `fechaSubida` ni `producto` mediante estos endpoints. `nombre` solo puede cambiarse con `PATCH /acopio/mediciones/renombrar` y siempre afecta al conjunto explícito de mediciones indicado en `medicionIds`. Esos datos de origen pertenecen a la incorporación externa de Báscula.

La integración externa debe actualizar los documentos con inserciones o actualizaciones parciales. Una operación de reemplazo completo del documento podría eliminar el campo `grupo` o sobrescribir un nombre gestionado desde Acopio.

## Fuente de contrato viva

La fuente ejecutable del contrato es OpenAPI, disponible en `GET /openapi.json` y en la interfaz `GET /docs` de cada despliegue. Esta guía Markdown es la referencia de contexto para desarrollo y debe actualizarse junto a cualquier cambio de endpoint o modelo.

## Pruebas de integración

La suite `tests/test_acopio_workflow.py` cubre Picking inicial, las tres clasificaciones, conservación de procedencia balizada, fusión válida, destino Mineral o Baja Ley, destinos Estéril, origen no balizado, conflicto de nombres, medición inexistente, auditoría embebida y concurrencia con actualización incompleta. También cubre el renombrado de una o varias mediciones, auditoría embebida, fechas UTC, IDs inexistentes, tarjetas distintas y validaciones de nombre e IDs.

Las pruebas de renombrado y fusión funcionan con MongoDB standalone. Configura una base de datos exclusiva de pruebas:

```powershell
$env:ACOPIO_TEST_MONGO_URI = "mongodb://localhost:27017/orovalle_acopio_test"
py -m unittest tests.test_acopio_workflow
```

Sin esa variable, las pruebas de integración se omiten y no modifican ninguna base de datos. La prueba unitaria de concurrencia no necesita MongoDB.
