import urllib.request
import pandas as pd
import numpy as np
from sklearn.preprocessing import LabelEncoder
import os

DATA_DIR = "/app/feature_store/data"
CSV_PATH = DATA_DIR + "/dataset.csv"
PARQUET_PATH = DATA_DIR + "/well_features.parquet"

DATASET_DOWNLOAD_URL = "http://datos.energia.gob.ar/dataset/c846e79c-026c-4040-897f-1ad3543b407c/resource/b5b58cdc-9e07-41f9-b392-fb9ec68b0725/download/produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv"


def download_data():
    if os.path.exists(CSV_PATH):
        print("Dataset ya existe, saltando descarga.")
        return
    print("Descargando dataset...")
    os.makedirs(DATA_DIR, exist_ok=True)
    urllib.request.urlretrieve(DATASET_DOWNLOAD_URL, CSV_PATH)
    print("Descarga completada.")


def prepare_offline_store():
    print("Preparando features históricas para el offline store...")
    df = pd.read_csv(CSV_PATH)
    df['fecha'] = pd.to_datetime(
        df['anio'].astype(str) + '-' + df['mes'].astype(str).str.zfill(2) + '-01'
    )

    columns = ['idpozo', 'fecha', 'prod_pet', 'prod_gas', 'tipoextraccion']
    df = df[columns].dropna()

    le = LabelEncoder()
    df['tipoextraccion'] = le.fit_transform(df['tipoextraccion'])

    df = df.sort_values(['idpozo', 'fecha']).reset_index(drop=True)

    print("Calculando features de ventana...")
    df['avg_prod_gas_10m'] = (
        df.groupby('idpozo')['prod_gas']
        .transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean())
    )
    df['avg_prod_pet_10m'] = (
        df.groupby('idpozo')['prod_pet']
        .transform(lambda x: x.shift(1).rolling(10, min_periods=1).mean())
    )
    df['last_prod_gas'] = df.groupby('idpozo')['prod_gas'].shift(1)
    df['last_prod_pet'] = df.groupby('idpozo')['prod_pet'].shift(1)
    df['n_readings'] = df.groupby('idpozo').cumcount().astype('int32')

    hist_df = df.dropna(subset=['last_prod_gas', 'last_prod_pet']).copy()
    print(f"Filas históricas: {len(hist_df)}")

    print("Generando filas futuras para el online store...")
    online_rows = []
    for well_id, group in df.groupby('idpozo'):
        tail_window = group.tail(10)
        online_rec = group.iloc[-1].to_dict()
        online_rec['fecha'] = online_rec['fecha'] + pd.DateOffset(months=1)
        online_rec['prod_gas'] = None
        online_rec['prod_pet'] = None
        online_rec['avg_prod_gas_10m'] = float(tail_window['prod_gas'].mean())
        online_rec['avg_prod_pet_10m'] = float(tail_window['prod_pet'].mean())
        online_rec['last_prod_gas'] = float(tail_window['prod_gas'].iloc[-1])
        online_rec['last_prod_pet'] = float(tail_window['prod_pet'].iloc[-1])
        online_rec['n_readings'] = int(len(tail_window))
        online_rows.append(online_rec)

    online_df = pd.DataFrame(online_rows)
    print(f"Filas futuras (online store): {len(online_df)}")

    feat_df = pd.concat([hist_df, online_df], ignore_index=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    feat_df.to_parquet(PARQUET_PATH, index=False)
    print(f"Parquet guardado en {PARQUET_PATH} con {len(feat_df)} filas totales.")


if __name__ == "__main__":
    download_data()
    prepare_offline_store()
