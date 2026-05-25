# Guía de reproducción — Entrega Final

Esta guía explica cómo levantar el sistema completo, correr el pipeline de ML con Airflow, revisar el reporte de monitoreo en MLflow y probar la API.

## Requisitos

- Docker Desktop instalado y abierto.
- En Windows: WSL2 con Ubuntu y Docker Desktop con integración WSL2 habilitada.

## Levantar el sistema

### 1. Ir a la carpeta del proyecto

```bash
cd <carpeta del proyecto>
```

### 2. Crear carpetas necesarias y asegurar permisos

```bash
mkdir -p logs plugins reports/model_monitoring feature_store/data
sudo chown -R "$USER":"$USER" logs plugins reports feature_store/data || true
chmod -R 777 logs plugins reports feature_store/data
```

Este paso evita errores de permisos de Airflow sobre carpetas montadas desde WSL.

### 3. Buildear las imágenes

```bash
docker compose build
```

### 4. Levantar todos los servicios

```bash
docker compose up -d
docker compose ps -a
```

Esto levanta MLflow, PostgreSQL, Airflow webserver, Airflow scheduler y API.

El contenedor `airflow-init` debe aparecer como `Exited (0)`. Es correcto: inicializa Airflow y termina.

La API puede aparecer como `Exited (1)` hasta que exista un modelo productivo en MLflow. Después de correr el DAG, reiniciar la API.

## Servicios

| Servicio | URL |
|---|---|
| Airflow UI | http://localhost:8080 |
| MLflow UI | http://localhost:5000 |
| API Swagger | http://localhost:8000/docs |

Credenciales Airflow:

- usuario: `admin`
- password: `admin`

## Correr el pipeline de ML con Airflow

El DAG principal es `ml_pipeline`.

Pasos del DAG:

1. `prepare_data_task`: descarga el CSV y genera el offline store.
2. `feast_apply_task`: registra entidades y feature views en Feast.
3. `materialize_task`: materializa features al online store.
4. `train_task`: entrena y registra el modelo en MLflow.
5. `monitoring_report_task`: genera el reporte de model decay, data drift y concept drift.
6. `populate_online_task`: actualiza el online store para servir inferencias.

El DAG tiene `schedule="@monthly"` y `catchup=False`.

## Correr simulación de monitoreo

El dataset disponible en el offline store llega hasta `2026-04-01`. Para simular seis meses posteriores al entrenamiento, usar cutoff `2025-10-01`.

```bash
RUN_ID="model_decay_$(date +%Y%m%d_%H%M%S)"

docker compose exec -T airflow-scheduler airflow dags trigger ml_pipeline \
  --run-id "$RUN_ID" \
  --conf '{"training_cutoff":"2025-10-01","monitoring_months":6,"baseline_months":18}'

docker compose exec -T airflow-scheduler airflow tasks states-for-dag-run ml_pipeline "$RUN_ID"
```

La corrida usa:

- baseline: `2024-04-01` a `2025-10-01`
- monitoring: `2025-11-01` a `2026-04-01`
- dataset disponible hasta: `2026-04-01`

## Revisar resultados en MLflow

1. Entrar a http://localhost:5000.
2. Cambiar a `Model training`.
3. Entrar a `Experiments`.
4. Abrir `oil_gas_monitoring`.
5. Abrir el run `monitoring_2025-10-01_to_2026-04-01`.
6. Entrar a `Artifacts > monitoring_report`.

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

## Entrenamiento: detalles técnicos

El dataset es de producción de pozos de gas y petróleo no convencional publicado por la Secretaría de Energía de Argentina. Tiene granularidad mensual.

El entrenamiento usa el offline store de Feast y recibe una fecha de corte. Por default, el DAG usa `data_interval_end`, pero para simulación/backtesting se puede pasar `training_cutoff` por `dag_run.conf`.

Para controlar memoria, `training/train.py` limita el entrenamiento a un máximo de `100_000` filas (`MAX_TRAINING_ROWS = 100_000`).

El modelo es un `MultiOutputRegressor` con `RandomForestRegressor`. Predice `prod_gas` y `prod_pet`; la API expone `prod_gas` como `prod`.

## Probar la API

Después de que el DAG termine en verde:

```bash
docker compose restart api
```

### GET `/api/v1/wells`

Devuelve los pozos con datos registrados en una fecha mensual.

```bash
curl "http://localhost:8000/api/v1/wells?date_query=2008-02-01"
```

### GET `/api/v1/forecast`

Devuelve el pronóstico mensual de gas para un pozo.

```bash
curl "http://localhost:8000/api/v1/forecast?id_well=10073&date_start=2026-01-15&date_end=2026-04-20"
```

Respuesta esperada:

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

## Troubleshooting

### Permisos en Airflow

Si Airflow falla con errores de permisos sobre `logs`, `plugins`, `reports` o `feature_store/data`:

```bash
sudo chown -R "$USER":"$USER" logs plugins reports feature_store/data || true
chmod -R 777 logs plugins reports feature_store/data
docker compose restart airflow-scheduler airflow-webserver
```

### API caída antes de entrenar

Si la API aparece como `Exited (1)` antes de correr el DAG, es esperable: al iniciar intenta cargar el modelo con alias `production`. Después de entrenar:

```bash
docker compose restart api
```

### Registry corrupto de Feast

Si `feast_apply_task` falla por problemas de registry:

```bash
rm -f feature_store/data/registry/registry.db
```

Luego volver a triggerear el DAG.

## Limpiar y empezar desde cero

```bash
docker compose down -v
docker compose build
docker compose up -d
```
