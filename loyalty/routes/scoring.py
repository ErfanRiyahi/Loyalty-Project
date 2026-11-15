from ..progress import stage, stage_call, units, stage_scope
from flask import Blueprint
from ..common import *

app = Blueprint("scoring", __name__)


# Select the source and metric, calculate scores and save CSV for download and clustering.
@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        payload = request.get_json()
        # dataset_address is now optional — falls back to the fixed source file for this standard
        standard = payload["standard"]
        dataset_address = payload.get("dataset_address") or source_path(
            STANDARD_SOURCE_KEY[standard]
        )
        required_columns = payload.get("required_columns") or STANDARD_COLUMNS[standard]

        df = read_source(dataset_address, usecols=required_columns)

        missing = [c for c in required_columns if c not in df.columns]
        if missing:
            return jsonify({"error": f"Missing columns: {missing}"}), 400

        # Score functions return dataframes; this route owns CSV persistence.
        if standard == "ARPU_CLV_GROWTH":
            result_df = arpu_clv_growth(df, required_columns)
        elif standard == "DATA_USAGE":
            result_df = data_usage(df, required_columns)
        elif standard == "VOICE_USAGE":
            result_df = voice_usage(df, required_columns)
        elif standard == "Transaction_Frequency":
            result_df = tranFreq(df, required_columns)
        else:
            return jsonify({"error": f"Unknown standard: {standard}"}), 400

        output_path = SCORE_FILES[standard]
        stage_call("Save output file", result_df.to_csv, output_path, index=False)
        if not os.path.exists(output_path):
            return (
                jsonify(
                    {
                        "error": f"{standard} ran but no output file was found at '{output_path}'. "
                        f"Check that standards.py saves to this exact filename/location."
                    }
                ),
                500,
            )

        result_df = stage_call("Read data file", pd.read_csv, output_path)
        stats = compute_score_stats(result_df)

        return jsonify(
            {
                "dataset_overview": {
                    "rows": len(df),
                    "columns": required_columns,
                    "missing_values": int(df.isna().sum().sum()),
                    "preview": df.head(5).to_dict(orient="records"),
                },
                "score": {
                    "label": standard,
                    "output_file": output_path,
                    "rows_scored": len(result_df),
                    "preview": result_df.head(20).to_dict(orient="records"),
                    "description": f"{standard} computed over {len(df)} rows.",
                    "stats": stats,
                    "distributions": score_distributions(result_df),
                },
            }
        )
    except Exception as e:
        return build_error_response(e)


CI_DOMAINS = ["data", "voice", "spend", "txn"]


# Read three columns for each of four domains and save the consistency result.
@app.route("/consistency_index", methods=["POST"])
def consistency_index_route():
    try:
        payload = request.get_json()
        domains_payload = payload["domains"]

        missing_domains = [d for d in CI_DOMAINS if d not in domains_payload]
        if missing_domains:
            return jsonify({"error": f"Missing domains: {missing_domains}"}), 400

        domain_dfs = {}
        domain_overviews = {}

        for domain in CI_DOMAINS:
            entry = domains_payload[domain]
            # dataset_address optional — falls back to the fixed source file for this domain
            dataset_address = entry.get("dataset_address") or source_path(
                CI_DOMAIN_SOURCE_KEY[domain]
            )
            columns = entry["columns"]

            if len(columns) != 3:
                return (
                    jsonify(
                        {
                            "error": f"Domain '{domain}' must have exactly 3 columns, got {len(columns)}."
                        }
                    ),
                    400,
                )

            df = read_source(dataset_address, usecols=columns)

            missing_cols = [c for c in columns if c not in df.columns]
            if missing_cols:
                return (
                    jsonify(
                        {"error": f"Domain '{domain}' missing columns: {missing_cols}"}
                    ),
                    400,
                )

            domain_dfs[domain] = df
            domain_overviews[domain] = {
                "rows": len(df),
                "columns": columns,
            }

        # --- plug in your existing Consistency Index function here ---
        # Passes each domain's DataFrame and its 3 columns; returns a
        # DataFrame with MSISDN + final CI_Score directly (no file write).
        result_df = consistency_index(
            domain_dfs["data"],
            domains_payload["data"]["columns"],
            domain_dfs["voice"],
            domains_payload["voice"]["columns"],
            domain_dfs["spend"],
            domains_payload["spend"]["columns"],
            domain_dfs["txn"],
            domains_payload["txn"]["columns"],
        )

        # persist to disk — /cluster reads this back the same way it reads the
        # other standards' *_SCORE.csv files
        stage_call(
            "Save output file",
            result_df.to_csv,
            SCORE_FILES["CONSISTENCY_INDEX"],
            index=False,
        )

        stats = compute_score_stats(result_df)

        return jsonify(
            {
                "dataset_overview": {
                    "domains": domain_overviews,
                    "preview": result_df.head(8).to_dict(orient="records"),
                },
                "score": {
                    "label": "CONSISTENCY_INDEX",
                    "output_file": SCORE_FILES["CONSISTENCY_INDEX"],
                    "rows_scored": len(result_df),
                    "description": f"Consistency Index computed across {', '.join(CI_DOMAINS)} domains.",
                    "stats": stats,
                    "distributions": score_distributions(result_df),
                },
            }
        )
    except Exception as e:
        return build_error_response(e)


TS_DOMAINS = ["order", "data", "voice"]


# Calculate temporal stability from purchase, data and voice activity.
@app.route("/temporal_stability", methods=["POST"])
def temporal_stability_route():
    try:
        payload = request.get_json()
        domains_payload = payload["domains"]

        missing_domains = [d for d in TS_DOMAINS if d not in domains_payload]
        if missing_domains:
            return jsonify({"error": f"Missing domains: {missing_domains}"}), 400

        domain_dfs = {}
        domain_overviews = {}

        for domain in TS_DOMAINS:
            entry = domains_payload[domain]
            # dataset_address optional — falls back to the fixed source file for this domain
            dataset_address = entry.get("dataset_address") or source_path(
                TS_DOMAIN_SOURCE_KEY[domain]
            )
            columns = entry["columns"]

            if len(columns) != 3:
                return (
                    jsonify(
                        {
                            "error": f"Domain '{domain}' must have exactly 3 columns, got {len(columns)}."
                        }
                    ),
                    400,
                )

            df = read_source(dataset_address, usecols=columns)

            missing_cols = [c for c in columns if c not in df.columns]
            if missing_cols:
                return (
                    jsonify(
                        {"error": f"Domain '{domain}' missing columns: {missing_cols}"}
                    ),
                    400,
                )

            domain_dfs[domain] = df
            domain_overviews[domain] = {
                "rows": len(df),
                "columns": columns,
            }

        result_df = temporal_stability(
            domain_dfs["order"],
            domains_payload["order"]["columns"],
            domain_dfs["data"],
            domains_payload["data"]["columns"],
            domain_dfs["voice"],
            domains_payload["voice"]["columns"],
        )

        # persist to disk — needed by /cluster
        stage_call(
            "Save output file",
            result_df.to_csv,
            SCORE_FILES["TEMPORAL_STABILITY"],
            index=False,
        )

        stats = compute_score_stats(result_df)

        return jsonify(
            {
                "dataset_overview": {
                    "domains": domain_overviews,
                    "preview": result_df.head(8).to_dict(orient="records"),
                },
                "score": {
                    "label": "TEMPORAL_STABILITY",
                    "output_file": SCORE_FILES["TEMPORAL_STABILITY"],
                    "rows_scored": len(result_df),
                    "description": f"Temporal Stability computed across {', '.join(TS_DOMAINS)} domains.",
                    "stats": stats,
                    "distributions": score_distributions(result_df),
                },
            }
        )
    except Exception as e:
        return build_error_response(e)


# Pass date and usage column names from the request to profiling without changes.
@app.route("/dataset_overview", methods=["POST"])
def dataset_overview_route():
    from ..services.profiling import profile_dataset

    try:
        payload = request.get_json() or {}
        frame = read_source(payload["dataset_address"])
        report = profile_dataset(
            frame,
            payload.get("date_column"),
            payload.get("usage_column"),
            payload.get("frequency", "day"),
            payload.get("user_column"),
        )
        return jsonify(json_safe(report))
    except (ValueError, KeyError, FileNotFoundError) as error:
        return build_error_response(error, status=400)
    except Exception as error:
        return build_error_response(error)
