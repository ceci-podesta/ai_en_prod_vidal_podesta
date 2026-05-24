from datetime import datetime


from airflow.decorators import dag, task
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import get_current_context
from feast import FeatureStore


from training.scripts.monitoring_report import generate_monitoring_report
from training.scripts.populate_online import populate_online_store
from training.scripts.prepare_data import download_data, prepare_offline_store
from training.train import train




FEATURE_STORE_REPO = "/app/feature_store"
DATASET_START = datetime(2006, 1, 1)




@dag(
    dag_id="ml_pipeline",
    start_date=datetime(2024, 1, 1),
    schedule="@monthly",
    catchup=False,
)
def ml_pipeline():
    start = EmptyOperator(task_id="start")


    @task
    def resolve_run_config_task():
        context = get_current_context()
        dag_conf = context["dag_run"].conf or {}


        training_cutoff = dag_conf.get(
            "training_cutoff",
            context["data_interval_end"].strftime("%Y-%m-%d"),
        )


        return {
            "training_cutoff": training_cutoff,
            "monitoring_months": int(dag_conf.get("monitoring_months", 6)),
            "baseline_months": int(dag_conf.get("baseline_months", 18)),
        }


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
    def train_task(run_config: dict):
        train(run_config["training_cutoff"])


    @task
    def monitoring_report_task(run_config: dict):
        return generate_monitoring_report(
            training_cutoff=run_config["training_cutoff"],
            monitoring_months=run_config["monitoring_months"],
            baseline_months=run_config["baseline_months"],
        )


    @task
    def populate_online_task():
        populate_online_store()


    run_config = resolve_run_config_task()
    prepared = prepare_data_task()
    applied = feast_apply_task()
    materialized = materialize_task()
    trained = train_task(run_config)
    monitored = monitoring_report_task(run_config)
    populated = populate_online_task()


    start >> run_config >> prepared >> applied >> materialized >> trained >> monitored >> populated




ml_pipeline()
