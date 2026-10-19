# Gravimetría

## Predicciones para gráfica temporal

`GET /gravimetria/predicciones`

Devuelve mediciones de granulometría para construir una gráfica temporal de burbujas. La API consulta `griphonv2.datacollector` y utiliza exclusivamente documentos con `worker: "rocks"`.

La API calcula las mediciones de cada cámara por separado: ordena por la fecha y hora de `predictions.timestamp` en orden descendente y conserva las `limit` más recientes de cada `metadata.camera_id`. Después combina todas las cámaras y entrega el array completo en orden descendente. Si el documento no tiene una marca de tiempo válida, se usa `created_at` como fecha de la medición.

### Parámetros de consulta

| Parámetro | Tipo | Obligatorio | Valor por defecto | Descripción |
| --- | --- | --- | --- | --- |
| `from` | fecha/hora ISO 8601 | No | - | Inicio inclusivo del intervalo. |
| `to` | fecha/hora ISO 8601 | No | - | Fin inclusivo del intervalo. |
| `limit` | entero | No | `500` | Número máximo de mediciones más recientes por cámara. Mínimo `1`, máximo `2000`. |

Ejemplo para pedir hasta 500 mediciones:

```http
GET /gravimetria/predicciones?limit=500
```

Ejemplo entre fechas:

```http
GET /gravimetria/predicciones?from=2026-08-01T00:00:00Z&to=2026-08-13T23:59:59.999Z&limit=100
```

También se aceptan fechas sin hora, como `from=2026-08-01`. Una fecha `to` sin hora equivale a las `00:00:00` de ese día; para incluir el día completo, el frontend debe enviar la hora final como en el ejemplo anterior.

### Respuesta `200`

Siempre responde un array JSON. Un array vacío significa que no hay mediciones válidas en el intervalo solicitado.

```json
[
  {
    "created_at": "2026-08-13T12:29:18.657Z",
    "metadata": {
      "camera_id": "CAM02",
      "granulometria": {
        "fino": 20,
        "medio": 50,
        "grueso": 100
      }
    },
    "predictions": {
      "timestamp": "2026-08-13T12:29:18.464Z",
      "rocks_by_model_class": {
        "Fuera de rango >140mm": 17,
        "Medianas": 17
      },
      "total_objects_in_roi": 34,
      "oversize_ratio_pct": 50
    }
  }
]
```

Cada elemento contiene únicamente estos campos:

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `created_at` | string ISO 8601 UTC | Momento en que el recolector guardó el documento. |
| `metadata.camera_id` | string | Identificador de la cámara que generó la predicción, por ejemplo `CAM01` o `CAM02`. |
| `metadata.granulometria` | objeto o `null` | Umbrales de tamaño configurados en milímetros: `fino`, `medio` y `grueso`. |
| `predictions.timestamp` | string ISO 8601 UTC | Momento de la predicción; es la fecha principal para el eje temporal. |
| `predictions.rocks_by_model_class` | objeto | Conteo por clase detectada. Las claves dependen del modelo, por ejemplo `Aceptables`, `Medianas` o `Fuera de rango >140mm`. |
| `predictions.total_objects_in_roi` | entero | Total de objetos detectados dentro de la región de interés. Siempre es mayor que cero. |
| `predictions.oversize_ratio_pct` | número | Porcentaje de objetos fuera de rango. |

El carácter `>` puede llegar serializado como `\u003E` por algunos clientes JSON. Ambos textos representan la misma clave: `Fuera de rango >140mm`.

### Reglas de selección

La API excluye documentos que no cumplan alguna de estas condiciones:

- `worker` distinto de `rocks`.
- `metadata.camera_id` ausente o no textual.
- Fecha de medición no convertible, sin `created_at` válido para usar como respaldo.
- `rocks_by_model_class` ausente o vacío.
- `total_objects_in_roi` menor o igual que cero.
- `oversize_ratio_pct` no numérico o no finito.

### Errores

- `422 Unprocessable Entity`: `from`, `to` no son fechas ISO 8601 válidas, o `limit` no es un entero entre `1` y `2000`.
- `503 Service Unavailable`: MongoDB no está disponible.

No hay paginación por cursor. Para una gráfica de rango amplio, el frontend debe acotar `from` y `to` o ajustar `limit` dentro del máximo permitido.
