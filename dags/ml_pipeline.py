from airflow.decorators import dag, task
from airflow.operators.empty import EmptyOperator
from datetime import datetime

# IMPORTÁS TU CÓDIGO EXISTENTE
from training.scripts.prepare_data import download_data, prepare_offline_store
from training.scripts.populate_online import populate_online_store
from training.train import train

from feast import FeatureStore

FEATURE_STORE_REPO = "/app/feature_store"


@dag(
    dag_id="ml_pipeline",
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False,
)
def ml_pipeline():

    start = EmptyOperator(task_id="start")

    @task
    def prepare_data_task():
        download_data()
        prepare_offline_store()

    @task
    def feast_apply_task():
        store = FeatureStore(repo_path=FEATURE_STORE_REPO)
        store.apply()

    @task
    def materialize_task():
        store = FeatureStore(repo_path=FEATURE_STORE_REPO)
        store.materialize(
            start_date=datetime(2006, 1, 1),
            end_date=datetime(2007, 12, 31),
        )

    @task
    def train_task():
        train("2007-12-31")

    @task
    def populate_online_task():
        populate_online_store()

    # ORQUESTACIÓN
    start >> prepare_data_task() >> feast_apply_task() >> materialize_task() >> train_task() >> populate_online_task()


ml_pipeline()