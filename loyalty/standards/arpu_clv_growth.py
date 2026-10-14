import numpy as np
from . import utils

def arpu_clv_growth(dataframe, required_columns):    
    # Read dataset
    # columns = ['MSISDN', 'PaidDateUtc', 'OrderTotal']
    # dataset_dir = r"D:\Loyality Project\customer order.csv"
    columns = required_columns
    # df = pd.read_csv(dataset_address,  usecols=columns)
    user_id, date_name, usage_name = columns
    
    # Clean dataset
    df = utils.clean_data(dataframe, columns)

    # Split six months
    df_6m = utils.split_six_months(df, columns)


    """ ********************************************* Start the process of calculating ARPU ********************************************* """
   
    # Flag active customers and winsorize them
    df_6m['IS_ACTIVE'] = (df_6m['OrderTotal'] > 0).astype(int)
    active_usage = df_6m.loc[df_6m['OrderTotal'] > 0, 'OrderTotal']
    
    # Winsorize data
    lower_bound = np.percentile(active_usage, utils.bottom_percentile(active_usage))
    upper_bound = np.percentile(active_usage, utils.upper_percentile(active_usage))
    result_w = df_6m[df_6m['OrderTotal'].between(lower_bound, upper_bound)]

    # Log-transform ARPU to compress right-skew/heavy tail into ratio-based (relative) distances, suitable for Euclidean-distance clustering
    # result_w_l = result_w.copy()
    # result_w_l['ARPU'] = np.log1p(result_w_l['ARPU'])

    # Calculate the sum of orders for each user per month
    result_w_l = (
        result_w.groupby([user_id, 'YearMonth'])[usage_name]
        .sum()
        .rename('ARPU')
    ).sort_values(ascending=False).reset_index()

    # Month Ranking
    current = result_w_l['YearMonth'].max()

    result_w_l['MONTH_RANK'] = (
        (current.year - result_w_l['YearMonth'].dt.year) * 12
        + (current.month - result_w_l['YearMonth'].dt.month)
        + 1
    )

    # Specify weights: first value has the most effect and represent the weight of 1 month ago
    weights = [2, 2, 2, 1, 1, 1]

    # Apply weights on the user score
    result_w_l['WEIGHTED_ARPU'] = result_w_l['ARPU'] * result_w_l['MONTH_RANK'].apply(lambda x: weights[x - 1])

    # Sum weighted ARPU for each customer
    result2 = (
        result_w_l.groupby([user_id])['WEIGHTED_ARPU']
        .sum()
        .rename('TOTAL_ARPU')
    ).sort_values(ascending=False).reset_index()

    # Normalization
    lower_bound = np.min(result2['TOTAL_ARPU'])
    upper_bound = np.max(result2['TOTAL_ARPU'])

    result2['ARPU_SCORE'] = (
        (10 * ((result2['TOTAL_ARPU'] - lower_bound)/(upper_bound - lower_bound)))
        .clip(1,10)        
    )

    result_arpu = (
        result2.reset_index()[[user_id,'ARPU_SCORE']]
        .sort_values('ARPU_SCORE', ascending=False)
        .reset_index(drop=True)
    )

    """ ********************************************* Calculate CLV ********************************************* """
    # Specify weights: first value has the most effect and represent the weight of 1 month ago
    clv_weights = [0.25, 0.25, 0.2, 0.15, 0.1, 0.05]

    result_clv = result_w_l

    # Apply weights on the user score
    result_clv['WEIGHTED_CLV'] = result_w_l['ARPU'] * result_w_l['MONTH_RANK'].apply(lambda x: clv_weights[x - 1])

    # The median CLV of whole customers in the last 3 months
    base_clv = result_w_l[result_w_l['MONTH_RANK'] <= 3]['WEIGHTED_CLV'].median()

    # Final step of calculating CLV
    result_c = (
        result_clv.groupby([user_id])['WEIGHTED_CLV']
        .sum()
        .rename('TOTAL_CLV')
    ).sort_values(ascending=False).reset_index()

    result_c["CLV_SCORE"] = (
        ((np.log10(result_c["TOTAL_CLV"].replace(0, np.nan) / base_clv) * 2 + 5))
        .clip(0, 10)        
    ).fillna(0)

    result_c = (
        result_c.reset_index()[[user_id,'CLV_SCORE']]
        .sort_values('CLV_SCORE', ascending=False)
        .reset_index(drop=True)
    )

    """ ********************************************* Calculate GROWTH TREND ********************************************* """
    # Split into windows
    recent_3   = result_w_l[result_w_l['MONTH_RANK'] <= 3]
    previous_3 = result_w_l[result_w_l['MONTH_RANK'] > 3]

    # Median per customer per window
    median_recent = (
        recent_3
        .groupby(user_id)['ARPU']
        .median()
        .rename('MEDIAN_RECENT')
    )

    median_previous = (
        previous_3
        .groupby(user_id)['ARPU']
        .median()
        .rename('MEDIAN_PREVIOUS')
    )

    result_w_l = result_w_l.join(median_recent, on=user_id)
    result_w_l = result_w_l.join(median_previous, on=user_id)
    result_w_l = result_w_l.fillna(0)

    # Separate customers with no value for prvious 3 months
    result_w_l['IS_NORMAL_CUSTOMER'] = (
        (result_w_l['MEDIAN_PREVIOUS'] != 0)
    ).astype(int)

    # Calculate growth score
    result_w_l['GROWTH'] = np.where(
        result_w_l['IS_NORMAL_CUSTOMER'] == 1,
        ((result_w_l['MEDIAN_RECENT'] - result_w_l['MEDIAN_PREVIOUS']) / result_w_l['MEDIAN_PREVIOUS']) * 100,
        0
    )

    # Remove duplicated customers
    result_g = (
        result_w_l
        .drop_duplicates(subset=user_id)
        .reset_index(drop=True)
    )

    # Final calculation
    L = np.min(result_g['GROWTH'])
    U = np.max(result_g['GROWTH'])

    result_g["GROWTH_SCORE"] = (
        ((((result_g['GROWTH'] - L) / (U - L)) * 9 + 1))
        .clip(1, 10)        
    ).fillna(0)

    result_growth = (
        result_g.reset_index()[[user_id,'GROWTH_SCORE']]
        .sort_values('GROWTH_SCORE', ascending=False)
        .reset_index(drop=True)
    )

    
    # Merge three scores together
    final_df = result_arpu.merge(result_c, on=user_id).merge(result_growth, on=user_id)
    
    # Save the output
    return final_df