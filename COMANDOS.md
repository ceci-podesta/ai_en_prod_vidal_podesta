mkdir -p logs plugins

docker compose build

docker compose up -d

docker compose ps -a

docker compose restart api
