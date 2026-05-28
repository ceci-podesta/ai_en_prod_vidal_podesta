# Comandos operativos - model decay / monitoring

Este documento complementa el README. La idea es tener a mano los comandos para reproducir la parte de Airflow + MLflow + reporte de monitoreo.

## 1. Levantar stack desde cero

```bash
cd <carpeta-del-repo>

mkdir -p logs plugins reports/model_monitoring feature_store/data

sudo chown -R "$USER":"$USER" logs plugins reports feature_store/data || true
chmod -R 777 logs plugins reports feature_store/data

docker compose build
docker compose up -d
docker compose ps -a
```

Servicios:

- Airflow: http://localhost:8080
- MLflow: http://localhost:5000
- API docs: http://localhost:8000/docs

Credenciales Airflow:

- usuario: `admin`
- password: `admin`

Nota: la API puede quedar en `Exited (1)` hasta que exista un modelo con alias `production` en MLflow. Despues de correr el DAG, reiniciar la API.

## 2. Correr DAG con simulacion de monitoreo

El dataset disponible en el offline store llega hasta `2026-04-01`.

Para simular 6 meses posteriores al entrenamiento, usar:

- `training_cutoff`: `2025-10-01`
- `monitoring_months`: `6`
- `baseline_months`: `18`

```bash
RUN_ID="model_decay_$(date +%Y%m%d_%H%M%S)"

docker compose exec -T airflow-scheduler airflow dags trigger ml_pipeline \
  --run-id "$RUN_ID" \
  --conf '{"training_cutoff":"2025-10-01","monitoring_months":6,"baseline_months":18}'

docker compose exec -T airflow-scheduler airflow tasks states-for-dag-run ml_pipeline "$RUN_ID"
```

El mismo run se puede mirar desde Airflow UI en el DAG `ml_pipeline`.

## 3. Revisar reporte en MLflow

En MLflow:

1. Ir a `Model training`.
2. Entrar a `Experiments`.
3. Abrir `oil_gas_monitoring`.
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

## 4. Reiniciar API y probar forecast

```bash
docker compose restart api

curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8000/docs

curl "http://localhost:8000/api/v1/forecast?id_well=10073&date_start=2026-01-15&date_end=2026-04-20"
```

Respuesta esperada: un objeto con `id_well` y un campo `data` con una predicción mensual por mes incluido en el rango.

## 5. Troubleshooting permisos Airflow

Si Airflow falla con errores de permisos sobre `logs`, `plugins`, `reports` o `feature_store/data`, correr:

```bash
sudo chown -R "$USER":"$USER" logs plugins reports feature_store/data || true
chmod -R 777 logs plugins reports feature_store/data
docker compose restart airflow-scheduler airflow-webserver
```

## 6. Limpiar stack

```bash
docker compose down
```

Para borrar volumenes y empezar desde cero:

```bash
docker compose down -v
```
