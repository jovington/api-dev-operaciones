Actúa como desarrollador senior de Backend especializado en Python, FastAPI y MongoDB. 

Necesito actualizar o añadir un endpoint de planta en nuestra API para que, partiendo del funcionamiento actual de `/planta/ultimo-dato`, permita consultar datos históricos filtrados por un límite máximo de registros y rangos de fechas/horas.

### Contexto de la Arquitectura del Proyecto:
Sigue estrictamente la estructura modular existente:
- app/routers/: Endpoints HTTP organizados por dominio.
- app/services/: Lógica de negocio.
- app/db/: Repositorios de MongoDB.
- app/models/: Contratos Pydantic de entrada y salida.

### Requisitos del Endpoint de Planta:

1. Modifica o crea un endpoint (manteniendo compatibilidad) orientado a la obtención de lecturas del PLC de planta.
2. Debe aceptar los siguientes **query parameters opcionales**:
   - `limit`: Entero opcional (por ejemplo, por defecto 1 o un máximo configurable como 100). Si no se especifica, debe comportarse igual que el endpoint actual `/planta/ultimo-dato` (devolviendo el registro más reciente).
   - `fecha_inicio`: Cadena de texto opcional (formato amigable o ISO como YYYY-MM-DDTHH:MM:SS o YYYY-MM-DD HH:MM:SS) para filtrar registros desde esa fecha y hora.
   - `fecha_fin`: Cadena de texto opcional para filtrar registros hasta esa fecha y hora.
3. **Lógica de la Base de Datos (MongoDB):**
   - La colección de planta almacena las lecturas ordenadas por `payload.timestamp`.
   - Construye la consulta dinámica (`find` / agregación en MongoDB) aplicando los filtros de fecha sobre el campo de timestamp si vienen informados.
   - Ordena los resultados descendentemente por timestamp (`payload.timestamp: -1`).
   - Aplica el operador `.limit()` según el parámetro recibido (si `limit` no viene, usa `limit(1)` para mantener la lógica de "último dato").

### Entregable:
Proporciona el código modularizado requerido para:
1. El contrato en Pydantic (`app/models/`).
2. La lógica en el repositorio/servicio (`app/services/` o `app/db/`).
3. La definición de la ruta en el router correspondiente (`app/routers/`).



Respeta la estructura: Le indica explícitamente dónde ubicar cada archivo (routers, services, db, models) basándose en tu README.md.

Mantiene la lógica previa: Asegura que si la aplicación móvil (o cualquier cliente) llama al endpoint sin parámetros, se siga comportando exactamente igual que el /planta/ultimo-dato actual.

Maneja los tipos flexibles: Al pedirle que acepte cadenas de texto opcionales para las fechas (fecha_inicio y fecha_fin), evita los problemas de parseo estricto y permite que la app móvil mande el string cómodamente.