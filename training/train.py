import argparse
import os
import pandas as pd
from feast import FeatureStore
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.multioutput import MultiOutputRegressor
import numpy as np
import mlflow
import mlflow.sklearn

FEATURE_STORE_REPO = "/app/feature_store"
PARQUET_PATH = FEATURE_STORE_REPO + "/data/well_features.parquet"
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
MODEL_NAME = "oil_gas_forecast"

FEATURES = [
    "tipoextraccion", "avg_prod_gas_10m",
    "avg_prod_pet_10m", "last_prod_gas",
    "last_prod_pet", "n_readings",
]
TARGETS = ["prod_gas", "prod_pet"]
MAX_TRAINING_ROWS = 100_000


def train(training_date: str):
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("oil_gas_forecast")

    print(f"Iniciando entrenamiento con fecha de corte: {training_date}...")

    store = FeatureStore(repo_path=FEATURE_STORE_REPO)

    print("Leyendo llaves de entidades desde el parquet...")
    raw_df = pd.read_parquet(PARQUET_PATH)

    # Filtrar hasta la fecha de corte indicada
    raw_df["fecha"] = pd.to_datetime(raw_df["fecha"])
    cutoff = pd.to_datetime(training_date)
    raw_df = raw_df[raw_df["fecha"] <= cutoff]

    # Limitar filas para controlar uso de memoria en el join de feast
    if len(raw_df) > MAX_TRAINING_ROWS:
        raw_df = raw_df.sample(n=MAX_TRAINING_ROWS, random_state=42)
        print(f"Dataset sampleado a {MAX_TRAINING_ROWS} filas.")



    print("Raw DF shape:", raw_df.shape)

    entity_df = raw_df[["idpozo", "fecha", "prod_gas", "prod_pet"]].copy()
    entity_df = entity_df.rename(columns={"fecha": "event_timestamp"})

    feast_features = [f"well_stats:{f}" for f in FEATURES]

    print("Obteniendo features históricas desde el Feature Store...")
    training_df = store.get_historical_features(
        entity_df=entity_df,
        features=feast_features,
    ).to_df()

    print("Training DF shape:", training_df.shape)
    print(training_df.head())

    training_df.columns = [c.split("__")[-1] for c in training_df.columns]

    training_df = training_df.dropna(subset=TARGETS)

    training_df = training_df.sort_values("event_timestamp")


    X = training_df[FEATURES]
    y = training_df[TARGETS]

    print(f"Dataset de entrenamiento: {len(X)} muestras.")

    with mlflow.start_run():

        mlflow.set_tag("training_cutoff_date", training_date)

        params = {"n_estimators": 100, "random_state": 42, "n_jobs": -1}
        mlflow.log_params({**params, "max_training_rows": MAX_TRAINING_ROWS})

        base_model = RandomForestRegressor(**params)
        model = MultiOutputRegressor(base_model)
        model.fit(X, y)

        y_pred = model.predict(X)
        r2_gas = r2_score(y["prod_gas"], y_pred[:, 0])
        r2_pet = r2_score(y["prod_pet"], y_pred[:, 1])
        rmse_gas = np.sqrt(mean_squared_error(y["prod_gas"], y_pred[:, 0]))
        rmse_pet = np.sqrt(mean_squared_error(y["prod_pet"], y_pred[:, 1]))

        mlflow.log_metric("r2_prod_gas", r2_gas)
        mlflow.log_metric("r2_prod_pet", r2_pet)
        mlflow.log_metric("rmse_prod_gas", rmse_gas)
        mlflow.log_metric("rmse_prod_pet", rmse_pet)
        mlflow.log_metric("n_samples", len(X))

        print(f"prod_gas  → R2: {r2_gas:.4f} | RMSE: {rmse_gas:.2f}")
        print(f"prod_pet  → R2: {r2_pet:.4f} | RMSE: {rmse_pet:.2f}")

        # Guardamos el modelo como artefacto del run (API clásica) y lo registramos
        # por separado para evitar el code path de "Logged Models" de MLflow 3.x
        # que escribe a /mlflow (inaccesible desde el worker de Airflow).
        import tempfile, os as _os
        with tempfile.TemporaryDirectory() as tmp_dir:
            model_dir = _os.path.join(tmp_dir, "model")
            mlflow.sklearn.save_model(model, model_dir)
            mlflow.log_artifacts(model_dir, artifact_path="model")

        run_id = mlflow.active_run().info.run_id
        model_uri = f"runs:/{run_id}/model"

        client = mlflow.tracking.MlflowClient()
        mv = mlflow.register_model(model_uri, MODEL_NAME)
        client.set_registered_model_alias(MODEL_NAME, "production", mv.version)

        print(f"Modelo registrado en MLflow como '{MODEL_NAME}' con alias 'production'.")
        print(f"Versión: {mv.version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Entrenar modelo de forecast de producción.")
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="Fecha de corte para el entrenamiento (YYYY-MM-DD). Solo usa datos hasta esa fecha.",
    )
    args = parser.parse_args()
    train(args.date)