from flask import Blueprint, send_file
from ..common import *
from .scoring import CI_DOMAINS, TS_DOMAINS
from ..services.clustering import *
app = Blueprint("clustering", __name__)

@app.route("/cluster", methods=["POST"])
def cluster_route():
    try:
        payload = request.get_json(silent=True) or {}

        if payload.get("run_missing"):
            # run each standard/domain with its default source file + the
            # column names supplied in the payload, same shape as the other tabs
            cols = {**STANDARD_COLUMNS,
                    "CONSISTENCY_INDEX": {d: STANDARD_COLUMNS[k] for d, k in CI_DOMAIN_STANDARD.items()},
                    "TEMPORAL_STABILITY": {d: STANDARD_COLUMNS[k] for d, k in TS_DOMAIN_STANDARD.items()},
                    **payload.get("columns", {})}
            if not os.path.exists(SCORE_FILES["ARPU_CLV_GROWTH"]):
                df = read_source(source_path("order"), usecols=cols["ARPU_CLV_GROWTH"])
                arpu_clv_growth(df, cols["ARPU_CLV_GROWTH"]).to_csv(SCORE_FILES["ARPU_CLV_GROWTH"], index=False)
            if not os.path.exists(SCORE_FILES["DATA_USAGE"]):
                df = read_source(source_path("data_cdr"), usecols=cols["DATA_USAGE"])
                data_usage(df, cols["DATA_USAGE"]).to_csv(SCORE_FILES["DATA_USAGE"], index=False)
            if not os.path.exists(SCORE_FILES["VOICE_USAGE"]):
                df = read_source(source_path("voice_cdr"), usecols=cols["VOICE_USAGE"])
                voice_usage(df, cols["VOICE_USAGE"]).to_csv(SCORE_FILES["VOICE_USAGE"], index=False)
            if not os.path.exists(SCORE_FILES["Transaction_Frequency"]):
                df = read_source(source_path("order"), usecols=cols["Transaction_Frequency"])
                tranFreq(df, cols["Transaction_Frequency"]).to_csv(SCORE_FILES["Transaction_Frequency"], index=False)
            if not os.path.exists(SCORE_FILES["CONSISTENCY_INDEX"]):
                ci_cols = cols["CONSISTENCY_INDEX"]  # {"data": [...], "voice": [...], "spend": [...], "txn": [...]}
                dfs = {d: read_source(source_path(CI_DOMAIN_SOURCE_KEY[d]), usecols=ci_cols[d]) for d in CI_DOMAINS}
                result_df = consistency_index(dfs["data"], ci_cols["data"], dfs["voice"], ci_cols["voice"],
                                               dfs["spend"], ci_cols["spend"], dfs["txn"], ci_cols["txn"])
                result_df.to_csv(SCORE_FILES["CONSISTENCY_INDEX"], index=False)
            if not os.path.exists(SCORE_FILES["TEMPORAL_STABILITY"]):
                ts_cols = cols["TEMPORAL_STABILITY"]  # {"order": [...], "data": [...], "voice": [...]}
                dfs = {d: read_source(source_path(TS_DOMAIN_SOURCE_KEY[d]), usecols=ts_cols[d]) for d in TS_DOMAINS}
                result_df = temporal_stability(dfs["order"], ts_cols["order"], dfs["data"], ts_cols["data"],
                                                dfs["voice"], ts_cols["voice"])
                result_df.to_csv(SCORE_FILES["TEMPORAL_STABILITY"], index=False)

        run_stability = payload.get("run_stability", True)
        if not isinstance(run_stability, bool):
            raise ValueError("run_stability must be true or false.")
        result = run_clustering(run_stability=run_stability)
        return jsonify(json_safe(result))
    except Exception as e:
        return build_error_response(e)


@app.route("/cluster/config", methods=["GET"])
def get_cluster_config():
    try:
        return jsonify(load_cluster_config())
    except Exception as e:
        return build_error_response(e)


@app.route("/cluster/config", methods=["POST"])
def update_cluster_config():
    """Update one or more feature weights. Takes effect on the NEXT /cluster
    run — it does not retroactively reweight an already-fitted model."""
    try:
        payload = request.get_json() or {}
        updates = payload.get("feature_weights", {})

        cfg = load_cluster_config()
        unknown = [k for k in updates if k not in cfg["feature_weights"]]
        if unknown:
            return jsonify({
                "error": f"Unknown feature(s): {unknown}. "
                         f"Valid features: {sorted(cfg['feature_weights'].keys())}"
            }), 400

        non_numeric = [k for k, v in updates.items() if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) or v < 0]
        if non_numeric:
            return jsonify({"error": f"Weights must be finite non-negative numbers: {non_numeric}"}), 400

        cfg["feature_weights"].update(updates)
        save_cluster_config(cfg)
        return jsonify(cfg)
    except Exception as e:
        return build_error_response(e)


@app.route("/cluster/history", methods=["GET"])
def get_cluster_history():
    try:
        return jsonify({"runs": load_model_registry()})
    except Exception as e:
        return build_error_response(e)



@app.get('/cluster/validation/download')
def download_validation():
    path = OUTPUT_ROOT / 'cluster_validation.json'
    if not path.exists():
        return jsonify(error='Run clustering first to generate validation.'), 404
    return send_file(path, as_attachment=True)
