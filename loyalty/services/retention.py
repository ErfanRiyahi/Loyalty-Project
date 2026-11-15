"""Three-month inactivity forecasting, with mature outcomes and behavioral evidence."""
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingClassifier
from . import monthly
from ..progress import stage, stage_call

VERSION = "three-month-inactivity-v1"
DOMAINS = {"orders": "خرید", "data": "مصرف اینترنت", "voice": "مکالمه"}
FEATURES = monthly.FEATURES + ["consecutive_inactive_months", "history_months"]


def enrich(frame, panel, month):
    result = frame.copy()
    prior = panel.loc[panel.month <= str(month)].copy()
    prior["active"] = prior[list(DOMAINS)].gt(0).any(axis=1)
    last = prior.loc[prior.active].groupby("MSISDN").month.max()
    result["last_active_month"] = result.MSISDN.map(last)
    result["consecutive_inactive_months"] = [
        pd.Period(month, freq="M").ordinal - pd.Period(value, freq="M").ordinal
        if pd.notna(value) else 0 for value in result.last_active_month
    ]
    return result


def target(frame, panel, month, observed_through):
    """Entry into three consecutive inactive months within the next three months."""
    month = pd.Period(month, freq="M")
    labels = pd.Series(np.nan, index=frame.index, dtype=float)
    if month + 3 > pd.Period(observed_through, freq="M"):
        return labels
    periods = pd.period_range(month - 1, month + 3, freq="M").astype(str)
    block = panel.loc[panel.month.isin(periods)].copy()
    block["active"] = block[list(DOMAINS)].gt(0).any(axis=1)
    activity = block.pivot(index="MSISDN", columns="month", values="active").reindex(index=frame.MSISDN, columns=periods)
    complete = activity.notna().all(axis=1).to_numpy()
    inactive = ~activity.astype("boolean").fillna(True).astype(bool)
    outcome = np.zeros(len(frame), dtype=bool)
    for end in [2, 3, 4]:
        outcome |= inactive.iloc[:, end-2:end+1].all(axis=1).to_numpy()
    eligible = (frame.history_months >= 3) & (frame.consecutive_inactive_months < 3) & complete
    labels.loc[eligible] = outcome[eligible.to_numpy()].astype(float)
    return labels


def new_model():
    return HistGradientBoostingClassifier(max_iter=150, max_leaf_nodes=7,
        min_samples_leaf=10, l2_regularization=5, learning_rate=0.06,
        early_stopping=False, random_state=42)


@stage("Train and evaluate three-month inactivity prediction")
def predict(snapshots, panel, latest, run_dir):
    frames = [enrich(frame, panel, frame.snapshot_month.iloc[0]) for frame in snapshots if not frame.empty]
    current = frames[-1].copy()
    current["churn_probability"] = np.nan
    current["model_factors"] = ""
    labeled = []
    for frame in frames:
        frame = frame.copy()
        frame["target"] = target(frame, panel, frame.snapshot_month.iloc[0], latest)
        labeled.append(frame.loc[frame.target.notna()])
    history = pd.concat(labeled, ignore_index=True)
    report = {"target": "Reach three consecutive complete months without purchases, positive data usage or positive voice usage within the next three months",
              "version": VERSION, "horizon_months": 3, "threshold": 0.5,
              "status": "insufficient_training_data", "algorithm": "HistGradientBoostingClassifier"}
    def sufficient(frame):
        return len(frame) >= 30 and frame.target.nunique() == 2 and frame.target.value_counts().min() >= 5
    if not history.empty and sufficient(history):
        # Each evaluation model sees only labels matured by its prediction date.
        periods = sorted(history.snapshot_month.unique())
        test_month = pd.Period(periods[-1], freq="M")
        validation_month = test_month - 3
        training = history.loc[history.snapshot_month <= str(validation_month - 3)]
        validation = history.loc[history.snapshot_month == str(validation_month)]
        test = history.loc[history.snapshot_month == str(test_month)]
        if sufficient(training) and not validation.empty and not test.empty:
            evaluator = stage_call("Fit model", new_model().fit, training[FEATURES], training.target.astype(int))
            report.update(training_months=sorted(training.snapshot_month.unique()),
                training_labels_observed_through=str(pd.Period(training.snapshot_month.max(), freq="M") + 3),
                validation_month=str(validation_month), test_month=str(test_month),
                validation=monthly.metrics(validation.target.astype(int), evaluator.predict_proba(validation[FEATURES])[:, 1]),
                candidate_test=monthly.metrics(test.target.astype(int), evaluator.predict_proba(test[FEATURES])[:, 1]))
        # Fixed model specification; no selection or promotion on the final test month.
        model = stage_call("Fit model", new_model().fit, history[FEATURES], history.target.astype(int))
        eligible = (current.history_months >= 3) & (current.consecutive_inactive_months < 3)
        if eligible.any():
            inputs = current.loc[eligible, FEATURES]
            probability = model.predict_proba(inputs)[:, 1]
            current.loc[eligible, "churn_probability"] = probability
            # Group replacement sensitivity is a model explanation, not a causal claim.
            medians = history[FEATURES].median()
            contributions = {}
            for domain, title in DOMAINS.items():
                altered = inputs.copy()
                fields = [column for column in FEATURES if column.startswith(domain + "_")]
                altered[fields] = medians[fields].to_numpy()
                contributions[title] = probability - model.predict_proba(altered)[:, 1]
            altered = inputs.copy()
            altered["consecutive_inactive_months"] = medians["consecutive_inactive_months"]
            contributions["طول بی‌فعالیتی"] = probability - model.predict_proba(altered)[:, 1]
            effects = pd.DataFrame(contributions, index=inputs.index)
            for index, row in effects.iterrows():
                factors = row[row > 0.005].nlargest(2).index.tolist()
                current.loc[index, "model_factors"] = "، ".join(factors)
        joblib.dump({"pipeline": model, "features": FEATURES, "version": VERSION,
                     "trained_through": str(latest), "latest_training_snapshot": history.snapshot_month.max()}, run_dir / "retention_model.pkl")
        report.update(status="trained", mature_training_rows=len(history),
                      evaluation_status="held_out" if "candidate_test" in report else "insufficient_history_for_independent_evaluation")
    else:
        report["reason"] = "Need at least 30 mature customer snapshots and five examples of each outcome. No probability is fabricated."
    statuses, levels, reasons = [], [], []
    for _, row in current.iterrows():
        inactive = int(row.consecutive_inactive_months)
        evidence = []
        if inactive:
            evidence.append(f"{inactive} ماه متوالی بدون فعالیت در منابع ثبت‌شده")
        for domain, title in DOMAINS.items():
            baseline = row[domain + "_previous3"]
            value = row[domain + "_current"]
            if baseline > 0 and value <= baseline * 0.5:
                percent = round((1 - value / baseline) * 100)
                evidence.append(f"کاهش {percent}٪ {title} نسبت به میانگین سه ماه پیش از دورهٔ اخیر")
        probability = row.churn_probability
        if inactive >= 3:
            state, level = "churned", "none"
        elif pd.notna(probability):
            state = "at_risk" if probability >= 0.5 else "low"
            level = "high" if probability >= 0.75 else "medium" if probability >= 0.5 else "low"
        else:
            state, level = "review", "review"
        statuses.append(state); levels.append(level)
        reasons.append("؛ ".join(evidence) if evidence else "نشانهٔ افت شدید در مقایسهٔ رفتار اخیر مشاهده نشد")
    current["retention_status"] = statuses
    current["risk_level"] = levels
    current["risk_reasons"] = reasons
    current["forecast_through"] = str(latest + 3)
    # Compatibility aliases for existing monthly exports, now explicitly using the new target.
    current["decline_probability"] = current.churn_probability
    current["prediction_status"] = current.retention_status
    current["predicted_next_month"] = str(latest + 3)
    return current, report
