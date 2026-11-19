"""Regression checks for the requested changes applied to version 3."""
from pathlib import Path
from unittest.mock import patch
import re
import json
import numpy as np
import pandas as pd
import pytest
from loyalty import create_app, common
from loyalty.services.profiling import profile_dataset
from loyalty.services import clustering, monthly, churn_prediction as forecasting
from loyalty.routes import scoring, clustering as clustering_routes, churn


@pytest.fixture
def client(tmp_path,monkeypatch):
    output=tmp_path/'outputs';output.mkdir()
    files={key:str(output/Path(path).name) for key,path in common.SCORE_FILES.items()}
    for module in [common,scoring,clustering,clustering_routes,churn]:
        if hasattr(module,'OUTPUT_ROOT'):monkeypatch.setattr(module,'OUTPUT_ROOT',output)
        if hasattr(module,'SCORE_FILES'):monkeypatch.setattr(module,'SCORE_FILES',files)
    monkeypatch.setattr(clustering,'MODELS_DIR',str(output/'models'))
    monkeypatch.setattr(clustering,'CLUSTER_CONFIG_FILE',str(output/'cluster_config.json'))
    monkeypatch.setattr(clustering,'MODEL_REGISTRY_FILE',str(output/'model_registry.json'))
    monkeypatch.setattr(forecasting,'ROOT',output/'churn')
    return create_app().test_client()


def test_profile_counts_dates_invalid_values_and_no_mutation():
    frame=pd.DataFrame({' date ':['2026-01-02','2026-01-01','bad',None,'2026-01-02','2026-01-02'],
                        'usage':[20,10,30,40,None,float('inf')],'id':['a','b','a','c','d','a']})
    before=frame.copy(deep=True)
    data=profile_dataset(frame,' date ','usage',user_column='id')
    summary=data['dataset_overview']
    assert summary['rows']==6 and summary['columns']==3
    assert summary['null_values']==2 and summary['rows_with_nulls']==2
    assert summary['invalid_dates']==1 and summary['invalid_usage']==1
    assert summary['rows_used_in_chart']==2 and summary['rows_excluded_from_chart']==4
    assert summary['unique_users']==4 and summary['column_info'][0]['name']==' date '
    assert [point['usage'] for point in data['time_series']['points']]==[10,20]
    pd.testing.assert_frame_equal(frame,before)


def test_profile_empty_duplicate_and_long_history():
    frame=pd.DataFrame({'date':['2026-01-01']*2,'usage':[3,3]})
    report=profile_dataset(frame,'date','usage')
    assert report['dataset_overview']['duplicate_rows']==1
    assert report['time_series']['points'][0]['usage']==6
    assert profile_dataset(pd.DataFrame(columns=['date','usage']),'date','usage')['time_series']['points']==[]
    dates=pd.date_range('2018-01-01',periods=4000)
    report=profile_dataset(pd.DataFrame({'date':dates.astype(str),'usage':np.ones(4000)}),'date','usage')
    assert len(report['time_series']['points'])<=1000
    assert sum(point['usage'] for point in report['time_series']['points'])==4000
    with pytest.raises(ValueError):profile_dataset(frame,'date')
    with pytest.raises(ValueError):profile_dataset(frame,'missing','usage')


def test_profile_report_download_and_exact_headers(client,tmp_path):
    path=tmp_path/'source.csv';path.write_text(' date ,usage,id\n2026-01-01,3,001\n2026-01-01,4,002\nwrong,,003\n')
    result=client.post('/dataset_overview',json={'dataset_address':str(path),'date_column':' date ','usage_column':'usage','user_column':'id'})
    assert result.status_code==200,result.json
    assert result.json['dataset_overview']['rows']==3
    assert result.json['time_series']['points'][0]['usage']==7
    response=client.get(result.json['download_url'])
    assert response.status_code==200 and 'attachment' in response.headers['Content-Disposition']
    assert json.loads(response.data)['dataset_overview']['column_info'][0]['name']==' date '
    assert client.get('/outputs/download/app.py').status_code==404
    assert client.get('/outputs/download/../../app.py').status_code==404
    assert client.post('/dataset_overview',json={'dataset_address':str(path),'date_column':'unknown','usage_column':'usage'}).status_code==400


def test_each_scoring_output_has_immutable_download(client,tmp_path):
    source=tmp_path/'source.csv';source.write_text('MSISDN,date,usage\n001,2026-01-01,3\n')
    payload={'standard':'VOICE_USAGE','dataset_address':str(source),'required_columns':['MSISDN','date','usage']}
    first=pd.DataFrame({'MSISDN':['001','002'],'VOICE_USAGE_SCORE':[2.,5.]})
    with patch.object(scoring,'voice_usage',return_value=first):
        result=client.post('/analyze',json=payload)
    assert result.status_code==200,result.json
    url=result.json['score']['download_url'];content=client.get(url).data
    assert result.json['score']['rows_scored']==2
    assert 'VOICE_USAGE_SCORE' in result.json['score']['distributions']
    second=pd.DataFrame({'MSISDN':['001','002'],'VOICE_USAGE_SCORE':[7.,9.]})
    with patch.object(scoring,'voice_usage',return_value=second):
        updated=client.post('/analyze',json=payload)
    assert url!=updated.json['score']['download_url']
    assert client.get(url).data==content
    assert client.get(updated.json['score']['download_url']).data!=content


def test_cluster_raw_features_and_saved_model_without_scaler(client):
    groups={'ARPU_CLV_GROWTH':['ARPU_SCORE','CLV_SCORE','GROWTH_SCORE'],'DATA_USAGE':['DATA_USAGE_SCORE'],'VOICE_USAGE':['VOICE_USAGE_SCORE'],
            'Transaction_Frequency':['Transaction_Frequency_SCORE'],'TEMPORAL_STABILITY':['TS_Score'],'CONSISTENCY_INDEX':['CI_Score']}
    for name,columns in groups.items():
        pd.DataFrame({'MSISDN':[str(100+i) for i in range(12)],**{col:np.linspace(1,10,12) for col in columns}}).to_csv(common.SCORE_FILES[name],index=False)
    original=clustering.KMeans.fit;captured={}
    def record(self,values,*args,**kwargs):
        captured['values']=values.copy();captured['k']=self.n_clusters
        return original(self,values,*args,**kwargs)
    with patch.object(clustering.KMeans,'fit',record):
        result=client.post('/cluster',json={'run_stability':False})
    assert result.status_code==200,result.json
    assert captured['k']==3
    np.testing.assert_allclose(captured['values'][:,0],np.linspace(1,10,12))
    assert client.get(result.json['download_url']).status_code==200
    assert client.get(result.json['report_download_url']).status_code==200
    import joblib
    model=joblib.load(next(Path(clustering.MODELS_DIR).glob('*/model.pkl')))
    assert 'scaler' not in model and model['preprocessing']=='none'


def test_monthly_raw_features_and_run_specific_download(client,tmp_path):
    orders=[];data=[];voice=[]
    for month_index,month in enumerate(pd.period_range('2024-01','2024-09',freq='M')):
        for customer in range(12):
            identifier=f'98{9000000000+customer}';date=str(month)+'-15';value=(customer+1)*(month_index+1)
            orders.append([identifier,date,value,30]);data.append([identifier,date,value*100]);voice.append([identifier,date,value*10])
    pd.DataFrame(orders,columns=['MSISDN','PaidDateUtc','OrderTotal','OrderStatusId']).to_csv(tmp_path/'orders.csv',index=False)
    pd.DataFrame(data,columns=['SERVED_MSISDN','START_TIMESTAMP','ACTUAL_USAGE']).to_csv(tmp_path/'data.csv',index=False)
    pd.DataFrame(voice,columns=['Subscriber_MSISDN','Call_Date','Call_Duration']).to_csv(tmp_path/'voice.txt',sep='|',index=False)
    payload={'as_of_month':'2024-09','confirm_complete':True,'run_stability':False,'sources':{'order':str(tmp_path/'orders.csv'),'data_cdr':str(tmp_path/'data.csv'),'voice_cdr':str(tmp_path/'voice.txt')}}
    with patch.object(clustering.KMeans,'fit',side_effect=AssertionError('Churn must not fit clusters')):
        result=client.post('/churn/update',json=payload)
    assert result.status_code==200,result.json
    report=result.json
    assert report['customers']==12 and report['workflow']=='independent_churn'
    assert client.get(report['download_url']).status_code==200
    assert client.get(report['report_download_url']).status_code==200
    assert client.get('/churn/runs/invalid/customers').status_code==404


def test_seven_tabs_brand_and_no_time_estimate(client):
    result=client.get('/');assert result.status_code==200
    page=result.text
    for name in ['Standard','CI','TS','DS','Cluster','Churn','Monthly']:
        assert f'id="tabBtn{name}"' in page and f'id="tab{name}"' in page
    assert 'Churn Prediction' in page and 'Adaptive Learning' in page
    assert 'brand/logo.svg' in page and 'workspace' in page
    progress=client.get('/static/js/progress.js').text
    assert 'زمان سپری‌شده کل' in progress and 'مدت اجرای مراحل' in progress
    assert 'remaining' not in progress.lower()
    for path in ['/static/brand/logo.svg','/static/fonts/Vazirmatn.woff2','/static/css/dashboard.css','/static/vendor/chart.umd.min.js']:
        assert client.get(path).status_code==200
