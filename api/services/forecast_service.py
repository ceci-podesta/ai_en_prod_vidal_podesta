from datetime import date
import pandas as pd
import mlflow.pyfunc
from feast import FeatureStore

MODEL_NAME = "oil_gas_forecast"

model = mlflow.pyfunc.load_model(f"models:/{MODEL_NAME}@production")

store = FeatureStore(repo_path="feature_store")

FEATURES = [
    "tipoextraccion",
    "avg_prod_gas_10m",
    "avg_prod_pet_10m",
    "last_prod_gas",
    "last_prod_pet",
    "n_readings",
]


def get_forecast(id_well: str, start: date, end: date):

    dates = pd.date_range(start=start, end=end)

    results = []

    for d in dates:
        entity_row = [{
            "idpozo": int(id_well),
            "event_timestamp": d,
        }]

        features = store.get_online_features(
            features=[f"well_stats:{f}" for f in FEATURES],
            entity_rows=entity_row,
        ).to_df()

        X = features[FEATURES]

        pred = model.predict(X)[0]

        results.append({
            "date": d.date().isoformat(),
            "prod": float(pred[0]) if len(pred) > 1 else float(pred),
        })

    return {
        "id_well": id_well,
        "data": results
    }