from datetime import timedelta
from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, Int32

# ── Entidad ──
pozo = Entity(
    name="idpozo",
    description="Identificador único del pozo de extracción",
)

# ── Fuente de datos (offline store) ──
well_stats_source = FileSource(
    path="/app/feature_store/data/well_features.parquet",
    timestamp_field="fecha",
)

# ── Feature View ──
well_stats = FeatureView(
    name="well_stats",
    entities=[pozo],
    schema=[
        Field(name="prod_gas",         dtype=Float32),
        Field(name="prod_pet",         dtype=Float32),
        Field(name="tipoextraccion",   dtype=Int32),
        Field(name="avg_prod_gas_10m", dtype=Float32),
        Field(name="avg_prod_pet_10m", dtype=Float32),
        Field(name="last_prod_gas",    dtype=Float32),
        Field(name="last_prod_pet",    dtype=Float32),
        Field(name="n_readings",       dtype=Int32),
    ],
    source=well_stats_source,
)
