import pandas as pd
import pytest
from loyalty.identifiers import normalize_identifiers, VERSION
from loyalty.standards import utils, temporal_stability
from loyalty.services import monthly, forecasting


@pytest.mark.parametrize('value',[
    '9121234567','09121234567','989121234567','+989121234567','00989121234567',
    '989121234567.0',989121234567,989121234567.0,'9.89121234567e11',
    '۰۹۱۲۱۲۳۴۵۶۷','٠٩١٢١٢٣٤٥٦٧','+98 (912) 123-4567',
])
def test_mobile_spellings_use_the_same_id_in_every_pipeline(value):
    values=pd.Series([value])
    assert normalize_identifiers(values).iloc[0]=='989121234567'
    frame=pd.DataFrame({'id':values,'date':['2025-01-01'],'amount':[100]})
    for cleaner in [utils.clean_data,temporal_stability.clean_data]:
        assert cleaner(frame.copy(),['id','date','amount']).MSISDN.iloc[0]=='989121234567'
    assert monthly.normalize_ids(values).iloc[0]=='989121234567'


def test_opaque_ids_and_long_numbers_are_preserved_without_float_conversion():
    values=pd.Series(['e6b916d9729755c6','000123','980001','9007199254740993','9.89121234567e-11','9e99999999','account-0001'],dtype='string')
    pd.testing.assert_series_equal(normalize_identifiers(values),values)
    frame=pd.DataFrame({'id':values,'date':['2025-01-01']*len(values),'amount':[100]*len(values)})
    for cleaner in [utils.clean_data,temporal_stability.clean_data]:
        assert cleaner(frame.copy(),['id','date','amount']).MSISDN.tolist()==values.tolist()
    assert monthly.normalize_ids(values).tolist()==values.tolist()


def test_empty_values_and_index_are_handled_consistently():
    values=pd.Series(['  ',None,'  account-01  '],index=[4,5,9],dtype='string')
    result=normalize_identifiers(values)
    assert result.index.tolist()==[4,5,9]
    assert result.iloc[:2].isna().all() and result.loc[9]=='account-01'
    with pytest.raises(ValueError,match='nonempty'):monthly.normalize_ids(values)


def test_recognized_phone_forms_collapse_to_one_customer():
    frame=pd.DataFrame({'id':['9121234567','989121234567','09121234567'],
                        'date':['2025-01-01']*3,'amount':[1,2,3]})
    cleaned=utils.clean_data(frame,['id','date','amount'])
    assert cleaned.groupby('MSISDN').amount.sum().to_dict()=={'989121234567':6}


def test_churn_uses_a_separate_versioned_history_without_rewriting_legacy(tmp_path,monkeypatch):
    parent=tmp_path/'churn';parent.mkdir()
    for name in ['history.sqlite','active_model.pkl','latest_report.json']:(parent/name).write_bytes(b'legacy state')
    monkeypatch.setattr(forecasting,'ROOT',parent/VERSION)
    sources={}
    specs={'order':['MSISDN','PaidDateUtc','OrderTotal','OrderStatusId'],
           'data_cdr':['SERVED_MSISDN','START_TIMESTAMP','ACTUAL_USAGE'],
           'voice_cdr':['Subscriber_MSISDN','Call_Date','Call_Duration']}
    for key,columns in specs.items():
        rows=[['9121234567',str(month)+'-15',100]+([30] if key=='order' else []) for month in pd.period_range('2024-01','2024-09',freq='M')]
        path=tmp_path/(key+'.csv');pd.DataFrame(rows,columns=columns).to_csv(path,index=False);sources[key]=str(path)
    result=forecasting.update({'as_of_month':'2024-09','confirm_complete':True,'sources':sources})
    assert result['identifier_version']==VERSION
    assert (parent/VERSION/'history.sqlite').is_file()
    for name in ['history.sqlite','active_model.pkl','latest_report.json']:assert (parent/name).read_bytes()==b'legacy state'


def test_historical_churn_exports_remain_downloadable(tmp_path,monkeypatch):
    from loyalty import create_app, common
    run='20250101_010101_000001'
    legacy=tmp_path/'churn'/'runs'/run
    legacy.mkdir(parents=True)
    (legacy/'report.json').write_text('{"historical":true}')
    monkeypatch.setattr(common,'OUTPUT_ROOT',tmp_path)
    monkeypatch.setattr(forecasting,'ROOT',tmp_path/'churn'/VERSION)
    response=create_app().test_client().get('/churn/runs/'+run+'/report')
    assert response.status_code==200 and response.json['historical'] is True
    assert create_app().test_client().get('/churn/runs/invalid/report').status_code==404
