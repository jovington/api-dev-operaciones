# Planificación

La importación usa la base de datos `Operaciones` y la colección `Planificacion`.

## Importar

`POST /api/planificacion/importar?tipo=mensual`

El body es `multipart/form-data` con el campo `archivo`. Se aceptan CSV UTF-8 o Latin-1 delimitados por `;`, `,` o tabulador. Las cabeceras obligatorias son `Tarea`, `ZONA`, `NIVEL`, `SUBNIVEL`, `ACTTYPE`, `CAMARA` y `PLANTA`; debe existir, además, al menos una columna de fecha `DD/MM/YYYY`.

El importador procesa todas las filas sin filtrar por `PLANTA` ni `Tarea`. Cada documento conserva esos campos como `planta` y `tarea`, por ejemplo `planta: "Si"` y `tarea: "Tonnes"`, para permitir filtros posteriores. Cada fila se persiste como un único documento y las columnas de fecha con toneladas positivas forman el array `cronograma`; las fechas vacías o con valor cero se omiten. Una fila sin una fecha positiva se descarta.

Las cifras europeas, como `1.234,50`, se convierten a números MongoDB. También se acepta el punto decimal que aparece en los CSV operativos. Los campos numéricos no reservados se guardan en `valores` con nombres `snake_case` y los textos en `atributos`.

`Area_Nivel` elimina el prefijo numérico de `ZONA`, normaliza el nivel y omite los marcadores de relleno `.` o `..`. Por ejemplo, `02.NW`, `-040`, `0`, `GL`, `s`, se convierte en `NW-40_GLS`.

Ejemplo de respuesta:

```json
{
  "tipo": "semanal",
  "registrosImportados": 42,
  "registrosActualizados": 0,
  "filasDescartadas": 120
}
```

Un CSV sin las cabeceras requeridas, sin fechas, con filas de longitud desigual o con valores no numéricos en columnas de fecha devuelve `400`. La clave determinista de cada fila permite reimportar el mismo archivo sin duplicar documentos.

## Consultar

`GET /api/planificacion`

Filtros opcionales: `tipo=mensual|semanal`, `fechaDesde`, `fechaHasta` en ISO 8601, `Area_Nivel`, `planta` y `tarea`. Los filtros de fecha se aplican sobre `cronograma.fecha`; la respuesta conserva un documento por fila y ordena por la fecha más reciente del cronograma.