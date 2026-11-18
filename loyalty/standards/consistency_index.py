from ..progress import stage, stage_call, units, stage_scope
import pandas as pd
import numpy as np
from . import utils
from ..identifiers import POLICY_DESCRIPTION


# Apply existing cleaning rules, including identifier conversion and filtering.
@stage("Clean data and convert types")
def clean_data(df, columns):
    user_id, date_name, usage_name = columns

    # Clean dataset
    df_cleaned = utils.clean_data(df, columns)

    # Split six months
    df_6m = utils.split_six_months(df_cleaned, columns)
    if df_6m.empty:
        return pd.DataFrame({"MSISDN": pd.Series(dtype="string"),
                             "YearMonth": pd.Series(dtype="period[M]"),
                             usage_name: pd.Series(dtype=float),
                             "W_" + usage_name: pd.Series(dtype=float)})

    # Flag active customers and winsorize them
    df_6m["IS_ACTIVE"] = (df_6m[usage_name] > 0).astype(int)
    active_usage = df_6m.loc[df_6m[usage_name] > 0, usage_name]

    if "OrderStatusId" in columns:
        df_6m = df_6m[df_6m["OrderStatusId"] == 30].copy()

        result = (
            df_6m.groupby(["MSISDN", "YearMonth"])
            .size()
            .rename(usage_name)
            .sort_values(ascending=False)
            .reset_index()
        )
    else:
        result = (
            df_6m.groupby(["MSISDN", "YearMonth"])[usage_name]
            .sum()
            .rename(usage_name)
            .sort_values(ascending=False)
            .reset_index()
        )

    # Ranking the months for next step (weighting the score)
    current = result["YearMonth"].max()

    result["MONTH_RANK"] = (
        (current.year - result["YearMonth"].dt.year) * 12
        + (current.month - result["YearMonth"].dt.month)
        + 1
    )

    # Specify weights: first value = most recent month, last = oldest (6 months back)
    weights = [0.25, 0.25, 0.20, 0.15, 0.10, 0.05]

    result["W_" + usage_name] = result[usage_name] * result["MONTH_RANK"].apply(
        lambda x: weights[x - 1]
    )

    return result


def calculate_mu(df, columns):
    _, _, usage_name = columns
    mu = df.groupby("MSISDN")["W_" + usage_name].sum().rename("mu").reset_index()
    return mu


def calculate_ta(df, columns):
    _, _, usage_name = columns
    last_month = df["YearMonth"].max()
    ta = df[df["YearMonth"] == last_month][usage_name].median()
    return ta


@stage("Calculate domain consistency")
def calculate_CI(cleaned_data, columns, column_name):
    mu = calculate_mu(cleaned_data, columns)
    ta = calculate_ta(cleaned_data, columns)  # population-level scalar threshold

    _, date_name, usage_name = columns
    user_id = "MSISDN"
    weights = [0.25, 0.25, 0.20, 0.15, 0.10, 0.05]  # most recent -> oldest
    epsilon = 0.1

    df = cleaned_data.merge(mu, on=user_id)

    current = df["YearMonth"].max()
    df["MONTH_RANK"] = (
        (current.year - df["YearMonth"].dt.year) * 12
        + (current.month - df["YearMonth"].dt.month)
        + 1
    )
    df["weight"] = df["MONTH_RANK"].apply(lambda x: weights[x - 1])

    df["weighted_sq_diff"] = df["weight"] * (df[usage_name] - df["mu"]) ** 2

    sigma_df = (
        df.groupby(user_id, as_index=False)["weighted_sq_diff"]
        .sum()
        .rename(columns={"weighted_sq_diff": "sigma_sq"})
    )
    sigma_df["sigma"] = np.sqrt(sigma_df["sigma_sq"])

    sigma_df = sigma_df.merge(mu, on=user_id)

    sigma_df["INACTIVE"] = sigma_df["mu"] < ta

    sigma_df["CI_raw"] = (1 - (sigma_df["sigma"] / (sigma_df["mu"] + epsilon))) * 10
    sigma_df["CI"] = np.where(
        sigma_df["INACTIVE"], 1, np.clip(sigma_df["CI_raw"], 1, 10)
    )

    sigma_df = sigma_df[[user_id, "CI"]].rename(
        columns={user_id: "MSISDN", "CI": f"CI_{column_name}"}
    )
    return sigma_df


# Calculate and combine domain consistency using the existing method.
@stage("Calculate consistency across four domains")
def consistency_index(
    df_data,
    data_columns,
    df_voice,
    voice_columns,
    df_spend,
    spend_columns,
    df_txn,
    txn_columns,
    return_diagnostics=False,
):
    """
    Compute the final Consistency Index across the 4 domains.

    Each df_* is the raw dataset for that domain, and each *_columns is a
    3-item list [user_id_col, date_col, usage_col] for that dataset.

    Returns a DataFrame with columns: MSISDN, CI_Score
    (sorted descending by CI_Score).
    """
    sources = {"data": (df_data, data_columns), "voice": (df_voice, voice_columns),
               "spend": (df_spend, spend_columns), "txn": (df_txn, txn_columns)}
    scores, domains, months, customers = {}, {}, {}, {}
    for domain, (raw, columns) in sources.items():
        cleaned = clean_data(raw, columns)
        scores[domain] = (calculate_CI(cleaned, columns, domain) if not cleaned.empty
                          else pd.DataFrame({"MSISDN": pd.Series(dtype="string"),
                                             "CI_" + domain: pd.Series(dtype=float)}))
        months[domain] = set(cleaned.YearMonth.astype(str))
        customers[domain] = set(scores[domain].MSISDN)
        dates = pd.to_datetime(raw[columns[1]], errors="coerce", format="mixed", utc=True)
        domains[domain] = {
            "input_rows": len(raw), "input_customers": int(raw[columns[0]].nunique()),
            "input_rows_with_missing_fields": int(raw[columns].isna().any(axis=1).sum()),
            "scored_customers": len(scores[domain]), "observed_months": len(months[domain]),
            "window_start": min(months[domain]) if months[domain] else None,
            "window_end": max(months[domain]) if months[domain] else None,
            "input_date_start": dates.min().isoformat() if dates.notna().any() else None,
            "input_date_end": dates.max().isoformat() if dates.notna().any() else None,
        }
    CI_data, CI_voice, CI_spend, CI_txn = [scores[domain] for domain in ["data", "voice", "spend", "txn"]]

    CI_final = (
        CI_data.merge(CI_voice, on="MSISDN")
        .merge(CI_txn, on="MSISDN")
        .merge(CI_spend, on="MSISDN")
    )

    # NOTE: this sums the 4 domain CI's unweighted, matching your original
    # script. If you want the weighted composite instead
    # (data=0.5, voice=0.2, txn=0.2, spend=0.1), replace the line below with:
    CI_final["CI_Score"] = (
        0.5 * CI_final["CI_data"]
        + 0.2 * CI_final["CI_voice"]
        + 0.2 * CI_final["CI_txn"]
        + 0.1 * CI_final["CI_spend"]
    )
    CI_final["CI_Score"] = (
        CI_final[["CI_data", "CI_voice", "CI_txn", "CI_spend"]].sum(axis=1).clip(1, 10)
    )
    CI_final = CI_final[["MSISDN", "CI_Score"]]

    result = CI_final.sort_values("CI_Score", ascending=False).reset_index(drop=True)

    result = result[["MSISDN", "CI_Score"]]
    if not return_diagnostics:
        return result
    common = set.intersection(*customers.values())
    common_months = sorted(set.intersection(*months.values()))
    warnings = []
    if any(not values for values in customers.values()):
        warnings.append({"code": "empty_domain", "message": "حداقل یک حوزه پس از پاک‌سازی و انتخاب بازه، مشتری قابل امتیازدهی ندارد."})
    if not common:
        warnings.append({"code": "no_common_customers", "message": "هیچ شناسهٔ مشتری مشترکی در هر چهار حوزه باقی نمانده است؛ شاخص نهایی برای کسی محاسبه نشد. یکسان بودن شناسه‌ها و نمونه‌گیری از مشتریان مشترک را بررسی کنید."})
    if not common_months:
        warnings.append({"code": "no_common_months", "message": "پنجره‌های انتخاب‌شده در چهار حوزه ماه مشترک ندارند؛ این خروجی برای مقایسهٔ هم‌زمان حوزه‌ها مناسب نیست. داده‌های یک دورهٔ مشترک را وارد کنید."})
    if any(len(values) < 6 for values in months.values()):
        warnings.append({"code": "short_history", "message": "حداقل یک حوزه کمتر از شش ماهِ دارای داده دارد؛ خروجی نباید به‌عنوان شاخص مبتنی بر شش ماه تاریخچهٔ کامل تفسیر شود."})
    diagnostics = {"domains": domains, "common_customers": len(common),
                   "common_months": common_months, "output_customers": len(result),
                   "pairwise_common_customers": [{"first": first, "second": second, "count": len(customers[first] & customers[second])}
                        for index, first in enumerate(customers) for second in list(customers)[index+1:]],
                   "warnings": warnings,
                   "identifier_policy": POLICY_DESCRIPTION}
    return result, diagnostics
