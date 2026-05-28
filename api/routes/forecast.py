from datetime import date


from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


from services.forecast_service import get_forecast




router = APIRouter()


class ForecastPoint(BaseModel):
    date: date
    prod: float


class ForecastResponse(BaseModel):
    id_well: str
    data: list[ForecastPoint]


@router.get("/forecast", response_model=ForecastResponse)
def forecast(id_well: str, date_start: date, date_end: date):
    if date_start > date_end:
        raise HTTPException(status_code=400, detail="date_start must be <= date_end")


    return {
        "id_well": id_well,
        "data": get_forecast(id_well, date_start, date_end),
    }
