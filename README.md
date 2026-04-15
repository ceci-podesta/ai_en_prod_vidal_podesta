# Oil & Gas Forecast — IA en Producción

Pipeline de pronóstico de producción de hidrocarburos no convencionales.

## Integrantes
- Cecilia Podesta
- Sol Vidal

## Arquitectura

El sistema está compuesto por los siguientes servicios:

- **PostgreSQL**: backend store de MLflow.
- **MLflow**: tracking de experimentos y model registry.
- **API**: servicio FastAPI que expone los endpoints de forecast.
- **Trainer**: contenedor para ejecutar el entrenamiento del modelo.

## Requisitos

- Docker y Docker Compose instalados.

## Configuración

1. Copiar el archivo de variables de entorno:
   ```bash
   cp .env.example .env
   ```
2. Completar los valores en `.env` según el entorno.

## Levantar el sistema

```bash
docker-compose up --build
```

Los servicios quedan disponibles en:
- API: http://localhost:8000
- MLflow UI: http://localhost:5000
- Documentación OpenAPI: http://localhost:8000/docs

## Entrenar el modelo

```bash
docker-compose --profile training run trainer python train.py --date YYYY-MM-DD
```

## Endpoints disponibles

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/forecast` | Pronóstico de producción de un pozo |
| GET | `/api/v1/wells` | Listado de pozos |

Ver documentación completa en `/docs` con el sistema levantado.

## Feature Store

<!-- TODO (PR2): documentar cómo se genera y populan los features -->

## Tracking de experimentos

<!-- TODO (PR3): documentar cómo acceder a MLflow y reproducir un entrenamiento -->



limpiar antes de correr: docker-compose down mlflow -v 

cp .env.example .env

docker-compose up mlflow -d

docker-compose --profile training run --rm -v $(pwd)/scripts:/app/scripts trainer python /app/scripts/prepare_data.py



docker-compose --profile training run --rm trainer feast -c /app/feature_store apply

cd /mnt/c/Users/Maria/Documents/MIA_UDESA_VIDAL/IA_produccion/ai_en_prod_vidal_podesta


docker-compose down -v
docker-compose build --no-cache
docker-compose up mlflow -d
docker-compose --profile training run --rm trainer python training/scripts/prepare_data.py
docker-compose --profile training run --rm trainer feast -c feature_store apply

docker-compose --profile training run --rm trainer python -u training/train.py --date 2024-01-31