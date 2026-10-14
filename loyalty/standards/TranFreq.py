import numpy as np
from . import utils

def tranFreq(dataframe, required_columns):
    columns = required_columns
    
    user_id, date_name, usage_name = columns
    
    # Clean dataset
    df = utils.clean_data(dataframe, columns)

    # Split six months
    df_6m = utils.split_six_months(df, columns)    

    # Calculate the sum of usage for each user per month
    result = (
        df_6m.groupby(['MSISDN', 'YearMonth'])[usage_name]
        .size()
        .reset_index(name="SuccessfulTransactionCount")
    )

    # Flag active customers and winsorize them
    df_6m['IS_ACTIVE'] = (df_6m[usage_name] > 0).astype(int)
    active_usage = df_6m.loc[df_6m[usage_name] > 0, usage_name]
    
    
    # Winsorize data
    # lower_bound = np.percentile(active_usage, utils.bottom_percentile(active_usage))
    # upper_bound = np.percentile(active_usage, utils.upper_percentile(active_usage))
    # result_w = result[result['SuccessfulTransactionCount'].between(lower_bound, upper_bound)]

    # Log-transform ARPU to compress right-skew/heavy tail into ratio-based (relative) distances, suitable for Euclidean-distance clustering
    result_w_l = result.copy()
    # result_w_l['SuccessfulTransactionCount'] = np.log1p(result_w_l['SuccessfulTransactionCount'])

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
    result_w_l['WEIGHTED_TranCount'] = result_w_l['SuccessfulTransactionCount'] * result_w_l['MONTH_RANK'].apply(lambda x: weights[x - 1])

    # Sum weighted usage for each customer
    result2 = (
        result_w_l.groupby(['MSISDN'])['WEIGHTED_TranCount']
        .sum()
        .rename('TOTAL_TranCount')
    ).sort_values(ascending=False).reset_index()

    # Calculate percentile 95 and use it as the maximum value
    p95 = np.percentile(result2['TOTAL_TranCount'], 95)

    result2['Transaction_Frequency_SCORE'] = (
        (10 * (result2['TOTAL_TranCount'] / p95))
        .clip(1,10)
    )

    result_final = (
        result2.reset_index()[['MSISDN','Transaction_Frequency_SCORE']]
        .sort_values('Transaction_Frequency_SCORE', ascending=False)
        .reset_index(drop=True)
    )
    result_final

    return result_final