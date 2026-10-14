import numpy as np
from . import utils

def data_usage(dataframe, required_columns):
    columns = required_columns
    
    user_id, date_name, usage_name = columns
    
    # Clean dataset
    df = utils.clean_data(dataframe, columns)

    # Split six months
    df_6m = utils.split_six_months(df, columns)    

    # Flag active customers and winsorize them
    df_6m['IS_ACTIVE'] = (df_6m[usage_name] > 0).astype(int)
    active_usage = df_6m.loc[df_6m[usage_name] > 0, usage_name]
  
    
    # Winsorize data
    lower_bound = np.percentile(active_usage, utils.bottom_percentile(active_usage))
    upper_bound = np.percentile(active_usage, utils.upper_percentile(active_usage))
    result_w = df_6m[df_6m['ACTUAL_USAGE'].between(lower_bound, upper_bound)]

    # Log-transform ARPU to compress right-skew/heavy tail into ratio-based (relative) distances, suitable for Euclidean-distance clustering
    # result_w_l = result_w.copy()
    # result_w_l['CUSTOMER_USAGE'] = np.log1p(result_w_l['CUSTOMER_USAGE'])

    # Calculate the sum of usage for each user per month
    result_w_l = (
        result_w.groupby(['MSISDN', 'YearMonth'])[usage_name]
        .sum()
        .reset_index()
        .rename(columns={usage_name: 'CUSTOMER_USAGE'})
    )  

    # Month Ranking
    current = result_w_l['YearMonth'].max()

    result_w_l['MONTH_RANK'] = (
        (current.year - result_w_l['YearMonth'].dt.year) * 12
        + (current.month - result_w_l['YearMonth'].dt.month)
        + 1
    )

    # Specify weights: first value has the most effect and represent the weight of 1 month ago
    weights = [0.25, 0.25, 0.2, 0.15, 0.1, 0.05]

    # Apply weights on the user score
    result_w_l['WEIGHTED_USAGE'] = result_w_l['CUSTOMER_USAGE'] * result_w_l['MONTH_RANK'].apply(lambda x: weights[x - 1])

    # Sum weighted usage for each customer
    result2 = (
        result_w_l.groupby(['MSISDN'])['WEIGHTED_USAGE']
        .sum()
        .rename('TOTAL_USAGE')
    ).sort_values(ascending=False).reset_index()

    # Calculate percentile 95 and use it as the maximum value
    p95 = np.percentile(result2['TOTAL_USAGE'], 95)

    result2['DATA_USAGE_SCORE'] = (
        (10 * (result2['TOTAL_USAGE'] / p95))
        .clip(1,10)
    )

    result_final = (
        result2.reset_index()[['MSISDN','DATA_USAGE_SCORE']]
        .sort_values('DATA_USAGE_SCORE', ascending=False)
        .reset_index(drop=True)
    )
    result_final

    return result_final