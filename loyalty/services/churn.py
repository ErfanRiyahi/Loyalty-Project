"""Cohort-relative baseline and experimental selective risk assessment.

Neither method is fitted on future churn outcomes or returns probabilities.
"""
import numpy as np
import pandas as pd

SCORE_DOMAINS = {
    'ARPU_SCORE': 'HAS_ACG', 'CLV_SCORE': 'HAS_ACG', 'GROWTH_SCORE': 'HAS_ACG',
    'DATA_USAGE_SCORE': 'HAS_DU', 'VOICE_USAGE_SCORE': 'HAS_VU',
    'Transaction_Frequency_SCORE': 'HAS_TF', 'TS_Score': 'HAS_TS', 'CI_Score': 'HAS_CI',
}
DOMAIN_GROUPS = {
    'financial': ['ARPU_SCORE', 'CLV_SCORE', 'GROWTH_SCORE'],
    'data': ['DATA_USAGE_SCORE'], 'voice': ['VOICE_USAGE_SCORE'],
    'transactions': ['Transaction_Frequency_SCORE'],
    'temporal': ['TS_Score'], 'consistency': ['CI_Score'],
}
METHODS = {'baseline', 'domain_balanced'}


def risk_band(value):
    if pd.isna(value):
        return 'Insufficient evidence'
    return 'High' if value >= 67 else 'Medium' if value >= 34 else 'Low'


def score_percentiles(frame):
    if frame.empty:
        raise ValueError('The final scored dataset is empty.')
    if 'MSISDN' not in frame:
        raise ValueError('Final scored CSV must contain MSISDN.')
    if frame['MSISDN'].isna().any() or frame['MSISDN'].astype(str).str.strip().eq('').any():
        raise ValueError('Every customer must have an MSISDN.')
    if frame['MSISDN'].duplicated().any():
        raise ValueError('Final scored CSV must have one row per MSISDN.')
    columns = [c for c in SCORE_DOMAINS if c in frame]
    if len(columns) < 2:
        raise ValueError('Provide at least two recognized score columns; raw transactions are not supported.')
    percentiles = pd.DataFrame(index=frame.index)
    for col in columns:
        values = pd.to_numeric(frame[col], errors='coerce').replace([np.inf, -np.inf], np.nan)
        flag = SCORE_DOMAINS[col]
        if flag in frame:
            values = values.where(pd.to_numeric(frame[flag], errors='coerce').eq(1))
        observed = values.dropna()
        if observed.nunique() < 2:
            percentiles[col] = np.nan
        else:
            percentiles[col] = (values.rank(method='average') - 1) / (len(observed) - 1)
    return percentiles, columns


def assess_risk(frame, method='baseline'):
    if method not in METHODS:
        raise ValueError('method must be baseline or domain_balanced.')
    # Work with a unique positional index for deterministic per-row explanations.
    frame = frame.reset_index(drop=True)
    percentiles, columns = score_percentiles(frame)
    count = percentiles.notna().sum(axis=1)
    baseline = ((1 - percentiles.mean(axis=1)) * 100).round(2).where(count >= 2)
    output = frame.copy()
    output['risk_index'] = baseline
    output['risk_band'] = baseline.map(risk_band)
    output['scores_used'] = count
    output['method'] = method
    def baseline_reason(row):
        if count.loc[row.name] < 2:
            return 'Fewer than two informative scores; cannot assess risk.'
        low = [c for c in columns if pd.notna(row[c]) and row[c] <= .33]
        return 'Low relative scores: ' + ', '.join(low) if low else 'Risk reflects average relative score position.'
    output['risk_reasons'] = percentiles.apply(baseline_reason, axis=1)
    if method == 'baseline':
        return output.sort_values('risk_index', ascending=False, na_position='last'), columns

    # Each of the six groups gets one vote; ACG's three metrics share that vote.
    # Unknown feature risks range from 0 to 100. Bounds also account for partial
    # coverage inside the financial group (not just entirely absent groups).
    feature_risk = 100 * (1 - percentiles.reindex(columns=list(SCORE_DOMAINS)))
    domain_risk = pd.DataFrame(index=frame.index)
    lower = pd.DataFrame(index=frame.index)
    upper = pd.DataFrame(index=frame.index)
    for domain, scores in DOMAIN_GROUPS.items():
        block = feature_risk[scores]
        domain_risk[domain] = block.mean(axis=1)
        known = block.notna().sum(axis=1)
        lower[domain] = block.fillna(0).sum(axis=1) / len(scores)
        upper[domain] = (block.fillna(0).sum(axis=1) + 100 * (len(scores) - known)) / len(scores)
        output['domain_risk_' + domain] = domain_risk[domain].round(2)
    used = domain_risk.notna().sum(axis=1)
    point = domain_risk.mean(axis=1).where(used >= 2)
    low_bound, high_bound = lower.mean(axis=1), upper.mean(axis=1)
    point_band = point.map(risk_band)
    # Deleting a group tests sensitivity, not sampling uncertainty.
    leave_one_out = pd.DataFrame(index=frame.index)
    for domain in DOMAIN_GROUPS:
        leave_one_out[domain] = ((domain_risk.sum(axis=1) - domain_risk[domain]) / (used - 1).replace(0, np.nan)).where((used >= 3) & domain_risk[domain].notna())
    deletion_low, deletion_high = leave_one_out.min(axis=1), leave_one_out.max(axis=1)
    bounds_stable = low_bound.map(risk_band).eq(high_bound.map(risk_band))
    deletion_stable = deletion_low.map(risk_band).eq(point_band) & deletion_high.map(risk_band).eq(point_band) & (used >= 3)
    accepted = (used >= 2) & bounds_stable & deletion_stable
    output['baseline_risk_index'] = baseline
    output['baseline_risk_band'] = baseline.map(risk_band)
    output['risk_index'] = point.round(2)
    output['point_risk_band'] = point_band
    output['domains_used'] = used
    output['domain_coverage'] = (used / len(DOMAIN_GROUPS)).round(4)
    output['evidence_coverage'] = (1 - (high_bound - low_bound) / 100).round(4)
    output['risk_lower_bound'] = low_bound.round(2)
    output['risk_upper_bound'] = high_bound.round(2)
    output['leave_one_domain_out_min'] = deletion_low.round(2)
    output['leave_one_domain_out_max'] = deletion_high.round(2)
    output['decision_stable'] = accepted
    output['risk_band'] = np.where(used < 2, 'Insufficient evidence', np.where(accepted, point_band, 'Needs review'))
    def explanation(index):
        if used.loc[index] < 2:
            return 'Fewer than two informative score groups; no point assessment.'
        contributions = domain_risk.loc[index].dropna().sort_values(ascending=False).head(2)
        text = 'Largest group risks: ' + ', '.join(f'{key} {value:.1f}' for key, value in contributions.items()) + '.'
        if not bounds_stable.loc[index]:
            text += ' Missing evidence could change the band.'
        if not deletion_stable.loc[index]:
            text += ' Removing a group changes the band or leaves too little evidence.'
        if accepted.loc[index]:
            text += ' Band survives both evidence and group-removal checks.'
        return text
    output['risk_reasons'] = [explanation(i) for i in frame.index]
    return output.sort_values('risk_index', ascending=False, na_position='last'), columns
