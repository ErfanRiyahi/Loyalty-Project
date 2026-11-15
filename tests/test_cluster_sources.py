from io import BytesIO
import json
import time
from pathlib import Path
import pandas as pd
from loyalty import create_app, common
from loyalty.services import clustering
from loyalty.routes import clustering as routes


def setup_sources(tmp_path,monkeypatch):
    keys={'ARPU_CLV_GROWTH':['ARPU_SCORE','CLV_SCORE','GROWTH_SCORE'],
          'DATA_USAGE':['DATA_USAGE_SCORE'],'VOICE_USAGE':['VOICE_USAGE_SCORE'],
          'Transaction_Frequency':['Transaction_Frequency_SCORE'],
          'TEMPORAL_STABILITY':['TS_Score'],'CONSISTENCY_INDEX':['CI_Score']}
    defaults={key:str(tmp_path/f'default_{key}.csv') for key in keys}
    for module in [common,clustering,routes]:
        monkeypatch.setattr(module,'SCORE_FILES',defaults)
        monkeypatch.setattr(module,'OUTPUT_ROOT',tmp_path)
    monkeypatch.setattr(clustering,'MODELS_DIR',str(tmp_path/'models'))
    monkeypatch.setattr(clustering,'CLUSTER_CONFIG_FILE',str(tmp_path/'config.json'))
    monkeypatch.setattr(clustering,'MODEL_REGISTRY_FILE',str(tmp_path/'registry.json'))
    selected={}
    for key,columns in keys.items():
        path=tmp_path/f'chosen_{key}.csv'
        pd.DataFrame({'MSISDN':[str(n).zfill(5) for n in range(12)],
                      **{col:[1+n*.7 for n in range(12)] for col in columns}}).to_csv(path,index=False)
        selected[key]=str(path)
    return create_app().test_client(),selected,defaults


def test_custom_paths_and_inventory_do_not_overwrite_default_scores(tmp_path,monkeypatch):
    client,selected,defaults=setup_sources(tmp_path,monkeypatch)
    assert all(not row['exists'] for row in client.get('/cluster/sources').json['sources'])
    response=client.post('/cluster',json={'input_mode':'custom','sources':selected,'run_stability':False})
    assert response.status_code==200,response.json
    assert response.json['n_customers']==12
    assert all(not Path(path).exists() for path in defaults.values())
    report=json.loads((tmp_path/'cluster_validation.json').read_text())
    assert {row['path'] for row in report['source_files']}==set(selected.values())
    # Validation happens before merging, to prevent inflated joins.
    frame=pd.read_csv(selected['DATA_USAGE']);pd.concat([frame,frame.iloc[:1]]).to_csv(selected['DATA_USAGE'],index=False)
    assert client.post('/cluster',json={'input_mode':'custom','sources':selected,'run_stability':False}).status_code==400


def test_multiple_uploads_work_through_background_job(tmp_path,monkeypatch):
    client,selected,defaults=setup_sources(tmp_path,monkeypatch)
    fields={'path':'/cluster','payload':json.dumps({'input_mode':'custom','sources':{},'run_stability':False})}
    for key,path in selected.items():
        fields[key]=(BytesIO(Path(path).read_bytes()),f'uploaded_{key}.csv')
    response=client.post('/jobs',data=fields,content_type='multipart/form-data')
    assert response.status_code==202,response.json
    for _ in range(300):
        result=client.get('/jobs/'+response.json['operation_id']).json
        if result['status']!='running':break
        time.sleep(.02)
    assert result['status']=='succeeded',result
    assert result['result']['n_customers']==12
    report=json.loads((tmp_path/'cluster_validation.json').read_text())
    assert all(row['path'].startswith('uploaded_') for row in report['source_files'])
    assert all(not Path(path).exists() for path in defaults.values())
