import pandas as pd
import numpy as np
from . import utils


def clean_data(df, columns):
    user_id, date_name, usage_name = columns

    # Convert data to right format
    # df[date_name] = pd.to_datetime(df[date_name])
    # df[usage_name] = pd.to_numeric(df[usage_name])

    # # Remove rows with nan datetime
    # df = df.dropna().copy()

    # # Fix the MSISDN format
    # if df[user_id].dtype == 'float64':
    #     df[user_id] = df[user_id].astype('Int64').astype('string')
    # else:
    #     df['MSISDN'] = df[user_id].astype('string').str[2:]

    # # Calculate percentile 99 and 1 and use it as the maximum and minimum value
    # p1 = np.percentile(df[usage_name], 1)
    # p99 = np.percentile(df[usage_name], 99)

    # df_winsorized = df[df[usage_name].between(p1, p99)]

    # max_date = df_winsorized[date_name].max()
    # six_months_ago = max_date - pd.DateOffset(months=5)

    # # Select the data within recent 6 months
    # df_6m = df_winsorized[df_winsorized[date_name] >= six_months_ago].copy()
    # df_6m['YearMonth'] = df_6m[date_name].dt.to_period('M')

    # Clean dataset
    df_cleaned = utils.clean_data(df, columns)

    # Split six months
    df_6m = utils.split_six_months(df_cleaned, columns)  

    # Flag active customers and winsorize them
    df_6m['IS_ACTIVE'] = (df_6m[usage_name] > 0).astype(int)
    active_usage = df_6m.loc[df_6m[usage_name] > 0, usage_name]

    if 'OrderStatusId' in columns:
        df_6m = df_6m[df_6m['OrderStatusId'] == 30].copy()

        result = (
            df_6m.groupby(['MSISDN', 'YearMonth'])
            .size()
            .rename(usage_name)
            .sort_values(ascending=False)
            .reset_index()
        )
    else:
        result = (
            df_6m.groupby(['MSISDN', 'YearMonth'])[usage_name]
            .sum()
            .rename(usage_name)
            .sort_values(ascending=False)
            .reset_index()
        )

    # Ranking the months for next step (weighting the score)
    current = result['YearMonth'].max()

    result['MONTH_RANK'] = (
        (current.year - result['YearMonth'].dt.year) * 12
        + (current.month - result['YearMonth'].dt.month)
        + 1
    )

    # Specify weights: first value = most recent month, last = oldest (6 months back)
    weights = [0.25, 0.25, 0.20, 0.15, 0.10, 0.05]

    result['W_' + usage_name] = result[usage_name] * result['MONTH_RANK'].apply(lambda x: weights[x - 1])

    return result


def calculate_mu(df, columns):
    _, _, usage_name = columns
    mu = (
        df.groupby('MSISDN')['W_' + usage_name]
        .sum()
        .rename('mu')
        .reset_index()
    )
    return mu


def calculate_ta(df, columns):
    _, _, usage_name = columns
    last_month = df['YearMonth'].max()
    ta = df[df['YearMonth'] == last_month][usage_name].median()
    return ta


def calculate_CI(cleaned_data, columns, column_name):
    mu = calculate_mu(cleaned_data, columns)
    ta = calculate_ta(cleaned_data, columns)  # population-level scalar threshold

    _, date_name, usage_name = columns
    user_id = 'MSISDN'
    weights = [0.25, 0.25, 0.20, 0.15, 0.10, 0.05]  # most recent -> oldest
    epsilon = 0.1

    df = cleaned_data.merge(mu, on=user_id)

    current = df['YearMonth'].max()
    df['MONTH_RANK'] = (
        (current.year - df['YearMonth'].dt.year) * 12
        + (current.month - df['YearMonth'].dt.month)
        + 1
    )
    df['weight'] = df['MONTH_RANK'].apply(lambda x: weights[x - 1])

    df['weighted_sq_diff'] = df['weight'] * (df[usage_name] - df['mu']) ** 2

    sigma_df = (
        df.groupby(user_id, as_index=False)['weighted_sq_diff']
          .sum()
          .rename(columns={'weighted_sq_diff': 'sigma_sq'})
    )
    sigma_df['sigma'] = np.sqrt(sigma_df['sigma_sq'])

    sigma_df = sigma_df.merge(mu, on=user_id)

    sigma_df['INACTIVE'] = sigma_df['mu'] < ta

    sigma_df['CI_raw'] = (1 - (sigma_df['sigma'] / (sigma_df['mu'] + epsilon))) * 10
    sigma_df['CI'] = np.where(
        sigma_df['INACTIVE'],
        1,
        np.clip(sigma_df['CI_raw'], 1, 10)
    )

    sigma_df = sigma_df[[user_id, 'CI']].rename(
        columns={user_id: 'MSISDN', 'CI': f'CI_{column_name}'}
    )
    return sigma_df


def consistency_index(df_data, data_columns, df_voice, voice_columns,
                       df_spend, spend_columns, df_txn, txn_columns):
    """
    Compute the final Consistency Index across the 4 domains.

    Each df_* is the raw dataset for that domain, and each *_columns is a
    3-item list [user_id_col, date_col, usage_col] for that dataset.

    Returns a DataFrame with columns: MSISDN, CI_Score
    (sorted descending by CI_Score).
    """
    cleaned_data = clean_data(df_data, data_columns)
    CI_data = calculate_CI(cleaned_data, data_columns, 'data')

    cleaned_voice = clean_data(df_voice, voice_columns)
    CI_voice = calculate_CI(cleaned_voice, voice_columns, 'voice')

    cleaned_spend = clean_data(df_spend, spend_columns)
    CI_spend = calculate_CI(cleaned_spend, spend_columns, 'spend')

    cleaned_txn = clean_data(df_txn, txn_columns)
    CI_txn = calculate_CI(cleaned_txn, txn_columns, 'txn')

    CI_final = (
        CI_data
        .merge(CI_voice, on='MSISDN')
        .merge(CI_txn, on='MSISDN')
        .merge(CI_spend, on='MSISDN')
    )

    # NOTE: this sums the 4 domain CI's unweighted, matching your original
    # script. If you want the weighted composite instead
    # (data=0.5, voice=0.2, txn=0.2, spend=0.1), replace the line below with:
    CI_final['CI_Score'] = (
        0.5 * CI_final['CI_data'] + 0.2 * CI_final['CI_voice']
        + 0.2 * CI_final['CI_txn'] + 0.1 * CI_final['CI_spend']
    )
    CI_final['CI_Score'] = CI_final[['CI_data', 'CI_voice', 'CI_txn', 'CI_spend']].sum(axis=1).clip(1,10)
    CI_final = CI_final[['MSISDN', 'CI_Score']]

    result = CI_final.sort_values('CI_Score', ascending=False).reset_index(drop=True)

    return result[['MSISDN', 'CI_Score']]