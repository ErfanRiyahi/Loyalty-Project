import pandas as pd
import numpy as np

def upper_percentile(series: pd.Series, start_percentile: float = 95, step: float = 1, ratio_threshold: float = 10):
    """
    Prints the difference between consecutive percentiles from start_percentile up to 100.
    Also flags a cutoff percentile where the ratio between consecutive diffs exceeds ratio_threshold.
    """
    s = series.dropna()
    percentiles = np.arange(start_percentile, 100 + step, step)
    values = s.quantile(percentiles / 100).values
    
    prev_diff = None
    for i in range(1, len(percentiles)):
        p_prev, p_curr = percentiles[i-1], percentiles[i]
        v_prev, v_curr = values[i-1], values[i]
        diff = v_curr - v_prev
        # print(f"P{p_prev:.1f} -> P{p_curr:.1f}: {v_prev:.4f} -> {v_curr:.4f}  | diff = {diff:.4f}")

        if prev_diff is not None and prev_diff != 0:
            ratio = diff / prev_diff                  
            if ratio > ratio_threshold:                
                # print(f"  >>> CUTOFF DETECTED at P{p_curr:.1f} (ratio = {ratio:.2f})")
                return p_prev

        prev_diff = diff
            
    return p_curr
# Example usage:
# upper_percentile(df["CONSISTENCY_INDEX"], start_percentile=90, step=1, ratio_threshold=20)


def bottom_percentile(series: pd.Series, step: float = 1, max_percentile: float = 10, ratio_threshold: float = 20):
    """
    Determines the bottom cutoff percentile:
    - If there's a block of zeros, cutoff = percentile where zeros end.
    - If that zero-block covers more than max_percentile, cap cutoff at max_percentile.
    - Otherwise, fall back to ratio-jump detection.
    """
    s = series.dropna()

    zero_frac = (s == 0).mean() * 100  # % of data that is exactly 0
    # print(f"Zero fraction: {zero_frac:.2f}%")

    if zero_frac > 0:
        if zero_frac > max_percentile:
            cutoff_percentile = max_percentile
            # print(f">>> Too many zeros ({zero_frac:.2f}%) -> capping cutoff at P{max_percentile}")
        else:
            cutoff_percentile = zero_frac
            # print(f">>> Zeros end around P{zero_frac:.2f} -> using that as cutoff")

        cutoff_value = s.quantile(cutoff_percentile / 100)
        # print(f"CUTOFF: P{cutoff_percentile:.2f} = {cutoff_value:.4f}")
        # return cutoff_percentile, cutoff_value
        # cutoff_percentile = cutoff_percentile.round()
        return cutoff_percentile

    # No zeros -> fall back to ratio-jump detection
    percentiles = np.arange(0, max_percentile + step, step)    
    values = s.quantile(percentiles / 100).values

    prev_diff = None
    cutoff_percentile = 0
    for i in range(1, len(percentiles)):
        p_prev, p_curr = percentiles[i-1], percentiles[i]
        v_prev, v_curr = values[i-1], values[i]
        diff = v_curr - v_prev
        # print(f"P{p_prev:.1f} -> P{p_curr:.1f}: {v_prev:.4f} -> {v_curr:.4f}  | diff = {diff:.4f}")

        if prev_diff is not None and prev_diff != 0:
            ratio = diff / prev_diff
            if ratio < (1 / ratio_threshold):
                cutoff_percentile = p_prev
                # print(f"  >>> CUTOFF DETECTED at P{p_prev:.1f} (ratio = {ratio:.4f})")

        prev_diff = diff
    
    cutoff_value = s.quantile(cutoff_percentile / 100)
    # print(f"CUTOFF: P{cutoff_percentile:.2f} = {cutoff_value:.4f}")
    # return cutoff_percentile, cutoff_value
    # cutoff_percentile = cutoff_percentile.round()
    return cutoff_percentile

# Example usage:
# cutoff_pct, cutoff_val = bottom_percentile(df["CONSISTENCY_INDEX"], max_percentile=10)

def clean_data(df: pd.Series, columns):
    user_id, date_name, usage_name = columns
    
    # Remove all nan items
    df = df.dropna().copy()

    df[date_name] = pd.to_datetime(df[date_name])
    df[usage_name] = pd.to_numeric(df[usage_name])

    # Convert date to year-month e.g. 2025-01
    df['YearMonth'] = df[date_name].dt.to_period('M')

    # Fix the MSISDN format
    if df[user_id].dtype == 'float64':
        df[user_id] = df[user_id].astype('Int64').astype('string')
    else:
        df['MSISDN'] = df[user_id].astype('string').str[2:]

    if 'OrderStatusId' in columns:
        # Select users with successful order
        df = df[df['OrderStatusId'] == 30]

    
    return df

def split_six_months(df, columns):
    date_name = columns[1]
    
    max_date = df[date_name].max()
    six_months_ago = max_date - pd.DateOffset(months=5)
    
    # Select the data within recent 6 months
    df = df[df[date_name] >= six_months_ago].copy()

    return df

