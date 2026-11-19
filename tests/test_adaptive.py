import json
from pathlib import Path
from unittest.mock import patch
import joblib
import numpy as np
import pandas as pd
import pytest
from loyalty import create_app, common
from loyalty.services import adaptive, clustering, churn_prediction as forecasting, retention
from loyalty.routes import clustering as routes


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for module in [common, clustering, routes]:
        monkeypatch.setattr(module, 'OUTPUT_ROOT', tmp_path)
    monkeypatch.setattr(clustering,'MODELS_DIR',str(tmp_path/'models'))
    monkeypatch.setattr(clustering,'MODEL_REGISTRY_FILE',str(tmp_path/'registry.json'))
    monkeypatch.setattr(clustering,'CLUSTER_CONFIG_FILE',str(tmp_path/'config.json'))
    monkeypatch.setattr(adaptive,'ROOT',tmp_path/'adaptive')
    monkeypatch.setattr(forecasting,'ROOT',tmp_path/'churn')
    sources={key:str(tmp_path/(key+'.csv')) for key in common.SCORE_FILES}
    for module in [common,clustering,routes]:monkeypatch.setattr(module,'SCORE_FILES',sources)
    return create_app().test_client(),sources


def scores(sources, centers):
    rng=np.random.default_rng(8)
    value=np.repeat(centers,50)+rng.normal(0,.05,150)
    columns={'ARPU_CLV_GROWTH':['ARPU_SCORE','CLV_SCORE','GROWTH_SCORE'],
             'DATA_USAGE':['DATA_USAGE_SCORE'],'VOICE_USAGE':['VOICE_USAGE_SCORE'],
             'Transaction_Frequency':['Transaction_Frequency_SCORE'],
             'TEMPORAL_STABILITY':['TS_Score'],'CONSISTENCY_INDEX':['CI_Score']}
    for key,fields in columns.items():
        pd.DataFrame({'MSISDN':[str(i).zfill(5) for i in range(150)],**{field:value for field in fields}}).to_csv(sources[key],index=False)


def test_bootstrap_rejection_promotion_rollback_and_active_inference(setup):
    client,sources=setup
    scores(sources,[1,5,9])
    body={'as_of_month':'2025-01','confirm_scores':True}
    first=client.post('/adaptive/update',json=body)
    assert first.status_code==200,first.json
    assert first.json['decision']=='bootstrap',first.json
    first_id=first.json['active_run_id']
    active=(adaptive.ROOT/'active.json').read_bytes()
    published=(clustering.OUTPUT_ROOT/'customer_segmentation_final.csv').read_bytes()
    with patch.object(retention,'predict',side_effect=AssertionError('Adaptive learning must not predict churn')):
        repeated=client.post('/adaptive/update',json=body)
    assert repeated.json['decision']=='rejected',repeated.json
    assert (adaptive.ROOT/'active.json').read_bytes()==active
    assert (clustering.OUTPUT_ROOT/'customer_segmentation_final.csv').read_bytes()==published
    scores(sources,[3,7,9.5])
    second=client.post('/adaptive/update',json={**body,'as_of_month':'2025-02'})
    assert second.status_code==200,second.json
    assert second.json['decision']=='promoted',second.json
    assert second.json['active_run_id']!=first_id
    with patch.object(clustering.KMeans,'fit',side_effect=AssertionError('Active inference must not refit')):
        prediction=client.post('/cluster',json={'run_stability':False})
    assert prediction.status_code==200,prediction.json
    assert prediction.json['active_model_run_id']==second.json['active_run_id']
    rollback=client.post('/adaptive/rollback',json={})
    assert rollback.status_code==200
    assert rollback.json['active_run_id']==first_id
    assert (clustering.OUTPUT_ROOT/'customer_segmentation_final.csv').read_bytes()==published
    assert client.get('/adaptive/status').json['decision']=='rolled_back'
    assert not forecasting.ROOT.exists()


def test_acceptance_requires_multiple_quality_checks():
    quality={'silhouette':.8,'davies_bouldin':.3,'cluster_sizes':[{'share':.3},{'share':.3},{'share':.4}]}
    stability={'successful_runs':5,'ari_min':.95}
    old={**quality,'silhouette':.6,'davies_bouldin':.4}
    assert adaptive.acceptance(quality,stability,old)[0]
    assert not adaptive.acceptance(quality,{**stability,'ari_min':.5},old)[0]
    assert not adaptive.acceptance({**quality,'cluster_sizes':[{'share':.005},{'share':.495},{'share':.5}]},stability,old)[0]
    assert not adaptive.acceptance(quality,stability,quality)[0]
    assert not adaptive.acceptance({**quality,'davies_bouldin':.9},stability,old)[0]


def test_no_confirmation_and_small_cohort_do_not_publish(setup):
    client,sources=setup
    scores(sources,[1,5,9])
    assert client.post('/adaptive/update',json={'as_of_month':'2025-01'}).status_code==400
    for path in sources.values():pd.read_csv(path).head(12).to_csv(path,index=False)
    response=client.post('/adaptive/update',json={'as_of_month':'2025-01','confirm_scores':True})
    assert response.status_code==400
    assert not (adaptive.ROOT/'active.json').exists()
    assert not (clustering.OUTPUT_ROOT/'customer_segmentation_final.csv').exists()


def test_existing_manual_clustering_becomes_baseline_without_overwrite(setup):
    client,sources=setup
    scores(sources,[1,5,9])
    manual=client.post('/cluster',json={'run_stability':False})
    assert manual.status_code==200
    published=(clustering.OUTPUT_ROOT/'customer_segmentation_final.csv').read_bytes()
    response=client.post('/adaptive/update',json={'as_of_month':'2025-01','confirm_scores':True})
    assert response.status_code==200,response.json
    assert response.json['decision']=='rejected'
    assert response.json['incumbent'] is not None
    assert response.json['active_run_id']==manual.json['run_id']
    assert (clustering.OUTPUT_ROOT/'customer_segmentation_final.csv').read_bytes()==published
