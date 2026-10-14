import pandas as pd
import numpy as np

# --------------------------------------------------------------------------
# Clean data
# --------------------------------------------------------------------------
def clean_data(df, columns):
    user_id, date_name, usage_name = columns
    df = df.copy()

    # Convert data to right format
    df[date_name] = pd.to_datetime(df[date_name])

    # Remove rows with nan datetime
    df = df.dropna(subset=[date_name]).copy()

    # Fix the MSISDN format
    # NOTE: fixed so both branches always populate a "MSISDN" column —
    # every downstream function hardcodes "MSISDN", so the float64 branch
    # previously left the DataFrame without one and broke everything after it.
    if df[user_id].dtype == "float64":
        df["MSISDN"] = df[user_id].astype("Int64").astype("string")
    else:
        df["MSISDN"] = df[user_id].astype("string").str[2:]

    if "OrderStatusId" in columns:
        # Select users with successful order
        df = df[df["OrderStatusId"] == 30]
    elif "ACTUAL_USAGE" in columns:
        df = df[df["ACTUAL_USAGE"] > 1]
    elif "Call_Duration" in columns:
        df = df[df["Call_Duration"] > 10]

    return df


# --------------------------------------------------------------------------
# Calculate LRD (Last Revenue Date)
# --------------------------------------------------------------------------
def calculate_LRD(df, columns):
    _, date_name, usage_name = columns
    user_id = "MSISDN"

    if "OrderStatusId" in columns:
        # Select users with successful order
        df = df[df["OrderStatusId"] == 30]
        result = (
            df.groupby(user_id)[date_name]
            .max()
            .rename("LRD")
            .sort_values(ascending=False)
            .reset_index()
        )
    else:
        result = (
            df.groupby(user_id)[date_name]
            .max()
            .rename("LRD")
            .sort_values(ascending=False)
            .reset_index()
        )

    return result


# --------------------------------------------------------------------------
# Calculate RI (Recency Index) = RR (Revenue Recency) + UR (Usage Recency)
# --------------------------------------------------------------------------
def calculate_RR(df_order_cleaned, columns_order):
    result_RR = calculate_LRD(df_order_cleaned, columns_order)
    today_RR = result_RR["LRD"].max()
    result_RR["DSLR"] = (today_RR - result_RR["LRD"]).dt.days  # Days Since Last Revenue
    result_RR["RR"] = result_RR["DSLR"].apply(lambda x: np.exp(-0.03 * x))
    result_RR = result_RR[["MSISDN", "RR"]]
    return result_RR, today_RR


def calculate_UR(df_data_cleaned, df_voice_cleaned, columns_data, columns_voice):
    result_data = calculate_LRD(df_data_cleaned, columns_data)
    result_voice = calculate_LRD(df_voice_cleaned, columns_voice)

    combined = pd.concat([result_data, result_voice])

    result_UR = combined.groupby("MSISDN", as_index=False)["LRD"].max()

    today_UR = result_UR["LRD"].max()
    result_UR["DSLR"] = (today_UR - result_UR["LRD"]).dt.days
    result_UR["UR"] = result_UR["DSLR"].apply(lambda x: np.exp(-0.02 * x))
    result_UR = result_UR[["MSISDN", "UR"]]
    return result_UR, today_UR, combined


def calculate_RI(result_RR, result_UR):
    result_RI = result_RR.merge(result_UR, on="MSISDN")
    result_RI["RI"] = result_RI["RR"] * 0.5 + result_RI["UR"] * 0.3
    return result_RI


# --------------------------------------------------------------------------
# Calculate RM (Recency Momentum)
# --------------------------------------------------------------------------
def calculate_RM(df_order_cleaned, df_data_cleaned, df_voice_cleaned, columns_order, columns_data, columns_voice):
    RM_R = (
        df_order_cleaned.groupby("MSISDN", as_index=False)
        .agg(EVENT_DATE=(columns_order[1], lambda x: sorted(x)))
    )

    RM_U1 = (
        df_data_cleaned.groupby("MSISDN", as_index=False)
        .agg(EVENT_DATE=(columns_data[1], lambda x: sorted(x)))
    )

    RM_U2 = (
        df_voice_cleaned.groupby("MSISDN", as_index=False)
        .agg(EVENT_DATE=(columns_voice[1], lambda x: sorted(x)))
    )

    RM_U = pd.concat([RM_U1, RM_U2], ignore_index=True)
    RM_U = (
        RM_U.groupby("MSISDN")["EVENT_DATE"]
        .sum()  # concatenates the lists
        .reset_index()
    )

    RM = pd.concat([RM_R, RM_U], ignore_index=True)
    RM = (
        RM.groupby("MSISDN")["EVENT_DATE"]
        .sum()  # concatenates the lists
        .reset_index()
    )

    # Keep the 3 most recent, de-duplicated event dates per MSISDN
    RM["EVENT_DATE"] = RM["EVENT_DATE"].apply(
        lambda x: sorted(set(x), reverse=True)[:3]
    )

    RM["GAP1"] = RM["EVENT_DATE"].apply(
        lambda x: (x[0] - x[1]) / np.timedelta64(1, "D") if len(x) > 1 else np.nan
    )

    RM["GAP2"] = RM["EVENT_DATE"].apply(
        lambda x: (x[1] - x[2]) / np.timedelta64(1, "D") if len(x) > 2 else np.nan
    )

    RM["RM"] = (RM["GAP2"] - RM["GAP1"]) / (RM["GAP2"] + RM["GAP1"])
    RM["RM_NORM"] = (RM["RM"] + 1) / 2

    RM = RM.dropna(subset=["RM"])
    RM = RM[["MSISDN", "RM_NORM"]]

    return RM


# --------------------------------------------------------------------------
# Calculate AV (Activity Velocity) = RA (Revenue Activity) + UA (Usage Activity)
# --------------------------------------------------------------------------
def calculate_AV(df_order_cleaned, combined, columns_order, today_RR, today_UR):
    # Separate data from the last 30 days
    df_order_cleaned_30 = df_order_cleaned[
        df_order_cleaned[columns_order[1]] >= today_RR - pd.Timedelta(days=30)
    ]
    df_combined_30 = combined[combined["LRD"] >= today_UR - pd.Timedelta(days=30)]

    result_RA = df_order_cleaned_30.groupby("MSISDN").size().reset_index(name="RA")
    result_RA = result_RA[["MSISDN", "RA"]]

    result_UA = df_combined_30.groupby("MSISDN").size().reset_index(name="UA")
    result_UA = result_UA[["MSISDN", "UA"]]

    result_AV = result_RA.merge(result_UA, on="MSISDN")
    result_AV["AV"] = np.minimum((result_AV["RA"] * 5 + result_AV["UA"] * 2) / 30, 3) / 3

    return result_AV


# --------------------------------------------------------------------------
# Final Calculation (TS_Score)
# --------------------------------------------------------------------------
def calculate_final_score(result_RI, result_AV, RM):
    score_df = (
        result_RI[["MSISDN", "RI"]]
        .merge(result_AV[["MSISDN", "AV"]], on="MSISDN")
        .merge(RM[["MSISDN", "RM_NORM"]], on="MSISDN")
    )

    score_df["TS_Score"] = (
        1
        + 9
        * (
            score_df["RI"] * 0.5
            + score_df["AV"] * 0.3
            + score_df["RM_NORM"] * 0.2
        )
    )

    score_df = score_df.dropna(subset="TS_Score")
    TS_score = score_df[["MSISDN", "TS_Score"]]

    return TS_score


# --------------------------------------------------------------------------
# Module entry point
# --------------------------------------------------------------------------
def temporal_stability(df_order, order_columns, df_data, data_columns, df_voice, voice_columns):
    """
    Compute the Temporal Stability score across order, data, and voice domains.

    Each df_* is the raw dataset for that domain, and each *_columns is a
    3-item list [user_id_col, date_col, marker_col] for that dataset, where
    marker_col must be literally named "OrderStatusId" (order domain),
    "ACTUAL_USAGE" (data domain), or "Call_Duration" (voice domain) — the
    filtering logic in clean_data() keys off that exact column name.

    Returns a DataFrame with columns: MSISDN, TS_Score.
    """
    df_order_cleaned = clean_data(df_order, order_columns)
    df_data_cleaned = clean_data(df_data, data_columns)
    df_voice_cleaned = clean_data(df_voice, voice_columns)

    result_RR, today_RR = calculate_RR(df_order_cleaned, order_columns)
    result_UR, today_UR, combined = calculate_UR(
        df_data_cleaned, df_voice_cleaned, data_columns, voice_columns
    )
    result_RI = calculate_RI(result_RR, result_UR)

    RM = calculate_RM(
        df_order_cleaned, df_data_cleaned, df_voice_cleaned,
        order_columns, data_columns, voice_columns,
    )

    result_AV = calculate_AV(df_order_cleaned, combined, order_columns, today_RR, today_UR)

    TS_score = calculate_final_score(result_RI, result_AV, RM)


    return TS_score