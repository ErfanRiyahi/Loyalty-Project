"""Guarded clustering adaptation with persistent active/previous versions."""
from pathlib import Path
import json
import shutil
import hashlib
import joblib
import numpy as np
import pandas as pd
from . import clustering
from .validation import validate_clusters
from ..common import OUTPUT_ROOT, json_safe
from ..progress import stage
from .monthly import write_json

ROOT = OUTPUT_ROOT / "adaptive"
POLICY = {"minimum_silhouette": 0.0, "minimum_cluster_share": 0.02,
          "minimum_stability_ari": 0.8, "minimum_successful_refits": 5,
          "minimum_silhouette_improvement": 0.01, "maximum_db_ratio": 1.05}



def file_hash(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def active_bundle():
    pointer = ROOT / "active.json"
    if not pointer.exists():
        return None
    value = json.loads(pointer.read_text())
    model = joblib.load(value["model_file"])
    model["active_run_id"] = value["run_id"]
    return model


def summarize(X, labels, mapping, stability=False):
    result = validate_clusters(X, labels, mapping, stability)
    return {key: result[key] for key in ["silhouette", "davies_bouldin", "cluster_sizes", "stability"]}


def acceptance(candidate, stability, incumbent=None):
    reasons = []
    silhouette = candidate["silhouette"]
    db = candidate["davies_bouldin"]
    if silhouette is None or silhouette <= POLICY["minimum_silhouette"] or db is None:
        reasons.append("جدایی خوشه‌ها برای پذیرش کافی نیست")
    if len(candidate["cluster_sizes"]) != 3 or min((item["share"] for item in candidate["cluster_sizes"]), default=0) < POLICY["minimum_cluster_share"]:
        reasons.append("اندازهٔ یک یا چند خوشه برای پذیرش کافی نیست")
    if stability["successful_runs"] < POLICY["minimum_successful_refits"] or (stability["ari_min"] or 0) < POLICY["minimum_stability_ari"]:
        reasons.append("پایداری خوشه‌بندی در بازآموزی‌های نمونه‌ای کافی نیست")
    if incumbent is not None:
        old_sil, old_db = incumbent["silhouette"], incumbent["davies_bouldin"]
        if old_sil is None or old_db is None:
            reasons.append("ارزیابی مدل فعال روی این داده کافی نیست؛ جایگزینی خودکار انجام نشد")
        elif silhouette is None or silhouette - old_sil < POLICY["minimum_silhouette_improvement"]:
            reasons.append("بهبود جدایی خوشه‌ها نسبت به مدل فعال کافی نیست")
        if old_db is not None and (db is None or db > old_db * POLICY["maximum_db_ratio"]):
            reasons.append("شاخص هم‌پوشانی خوشه‌ها نسبت به مدل فعال افت کرده است")
    return not reasons, reasons


def publish(pointer):
    """Publish the selected version's artifacts; candidates cannot touch these paths."""
    for source, destination in [(pointer["output_file"], clustering.OUTPUT_ROOT / "customer_segmentation_final.csv"),
                                (pointer["validation_file"], clustering.OUTPUT_ROOT / "cluster_validation.json")]:
        destination = Path(destination)
        temporary = destination.with_suffix(".tmp")
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    write_json(ROOT / "active.json", pointer)


@stage("Evaluate adaptive clustering candidate")
def update(payload):
    period = payload.get("as_of_month")
    try:
        month = pd.Period(period, freq="M")
        if str(month) != period or month >= pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M"):
            raise ValueError()
    except Exception as exc:
        raise ValueError("برای دورهٔ امتیازها یک ماه کامل با قالب YYYY-MM انتخاب کنید.") from exc
    if payload.get("confirm_scores") is not True:
        raise ValueError("تأیید کنید امتیازها مربوط به دوره و تعریف ویژگی یکسان هستند.")
    latest = ROOT / "latest_report.json"
    if latest.exists() and period < json.loads(latest.read_text())["as_of_month"]:
        raise ValueError("دورهٔ جدید نباید از آخرین ارزیابی قدیمی‌تر باشد.")
    sources = payload.get("sources")
    if sources is not None and (not isinstance(sources, dict) or set(sources) != set(clustering.SCORE_FILES) or any(not isinstance(value, str) or not value.strip() for value in sources.values())):
        raise ValueError("مسیر هر شش فایل امتیازدهی را مشخص کنید.")
    incumbent_pointer = json.loads((ROOT / "active.json").read_text()) if (ROOT / "active.json").exists() else None
    incumbent = active_bundle()
    if incumbent is None:
        registry = clustering.load_model_registry()
        if registry:
            entry = registry[-1]
            folder = Path(entry["validation_file"]).parent
            if all((folder / name).is_file() for name in ["model.pkl", "segmentation.csv", "validation.json"]):
                incumbent_pointer = {"run_id": entry["run_id"], "model_file": str(folder / "model.pkl"),
                                     "output_file": str(folder / "segmentation.csv"), "validation_file": str(folder / "validation.json")}
                incumbent = joblib.load(incumbent_pointer["model_file"])
                write_json(ROOT / "active.json", incumbent_pointer)
    if incumbent and incumbent["weights"] != clustering.load_cluster_config()["feature_weights"]:
        raise ValueError("وزن ویژگی‌ها با مدل فعال متفاوت است؛ ابتدا تنظیمات وزن را به نسخهٔ فعال برگردانید.")
    result = clustering.run_clustering(run_stability=False, score_files=sources, publish=False, holdout=True)
    candidate = joblib.load(result["model_file"])
    frame = pd.read_csv(result["output_file"], dtype={"MSISDN": "string"})
    multi = frame.loc[frame.N_ACTIVE_DOMAINS >= 2].copy()
    features = candidate["continuous_features"] + candidate["binary_features"]
    # Use the incumbent's fixed floors for both models so evaluation has one feature space.
    if not incumbent:
        train = multi.loc[~multi.MSISDN.isin(candidate["evaluation_ids"])]
        candidate["arpu_floor"] = train.loc[train.HAS_ACG == 1, "ARPU_SCORE"].min()
        candidate["ci_floor"] = train.loc[train.HAS_CI == 1, "CI_Score"].min()
    floors = incumbent or candidate
    multi["IS_ARPU_ABOVE_FLOOR"] = ((multi.HAS_ACG == 1) & (multi.ARPU_SCORE > floors["arpu_floor"])).astype(int)
    multi["IS_CI_AT_FLOOR"] = ((multi.HAS_CI == 1) & (multi.CI_Score == floors["ci_floor"])).astype(int)
    candidate["arpu_floor"], candidate["ci_floor"] = floors["arpu_floor"], floors["ci_floor"]
    X = multi[features].to_numpy(dtype=float) * np.array([candidate["weights"][field] for field in features])
    evaluation = multi.MSISDN.isin(candidate["evaluation_ids"]).to_numpy()
    # Refit the fixed candidate specification on training rows only, in this shared space.
    candidate["kmeans"].fit(X[~evaluation])
    labels = candidate["kmeans"].predict(X)
    engagement = multi.loc[~evaluation].assign(cluster=labels[~evaluation]).groupby("cluster")[clustering.CLUSTER_SCORE_COLS].mean().mean(axis=1).sort_values()
    if len(engagement) != 3:
        raise ValueError("مدل جدید هر سه خوشه را تشکیل نداد.")
    mapping = dict(zip(engagement.index, clustering.CLUSTER_LABEL_ORDER))
    candidate["cluster_labels_map"] = mapping
    quality = summarize(X[evaluation], labels[evaluation], mapping)
    stability = summarize(X[~evaluation], labels[~evaluation], mapping, True)["stability"]
    incumbent_quality = None
    if incumbent:
        if incumbent["continuous_features"] + incumbent["binary_features"] != features:
            raise ValueError("نسخهٔ ویژگی مدل فعال با ورودی‌ها سازگار نیست.")
        incumbent_quality = summarize(X[evaluation], incumbent["kmeans"].predict(X[evaluation]), incumbent["cluster_labels_map"])
    accepted, reasons = acceptance(quality, stability, incumbent_quality)
    population_labels, population_counts = np.unique(labels, return_counts=True)
    population_sizes = {str(int(label)): int(count) for label, count in zip(population_labels, population_counts)}
    if len(population_counts) != 3 or population_counts.min() / len(labels) < POLICY["minimum_cluster_share"]:
        accepted = False
        reasons.append("اندازهٔ یک خوشه در کل جمعیت کمتر از حد پذیرش است")
    # Snapshot predictions of this exact candidate, including unchanged Limited customers.
    frame.loc[multi.index, "cluster_id"] = labels
    frame.loc[multi.index, "cluster_label"] = [mapping[int(label)] for label in labels]
    frame.loc[multi.index, "segment"] = [mapping[int(label)] for label in labels]
    for column in ["IS_ARPU_ABOVE_FLOOR", "IS_CI_AT_FLOOR"]:
        frame.loc[multi.index, column] = multi[column]
    frame.to_csv(result["output_file"], index=False)
    joblib.dump(candidate, result["model_file"])
    validation_path = Path(result["model_file"]).with_name("validation.json")
    validation = json.loads(validation_path.read_text())
    validation.update(validate_clusters(X, labels, mapping, False))
    validation["adaptive_evaluation"] = quality
    validation["adaptive_stability"] = stability
    write_json(validation_path, validation)
    pointer = {"run_id": result["run_id"], "model_file": result["model_file"],
               "output_file": result["output_file"], "validation_file": str(validation_path)}
    report = {"run_id": result["run_id"], "as_of_month": period,
              "accepted": accepted, "decision": "bootstrap" if accepted and not incumbent else "promoted" if accepted else "rejected",
              "reasons": reasons, "candidate": quality, "incumbent": incumbent_quality,
              "stability": stability, "policy": POLICY, "training_rows": int((~evaluation).sum()),
              "evaluation_rows": int(evaluation.sum()), "population_cluster_sizes": population_sizes, "previous_run_id": incumbent_pointer["run_id"] if incumbent_pointer else None,
              "input_hashes": {key: file_hash(path) for key, path in (sources or clustering.SCORE_FILES).items()},
              "note": "Same current-cohort evaluation rows excluded from candidate fitting. Internal separation and robustness criteria, not proof of business improvement or churn accuracy."}
    if accepted:
        if incumbent_pointer:
            write_json(ROOT / "previous.json", incumbent_pointer)
        publish(pointer)
    report["active_run_id"] = (pointer if accepted else incumbent_pointer or {}).get("run_id")
    write_json(Path(result["model_file"]).with_name("adaptive_report.json"), report)
    write_json(latest, report)
    return json_safe(report)


def rollback():
    previous = ROOT / "previous.json"
    if not previous.exists():
        raise ValueError("نسخهٔ قبلی برای بازگشت وجود ندارد.")
    target = json.loads(previous.read_text())
    current = json.loads((ROOT / "active.json").read_text())
    publish(target)
    write_json(previous, current)
    latest = ROOT / "latest_report.json"
    report = json.loads(latest.read_text()) if latest.exists() else {}
    report.update(decision="rolled_back", active_run_id=target["run_id"])
    write_json(latest, report)
    return {"active_run_id": target["run_id"], "decision": "rolled_back"}
