from fastapi import FastAPI
from routes.forecast import router as forecast_router
from routes.wells import router as wells_router

app = FastAPI(
    title="Oil & Gas Forecast API",
    version="1.0.0"
)

app.include_router(forecast_router, prefix="/api/v1")
app.include_router(wells_router, prefix="/api/v1")