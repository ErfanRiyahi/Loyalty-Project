import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from loyalty import create_app
from loyalty.services import monthly, retention


def test_three_month_target_and_incomplete_followup():
    frame = pd.DataFrame({'MSISDN':['a','b','c','d'], 'history_months':[6]*4,
                          'consecutive_inactive_months':[2,0,3,0]})
    rows=[]
    for month in pd.period_range('2025-01','2025-05',freq='M'):
        for customer in ['a','b','c','d']:
            if customer=='d' and str(month)=='2025-05': continue
            active = customer=='b' or (customer=='a' and str(month)>='2025-04')
            rows.append([customer,str(month),int(active),0,0])
    panel=pd.DataFrame(rows,columns=['MSISDN','month','orders','data','voice'])
    y=retention.target(frame,panel,'2025-02','2025-05')
    assert y.iloc[0]==1  # Jan/Feb/Mar inactive, even if activity resumes in April.
    assert y.iloc[1]==0  # Activity in any one domain prevents inactivity churn.
    assert pd.isna(y.iloc[2])  # Already churned, excluded from prospective model.
    assert pd.isna(y.iloc[3])  # Incomplete observation never becomes a negative label.
    assert retention.target(frame,panel,'2025-02','2025-04').isna().all()


def make_history():
    months=pd.period_range('2022-01','2024-06',freq='M')
    rows=[]
    for i,month in enumerate(months):
        for customer in range(40):
            active=i<3 or ((i+customer)%9)<5
            level=(customer+1) if active else 0
            rows.append([str(customer).zfill(4),str(month),level,level*100,level*10,level*50])
    panel=pd.DataFrame(rows,columns=['MSISDN','month','orders','data','voice','spend'])
    first=panel.groupby('MSISDN').month.min()
    snapshots=[monthly.snapshot(panel,first,month) for month in months[5:]]
    return months,panel,snapshots


def test_model_target_explanations_churn_separation_and_mature_splits(tmp_path):
    months,panel,snapshots=make_history()
    output,report=retention.predict(snapshots,panel,months[-1],tmp_path)
    assert report['status']=='trained'
    assert report['horizon_months']==3
    assert report['evaluation_status']=='held_out'
    assert pd.Period(report['training_labels_observed_through'],'M') <= pd.Period(report['validation_month'],'M')
    assert pd.Period(report['validation_month'],'M')+3 <= pd.Period(report['test_month'],'M')
    assert pd.Period(report['test_month'],'M')+3 <= months[-1]
    churned=output.loc[output.consecutive_inactive_months>=3]
    assert len(churned)>0 and churned.churn_probability.isna().all()
    assert churned.retention_status.eq('churned').all()
    assert output.risk_reasons.str.len().gt(0).all()
    assert output.loc[output.retention_status=='at_risk','churn_probability'].ge(.5).all()
    assert (tmp_path/'retention_model.pkl').is_file()


def test_no_fabricated_probabilities_when_labels_not_mature(tmp_path):
    months,panel,snapshots=make_history()
    last=months[7]
    selected=[frame for frame in snapshots if frame.snapshot_month.iloc[0]<=str(last)]
    output,report=retention.predict(selected,panel.loc[panel.month<=str(last)],last,tmp_path)
    assert report['status']=='insufficient_training_data'
    assert output.churn_probability.isna().all()
    assert not output.retention_status.eq('at_risk').any()


def test_customer_api_filters_pagination_and_export_all_rows(tmp_path):
    root=tmp_path/'monthly';run='20260101_010101_000001';directory=root/'runs'/run;directory.mkdir(parents=True)
    rows=[]
    for i in range(110):
        rows.append({'MSISDN':str(i).zfill(4),'retention_status':'at_risk','risk_level':'high' if i<10 else 'medium',
                     'churn_probability':.9-i/1000,'last_active_month':'2025-11','consecutive_inactive_months':1,
                     'forecast_through':'2026-03','risk_reasons':'کاهش مصرف','model_factors':'مصرف اینترنت'})
    rows.append({**rows[0],'MSISDN':'9999','retention_status':'churned','risk_level':'none','churn_probability':np.nan,'consecutive_inactive_months':3})
    pd.DataFrame(rows).to_csv(directory/'retention.csv',index=False)
    report={'run_id':run,'as_of_month':'2025-12','predicting_month':'2026-03','retention_version':retention.VERSION,'learning':{'status':'trained'}}
    (root/'latest_report.json').write_text(json.dumps(report))
    with patch.object(monthly,'ROOT',root):
        client=create_app().test_client()
        response=client.get('/churn/customers?page=5')
        assert response.status_code==200
        assert response.json['total']==110 and len(response.json['rows'])==10
        assert response.json['rows'][0]['priority']==101
        assert client.get('/churn/customers?status=churned').json['total']==1
        assert client.get('/churn/customers?risk=high').json['total']==10
        assert client.get('/churn/customers?q=0001').json['rows'][0]['MSISDN']=='0001'
        csv=client.get('/churn/customers/download').data.decode('utf-8-sig')
        assert len(csv.strip().splitlines())==111  # Entire selection, never only the preview/page.
        assert '9999' not in csv
        assert client.get('/churn/customers?page=-1').status_code==400
        report.pop('retention_version');(root/'latest_report.json').write_text(json.dumps(report))
        assert client.get('/churn/customers').status_code==400  # Reject legacy next-month models.


def test_monthly_ingestion_to_retention_list(tmp_path):
    months,panel,_=make_history()
    paths={}
    for source,domain,columns in [
        ('order','orders',['MSISDN','PaidDateUtc','OrderTotal','OrderStatusId']),
        ('data_cdr','data',['SERVED_MSISDN','START_TIMESTAMP','ACTUAL_USAGE']),
        ('voice_cdr','voice',['Subscriber_MSISDN','Call_Date','Call_Duration'])]:
        rows=[]
        for row in panel.loc[panel[domain]>0].itertuples():
            values=['98'+row.MSISDN,row.month+'-15',getattr(row,domain)]
            if source=='order':values.append(30)
            rows.append(values)
        path=tmp_path/(source+'.csv');pd.DataFrame(rows,columns=columns).to_csv(path,index=False);paths[source]=str(path)
    with patch.object(monthly,'ROOT',tmp_path/'monthly'):
        client=create_app().test_client()
        response=client.post('/monthly/update',json={'as_of_month':str(months[-1]),'confirm_complete':True,'run_stability':False,'sources':paths})
        assert response.status_code==200,response.json
        report=response.json
        assert report['retention_version']==retention.VERSION
        assert report['learning']['status']=='trained'
        assert report['retention_counts']['churned']>0
        assert client.get('/churn/customers?status=churned').json['total']>0
        assert client.get('/churn/customers/download?status=all').status_code==200
