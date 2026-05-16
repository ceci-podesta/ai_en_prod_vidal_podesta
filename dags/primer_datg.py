from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

def saludo():
    print("Hola 👋 Airflow está funcionando")

with DAG(
    dag_id="primer_dag",
    start_date=datetime(2024, 1, 1),
    schedule=None,
    catchup=False,
) as dag:

    tarea = PythonOperator(
        task_id="saludo_task",
        python_callable=saludo
    )