# Oil & Gas Forecast — IA en Producción

Pipeline de pronóstico de producción de hidrocarburos para pozos no convencionales. Trabajo integrador de la materia IA en Producción.

**Integrantes:** Cecilia Podesta · Sol Vidal

---

## Descripción del problema

Los equipos de planificación e ingeniería de reservorios necesitan estimar la producción futura de hidrocarburos para tomar decisiones operativas y presupuestarias. Este sistema reemplaza planillas dispersas y modelos manuales con un pipeline reproducible de ML que expone sus resultados vía API REST.

El foco está en el despliegue productivo: feature store, tracking de experimentos, orquestación recurrente, monitoreo de degradación y exposición escalable vía API. El modelo predictivo es intencionalmente simple; actúa como componente dentro del pipeline de MLOps.

---

## Arquitectura

El sistema corre localmente con Docker Compose. Los servicios permanentes son:

| Servicio | Descripción |
|---|---|
| `mlflow` | Tracking de experimentos y model registry |
| `postgres` | Base de datos de Airflow |
| `airflow-webserver` | UI de Airflow |
| `airflow-scheduler` | Ejecutor del DAG |
| `api` | FastAPI + Ray Serve para inferencia escalable |

El flujo completo está orquestado en el DAG `ml_pipeline`, configurado con `schedule="@monthly"` y `catchup=False`. Esto significa que Airflow ejecuta el pipeline automáticamente el primer día de cada mes, reentrenando el modelo con los datos disponibles hasta esa fecha. No requiere intervención manual para las corridas regulares.

El DAG ejecuta en orden:

1. `prepare_data_task` — descarga el CSV crudo y genera el offline store de Feast (Parquet con features)
2. `feast_apply_task` — registra entidades y feature views en Feast
3. `materialize_task` — materializa features al online store (SQLite)
4. `train_task` — entrena el modelo y lo registra en MLflow con alias `production`
5. `monitoring_report_task` — genera el reporte de model decay, data drift y concept drift
6. `populate_online_task` — actualiza el online store para servir inferencias desde la API

---

## Dataset

Dataset de Producción de Pozos de Gas y Petróleo No Convencional, publicado por la Secretaría de Energía de Argentina. Granularidad mensual: cada registro representa la producción de un pozo en un mes. El script `prepare_data.py` construye la fecha como el primer día de cada mes (`YYYY-MM-01`) a partir de los campos `anio` y `mes`. El dataset disponible cubre hasta `2026-04-01`. Nuestra última consulta fue el 27/05/2026.

---

## Requisitos

- Docker Desktop instalado y abierto.
- En Windows: WSL2 con Ubuntu y Docker Desktop con integración WSL2 habilitada. Todos los comandos deben correrse desde la terminal de WSL.

---

## Setup y ejecución completa

### 1. Ir a la carpeta del proyecto

```bash
cd <carpeta del proyecto>
```

### 2. Crear carpetas necesarias

```bash
mkdir -p logs plugins reports/model_monitoring feature_store/data
```

En WSL puede ser necesario asegurar permisos sobre las carpetas montadas:

```bash
sudo chown -R "$USER":"$USER" logs plugins reports feature_store/data || true
chmod -R 777 logs plugins reports feature_store/data
```

### 3. Buildear las imágenes

```bash
docker compose build
```

### 4. Levantar todos los servicios

```bash
docker compose up -d
docker compose ps -a
```

Estado esperado:

| Contenedor | Status |
|---|---|
| `mlflow` | Up |
| `postgres` | Up (healthy) |
| `airflow-webserver` | Up |
| `airflow-scheduler` | Up |
| `airflow-init` | Exited (0) ← correcto, solo inicializa y termina |
| `api` | Up o Exited (1) ← puede estar caída hasta que exista un modelo |

### 5. Limpiar la base de datos de MLflow (solo la primera vez)

Necesario para que MLflow cree el experimento con la configuración correcta de almacenamiento de artefactos:

```bash
docker compose exec mlflow rm -f /mlflow/data/mlflow.db
docker compose restart mlflow
```

Esperá unos segundos hasta que MLflow esté disponible en http://localhost:5000.

### 6. Triggerear el DAG desde Airflow

- URL: http://localhost:8080
- Usuario: `admin` / Contraseña: `admin`

Buscá el DAG `ml_pipeline`, activalo (toggle ON) y disparalo con el botón ▶.

Cuando todas las tasks terminen en verde, el pipeline corrió exitosamente:

![Airflow DAG completo en verde](docs/screenshots/airflow_dag_green.png)

Para reproducir la simulación con monitoreo, usá este comando desde la terminal:

```bash
RUN_ID="model_decay_$(date +%Y%m%d_%H%M%S)"

docker compose exec -T airflow-scheduler airflow dags trigger ml_pipeline \
  --run-id "$RUN_ID" \
  --conf '{"training_cutoff":"2025-10-01","monitoring_months":6,"baseline_months":18}'
```

Esta configuración usa:

- `training_cutoff`: `2025-10-01`
- baseline: `2024-04-01` a `2025-10-01` (18 meses)
- monitoring: `2025-11-01` a `2026-04-01` (6 meses)

Como el dataset llega hasta `2026-04-01`, esto permite simular seis meses posteriores al entrenamiento. Es necesario correrlo desde la terminal por la version de Airflow que no permite ingresar el parametro de fecha de corrida y otros manualmente desde la UI. 

El primer run tarda varios minutos porque descarga el CSV completo (~400k filas) y entrena el modelo.

### 7. Reiniciar la API después de que termine el DAG

```bash
docker compose restart api
```

La API carga el modelo en el primer request (lazy loading), no al arrancar. Esto significa que queda disponible inmediatamente después del restart, pero la primera llamada al endpoint de forecast tardará unos segundos mientras carga el modelo desde MLflow.

---

## Links rápidos

| Servicio | URL |
|---|---|
| Airflow UI | http://localhost:8080 |
| MLflow UI | http://localhost:5000 |
| API Swagger | http://localhost:8000/docs |
| API base | http://localhost:8000 |

---

## Modelo

Se usa un `MultiOutputRegressor` con `RandomForestRegressor` como estimador base. El modelo predice simultáneamente:

- `prod_gas` — producción mensual de gas (m³)
- `prod_pet` — producción mensual de petróleo (m³)

La API expone únicamente `prod_gas` como el campo `prod` de la respuesta.

El entrenamiento recibe una fecha de corte y usa datos con `fecha <= training_cutoff`. Para controlar el uso de memoria, el entrenamiento toma hasta `100_000` filas del dataset (por tema de recursos computacionales). Si el dataset tiene más filas, se hace un muestreo aleatorio con semilla fija.

MLflow registra parámetros, métricas (RMSE, MAE, R²), artefactos del modelo y lo registra como `oil_gas_forecast` con alias `production`.

![MLflow model registry con alias production](docs/screenshots/mlflow_model_registry.png)

---

## Feature Store

El feature store usa Feast con provider local.

- **Offline store:** archivo Parquet generado por `prepare_data.py`. Contiene features históricas de todos los pozos con timestamps. Se usa durante el entrenamiento para obtener features point-in-time correctas con `get_historical_features`.
- **Online store:** base SQLite materializada por Feast. Lo consume la API en tiempo de inferencia con `get_online_features`.

Las features de producción usan `shift(1)`: para un pozo-mes `n`, se calculan con información disponible hasta el mes `n-1`. El target corresponde a la producción del mes `n`. Las features de ventana móvil (`avg_prod_gas_10m`, `avg_prod_pet_10m`) calculan el promedio de los últimos 10 meses previos al mes objetivo.

| Feature | Descripción |
|---|---|
| `tipoextraccion` | Tipo de extracción del pozo, codificado como variable categórica |
| `avg_prod_gas_10m` | Promedio de producción de gas en los últimos 10 meses |
| `avg_prod_pet_10m` | Promedio de producción de petróleo en los últimos 10 meses |
| `last_prod_gas` | Última producción de gas registrada |
| `last_prod_pet` | Última producción de petróleo registrada |
| `n_readings` | Cantidad acumulada de lecturas mensuales previas del pozo |

---

## Monitoreo de model decay y drift

El DAG genera automáticamente un reporte de monitoreo después de cada entrenamiento. Compara una ventana baseline anterior al `training_cutoff` contra una ventana posterior de monitoreo. Los parametros seteados por default son 18 meses antes del `training_cutoff` para el baseline, y 6 meses posteriores (simulacion de data productiva) para la ventana de monitoreo (ver sección 6). 

### Ver el reporte en MLflow

1. Entrar a http://localhost:5000
2. Ir a `Experiments`
3. Abrir `oil_gas_monitoring`
4. Abrir el run `monitoring_2025-10-01_to_2026-04-01`
5. Entrar a `Artifacts > monitoring_report`

### Artefactos generados

| Archivo | Contenido |
|---|---|
| `status.csv` | Resumen de alertas por métrica |
| `model_performance_comparison.csv` | RMSE, MAE y R² baseline vs monitoring |
| `numeric_drift_summary.csv` | PSI y KS sobre features numéricas |
| `categorical_drift_tipoextraccion_comparison.csv` | PSI categórico para `tipoextraccion` |
| `concept_drift_comparison.csv` | Media y dispersión de residuos baseline vs monitoring |
| `model_decay_deltas.png` | Gráfico de degradación de performance |
| `numeric_drift_psi.png` | PSI por feature numérica |
| `numeric_drift_ks.png` | KS por feature numérica |
| `categorical_drift_tipoextraccion.png` | Distribución de `tipoextraccion` baseline vs monitoring |
| `concept_drift_residuals.png` | Distribución de residuos baseline vs monitoring |

### Métricas monitoreadas

- **Model decay:** RMSE, MAE y R² comparados entre baseline y monitoring
- **Data drift:** PSI y estadístico KS sobre features numéricas; PSI categórico para `tipoextraccion`
- **Concept drift:** cambios en la media y dispersión de residuos (`y_real - y_pred`) entre ventanas


![MLflow artifacts del reporte de monitoreo](docs/screenshots/mlflow_monitoring_artifacts.png)

---

## API escalable con Ray Serve

La API corre con Ray Serve, que levanta dos réplicas de la aplicación FastAPI y distribuye el tráfico entre ellas (load balancing automático). Esto permite manejar picos de demanda con baja latencia.

Configuración en `api/serve_app.py`:

```python
@serve.deployment(
    num_replicas=2,
    max_queued_requests=100,
)
```

- `num_replicas=2`: dos instancias de la aplicación corriendo en paralelo
- `max_queued_requests=100`: cola máxima de 100 requests pendientes. Si la cola está llena, el servidor responde 503 en vez de encolar indefinidamente. Esto es intencional: es preferible rechazar requests rápido que dejar acumular latencia sin límite.

### Nota sobre warnings de memoria en WSL

En Docker sobre WSL2, Ray muestra warnings como:

```
WARNING: The object store is using /tmp instead of /dev/shm because /dev/shm has only 67108864 bytes available.
```

Esto es esperado: Ray requiere más memoria compartida de la que Docker asigna por defecto en WSL2. El sistema se auto-recupera y funciona correctamente. Para eliminarlo en producción real se pasaría `--shm-size=4gb` al contenedor Docker, pero en este entorno local no es necesario.

---

## Endpoints

### GET `/api/v1/wells`

Devuelve la lista de pozos con datos registrados en una fecha mensual.

**Parámetro:** `date_query` — primer día del mes a consultar (`YYYY-MM-01`)

```bash
curl "http://localhost:8000/api/v1/wells?date_query=2008-02-01"
```

Respuesta:

```json
[
  {"id_well": "3640"},
  {"id_well": "8043"},
  {"id_well": "10073"}
]
```

---

### GET `/api/v1/forecast`

Devuelve el pronóstico mensual de producción de gas para un pozo en un rango de fechas. La API devuelve una entrada por cada mes incluido en el rango, usando el primer día del mes como fecha.

**Parámetros:**

| Parámetro | Tipo | Descripción |
|---|---|---|
| `id_well` | string | ID del pozo |
| `date_start` | date | Inicio del rango (`YYYY-MM-DD`) |
| `date_end` | date | Fin del rango (`YYYY-MM-DD`) |

```bash
curl "http://localhost:8000/api/v1/forecast?id_well=10073&date_start=2026-01-15&date_end=2026-04-20"
```

Respuesta:

```json
{
  "id_well": "10073",
  "data": [
    {"date": "2026-01-01", "prod": 109.77},
    {"date": "2026-02-01", "prod": 109.77},
    {"date": "2026-03-01", "prod": 109.77},
    {"date": "2026-04-01", "prod": 109.77}
  ]
}
```

El campo `prod` representa la producción mensual estimada de gas (m³). El valor es el mismo para todos los meses del rango porque el modelo usa features fijas del online store (las del último mes materializado) y no incorpora tendencias temporales.

La UI interactiva con todos los endpoints está en http://localhost:8000/docs.

![API Swagger con endpoints disponibles](docs/screenshots/api_swagger.png)

![Respuesta del endpoint forecast](docs/screenshots/api_forecast_response.png)

---

## Tracking de experimentos en MLflow

MLflow registra en cada entrenamiento:

- **Parámetros:** `n_estimators`, `random_state`, `n_jobs`, `max_training_rows`
- **Métricas:** `rmse_gas`, `rmse_pet`, `r2_gas`, `r2_pet`
- **Tags:** `training_cutoff_date`
- **Artefactos:** modelo serializado (sklearn)
- **Model Registry:** modelo registrado como `oil_gas_forecast` con alias `production`

---

## Decisiones de diseño

**Feature store compartido entre train y serve.** Las features se generan una vez y se persisten en Feast. Tanto entrenamiento como inferencia consumen del mismo store, evitando training-serving skew.

**Fecha de corte configurable.** El DAG puede recibir `training_cutoff` por `dag_run.conf`, lo que permite simular backtesting sobre el dataset cerrado. Si no se pasa configuración, Airflow usa `data_interval_end`. Esto no permite simular una ventana productiva. 

**Forecast mensual.** La granularidad real del dataset y el modelo es mensual. La API devuelve una predicción por mes porque eso es lo que el modelo puede estimar con sentido.

**Lazy loading del modelo en la API.** El modelo se carga desde MLflow en el primer request, no al arrancar el contenedor. Esto permite que la API esté disponible inmediatamente aunque todavía no exista un modelo registrado.


**Ray Serve con cola finita.** `max_queued_requests=100` es un trade-off explícito entre error rate y latencia: el sistema rechaza requests cuando está saturado en vez de acumular una cola ilimitada que haría crecer la latencia indefinidamente.

---

## Limitaciones conocidas

**Predicción constante en el rango de fechas.** El modelo no incorpora componentes temporales ni tendencias. Las features del online store son fijas por pozo, por lo que todos los meses dentro del rango de forecast muestran el mismo valor estimado.

**Dependencia del dataset público.** La descarga del CSV depende de la disponibilidad del portal externo. Si falla, puede reintentarse el DAG.

**Dataset cerrado para simulación.** Como el dataset disponible llega hasta `2026-04-01`, las corridas de monitoreo deben elegir un `training_cutoff` que deje datos posteriores suficientes para evaluar.

---

## Troubleshooting

### La API aparece como Exited (1) al levantar

Es esperable si todavía no existe un modelo registrado en MLflow. Después de que el DAG termine:

```bash
docker compose restart api
```

### feast_apply_task falla con "Error parsing message"

Hay un `registry.db` corrupto de una corrida anterior. Como es un bind mount, sobrevive al `docker compose down -v`. Solución:

```bash
rm -f feature_store/data/registry/registry.db
```

Volver a triggerear el DAG.

### Airflow falla con errores de permisos

Si las tasks de Airflow fallan con errores de permisos sobre `logs`, `plugins`, `reports` o `feature_store/data`:

```bash
sudo chown -R "$USER":"$USER" logs plugins reports feature_store/data || true
chmod -R 777 logs plugins reports feature_store/data
docker compose restart airflow-scheduler airflow-webserver
```

### Ray Serve muestra warnings de memoria en los logs

Esperado en Docker sobre WSL2. El sistema se auto-recupera y funciona correctamente. No requiere intervención.

---

## Limpiar y empezar desde cero

```bash
docker compose down -v
docker compose build
docker compose up -d
```

El flag `-v` elimina los named volumes de Docker, incluyendo los datos de MLflow y los modelos registrados.
