import io
import os
import tempfile
import unittest
from unittest.mock import patch

scratch = tempfile.TemporaryDirectory()
os.environ['LOYALTY_OUTPUT_ROOT'] = scratch.name
import pandas as pd
from loyalty import create_app
from loyalty.common import SCORE_FILES, OUTPUT_ROOT
from loyalty.services.churn import assess_risk

class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_dashboard_and_assets(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        for tab in ['Standard','CI','TS','DS','Cluster','Churn','Monthly']:
            self.assertIn(('id="tab'+tab+'"').encode(), response.data)
        for script in ['shared','standard','consistency','temporal','overview','cluster','churn','monthly','navigation']:
            with self.client.get('/static/js/'+script+'.js') as asset:
                self.assertEqual(asset.status_code,200)

    def test_standard_score_persistence(self):
        source = OUTPUT_ROOT / 'input.csv'
        source.write_text('MSISDN,date,usage\n001,2026-01-01,10\n')
        for standard, function in [('ARPU_CLV_GROWTH','arpu_clv_growth'), ('DATA_USAGE','data_usage'), ('VOICE_USAGE','voice_usage'), ('Transaction_Frequency','tranFreq')]:
            with self.subTest(standard=standard), patch('loyalty.routes.scoring.'+function, return_value=pd.DataFrame({'MSISDN':['001'],'SCORE':[1.0]})):
                response=self.client.post('/analyze',json={'standard':standard,'dataset_address':str(source),'required_columns':['MSISDN','date','usage']})
                self.assertEqual(response.status_code,200,response.json)
                self.assertTrue(os.path.exists(SCORE_FILES[standard]))
                self.assertEqual(response.json['score']['rows_scored'],1)

    def test_risk_order_and_missing_evidence(self):
        result,_ = assess_risk(pd.DataFrame({'MSISDN':['001','002','003','004'], 'ARPU_SCORE':[1,2,3,None], 'DATA_USAGE_SCORE':[1,2,3,None]}))
        self.assertEqual(result['risk_band'].tolist(),['High','Medium','Low','Insufficient evidence'])
        self.assertEqual(result['risk_index'].dropna().tolist(),[100,50,0])

    def test_constant_and_absent_domains(self):
        result,_ = assess_risk(pd.DataFrame({'MSISDN':['01','02'], 'ARPU_SCORE':[1,1], 'DATA_USAGE_SCORE':[0,2], 'HAS_DU':[0,1]}))
        self.assertTrue(result['risk_index'].isna().all())

    def test_csv_upload_download_and_invalid_data(self):
        response=self.client.post('/churn/assess',data={'file':(io.BytesIO(b'MSISDN,ARPU_SCORE,DATA_USAGE_SCORE\n001,1,1\n002,2,2\n003,3,3\n'),'scores.csv')})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['preview'][0]['MSISDN'],'001')
        with self.client.get('/churn/download') as download:
            self.assertIn(b'risk_band',download.data)
        bad=self.client.post('/churn/assess',data={'file':(io.BytesIO(b'MSISDN,value\n1,10'),'raw.csv')})
        self.assertEqual(bad.status_code,400)
        self.assertEqual(self.client.post('/churn/assess',json={'dataset_address':'nonexistent.csv'}).status_code,400)
        with self.assertRaises(ValueError):
            assess_risk(pd.DataFrame({'MSISDN':['01','01'],'ARPU_SCORE':[1,2],'CLV_SCORE':[1,2]}))

    def test_fixed_three_clusters_and_small_sample_metrics(self):
        ids=['01','02','03']
        mapping={'ARPU_CLV_GROWTH':['ARPU_SCORE','CLV_SCORE','GROWTH_SCORE'], 'DATA_USAGE':['DATA_USAGE_SCORE'], 'VOICE_USAGE':['VOICE_USAGE_SCORE'], 'Transaction_Frequency':['Transaction_Frequency_SCORE'], 'TEMPORAL_STABILITY':['TS_Score'], 'CONSISTENCY_INDEX':['CI_Score']}
        for key,columns in mapping.items():
            frame=pd.DataFrame({'MSISDN':ids,**{col:[1.,5.,10.] for col in columns}})
            frame.to_csv(SCORE_FILES[key],index=False)
        response=self.client.post('/cluster',json={})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(len(response.json['cluster_profile']),3)
        self.assertIsNone(response.json['silhouette'])
        self.assertTrue((OUTPUT_ROOT/'customer_segmentation_final.csv').exists())
        self.assertEqual(self.client.post('/churn/assess',json={}).status_code,200)
        self.assertEqual(self.client.get('/cluster/history').status_code,200)

if __name__=='__main__': unittest.main()
