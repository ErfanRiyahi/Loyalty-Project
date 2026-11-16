import pandas as pd
from loyalty import create_app, common
from loyalty.routes import scoring
from loyalty.standards.consistency_index import consistency_index

COLUMNS=['id','date','value']


def source(identifier='980001',start='2025-01',periods=6,value=30):
    return pd.DataFrame({'id':[identifier]*periods,'date':[str(month)+'-15' for month in pd.period_range(start,periods=periods,freq='M')],'value':[value]*periods})


def compute(frames,details=True):
    return consistency_index(*[item for frame in frames for item in [frame,COLUMNS]],return_diagnostics=details)


def test_disjoint_cohorts_and_dates_are_explained_without_inventing_scores():
    frames=[source('980001','2025-12',1),source('980002','2025-12',1),source('980003'),source('980003')]
    result,details=compute(frames)
    assert result.empty
    assert details['common_customers']==0 and details['common_months']==[]
    assert {item['code'] for item in details['warnings']}=={'no_common_customers','no_common_months','short_history'}
    assert all(item['scored_customers']==1 for item in details['domains'].values())
    assert next(item for item in details['pairwise_common_customers'] if item['first']=='spend' and item['second']=='txn')['count']==1


def test_diagnostics_do_not_change_the_existing_scoring_result():
    frames=[source() for _ in range(4)]
    normal=compute(frames,False)
    result,details=compute(frames)
    pd.testing.assert_frame_equal(normal,result)
    assert len(result)==details['common_customers']==1
    assert len(details['common_months'])==6
    assert details['warnings']==[]


def test_empty_domain_after_cleaning_returns_explanation():
    empty=source();empty['value']=None
    result,details=compute([empty,source(),source(),source()])
    assert result.empty
    assert details['domains']['data']['scored_customers']==0
    assert details['domains']['data']['input_rows_with_missing_fields']==6
    assert 'empty_domain' in [item['code'] for item in details['warnings']]


def test_consistency_api_includes_diagnostics_and_downloadable_report(tmp_path,monkeypatch):
    monkeypatch.setattr(common,'OUTPUT_ROOT',tmp_path)
    paths={**scoring.SCORE_FILES,'CONSISTENCY_INDEX':str(tmp_path/'CONSISTENCY_INDEX_SCORE.csv')}
    monkeypatch.setattr(scoring,'SCORE_FILES',paths)
    inputs={}
    for domain,identifier in [('data','980001'),('voice','980002'),('spend','980003'),('txn','980003')]:
        path=tmp_path/(domain+'.csv');source(identifier).to_csv(path,index=False)
        inputs[domain]={'dataset_address':str(path),'columns':COLUMNS}
    client=create_app().test_client()
    response=client.post('/consistency_index',json={'domains':inputs})
    assert response.status_code==200,response.json
    score=response.json['score']
    assert score['rows_scored']==0 and score['diagnostics']['common_customers']==0
    report=client.get(score['report_download_url'])
    assert report.status_code==200 and report.json['output_customers']==0
    assert client.get(score['download_url']).status_code==200
