from fastapi import APIRouter, HTTPException
from datetime import date
from services.forecast_service import get_forecast

router = APIRouter()

@router.get("/forecast")
def forecast(id_well: str, date_start: date, date_end: date):

    if date_start > date_end:
        raise HTTPException(status_code=400, detail="date_start must be <= date_end")

    data = get_forecast(id_well, date_start, date_end)

    return {
        "id_well": id_well,
        "data": data
    }