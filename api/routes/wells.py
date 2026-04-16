from fastapi import APIRouter, HTTPException
from datetime import date
import pandas as pd

router = APIRouter()

PARQUET_PATH = "/app/feature_store/data/well_features.parquet"


@router.get("/wells")
def wells(date_query: date):
    try:
        # Leer datos
        df = pd.read_parquet(PARQUET_PATH)

        # Asegurar formato fecha
        df["fecha"] = pd.to_datetime(df["fecha"])

        # Filtrar por fecha (convertimos date → datetime)
        df_filtered = df[df["fecha"] == pd.to_datetime(date_query)]

        if df_filtered.empty:
            return []

        # Obtener pozos únicos
        wells = df_filtered["idpozo"].dropna().unique()

        return [{"id_well": str(w)} for w in wells]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))