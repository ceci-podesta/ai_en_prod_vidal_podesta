# Oil & Gas Forecast — IA en Producción

Pipeline de pronóstico de producción de hidrocarburos para pozos no convencionales, construido como trabajo integrador de la materia IA en Producción.

## Integrantes

- Cecilia Podesta
- Sol Vidal

## Descripción del problema

Los equipos de planificación e ingeniería de reservorios necesitan estimar la producción futura de hidrocarburos para tomar decisiones operativas y presupuestarias. Actualmente estos pronósticos se realizan con planillas dispersas y modelos manuales, sin trazabilidad sobre los supuestos utilizados. Este sistema busca reemplazar ese proceso con un pipeline reproducible de ML que expone sus resultados vía API REST.

El foco del trabajo está puesto en el despliegue productivo del sistema: feature store, tracking de experimentos, orquestación recurrente, monitoreo de degradación y exposición vía API. El modelo predictivo es intencionalmente simple; se utiliza como componente dentro del pipeline de MLOps.

## Arquitectura

El sistema corre localmente con Docker Compose y contiene los siguientes servicios:

- MLflow para tracking de experimentos y model registry.
- PostgreSQL para Airflow.
- Airflow webserver y scheduler para orquestación.
- FastAPI para inferencia.
- Feast como feature store local, con offline store en Parquet y online store en SQLite.

El flujo principal queda orquestado en el DAG `ml_pipeline`:

1. `prepare_data_task`: descarga el CSV crudo del portal de datos de energía y genera el Parquet con features.
2. `feast_apply_task`: registra entidades y feature views en Feast.
3. `materialize_task`: materializa features hacia el online store.
4. `train_task`: entrena el modelo y lo registra en MLflow con alias `production`.
5. `monitoring_report_task`: genera el reporte de model decay, data drift y concept drift.
6. `populate_online_task`: actualiza el online store para servir inferencias desde la API.

## Dataset

Se utiliza el dataset de Producción de Pozos de Gas y Petróleo No Convencional publicado por la Secretaría de Energía de Argentina:

https://datos.energia.gob.ar/dataset/c846e79c-026c-4040-897f-1ad3543b407c/resource/b5b58cdc-9e07-41f9-b392-fb9ec68b0725/download/produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv

Los datos tienen granularidad mensual: cada registro representa la producción de un pozo en un mes dado. El script `prepare_data.py` construye la fecha como el primer día de cada mes (`YYYY-MM-01`) a partir de los campos `anio` y `mes`.

En el offline store generado por Feast (`feature_store/data/well_features.parquet`), cada fila representa un par pozo-mes con features completas y targets reales. Para la corrida de referencia se validó que el rango disponible para monitoreo va de `2006-02-01` a `2026-04-01`.

## Requisitos

- Docker y Docker Compose instalados.
- En Windows: WSL 2 + Docker Desktop con integración WSL habilitada.

## Setup y ejecución

### 1. Crear carpetas necesarias

```bash
mkdir -p logs plugins reports/model_monitoring feature_store/data
```

En WSL puede ser necesario asegurar permisos sobre las carpetas montadas:

```bash
sudo chown -R "$USER":"$USER" logs plugins reports feature_store/data || true
chmod -R 777 logs plugins reports feature_store/data
```

### 2. Buildear y levantar servicios

```bash
docker compose build
docker compose up -d
docker compose ps -a
```

Servicios:

| Servicio | URL |
|---|---|
| Airflow UI | http://localhost:8080 |
| MLflow UI | http://localhost:5000 |
| API Swagger | http://localhost:8000/docs |
| API base | http://localhost:8000 |

Airflow:

- usuario: `admin`
- password: `admin`

La API puede quedar en `Exited (1)` hasta que exista un modelo registrado con alias `production` en MLflow. Luego de correr el DAG, reiniciar la API.

## Correr el pipeline con Airflow

El DAG principal es `ml_pipeline`. Está configurado con `schedule="@monthly"` y `catchup=False`, por lo que puede ejecutarse automáticamente con frecuencia mensual.

Para reproducir la simulación usada en la entrega, conviene dispararlo por CLI con configuración explícita:

```bash
RUN_ID="model_decay_$(date +%Y%m%d_%H%M%S)"

docker compose exec -T airflow-scheduler airflow dags trigger ml_pipeline \
  --run-id "$RUN_ID" \
  --conf '{"training_cutoff":"2025-10-01","monitoring_months":6,"baseline_months":18}'

docker compose exec -T airflow-scheduler airflow tasks states-for-dag-run ml_pipeline "$RUN_ID"
```

Esta configuración usa:

- `training_cutoff`: `2025-10-01`
- baseline: `2024-04-01` a `2025-10-01`
- monitoring: `2025-11-01` a `2026-04-01`
- `monitoring_months`: `6`
- `baseline_months`: `18`

Como el dataset llega hasta `2026-04-01`, usar `2025-10-01` permite simular seis meses posteriores al entrenamiento.

## Feature Store

El feature store usa Feast con provider local.

El offline store es un archivo Parquet generado por `prepare_data.py` con features históricas de todos los pozos. Se usa durante el entrenamiento y el monitoreo.

El online store es una base SQLite materializada por Feast. Lo consume la API en tiempo de inferencia mediante `get_online_features`.

### Features generadas

| Feature | Descripción |
|---|---|
| `tipoextraccion` | Tipo de extracción del pozo, codificado como variable categórica |
| `avg_prod_gas_10m` | Promedio de producción de gas en los últimos 10 meses previos |
| `avg_prod_pet_10m` | Promedio de producción de petróleo en los últimos 10 meses previos |
| `last_prod_gas` | Última producción de gas registrada antes del mes objetivo |
| `last_prod_pet` | Última producción de petróleo registrada antes del mes objetivo |
| `n_readings` | Cantidad acumulada de lecturas mensuales previas disponibles para ese pozo |

Las features de producción usan `shift(1)`, por lo que para un pozo-mes `n` se calculan con información disponible hasta el mes `n-1`. El target corresponde a la producción del mes `n`.

## Modelo

Se usa un `MultiOutputRegressor` con `RandomForestRegressor` como estimador base. El modelo predice simultáneamente:

- `prod_gas`
- `prod_pet`

Las features usadas para ambos targets son:

- `tipoextraccion`
- `avg_prod_gas_10m`
- `avg_prod_pet_10m`
- `last_prod_gas`
- `last_prod_pet`
- `n_readings`

El entrenamiento recibe una fecha de corte y usa datos con `fecha <= training_cutoff`. Para controlar el uso de memoria, `train.py` limita el entrenamiento a un máximo de `100_000` filas si el dataset supera ese tamaño.

MLflow registra parámetros, métricas, artefactos del modelo y registra el modelo como `oil_gas_forecast` con alias `production`.

## Monitoreo de model decay y drift

El DAG genera un reporte de monitoreo después del entrenamiento. El reporte compara una ventana baseline anterior al `training_cutoff` contra una ventana posterior simulada de monitoreo.

Para la corrida de referencia:

- `training_cutoff`: `2025-10-01`
- baseline: `2024-04-01` a `2025-10-01`
- monitoring: `2025-11-01` a `2026-04-01`
- filas baseline: `80.815`
- filas monitoring: `28.539`

El reporte queda registrado en MLflow en el experimento `oil_gas_monitoring`. Para verlo:

1. Ir a MLflow.
2. Cambiar a `Model training`.
3. Abrir el experimento `oil_gas_monitoring`.
4. Abrir el run `monitoring_2025-10-01_to_2026-04-01`.
5. Entrar a `Artifacts > monitoring_report`.

Artefactos principales:

- `status.csv`
- `model_performance_comparison.csv`
- `numeric_drift_summary.csv`
- `categorical_drift_tipoextraccion_comparison.csv`
- `concept_drift_comparison.csv`
- `model_decay_deltas.png`
- `numeric_drift_psi.png`
- `numeric_drift_ks.png`
- `categorical_drift_tipoextraccion.png`
- `concept_drift_residuals.png`

Métricas incluidas:

- model decay: RMSE, MAE y R2 baseline vs monitoring;
- data drift: PSI y KS sobre features numéricas, y PSI categórico para `tipoextraccion`;
- concept drift: cambios en la media y dispersión de residuos (`y_real - y_pred`) entre baseline y monitoring.

En la corrida de referencia no se observa drift fuerte en las features monitoreadas. Sí se observa degradación de performance, especialmente en petróleo. Esto es compatible con un modelo simple y un set de features limitado para generalizar temporalmente, con posibles variables relevantes no incluidas o cambios en la relación entre features y targets. El foco del trabajo no está en optimizar el modelo predictivo, sino en detectar, registrar y hacer visible este comportamiento dentro de un pipeline productivo.

## Endpoints

### GET `/api/v1/wells`

Devuelve la lista de pozos con datos registrados en la fecha indicada. Como los datos son mensuales, `date_query` debe indicar el primer día del mes (`YYYY-MM-01`).

Ejemplo:

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

### GET `/api/v1/forecast`

Devuelve el pronóstico de producción mensual de gas para un pozo en un rango de fechas. Como el dataset y el modelo trabajan con granularidad mensual, la API devuelve una entrada por cada mes incluido en el rango solicitado, usando el primer día del mes como fecha (`YYYY-MM-01`).

Ejemplo:

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

## Decisiones de diseño y trade-offs

**Feature store compartido entre train y serve.** Las features se generan una vez y se persisten en Feast. Tanto entrenamiento como inferencia consumen del mismo store, evitando training-serving skew.

**Fecha de corte configurable.** El DAG puede tomar `training_cutoff` desde `dag_run.conf`, lo que permite simular backtesting sobre un dataset cerrado. Si no se pasa configuración, Airflow usa `data_interval_end`.

**Forecast mensual.** El endpoint devuelve una predicción por mes porque la granularidad real de los datos y del modelo es mensual.

**Modelo simple.** Se usa RandomForest multioutput con features tabulares simples. Esto es suficiente para demostrar el pipeline productivo, aunque no agota posibles mejoras predictivas.

## Limitaciones conocidas

**Modelo predictivo simple.** El modelo no incorpora tendencias temporales explícitas, variables externas ni efectos de calendario. El objetivo del TP está en el pipeline de producción y observabilidad, no en optimizar la calidad predictiva.

**Dependencia del dataset público.** La descarga del CSV depende de la disponibilidad del portal externo. Si el portal responde con errores temporales, puede reintentarse el DAG.

**Dataset cerrado para simulación.** Como el dataset disponible llega hasta `2026-04-01`, las corridas de monitoreo deben elegir un `training_cutoff` que deje datos posteriores suficientes para evaluar.

## Cómo limpiar y empezar de cero

```bash
docker compose down -v
docker compose build --no-cache
```

El flag `-v` elimina los volúmenes de Docker, incluyendo datos de MLflow y modelos registrados.
