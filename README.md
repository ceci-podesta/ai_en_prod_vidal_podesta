# Oil & Gas Forecast — IA en Producción

Pipeline de pronóstico de producción de hidrocarburos para pozos no convencionales, construido como trabajo integrador de la materia IA en Producción.

## Integrantes

- Cecilia Podesta
- Sol Vidal

## Descripción del problema

Los equipos de planificación e ingeniería de reservorios necesitan estimar la producción futura de hidrocarburos para tomar decisiones operativas y presupuestarias. Actualmente estos pronósticos se realizan con planillas dispersas y modelos manuales, sin trazabilidad sobre los supuestos utilizados. Este sistema busca reemplazar ese proceso con un pipeline reproducible de ML que expone sus resultados vía API REST.

## Arquitectura

El sistema corre localmente con Docker Compose. El proceso completo tiene cuatro etapas, cada una se ejecuta por separado con su propio comando:

Primero, `prepare_data.py` descarga el CSV crudo del portal de datos de energía y genera un archivo Parquet con las features de ventana móvil (promedios, últimas lecturas, cantidad de registros por pozo). Este Parquet funciona como el offline store de Feast.

Después, se configura Feast con `feast apply` (que registra las entidades y feature views) y `feast materialize` (que copia las últimas features de cada pozo al online store, una base SQLite). Esto deja listo tanto el store histórico para entrenar como el store en tiempo real para predecir.

Luego, `train.py` entrena el modelo consumiendo features históricas del offline store. Loguea los parámetros, métricas y artefactos en MLflow, y registra el modelo en el model registry con el alias `production`.

Finalmente, se levanta la API (FastAPI + Uvicorn). Al arrancar, carga el modelo que tenga el alias `production` en MLflow. Cuando recibe un request de predicción, consulta el online store de Feast para obtener las features del pozo y genera el pronóstico.

Los tres primeros pasos corren en el contenedor `trainer`, que se invoca con el perfil `training` y solo se levanta cuando se lo llama explícitamente. MLflow corre como servicio permanente usando la imagen oficial `ghcr.io/mlflow/mlflow:v3.10.1` con SQLite y un named volume de Docker. La API corre como otro servicio permanente.

## Dataset

Se utiliza el dataset de Producción de Pozos de Gas y Petróleo No Convencional publicado por la Secretaría de Energía de Argentina: https://datos.energia.gob.ar/dataset/c846e79c-026c-4040-897f-1ad3543b407c/resource/b5b58cdc-9e07-41f9-b392-fb9ec68b0725/download/produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv

Los datos son de granularidad mensual: cada registro representa la producción de un pozo en un mes dado. El script `prepare_data.py` construye la fecha como el primer día de cada mes (`YYYY-MM-01`) a partir de los campos `anio` y `mes` del CSV original.

## Requisitos

- Docker y Docker Compose instalados.
- En Windows: WSL 2 + Docker Desktop con integración WSL habilitada.

## Setup y ejecución completa

### 1. Configuración inicial

```bash
cp .env.example .env
```

### 2. Levantar MLflow

```bash
docker-compose up mlflow -d
```

Verificar que MLflow esté corriendo en http://localhost:5000.

### 3. Preparar datos

Descarga el CSV crudo y genera el parquet con las features de ventana móvil (promedios de últimos 10 meses, última lectura, cantidad de lecturas):

```bash
docker-compose --profile training run --rm trainer python training/scripts/prepare_data.py
```

### 4. Configurar Feature Store

Registrar las entidades y feature views en Feast, y materializar las features al online store:

```bash
docker-compose --profile training run --rm trainer feast -c feature_store apply
docker-compose --profile training run --rm trainer feast -c feature_store materialize 2006-01-01 2007-12-31
```

### 5. Entrenar el modelo

El entrenamiento es reproducible: recibe una fecha de corte (`--date`) que determina hasta qué fecha se usan los datos. Esto permite reentrenar con distintos cortes temporales sin modificar código:

```bash
docker-compose --profile training run --rm trainer python -u training/train.py --date 2007-12-31
```

El modelo queda registrado en MLflow como `oil_gas_forecast` con el alias `production`.

### 6. Levantar la API

```bash
docker-compose up api -d
```

La API queda disponible en http://localhost:8000 y la documentación OpenAPI (Swagger) en http://localhost:8000/docs.

## Endpoints

### GET `/api/v1/wells`

Devuelve la lista de pozos con datos registrados en la fecha indicada. Como los datos de producción son mensuales y se almacenan con fecha del primer día de cada mes, `date_query` debe indicar el primer día del mes a consultar (formato `YYYY-MM-01`).

**Parámetros:**

| Parámetro    | Tipo   | Descripción                              |
|-------------|--------|------------------------------------------|
| `date_query` | date   | Primer día del mes a consultar (YYYY-MM-01) |

**Ejemplo:**

```bash
curl "http://localhost:8000/api/v1/wells?date_query=2007-06-01"
```

**Respuesta:**

```json
[
  {"id_well": "40537"},
  {"id_well": "40538"},
  {"id_well": "40539"}
]
```

### GET `/api/v1/forecast`

Devuelve el pronóstico de producción de gas para un pozo en un rango de fechas. El endpoint genera una entrada por cada día del rango solicitado. Dado que el modelo fue entrenado con datos mensuales y las features del online store son fijas por pozo (corresponden al último mes materializado), el valor de `prod` es el mismo para todos los días del rango. Este valor representa la producción mensual estimada de gas para ese pozo.

**Parámetros:**

| Parámetro    | Tipo   | Descripción                              |
|-------------|--------|------------------------------------------|
| `id_well`    | string | ID del pozo                              |
| `date_start` | date   | Inicio del rango (YYYY-MM-DD)            |
| `date_end`   | date   | Fin del rango (YYYY-MM-DD)               |

**Ejemplo:**

```bash
curl "http://localhost:8000/api/v1/forecast?id_well=40537&date_start=2008-01-01&date_end=2008-01-03"
```

**Respuesta:**

```json
{
  "id_well": "40537",
  "data": {
    "id_well": "40537",
    "data": [
      {"date": "2008-01-01", "prod": 1234.5},
      {"date": "2008-01-02", "prod": 1234.5},
      {"date": "2008-01-03", "prod": 1234.5}
    ]
  }
}
```

## Feature Store

El feature store usa Feast con provider local. El offline store es un archivo Parquet generado por `prepare_data.py` que contiene las features históricas de todos los pozos con sus timestamps. Se usa durante el entrenamiento para obtener features point-in-time correctas mediante `get_historical_features`. El online store es una base SQLite que se materializa con `feast materialize` y contiene la última lectura de features por pozo. Lo consume la API en tiempo de inferencia mediante `get_online_features`.

La generación de features a partir de los datos crudos queda persistida en el feature store, y tanto el entrenamiento como la inferencia consumen del mismo store, garantizando consistencia entre train y serve.

### Features generadas

| Feature            | Descripción                                           |
|-------------------|-------------------------------------------------------|
| `tipoextraccion`   | Tipo de extracción del pozo (categórico codificado)   |
| `avg_prod_gas_10m` | Promedio de producción de gas en los últimos 10 meses |
| `avg_prod_pet_10m` | Promedio de producción de petróleo en los últimos 10 meses |
| `last_prod_gas`    | Última producción de gas registrada                   |
| `last_prod_pet`    | Última producción de petróleo registrada              |
| `n_readings`       | Cantidad de lecturas históricas del pozo              |

## Tracking de experimentos

MLflow registra en cada entrenamiento:

- **Parámetros**: `n_estimators`, `random_state`, `n_jobs`
- **Métricas**: `rmse_gas`, `rmse_pet`, `r2_gas`, `r2_pet`
- **Tags**: `training_cutoff_date` (fecha de corte usada para el entrenamiento)
- **Artefactos**: modelo serializado (sklearn)
- **Model Registry**: el modelo se registra como `oil_gas_forecast` y se le asigna automáticamente el alias `production`, de modo que siempre se puede saber qué modelo está productivo

El entrenamiento es repetible con un solo comando para cualquier fecha de corte: `docker-compose --profile training run --rm trainer python -u training/train.py --date YYYY-MM-DD`. Cambiar la fecha cambia qué datos se incluyen en el entrenamiento, lo que permite reproducir y comparar entrenamientos.

Para acceder a la UI de MLflow: http://localhost:5000

## Modelo

Se usa un `MultiOutputRegressor` con `RandomForestRegressor` como estimador base. El modelo predice simultáneamente producción de gas (`prod_gas`) y petróleo (`prod_pet`) a partir de las 6 features del feature store. La API expone únicamente la predicción de gas en el campo `prod` de la respuesta, siguiendo la especificación OpenAPI del enunciado que define un solo campo de volumen producido.

## Decisiones de diseño y trade-offs

**Imagen oficial de MLflow.** Usamos `ghcr.io/mlflow/mlflow:v3.10.1` en lugar de una imagen custom con Dockerfile propio. Simplifica el mantenimiento y garantiza compatibilidad. Es suficiente porque usamos SQLite (incluido en la imagen).

**Perfil training en Docker Compose.** El contenedor de entrenamiento no se levanta con `docker-compose up`, solo cuando se invoca explícitamente con `--profile training`. Esto evita reentrenamientos accidentales y ahorra recursos.

**Fecha de corte como argumento del entrenamiento.** `train.py` recibe `--date` para determinar qué datos se incluyen. Esto permite reproducir entrenamientos con distintos puntos de corte temporal sin modificar código, cumpliendo el requerimiento de repetibilidad.

**Feature store compartido entre train y serve.** Las features se generan una vez con `prepare_data.py` y se persisten en Feast. Tanto el entrenamiento (offline store) como la inferencia (online store) consumen del mismo feature store, evitando el problema de training-serving skew.

## Limitaciones conocidas

**Predicción constante en el rango de fechas.** El modelo utiliza un RandomForestRegressor que no incorpora componentes autoregresivos ni tendencias temporales. Las features del online store son fijas por pozo (corresponden al último período materializado), por lo que al predecir un rango de fechas futuras, el valor de producción estimado es el mismo para todos los períodos. Un modelo con componentes temporales (como ARIMA o un modelo secuencial) podría capturar tendencias, pero el foco del trabajo está en el pipeline de ML Engineering, no en la sofisticación del modelo de predicción.

**Granularidad diaria sobre datos mensuales.** El endpoint de forecast genera una entrada por cada día del rango solicitado, pero el modelo fue entrenado con datos mensuales. Esto significa que todos los días dentro de un mismo mes muestran el mismo valor de producción, que corresponde a la estimación mensual. Esta decisión se tomó para cumplir con la especificación de la API que solicita una entrada por cada fecha entre `date_start` y `date_end`.

**Exposición de un solo target.** El modelo predice internamente dos variables (producción de gas y de petróleo), pero la API expone únicamente la producción de gas en el campo `prod`, de acuerdo con la especificación OpenAPI del enunciado que define un único campo de volumen producido.

## Cómo limpiar y empezar de cero

```bash
docker-compose down -v
docker-compose build --no-cache
```

El flag `-v` elimina los named volumes (los named volumes son espacios de almacenamiento que Docker gestiona internamente para persistir datos entre reinicios de contenedores). Esto borra los datos de MLflow y los modelos registrados.
