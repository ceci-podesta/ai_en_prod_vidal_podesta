from datetime import date


import mlflow.pyfunc
import pandas as pd
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




def monthly_dates(start: date, end: date):
    """Devuelve el primer dia de cada mes incluido en el rango solicitado."""
    months = pd.period_range(start=start, end=end, freq="M")
    return months.to_timestamp()




def get_forecast(id_well: str, start: date, end: date):
    results = []


    for d in monthly_dates(start, end):
        entity_row = [
            {
                "idpozo": int(id_well),
                "event_timestamp": d,
            }
        ]


        features = store.get_online_features(
            features=[f"well_stats:{feature}" for feature in FEATURES],
            entity_rows=entity_row,
        ).to_df()


        X = features[FEATURES]
        pred = model.predict(X)[0]


        # TARGETS en training/train.py es ["prod_gas", "prod_pet"].
        # Este endpoint mantiene el contrato original de devolver gas como "prod".
        results.append(
            {
                "date": d.date().isoformat(),
                "prod": float(pred[0]) if len(pred) > 1 else float(pred),
            }
        )


    return results
