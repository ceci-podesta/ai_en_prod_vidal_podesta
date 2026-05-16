limpiar antes de correr:


cp .env.example .env




docker compose restart

docker-compose down -v


docker-compose build --no-cache


docker-compose up mlflow -d


docker-compose --profile training run --rm trainer python training/scripts/prepare_data.py


docker-compose --profile training run --rm trainer feast -c feature_store apply


docker-compose --profile training run --rm trainer feast -c feature_store materialize 2006-01-01 2007-12-31


docker-compose --profile training run --rm trainer python -u training/train.py --date 2007-12-31


docker-compose up api -d



#################################################################

creo las carpetas que son obligatorias para airflow
mkdir -p ./dags ./logs ./plugins ./config


http://127.0.0.1:8080/home
http://127.0.0.1:8080
si no: http://localhost:8080/home

usuario y contraseña: admin