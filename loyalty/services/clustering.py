from ..common import *

from sklearn.preprocessing import RobustScaler
from sklearn.cluster import KMeans
from .validation import validate_clusters

CLUSTER_SCORE_COLS = ['ARPU_SCORE', 'CLV_SCORE', 'GROWTH_SCORE', 'DATA_USAGE_SCORE',
                       'VOICE_USAGE_SCORE', 'Transaction_Frequency_SCORE', 'TS_Score', 'CI_Score']
CLUSTER_DOMAIN_FLAGS = ['HAS_ACG', 'HAS_DU', 'HAS_VU', 'HAS_TF', 'HAS_TS', 'HAS_CI']
CLUSTER_LABEL_ORDER = ['At-Risk/Churning', 'Neutral', 'Loyal']
CLUSTER_CONTINUOUS_FEATURES = ['CLV_SCORE', 'VOICE_USAGE_SCORE', 'TS_Score', 'DATA_USAGE_SCORE',
                                'Transaction_Frequency_SCORE', 'GROWTH_SCORE', 'N_ACTIVE_DOMAINS']
CLUSTER_BINARY_FEATURES = ['HAS_ACG', 'HAS_CI', 'IS_ARPU_ABOVE_FLOOR', 'IS_CI_AT_FLOOR']

# ---------------------------------------------------------------------------
# MANUAL RETRAINING — persisted feature weights and versioned run history.
# Retraining stays manual (you trigger /cluster yourself every 1-3 months when
# new data lands), but weights and past runs are tracked here instead of
# living only inside one in-memory run.
# ---------------------------------------------------------------------------
CLUSTER_CONFIG_FILE = str(OUTPUT_ROOT / "cluster_config.json")
MODEL_REGISTRY_FILE = str(OUTPUT_ROOT / "model_registry.json")
MODELS_DIR = str(OUTPUT_ROOT / "models")

DEFAULT_FEATURE_WEIGHTS = {f: 1.0 for f in CLUSTER_CONTINUOUS_FEATURES + CLUSTER_BINARY_FEATURES}


def load_cluster_config():
    """Feature weights, loaded from disk and merged over the defaults so a
    config file written before a new feature existed still works."""
    cfg = {}
    if os.path.exists(CLUSTER_CONFIG_FILE):
        with open(CLUSTER_CONFIG_FILE) as f:
            cfg = json.load(f)
    cfg["feature_weights"] = {**DEFAULT_FEATURE_WEIGHTS, **cfg.get("feature_weights", {})}
    return cfg


def save_cluster_config(cfg):
    with open(CLUSTER_CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def load_model_registry():
    if os.path.exists(MODEL_REGISTRY_FILE):
        with open(MODEL_REGISTRY_FILE) as f:
            return json.load(f)
    return []


def save_model_registry(registry):
    with open(MODEL_REGISTRY_FILE, "w") as f:
        json.dump(registry, f, indent=2)


def run_clustering(run_stability=True):
    """Same logic as cluster_v3.md's merge -> tier split -> K-Means, packaged
    to run inside the request instead of a notebook. Raises if a required
    *_SCORE.csv is missing — run the corresponding tab (or /cluster with
    run_missing=true) first."""
    missing_files = [f for f in SCORE_FILES.values() if not os.path.exists(f)]
    if missing_files:
        raise FileNotFoundError(
            f"Missing score file(s): {missing_files}. Run each standard's tab "
            f"first, or POST /cluster with run_missing=true."
        )

    required = {
        "ARPU_CLV_GROWTH": ["ARPU_SCORE", "CLV_SCORE", "GROWTH_SCORE"],
        "DATA_USAGE": ["DATA_USAGE_SCORE"], "VOICE_USAGE": ["VOICE_USAGE_SCORE"],
        "Transaction_Frequency": ["Transaction_Frequency_SCORE"],
        "TEMPORAL_STABILITY": ["TS_Score"], "CONSISTENCY_INDEX": ["CI_Score"],
    }
    sources = {}
    source_summary = []
    for key, columns in required.items():
        source = pd.read_csv(SCORE_FILES[key], dtype={"MSISDN": "string"}, usecols=["MSISDN"] + columns)
        if source['MSISDN'].isna().any() or source['MSISDN'].str.strip().eq('').any() or source['MSISDN'].duplicated().any():
            raise ValueError(f"{key} needs a nonempty, unique MSISDN for each customer. Check ID normalization and duplicate rows.")
        for col in columns:
            numeric = pd.to_numeric(source[col], errors='coerce')
            if (source[col].notna() & numeric.isna()).any() or np.isinf(numeric).any():
                raise ValueError(f"{key}: {col} contains invalid or infinite scores.")
            source[col] = numeric
        sources[key] = source
        source_summary.append({'standard': key, 'rows': len(source), 'path': SCORE_FILES[key],
                               'modified_at': pd.Timestamp(os.path.getmtime(SCORE_FILES[key]), unit='s', tz='UTC').isoformat()})
    acg, du, vu, tf, ts, ci = [sources[key] for key in required]

    df = (acg.merge(du, on="MSISDN", how='outer')
             .merge(vu, on="MSISDN", how='outer')
             .merge(tf, on='MSISDN', how='outer')
             .merge(ts, on='MSISDN', how='outer')
             .merge(ci, on='MSISDN', how='outer'))

    df['HAS_ACG'] = df['ARPU_SCORE'].notna().astype(int)
    df['HAS_DU']  = df['DATA_USAGE_SCORE'].notna().astype(int)
    df['HAS_VU']  = df['VOICE_USAGE_SCORE'].notna().astype(int)
    df['HAS_TF']  = df['Transaction_Frequency_SCORE'].notna().astype(int)
    df['HAS_TS']  = df['TS_Score'].notna().astype(int)
    df['HAS_CI']  = df['CI_Score'].notna().astype(int)
    df['N_ACTIVE_DOMAINS'] = df[CLUSTER_DOMAIN_FLAGS].sum(axis=1)

    df[CLUSTER_SCORE_COLS] = df[CLUSTER_SCORE_COLS].fillna(0)

    arpu_floor = df.loc[df['HAS_ACG'] == 1, 'ARPU_SCORE'].min()
    ci_floor   = df.loc[df['HAS_CI']  == 1, 'CI_Score'].min()
    df['IS_ARPU_ABOVE_FLOOR'] = ((df['HAS_ACG'] == 1) & (df['ARPU_SCORE'] > arpu_floor)).astype(int)
    df['IS_CI_AT_FLOOR']      = ((df['HAS_CI']  == 1) & (df['CI_Score'] == ci_floor)).astype(int)

    multi = df['N_ACTIVE_DOMAINS'] >= 2
    df['tier'] = np.where(multi, 'multi', 'single')
    df_multi = df.loc[multi].copy()

    continuous_features = CLUSTER_CONTINUOUS_FEATURES
    binary_features = CLUSTER_BINARY_FEATURES

    cfg = load_cluster_config()
    weights = cfg["feature_weights"]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) or v < 0 for v in weights.values()):
        raise ValueError("Feature weights must be finite non-negative numbers.")
    w_cont = np.array([weights[f] for f in continuous_features])
    w_bin = np.array([weights[f] for f in binary_features])

    if len(df_multi) < 3:
        raise ValueError("k=3 requires at least three customers with two or more active domains.")
    scaler = RobustScaler()
    X_continuous_scaled = scaler.fit_transform(df_multi[continuous_features]) * w_cont
    X_binary_weighted = df_multi[binary_features].values.astype(float) * w_bin
    X_final = np.hstack([X_continuous_scaled, X_binary_weighted])

    if np.unique(X_final, axis=0).shape[0] < 3:
        raise ValueError("k=3 requires at least three distinct feature vectors.")
    km = KMeans(n_clusters=3, n_init=10, random_state=42)
    df_multi['cluster'] = km.fit_predict(X_final)

    engagement = df_multi.groupby('cluster')[CLUSTER_SCORE_COLS].mean().mean(axis=1).sort_values()
    cluster_labels_map = dict(zip(engagement.index, CLUSTER_LABEL_ORDER))
    df_multi['cluster_label'] = df_multi['cluster'].map(cluster_labels_map)

    profile = df_multi.groupby('cluster')[continuous_features + binary_features].mean()
    validation = validate_clusters(X_final, df_multi['cluster'], cluster_labels_map, run_stability)
    validation['source_files'] = source_summary
    validation['n_excluded_limited'] = int((~multi).sum())
    validation['domain_coverage_counts'] = {flag: int(df[flag].sum()) for flag in CLUSTER_DOMAIN_FLAGS}
    sil = validation['silhouette']
    db = validation['davies_bouldin']

    df['cluster_id'] = df_multi['cluster'].reindex(df.index).astype('Int64')
    df['cluster_label'] = df_multi['cluster_label']
    df['segment'] = df['cluster_label']  # single-domain "Limited" tiering can be layered on later
    df.loc[~multi, 'segment'] = 'Limited (single-domain)'

    df.to_csv(OUTPUT_ROOT / "customer_segmentation_final.csv", index=False)

    # ---- versioned snapshot, for rollback / comparing runs over time ----
    run_id = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S_%f")
    model_dir = os.path.join(MODELS_DIR, run_id)
    os.makedirs(model_dir, exist_ok=True)
    joblib.dump({
        "scaler": scaler, "kmeans": km, "cluster_labels_map": cluster_labels_map,
        "arpu_floor": arpu_floor, "ci_floor": ci_floor, "weights": weights,
        "continuous_features": continuous_features, "binary_features": binary_features,
    }, os.path.join(model_dir, "model.pkl"))

    validation['run_id'] = run_id
    validation['weights_used'] = weights
    validation['continuous_features'] = continuous_features
    validation['binary_features'] = binary_features
    for target in [OUTPUT_ROOT / 'cluster_validation.json', Path(model_dir) / 'validation.json']:
        with open(target, 'w') as stream:
            json.dump(json_safe(validation), stream, indent=2, allow_nan=False)
    df.to_csv(Path(model_dir) / 'segmentation.csv', index=False)
    segment_counts = df['segment'].value_counts().to_dict()

    registry = load_model_registry()
    previous = registry[-1] if registry else None
    registry.append({
        "run_id": run_id,
        "timestamp": pd.Timestamp.now().isoformat(),
        "n_customers": int(len(df)),
        "n_multi_domain": int(multi.sum()),
        "silhouette": round(sil, 3) if sil is not None else None,
        "davies_bouldin": round(db, 3) if db is not None else None,
        "segment_counts": segment_counts,
        "weights_used": weights,
        "validation_file": str(Path(model_dir) / "validation.json"),
    })
    save_model_registry(registry)

    # simple drift/quality proxy vs the last run — a real check, not just a log entry.
    # this doesn't block anything (retraining is manual), it just tells you when a
    # new run is worth a closer look before you treat it as the new baseline
    quality_flag = None
    if previous:
        sil_drop = previous["silhouette"] - sil if previous.get("silhouette") is not None and sil is not None else 0
        if sil_drop > 0.05:
            quality_flag = (f"Silhouette dropped from {previous['silhouette']} to {sil:.3f} "
                             f"vs run {previous['run_id']} — review before promoting this run.")
        else:
            prev_multi_share = previous["n_multi_domain"] / max(previous["n_customers"], 1)
            new_multi_share = int(multi.sum()) / max(len(df), 1)
            if abs(new_multi_share - prev_multi_share) > 0.05:
                quality_flag = (f"Share of multi-domain customers moved from "
                                 f"{prev_multi_share:.1%} to {new_multi_share:.1%} vs run "
                                 f"{previous['run_id']} — check whether a source file's coverage changed.")

    return {
        "run_id": run_id,
        "previous_run_id": previous["run_id"] if previous else None,
        "quality_flag": quality_flag,
        "n_customers": int(len(df)),
        "n_multi_domain": int(multi.sum()),
        "n_single_domain": int((~multi).sum()),
        "silhouette": round(sil, 3) if sil is not None else None,
        "davies_bouldin": round(db, 3) if db is not None else None,
        "segment_counts": segment_counts,
        "weights_used": weights,
        "cluster_profile": {
            str(cluster_labels_map[c]): {k: round(float(v), 3) for k, v in row.items()}
            for c, row in profile.iterrows()
        },
        "output_file": str(OUTPUT_ROOT / "customer_segmentation_final.csv"),
        "validation": validation,
        "validation_download_url": "/cluster/validation/download",
    }


