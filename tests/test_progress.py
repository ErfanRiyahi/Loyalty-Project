"""Checks real telemetry, output compatibility, isolation, errors and retries."""
import io
import time
from threading import Event
from unittest.mock import patch
import pandas as pd
from flask import jsonify
from loyalty import create_app
from loyalty.progress import stage_scope, units


def finished(client, ident):
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        value=client.get('/jobs/'+ident).json
        if value['status'] != 'running': return value
        time.sleep(.01)
    raise AssertionError('worker did not finish')


def test_real_stages_idempotency_locks_and_recovery():
    app=create_app(); client=app.test_client(); entered=Event(); release=Event()
    def actual_work():
        with stage_scope('Actual test stage'):
            units(12, total=20)
            entered.set()
            assert release.wait(5)
        return jsonify(done=True)
    app.view_functions['scoring.dataset_overview_route']=actual_work
    response=client.post('/jobs',json={'path':'/dataset_overview','body':{}},headers={'Idempotency-Key':'same'})
    ident=response.json['operation_id']
    try:
        assert entered.wait(5)
        report=client.get('/jobs/'+ident).json
        assert report['status']=='running' and report['percentage'] is None
        assert report['stage']=='Actual test stage'
        assert report['events'][-1]['completed_units']==12
        assert 'remaining_seconds' not in report
        assert client.post('/jobs',json={'path':'/cluster'}).status_code==409
        assert client.post('/cluster',json={}).status_code==409
        same=client.post('/jobs',json={'path':'/dataset_overview'},headers={'Idempotency-Key':'same'})
        assert same.json['operation_id']==ident
        assert client.get('/jobs/request/same').json['operation_id']==ident
        # A separate client can retrieve the same job without restarting work.
        assert app.test_client().get('/jobs/'+ident).json['stage']==report['stage']
    finally:release.set()
    done=finished(client,ident)
    assert done['percentage']==100 and done['result']=={'done':True}
    assert all(e['status']=='completed' for e in done['events'])
    assert all(e['elapsed_seconds']>=0 for e in done['events'])


def test_failure_never_reports_completion_and_next_job_is_clean():
    app=create_app();client=app.test_client()
    def broken():
        with stage_scope('Failed calculation'):raise ValueError('test failure')
    app.view_functions['scoring.dataset_overview_route']=broken
    ident=client.post('/jobs',json={'path':'/dataset_overview'}).json['operation_id']
    report=finished(client,ident)
    assert report['status']=='failed' and report['percentage'] is None
    assert any(e['status']=='failed' for e in report['events'])
    app.view_functions['scoring.dataset_overview_route']=lambda:jsonify(done=True)
    second=client.post('/jobs',json={'path':'/dataset_overview'}).json['operation_id']
    assert second!=ident
    report2=finished(client,second)
    assert report2['status']=='succeeded'
    assert not any(e['label']=='Failed calculation' for e in report2['events'])
    assert client.get('/jobs/not-present').status_code==404


def test_score_result_matches_synchronous_api_and_reports_real_work(tmp_path):
    app=create_app();client=app.test_client()
    source=tmp_path/'voice.csv'
    pd.DataFrame([{'MSISDN':'98'+str(900+i),'date':f'2026-{m:02d}-10','Call_Duration':(i+1)*m} for i in range(12) for m in range(1,7)]).to_csv(source,index=False)
    body={'standard':'VOICE_USAGE','dataset_address':str(source),'required_columns':['MSISDN','date','Call_Duration']}
    direct=client.post('/analyze',json=body)
    assert direct.status_code==200,direct.json
    ident=client.post('/jobs',json={'path':'/analyze','body':body}).json['operation_id']
    report=finished(client,ident)
    assert report['status']=='succeeded',report
    direct_data=direct.json
    async_data=report['result']
    direct_url=direct_data['score'].pop('download_url')
    async_url=async_data['score'].pop('download_url')
    assert client.get(direct_url).data==client.get(async_url).data
    assert async_data==direct_data
    labels=[e['label'] for e in report['events']]
    assert 'Clean data and convert types' in labels
    assert 'Select the latest six months' in labels
    assert 'Save output file' in labels


def test_upload_and_api_failures():
    app=create_app();client=app.test_client()
    assert client.post('/jobs',json={'path':'/unknown'}).status_code==400
    assert client.post('/jobs',json=[]).status_code==400
    data={'path':'/churn/assess','method':'baseline','file':(io.BytesIO(b'MSISDN,ARPU_SCORE,DATA_USAGE_SCORE\n001,1,1\n002,2,2\n003,3,3\n'),'scores.csv')}
    ident=client.post('/jobs',data=data).json['operation_id']
    report=finished(client,ident)
    assert report['status']=='succeeded',report
    assert report['result']['rows']==3
    ident=client.post('/jobs',json={'path':'/monthly/update','body':{}}).json['operation_id']
    report=finished(client,ident)
    assert report['status']=='failed' and report['http_status']==400
    assert report['percentage'] is None and 'error' in report['result']


def test_monthly_job_reports_processed_rows_and_real_model_stages(tmp_path):
    from loyalty.services import monthly
    orders=[];data=[];voice=[]
    for index,month in enumerate(pd.period_range('2024-01','2024-09',freq='M')):
        for customer in range(12):
            identifier=f'98{9000000000+customer}'
            date=str(month)+'-15'
            value=(customer+1)*(index+1)
            orders.append([identifier,date,value,30])
            data.append([identifier,date,value*100])
            voice.append([identifier,date,value*10])
    pd.DataFrame(orders,columns=['MSISDN','PaidDateUtc','OrderTotal','OrderStatusId']).to_csv(tmp_path/'orders.csv',index=False)
    pd.DataFrame(data,columns=['SERVED_MSISDN','START_TIMESTAMP','ACTUAL_USAGE']).to_csv(tmp_path/'data.csv',index=False)
    pd.DataFrame(voice,columns=['Subscriber_MSISDN','Call_Date','Call_Duration']).to_csv(tmp_path/'voice.txt',sep='|',index=False)
    body={'as_of_month':'2024-09','confirm_complete':True,'run_stability':False,
          'sources':{'order':str(tmp_path/'orders.csv'),'data_cdr':str(tmp_path/'data.csv'),'voice_cdr':str(tmp_path/'voice.txt')}}
    with patch.object(monthly,'ROOT',tmp_path/'monthly_outputs'):
        client=create_app().test_client()
        ident=client.post('/jobs',json={'path':'/monthly/update','body':body}).json['operation_id']
        report=finished(client,ident)
    assert report['status']=='succeeded',report
    assert report['result']['customers']==12
    source_events=[e for e in report['events'] if e['completed_units'] is not None]
    assert len(source_events)==3
    assert all(e['completed_units']==108 and e['total_units'] is None for e in source_events)
    labels=[e['label'] for e in report['events']]
    assert 'Train and evaluate three-month inactivity prediction' in labels
    assert 'Validate cluster quality and stability' in labels
    assert 'Save output file' in labels
