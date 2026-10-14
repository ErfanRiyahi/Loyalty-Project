"""Regression tests for evidence bounds, validation, and the supplied reader."""
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.datasets import make_blobs
from loyalty import create_app
from loyalty.common import read_source, json_safe
from loyalty.services.churn import assess_risk, SCORE_DOMAINS
from loyalty.services.validation import validate_clusters


def full_scores():
    return pd.DataFrame({'MSISDN': ['001', '002', '003'],
                         **{col: [1., 2., 3.] for col in SCORE_DOMAINS}})


class ThesisUpdateTests(unittest.TestCase):
    def test_reader_pipe_and_identifier_strings(self):
        with tempfile.TemporaryDirectory() as directory:
            voice = Path(directory) / 'voice.txt'
            voice.write_text('Subscriber_MSISDN|Call_Date|Call_Duration\n0098912|2026-01-01|12\n')
            frame = read_source(str(voice), ['Subscriber_MSISDN', 'Call_Date', 'Call_Duration'])
            self.assertEqual(frame.loc[0, 'Subscriber_MSISDN'], '0098912')
            self.assertEqual(str(frame['Subscriber_MSISDN'].dtype), 'string')
            data = Path(directory) / 'data.csv'
            data.write_text('SERVED_MSISDN,ACTUAL_USAGE\n00123,40\n')
            self.assertEqual(read_source(str(data), ['SERVED_MSISDN', 'ACTUAL_USAGE']).iloc[0, 0], '00123')

    def test_complete_evidence_and_abstention(self):
        result, _ = assess_risk(full_scores(), 'domain_balanced')
        self.assertEqual(result['risk_band'].tolist(), ['High', 'Medium', 'Low'])
        self.assertTrue(result['decision_stable'].all())
        self.assertTrue(result['risk_lower_bound'].eq(result['risk_upper_bound']).all())
        result, _ = assess_risk(full_scores().drop(columns=['VOICE_USAGE_SCORE', 'TS_Score']), 'domain_balanced')
        self.assertTrue(result['risk_band'].eq('Needs review').any())
        self.assertTrue((result['risk_lower_bound'] <= result['risk_index']).all())
        self.assertTrue((result['risk_upper_bound'] >= result['risk_index']).all())

    def test_group_balance_differs_from_baseline(self):
        frame = full_scores()
        for col in ['ARPU_SCORE', 'CLV_SCORE', 'GROWTH_SCORE']:
            frame[col] = [3., 2., 1.]
        result, _ = assess_risk(frame, 'domain_balanced')
        first = result.set_index('MSISDN').loc['001']
        self.assertAlmostEqual(first['baseline_risk_index'], 62.5)
        self.assertAlmostEqual(first['risk_index'], 83.33, places=2)
        self.assertEqual(first['domains_used'], 6)
        # Three financial scores alone still represent one group.
        result, _ = assess_risk(frame[['MSISDN', 'ARPU_SCORE', 'CLV_SCORE', 'GROWTH_SCORE']], 'domain_balanced')
        self.assertTrue(result['risk_index'].isna().all())
        self.assertTrue(result['risk_band'].eq('Insufficient evidence').all())

    def test_partial_group_missingness_is_in_bounds(self):
        result, _ = assess_risk(full_scores().drop(columns=['CLV_SCORE', 'GROWTH_SCORE']), 'domain_balanced')
        # Missing 2/3 of one of six equally weighted groups = 100/9 points.
        width = result['risk_upper_bound'] - result['risk_lower_bound']
        np.testing.assert_allclose(width, 100 / 9, atol=.02)
        frame = full_scores()
        frame['HAS_DU'] = 0
        result, _ = assess_risk(frame, 'domain_balanced')
        self.assertTrue(result['domain_risk_data'].isna().all())
        self.assertTrue(result['domains_used'].eq(5).all())

    def test_finite_json_new_route(self):
        frame = full_scores()
        frame.loc[0, 'VOICE_USAGE_SCORE'] = np.inf
        body = {'file': (io.BytesIO(frame.to_csv(index=False).encode()), 'scores.csv'), 'method': 'domain_balanced'}
        response = create_app().test_client().post('/churn/assess', data=body)
        self.assertEqual(response.status_code, 200, response.data)
        def reject(value): raise AssertionError(value)
        result = json.loads(response.data, parse_constant=reject)
        self.assertIn('accepted_band_share', result['diagnostics'])
        self.assertEqual(sum(result['diagnostics']['ablation']['baseline_equal_score'].values()), 3)
        self.assertEqual(sum(result['diagnostics']['ablation']['group_balanced_with_review'].values()), 3)
        self.assertEqual(result['method'], 'domain_balanced')
        self.assertIsNone(json_safe(pd.NA))

    def test_separated_clusters_and_refit_reproducibility(self):
        X, _ = make_blobs(n_samples=120, centers=[[-10,-10],[0,0],[10,10]], cluster_std=.2, random_state=2)
        labels = KMeans(n_clusters=3, n_init=10, random_state=42).fit_predict(X)
        report = validate_clusters(X, labels, {0:'A',1:'B',2:'C'})
        self.assertGreater(report['silhouette'], .9)
        self.assertGreater(report['stability']['ari_min'], .9)
        self.assertEqual(report['stability']['successful_runs'], 5)
        self.assertEqual(report, validate_clusters(X, labels, {0:'A',1:'B',2:'C'}))
        json.dumps(report, allow_nan=False)

    def test_metrics_small_sample_and_cap(self):
        report = validate_clusters(np.eye(3), [0,1,2], {0:'A',1:'B',2:'C'})
        self.assertIsNone(report['silhouette'])
        self.assertIsNone(report['calinski_harabasz'])
        self.assertEqual(report['stability']['status'], 'unavailable')
        X, labels = make_blobs(n_samples=2100, centers=3, random_state=42)
        report = validate_clusters(X, labels, {0:'A',1:'B',2:'C'}, False)
        self.assertEqual(report['silhouette_sample_size'], 2000)
        self.assertEqual(report['stability']['status'], 'disabled')
        self.assertEqual(report['external_validation']['status'], 'not_available')

if __name__ == '__main__':
    unittest.main()
