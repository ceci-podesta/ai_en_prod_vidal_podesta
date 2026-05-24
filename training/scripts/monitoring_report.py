import argparse
import math
import os
from pathlib import Path


import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score




FEATURE_STORE_REPO = "/app/feature_store"
PARQUET_PATH = f"{FEATURE_STORE_REPO}/data/well_features.parquet"
REPORTS_DIR = "/app/reports/model_monitoring"
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
MODEL_NAME = "oil_gas_forecast"


CATEGORICAL_FEATURES = ["tipoextraccion"]
NUMERIC_PSI_FEATURES = [
    "avg_prod_gas_10m",
    "avg_prod_pet_10m",
    "last_prod_gas",
    "last_prod_pet",
    "n_readings",
]
CONTINUOUS_KS_FEATURES = [
    "avg_prod_gas_10m",
    "avg_prod_pet_10m",
    "last_prod_gas",
    "last_prod_pet",
]


FEATURES = CATEGORICAL_FEATURES + NUMERIC_PSI_FEATURES
TARGETS = ["prod_gas", "prod_pet"]




def clean_metric(value):
    if value is None:
        return None
    if isinstance(value, (float, np.floating)) and (math.isnan(value) or math.isinf(value)):
        return None
    return float(value)




def round_df(df: pd.DataFrame) -> pd.DataFrame:
    rounded = df.copy()
    for col in rounded.columns:
        if pd.api.types.is_float_dtype(rounded[col]):
            if "share" in col or "psi" in col or "ks" in col or "r2" in col:
                rounded[col] = rounded[col].round(4)
            elif "pct" in col:
                rounded[col] = rounded[col].round(2)
            else:
                rounded[col] = rounded[col].round(2)
    return rounded




def save_csv(df: pd.DataFrame, path: Path) -> Path:
    round_df(df).to_csv(path, index=False)
    return path




def psi_label(value) -> str:
    if value is None or pd.isna(value):
        return "not_available"
    if value < 0.1:
        return "no_significant_drift"
    if value < 0.25:
        return "moderate_drift"
    return "strong_drift"




def category_label(value) -> str:
    if pd.isna(value):
        return "__missing__"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value)




def tipoextraccion_mapping() -> dict:
    dataset_path = Path(FEATURE_STORE_REPO) / "data" / "dataset.csv"
    if not dataset_path.exists():
        return {}


    raw = pd.read_csv(dataset_path, usecols=["tipoextraccion"])
    classes = sorted(raw["tipoextraccion"].dropna().astype(str).unique())
    return {str(idx): label for idx, label in enumerate(classes)}




def ks_statistic(expected: pd.Series, actual: pd.Series) -> float:
    expected_values = pd.Series(expected).dropna().astype(float).to_numpy()
    actual_values = pd.Series(actual).dropna().astype(float).to_numpy()


    if len(expected_values) == 0 or len(actual_values) == 0:
        return float("nan")


    expected_sorted = np.sort(expected_values)
    actual_sorted = np.sort(actual_values)
    values = np.sort(np.concatenate([expected_sorted, actual_sorted]))


    expected_cdf = np.searchsorted(expected_sorted, values, side="right") / len(expected_sorted)
    actual_cdf = np.searchsorted(actual_sorted, values, side="right") / len(actual_sorted)


    return float(np.max(np.abs(expected_cdf - actual_cdf)))




def numeric_psi(expected: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    expected_values = pd.Series(expected).dropna().astype(float).to_numpy()
    actual_values = pd.Series(actual).dropna().astype(float).to_numpy()


    if len(expected_values) == 0 or len(actual_values) == 0:
        return float("nan")


    edges = np.unique(np.quantile(expected_values, np.linspace(0, 1, bins + 1)))


    if len(edges) < 3:
        min_value = min(expected_values.min(), actual_values.min())
        max_value = max(expected_values.max(), actual_values.max())
        if min_value == max_value:
            return 0.0
        edges = np.linspace(min_value, max_value, bins + 1)


    edges[0] = -np.inf
    edges[-1] = np.inf


    expected_counts, _ = np.histogram(expected_values, bins=edges)
    actual_counts, _ = np.histogram(actual_values, bins=edges)


    expected_pct = np.clip(expected_counts / max(expected_counts.sum(), 1), 1e-6, None)
    actual_pct = np.clip(actual_counts / max(actual_counts.sum(), 1), 1e-6, None)


    return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))




def categorical_psi(expected: pd.Series, actual: pd.Series) -> float:
    expected_labels = pd.Series(expected).map(category_label)
    actual_labels = pd.Series(actual).map(category_label)


    expected_counts = expected_labels.value_counts()
    actual_counts = actual_labels.value_counts()
    categories = sorted(set(expected_counts.index).union(set(actual_counts.index)))


    expected_total = max(expected_counts.sum(), 1)
    actual_total = max(actual_counts.sum(), 1)


    expected_pct = np.array(
        [expected_counts.get(category, 0) / expected_total for category in categories],
        dtype=float,
    )
    actual_pct = np.array(
        [actual_counts.get(category, 0) / actual_total for category in categories],
        dtype=float,
    )


    expected_pct = np.clip(expected_pct, 1e-6, None)
    actual_pct = np.clip(actual_pct, 1e-6, None)


    return float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))




def categorical_comparison(baseline_df: pd.DataFrame, monitoring_df: pd.DataFrame, feature: str) -> pd.DataFrame:
    baseline_counts = baseline_df[feature].map(category_label).value_counts()
    monitoring_counts = monitoring_df[feature].map(category_label).value_counts()
    categories = sorted(set(baseline_counts.index).union(set(monitoring_counts.index)))


    baseline_total = max(baseline_counts.sum(), 1)
    monitoring_total = max(monitoring_counts.sum(), 1)


    rows = []
    for category in categories:
        baseline_count = int(baseline_counts.get(category, 0))
        monitoring_count = int(monitoring_counts.get(category, 0))
        baseline_share = baseline_count / baseline_total
        monitoring_share = monitoring_count / monitoring_total


        rows.append(
            {
                feature: category,
                "baseline_count_rows": baseline_count,
                "monitoring_count_rows": monitoring_count,
                "baseline_share_rows": baseline_share,
                "monitoring_share_rows": monitoring_share,
                "share_delta": monitoring_share - baseline_share,
            }
        )


    return pd.DataFrame(rows)




def evaluate_regression(y_true: pd.DataFrame, y_pred: np.ndarray, window: str) -> pd.DataFrame:
    y_pred = np.asarray(y_pred)
    if y_pred.ndim == 1:
        y_pred = y_pred.reshape(-1, 1)


    rows = []


    for idx, target in enumerate(TARGETS):
        true_values = y_true[target].to_numpy()
        pred_values = y_pred[:, idx]
        residuals = true_values - pred_values
        r2 = r2_score(true_values, pred_values) if len(true_values) > 1 else float("nan")


        rows.append(
            {
                "window": window,
                "target": target,
                "n_rows": int(len(true_values)),
                "rmse": float(math.sqrt(mean_squared_error(true_values, pred_values))),
                "mae": float(mean_absolute_error(true_values, pred_values)),
                "r2": float(r2),
                "residual_mean": float(np.mean(residuals)),
                "residual_std": float(np.std(residuals, ddof=0)),
            }
        )


    return pd.DataFrame(rows)




def performance_comparison(performance_df: pd.DataFrame) -> pd.DataFrame:
    rows = []


    for target in TARGETS:
        baseline = performance_df[
            (performance_df["window"] == "baseline")
            & (performance_df["target"] == target)
        ].iloc[0]


        monitoring = performance_df[
            (performance_df["window"] == "monitoring")
            & (performance_df["target"] == target)
        ].iloc[0]


        for metric in ["rmse", "mae", "r2"]:
            baseline_value = float(baseline[metric])
            monitoring_value = float(monitoring[metric])
            delta = monitoring_value - baseline_value
            delta_pct = (delta / baseline_value * 100) if baseline_value != 0 else float("nan")


            rows.append(
                {
                    "target": target,
                    "metric": metric,
                    "baseline": baseline_value,
                    "monitoring": monitoring_value,
                    "delta": delta,
                    "delta_pct": delta_pct,
                    "direction": "higher_is_worse" if metric in ["rmse", "mae"] else "lower_is_worse",
                }
            )


    return pd.DataFrame(rows)




def concept_drift_comparison(performance_df: pd.DataFrame) -> pd.DataFrame:
    rows = []


    for target in TARGETS:
        baseline = performance_df[
            (performance_df["window"] == "baseline")
            & (performance_df["target"] == target)
        ].iloc[0]


        monitoring = performance_df[
            (performance_df["window"] == "monitoring")
            & (performance_df["target"] == target)
        ].iloc[0]


        for metric in ["residual_mean", "residual_std"]:
            baseline_value = float(baseline[metric])
            monitoring_value = float(monitoring[metric])
            delta = monitoring_value - baseline_value


            rows.append(
                {
                    "target": target,
                    "metric": metric,
                    "baseline": baseline_value,
                    "monitoring": monitoring_value,
                    "delta": delta,
                    "interpretation": (
                        "positive_mean_means_model_underestimates"
                        if metric == "residual_mean"
                        else "positive_delta_means_more_error_dispersion"
                    ),
                }
            )


    return pd.DataFrame(rows)




def build_windows(
    df: pd.DataFrame,
    training_cutoff: str,
    monitoring_months: int,
    baseline_months: int,
):
    training_cutoff_ts = pd.to_datetime(training_cutoff)
    monitoring_end_requested = training_cutoff_ts + pd.DateOffset(months=monitoring_months)
    available_end = df["fecha"].max()
    monitoring_end_effective = min(monitoring_end_requested, available_end)
    baseline_start = training_cutoff_ts - pd.DateOffset(months=baseline_months)


    baseline_df = df[
        (df["fecha"] >= baseline_start)
        & (df["fecha"] <= training_cutoff_ts)
    ].copy()


    monitoring_df = df[
        (df["fecha"] > training_cutoff_ts)
        & (df["fecha"] <= monitoring_end_effective)
    ].copy()


    available_monitoring_months = (
        monitoring_df["fecha"].dt.to_period("M").nunique()
        if not monitoring_df.empty
        else 0
    )


    return {
        "training_cutoff": training_cutoff_ts,
        "monitoring_months_requested": monitoring_months,
        "monitoring_end_requested": monitoring_end_requested,
        "monitoring_end_effective": monitoring_end_effective,
        "available_end": available_end,
        "available_monitoring_months": int(available_monitoring_months),
        "baseline_start": baseline_start,
        "baseline_df": baseline_df,
        "monitoring_df": monitoring_df,
    }




def add_metric(summary_rows: list, logged_metrics: dict, section: str, metric: str, value):
    safe_value = clean_metric(value)
    summary_rows.append({"section": section, "metric": metric, "value": safe_value})
    if safe_value is not None:
        logged_metrics[metric] = safe_value




def label_bars(ax, decimals: int = 2):
    for container in ax.containers:
        labels = []
        for value in container.datavalues:
            labels.append(f"{value:.{decimals}f}")
        ax.bar_label(container, labels=labels, padding=3, fontsize=8)




def plot_model_decay(comparison_df: pd.DataFrame, path: Path):
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), constrained_layout=True)


    for ax, metric in zip(axes, ["rmse", "mae", "r2"]):
        data = comparison_df[comparison_df["metric"] == metric]
        ax.bar(data["target"], data["delta"], color="#0EA5E9")
        ax.axhline(0, color="#101828", linewidth=1)
        ax.set_title(f"{metric.upper()} delta")
        ax.set_ylabel("Monitoring - baseline")
        ax.grid(axis="y", color="#EAECF0")
        ax.grid(axis="x", visible=False)
        label_bars(ax, 2 if metric != "r2" else 4)


    fig.suptitle("Model decay deltas", fontsize=15, fontweight="bold")
    fig.savefig(path, dpi=160)
    plt.close(fig)




def plot_numeric_drift(numeric_drift_df: pd.DataFrame, path: Path):
    data = numeric_drift_df.sort_values("psi", ascending=True)


    fig, ax = plt.subplots(figsize=(10, 4.8), constrained_layout=True)
    ax.barh(data["feature"], data["psi"], color="#0EA5E9")
    ax.axvline(0.10, color="#F59E0B", linestyle="--", linewidth=1.3, label="PSI 0.10")
    ax.axvline(0.25, color="#94A3B8", linestyle="--", linewidth=1.3, label="PSI 0.25")
    ax.set_title("Data drift: numeric features")
    ax.set_xlabel("PSI")
    ax.grid(axis="x", color="#EAECF0")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")
    label_bars(ax, 4)


    fig.savefig(path, dpi=160)
    plt.close(fig)




def plot_ks_drift(numeric_drift_df: pd.DataFrame, path: Path):
    data = numeric_drift_df.dropna(subset=["ks"]).sort_values("ks", ascending=True)


    fig, ax = plt.subplots(figsize=(10, 4.8), constrained_layout=True)
    ax.barh(data["feature"], data["ks"], color="#0EA5E9")
    ax.set_title("Data drift: continuous features")
    ax.set_xlabel("KS statistic")
    ax.grid(axis="x", color="#EAECF0")
    ax.grid(axis="y", visible=False)
    label_bars(ax, 4)


    fig.savefig(path, dpi=160)
    plt.close(fig)




def plot_concept_drift(concept_df: pd.DataFrame, path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4), constrained_layout=True)


    for ax, metric, title in [
        (axes[0], "residual_mean", "Residual mean delta"),
        (axes[1], "residual_std", "Residual standard deviation delta"),
    ]:
        data = concept_df[concept_df["metric"] == metric]
        ax.bar(data["target"], data["delta"], color="#0EA5E9")
        ax.axhline(0, color="#101828", linewidth=1)
        ax.set_title(title)
        ax.set_ylabel("Monitoring - baseline")
        ax.grid(axis="y", color="#EAECF0")
        ax.grid(axis="x", visible=False)
        label_bars(ax, 2)


    fig.suptitle("Concept drift: residual changes", fontsize=15, fontweight="bold")
    fig.savefig(path, dpi=160)
    plt.close(fig)




def plot_categorical_distribution(categorical_df: pd.DataFrame, path: Path):
    label_col = "tipoextraccion_label" if "tipoextraccion_label" in categorical_df.columns else "tipoextraccion"
    data = categorical_df.sort_values("baseline_share_rows", ascending=True)
    y = np.arange(len(data))
    height = 0.36


    fig, ax = plt.subplots(figsize=(11, 5.8), constrained_layout=True)
    ax.barh(y - height / 2, data["baseline_share_rows"], height, label="Baseline", color="#3B82F6")
    ax.barh(y + height / 2, data["monitoring_share_rows"], height, label="Monitoring", color="#F97316")
    ax.set_yticks(y)
    ax.set_yticklabels(data[label_col])
    ax.set_xlabel("Share of pozo-month observations")
    ax.set_title("Data drift: tipoextraccion")
    ax.grid(axis="x", color="#EAECF0")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")


    fig.savefig(path, dpi=160)
    plt.close(fig)




def log_to_mlflow(
    status: str,
    warnings: list[str],
    windows: dict,
    baseline_months: int,
    min_rows_warning: int,
    artifact_paths: list[Path],
    logged_metrics: dict,
):
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment("oil_gas_monitoring")


    run_name = (
        f"monitoring_{windows['training_cutoff'].date().isoformat()}"
        f"_to_{windows['monitoring_end_effective'].date().isoformat()}"
    )


    with mlflow.start_run(run_name=run_name):
        mlflow.log_param("status", status)
        mlflow.log_param("training_cutoff", windows["training_cutoff"].date().isoformat())
        mlflow.log_param("baseline_months", baseline_months)
        mlflow.log_param("monitoring_months_requested", windows["monitoring_months_requested"])
        mlflow.log_param("monitoring_end_requested", windows["monitoring_end_requested"].date().isoformat())
        mlflow.log_param("monitoring_end_effective", windows["monitoring_end_effective"].date().isoformat())
        mlflow.log_param("available_data_end", windows["available_end"].date().isoformat())
        mlflow.log_param("available_monitoring_months", windows["available_monitoring_months"])
        mlflow.log_param("baseline_rows", len(windows["baseline_df"]))
        mlflow.log_param("monitoring_rows", len(windows["monitoring_df"]))
        mlflow.log_param("min_rows_warning", min_rows_warning)
        mlflow.log_param("n_warnings", len(warnings))


        for key, value in logged_metrics.items():
            safe_value = clean_metric(value)
            if safe_value is not None:
                mlflow.log_metric(key, safe_value)


        for artifact_path in artifact_paths:
            mlflow.log_artifact(str(artifact_path), artifact_path="monitoring_report")




def generate_monitoring_report(
    training_cutoff: str,
    monitoring_months: int = 6,
    baseline_months: int = 18,
    min_rows_warning: int = 100,
    psi_bins: int = 10,
) -> str:
    print("Generando reporte de monitoreo...")
    print(f"training_cutoff={training_cutoff}")
    print(f"monitoring_months={monitoring_months}")


    df = pd.read_parquet(PARQUET_PATH)
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df.dropna(subset=TARGETS + FEATURES).copy()


    if df.empty:
        raise ValueError("No hay datos con features y targets completos para monitoreo.")


    windows = build_windows(
        df=df,
        training_cutoff=training_cutoff,
        monitoring_months=monitoring_months,
        baseline_months=baseline_months,
    )


    baseline_df = windows["baseline_df"]
    monitoring_df = windows["monitoring_df"]


    warnings = []
    status = "ok"
    skip_reason = None


    if windows["monitoring_end_effective"] < windows["monitoring_end_requested"]:
        warnings.append(
            "Se solicitaron mas meses de monitoreo que los disponibles en el offline store; "
            "se usa la ventana disponible."
        )


    if baseline_df.empty:
        status = "skipped"
        skip_reason = "No hay datos baseline disponibles para el training_cutoff seleccionado."


    if monitoring_df.empty:
        status = "skipped"
        skip_reason = "Aun no hay datos posteriores al training_cutoff para monitorear."


    if status == "ok":
        if len(baseline_df) < min_rows_warning:
            warnings.append(f"baseline_rows={len(baseline_df)} es menor al umbral recomendado de {min_rows_warning}.")
        if len(monitoring_df) < min_rows_warning:
            warnings.append(f"monitoring_rows={len(monitoring_df)} es menor al umbral recomendado de {min_rows_warning}.")
    else:
        warnings.append(skip_reason)


    output_dir = Path(REPORTS_DIR) / (
        f"monitoring_{windows['training_cutoff'].date().isoformat()}"
        f"_to_{windows['monitoring_end_effective'].date().isoformat()}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)


    artifact_paths = []
    summary_rows = []
    logged_metrics = {}


    status_df = pd.DataFrame(
        [
            {
                "status": status,
                "skip_reason": skip_reason,
                "training_cutoff": windows["training_cutoff"].date().isoformat(),
                "baseline_start": windows["baseline_start"].date().isoformat(),
                "monitoring_end_requested": windows["monitoring_end_requested"].date().isoformat(),
                "monitoring_end_effective": windows["monitoring_end_effective"].date().isoformat(),
                "available_data_end": windows["available_end"].date().isoformat(),
                "available_monitoring_months": windows["available_monitoring_months"],
                "baseline_rows": len(baseline_df),
                "monitoring_rows": len(monitoring_df),
            }
        ]
    )
    artifact_paths.append(save_csv(status_df, output_dir / "status.csv"))


    warnings_df = pd.DataFrame({"warning": warnings})
    artifact_paths.append(save_csv(warnings_df, output_dir / "warnings.csv"))


    if status == "ok":
        model = mlflow.pyfunc.load_model(f"models:/{MODEL_NAME}@production")


        baseline_pred = model.predict(baseline_df[FEATURES])
        monitoring_pred = model.predict(monitoring_df[FEATURES])


        performance_df = pd.concat(
            [
                evaluate_regression(baseline_df[TARGETS], baseline_pred, "baseline"),
                evaluate_regression(monitoring_df[TARGETS], monitoring_pred, "monitoring"),
            ],
            ignore_index=True,
        )
        performance_comparison_df = performance_comparison(performance_df)
        concept_comparison_df = concept_drift_comparison(performance_df)


        artifact_paths.append(save_csv(performance_df, output_dir / "model_performance_long.csv"))
        artifact_paths.append(save_csv(performance_comparison_df, output_dir / "model_performance_comparison.csv"))
        artifact_paths.append(save_csv(concept_comparison_df, output_dir / "concept_drift_comparison.csv"))


        for _, row in performance_comparison_df.iterrows():
            target = row["target"]
            metric = row["metric"]
            add_metric(summary_rows, logged_metrics, "model_decay", f"baseline_{metric}_{target}", row["baseline"])
            add_metric(summary_rows, logged_metrics, "model_decay", f"monitoring_{metric}_{target}", row["monitoring"])
            add_metric(summary_rows, logged_metrics, "model_decay", f"decay_{metric}_delta_{target}", row["delta"])


        for _, row in concept_comparison_df.iterrows():
            target = row["target"]
            metric = row["metric"]
            add_metric(summary_rows, logged_metrics, "concept_drift", f"baseline_{metric}_{target}", row["baseline"])
            add_metric(summary_rows, logged_metrics, "concept_drift", f"monitoring_{metric}_{target}", row["monitoring"])
            add_metric(summary_rows, logged_metrics, "concept_drift", f"{metric}_delta_{target}", row["delta"])


        numeric_drift_rows = []
        for feature in NUMERIC_PSI_FEATURES:
            psi_value = numeric_psi(baseline_df[feature], monitoring_df[feature], bins=psi_bins)
            ks_value = (
                ks_statistic(baseline_df[feature], monitoring_df[feature])
                if feature in CONTINUOUS_KS_FEATURES
                else None
            )


            numeric_drift_rows.append(
                {
                    "feature": feature,
                    "psi": clean_metric(psi_value),
                    "psi_interpretation": psi_label(psi_value),
                    "ks": clean_metric(ks_value),
                    "ks_note": "continuous_feature" if feature in CONTINUOUS_KS_FEATURES else "not_applied",
                }
            )


            add_metric(summary_rows, logged_metrics, "data_drift", f"psi_{feature}", psi_value)
            if ks_value is not None:
                add_metric(summary_rows, logged_metrics, "data_drift", f"ks_{feature}", ks_value)


        numeric_drift_df = pd.DataFrame(numeric_drift_rows)
        artifact_paths.append(save_csv(numeric_drift_df, output_dir / "numeric_drift_summary.csv"))


        categorical_psi_value = categorical_psi(baseline_df["tipoextraccion"], monitoring_df["tipoextraccion"])
        categorical_df = categorical_comparison(baseline_df, monitoring_df, "tipoextraccion")
        mapping = tipoextraccion_mapping()
        categorical_df["tipoextraccion_id"] = categorical_df["tipoextraccion"].astype(str)
        categorical_df["tipoextraccion_label"] = (
            categorical_df["tipoextraccion_id"].map(mapping).fillna("tipo_" + categorical_df["tipoextraccion_id"])
        )
        categorical_df = categorical_df[
            [
                "tipoextraccion_id",
                "tipoextraccion_label",
                "baseline_count_rows",
                "monitoring_count_rows",
                "baseline_share_rows",
                "monitoring_share_rows",
                "share_delta",
            ]
        ]
        categorical_df["psi_tipoextraccion"] = clean_metric(categorical_psi_value)
        categorical_df["psi_interpretation"] = psi_label(categorical_psi_value)


        artifact_paths.append(save_csv(categorical_df, output_dir / "categorical_drift_tipoextraccion_comparison.csv"))
        add_metric(summary_rows, logged_metrics, "data_drift", "psi_tipoextraccion", categorical_psi_value)


        model_decay_plot = output_dir / "model_decay_deltas.png"
        plot_model_decay(performance_comparison_df, model_decay_plot)
        artifact_paths.append(model_decay_plot)


        numeric_psi_plot = output_dir / "numeric_drift_psi.png"
        plot_numeric_drift(numeric_drift_df, numeric_psi_plot)
        artifact_paths.append(numeric_psi_plot)


        ks_plot = output_dir / "numeric_drift_ks.png"
        plot_ks_drift(numeric_drift_df, ks_plot)
        artifact_paths.append(ks_plot)


        concept_plot = output_dir / "concept_drift_residuals.png"
        plot_concept_drift(concept_comparison_df, concept_plot)
        artifact_paths.append(concept_plot)


        categorical_plot = output_dir / "categorical_drift_tipoextraccion.png"
        plot_categorical_distribution(categorical_df, categorical_plot)
        artifact_paths.append(categorical_plot)


    summary_df = pd.DataFrame(summary_rows)
    artifact_paths.append(save_csv(summary_df, output_dir / "summary_metrics.csv"))


    log_to_mlflow(
        status=status,
        warnings=warnings,
        windows=windows,
        baseline_months=baseline_months,
        min_rows_warning=min_rows_warning,
        artifact_paths=artifact_paths,
        logged_metrics=logged_metrics,
    )


    print(f"Status: {status}")
    if skip_reason:
        print(f"Skip reason: {skip_reason}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    print(f"Artifacts dir: {output_dir}")


    return str(output_dir)




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generar reporte de model decay, data drift y concept drift.")
    parser.add_argument("--training-cutoff", required=True, help="Fecha hasta la que se entreno el modelo (YYYY-MM-DD).")
    parser.add_argument("--monitoring-months", type=int, default=6, help="Cantidad de meses posteriores al cutoff a monitorear.")
    parser.add_argument("--baseline-months", type=int, default=18)
    parser.add_argument("--min-rows-warning", type=int, default=100)
    parser.add_argument("--psi-bins", type=int, default=10)
    args = parser.parse_args()


    generate_monitoring_report(
        training_cutoff=args.training_cutoff,
        monitoring_months=args.monitoring_months,
        baseline_months=args.baseline_months,
        min_rows_warning=args.min_rows_warning,
        psi_bins=args.psi_bins,
    )
