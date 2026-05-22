from airflow.decorators import dag, task
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import get_current_context
from datetime import datetime

from training.scripts.prepare_data import download_data, prepare_offline_store
from training.scripts.populate_online import populate_online_store
from training.train import train

from feast import FeatureStore

FEATURE_STORE_REPO = "/app/feature_store"
DATASET_START = datetime(2006, 1, 1)


@dag(
    dag_id="ml_pipeline",
    start_date=datetime(2024, 1, 1),
    schedule_interval="@monthly",
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
        import sys
        sys.path.insert(0, FEATURE_STORE_REPO)
        from features import pozo, well_stats
        store = FeatureStore(repo_path=FEATURE_STORE_REPO)
        store.apply([pozo, well_stats])

    @task
    def materialize_task():
        context = get_current_context()
        end_date = context["data_interval_end"].replace(tzinfo=None)
        store = FeatureStore(repo_path=FEATURE_STORE_REPO)
        store.materialize(
            start_date=DATASET_START,
            end_date=end_date,
        )

    @task
    def train_task():
        context = get_current_context()
        cutoff = context["data_interval_end"].strftime("%Y-%m-%d")
        train(cutoff)

    @task
    def populate_online_task():
        populate_online_store()

    start >> prepare_data_task() >> feast_apply_task() >> materialize_task() >> train_task() >> populate_online_task()


ml_pipeline()
