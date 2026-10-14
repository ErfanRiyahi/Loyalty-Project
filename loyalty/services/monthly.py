"""Monthly batch learning from the existing source schemas.

Events are retained locally; snapshots/targets are built with explicit month cutoffs.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.preprocessing import RobustScaler, StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, roc_auc_score, brier_score_loss,
                             confusion_matrix, precision_score, recall_score)

from ..common import OUTPUT_ROOT, source_path, json_safe, source_read_options
from .validation import validate_clusters

ROOT = OUTPUT_ROOT / 'monthly'
SOURCES = {
    'order': ('MSISDN', 'PaidDateUtc', 'OrderTotal'),
    'data_cdr': ('SERVED_MSISDN', 'START_TIMESTAMP', 'ACTUAL_USAGE'),
    'voice_cdr': ('Subscriber_MSISDN', 'Call_Date', 'Call_Duration'),
}
ACTIVITY = ['orders', 'data', 'voice']
FEATURES = [f'{domain}_{part}' for domain in ACTIVITY for part in ['log_current','log_mean3','log_mean6','ratio','inactive_months']]
CLUSTER_FEATURES = ['ARPU_SCORE', 'CLV_SCORE', 'GROWTH_SCORE', 'DATA_USAGE_SCORE', 'VOICE_USAGE_SCORE', 'Transaction_Frequency_SCORE']


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(json_safe(value), indent=2, allow_nan=False))
    temporary.replace(path)


def normalize_ids(values):
    # Preserve the supplied cleaners' string-ID rule. Do not silently change it.
    result = values.astype('string').str[2:]
    if result.isna().any() or result.str.strip().eq('').any():
        raise ValueError('Legacy removal of the first two ID characters produced an empty ID. Check source identifiers.')
    return result


def ingest(paths):
    ROOT.mkdir(parents=True, exist_ok=True)
    report = {}
    with sqlite3.connect(ROOT / 'history.sqlite') as database:
        database.execute('CREATE TABLE IF NOT EXISTS events (source TEXT, event_key TEXT, customer TEXT, month TEXT, value REAL, successful INTEGER, occurrences INTEGER, PRIMARY KEY(source,event_key))')
        for source, (id_col, date_col, value_col) in SOURCES.items():
            path = str(paths.get(source) or source_path(source))
            required = [id_col, date_col, value_col]
            if source == 'order': required.append('OrderStatusId')
            read_options = source_read_options(path, required)
            header = pd.read_csv(path, **read_options, nrows=0).columns.tolist()
            absent = [col for col in required if col not in header]
            if absent: raise ValueError(f'{source}: missing columns {absent}')
            # Orders can be corrected reliably if their event Id is supplied.
            event_id = 'Id' if source == 'order' and 'Id' in header else None
            selected = required + ([event_id] if event_id else [])
            database.execute('CREATE TEMP TABLE IF NOT EXISTS incoming (event_key TEXT PRIMARY KEY, customer TEXT, month TEXT, value REAL, successful INTEGER, occurrences INTEGER)')
            database.execute('DELETE FROM incoming')
            read_rows = dropped = 0
            for chunk in pd.read_csv(path, **read_options, usecols=selected,
                                     dtype={id_col:'string', **({event_id:'string'} if event_id else {})},
                                     low_memory=True, chunksize=100000):
                incoming = Counter()
                payloads = {}
                read_rows += len(chunk)
                dates = pd.to_datetime(chunk[date_col], errors='coerce', utc=True)
                values = pd.to_numeric(chunk[value_col], errors='coerce')
                valid = dates.notna() & chunk[id_col].notna() & values.notna() & np.isfinite(values) & (values >= 0)
                if event_id: valid &= chunk[event_id].notna()
                dropped += int((~valid).sum())
                chunk = chunk.loc[valid].copy()
                ids = normalize_ids(chunk[id_col])
                months = dates.loc[valid].dt.strftime('%Y-%m')
                status = pd.to_numeric(chunk['OrderStatusId'], errors='coerce').eq(30) if source == 'order' else pd.Series(True,index=chunk.index)
                for index in chunk.index:
                    if event_id:
                        key = 'id:' + str(chunk.loc[index,event_id])
                    else:
                        # Preserve within-delivery multiplicity; repeat/overlap feeds do not add it again.
                        raw = [str(chunk.loc[index,col]) for col in required]
                        key = hashlib.sha256(json.dumps(raw,ensure_ascii=False).encode()).hexdigest()
                    incoming[key] += 1
                    payloads[key] = (str(ids.loc[index]),str(months.loc[index]),float(values.loc[index]),int(status.loc[index]))
                records=[(key,*payloads[key],1 if event_id else count) for key,count in incoming.items()]
                database.executemany('INSERT INTO incoming VALUES (?,?,?,?,?,?) ON CONFLICT(event_key) DO UPDATE SET customer=excluded.customer,month=excluded.month,value=excluded.value,successful=excluded.successful,occurrences=incoming.occurrences+excluded.occurrences',records)
            if event_id:
                database.execute('INSERT INTO events SELECT ?,event_key,customer,month,value,successful,1 FROM incoming WHERE 1 ON CONFLICT(source,event_key) DO UPDATE SET customer=excluded.customer,month=excluded.month,value=excluded.value,successful=excluded.successful,occurrences=1',(source,))
            else:
                database.execute('INSERT INTO events SELECT ?,event_key,customer,month,value,successful,occurrences FROM incoming WHERE 1 ON CONFLICT(source,event_key) DO UPDATE SET occurrences=MAX(events.occurrences,excluded.occurrences)',(source,))
            report[source] = {'path':path,'input_rows':read_rows,'invalid_rows_skipped':dropped,
                              'deduplication':'Id upsert' if event_id else 'Exact selected-field fingerprint, maximum multiplicity across deliveries',
                              'stored_events':database.execute('SELECT COALESCE(SUM(occurrences),0) FROM events WHERE source=?',(source,)).fetchone()[0]}
        database.commit()
    return report


def aggregates(as_of):
    with sqlite3.connect(ROOT / 'history.sqlite') as database:
        all_data = pd.read_sql_query('SELECT source,customer,month,SUM(value*occurrences) AS volume,SUM(occurrences) AS frequency FROM events WHERE successful=1 AND month<=? GROUP BY source,customer,month', database,params=[str(as_of)])
    if all_data.empty: raise ValueError('No usable historical events through this month.')
    first_by_source = all_data.groupby('source')['month'].min()
    if set(first_by_source.index) != set(SOURCES): raise ValueError('All three sources need usable historical events.')
    start = pd.Period(max(first_by_source),freq='M')
    if as_of.ordinal - start.ordinal < 6: raise ValueError('At least seven complete common-history months are needed. Provide the historical files for initial setup.')
    months = pd.period_range(start, as_of, freq='M')
    ids = sorted(all_data['customer'].unique())
    index = pd.MultiIndex.from_product([ids,months.astype(str)],names=['MSISDN','month'])
    panel = pd.DataFrame(index=index)
    for source, name in [('order','orders'),('data_cdr','data'),('voice_cdr','voice')]:
        data = all_data.loc[all_data.source==source].set_index(['customer','month'])
        panel[name] = data['frequency' if source=='order' else 'volume'].reindex(index).fillna(0)
        if source=='order': panel['spend'] = data['volume'].reindex(index).fillna(0)
    first_seen = all_data.groupby('customer')['month'].min()
    return panel.reset_index(), first_seen, months


def snapshot(panel, first_seen, month):
    month = pd.Period(month,freq='M')
    ids = first_seen.loc[first_seen <= str(month)].index
    recent = pd.period_range(month-5,month,freq='M').astype(str)
    frame = pd.DataFrame(index=ids)
    frame.index.name='MSISDN'
    frame['snapshot_month']=str(month)
    frame['history_months'] = [month.ordinal-pd.Period(first_seen.loc[item],freq='M').ordinal+1 for item in ids]
    for domain in ACTIVITY+['spend']:
        values = panel.loc[panel.month.isin(recent)].pivot(index='MSISDN',columns='month',values=domain).reindex(index=ids,columns=recent).fillna(0)
        mean3=values.iloc[:,-3:].mean(axis=1)
        frame[domain+'_current']=values.iloc[:,-1]
        frame[domain+'_mean3']=mean3
        frame[domain+'_mean6']=values.mean(axis=1)
        frame[domain+'_previous3']=values.iloc[:,:3].mean(axis=1)
        frame[domain+'_weighted6']=values.dot(np.array([.05,.10,.15,.20,.25,.25]))
        frame[domain+'_recent3_median']=values.iloc[:,-3:].median(axis=1)
        frame[domain+'_previous3_median']=values.iloc[:,:3].median(axis=1)
        if domain == 'spend': frame['weighted_arpu']=values.dot(np.array([1,1,1,2,2,2])) / 9
        if domain in ACTIVITY:
            frame[domain+'_log_current']=np.log1p(frame[domain+'_current'])
            frame[domain+'_log_mean3']=np.log1p(mean3)
            frame[domain+'_log_mean6']=np.log1p(frame[domain+'_mean6'])
            frame[domain+'_ratio']=(frame[domain+'_current']/frame[domain+'_previous3'].replace(0,np.nan)).clip(0,10).fillna(1)
            frame[domain+'_inactive_months']=(values==0).sum(axis=1)
    previous = frame.spend_previous3_median
    frame['growth_pct'] = ((frame.spend_recent3_median/previous.replace(0,np.nan)-1)*100).replace([np.inf,-np.inf],np.nan).fillna(0)
    return frame.reset_index()


def targets(frame, panel, next_month):
    outcome = panel.loc[panel.month==str(next_month)].set_index('MSISDN')
    drops=[]
    for domain in ACTIVITY:
        baseline=frame[domain+'_mean3']
        actual=frame.MSISDN.map(outcome[domain]).fillna(0)
        drops.append((baseline>0) & (actual <= .5*baseline))
    active = sum(frame[d+'_mean3'].gt(0).astype(int) for d in ACTIVITY)
    eligible=(active>=2)&(frame.history_months>=3)
    y=(sum(drop.astype(int) for drop in drops)>=2).astype(int).where(eligible)
    return y


def fit_references(frame):
    references={}
    for feature, raw in [('ARPU_SCORE','weighted_arpu'),('DATA_USAGE_SCORE','data_mean6'),('VOICE_USAGE_SCORE','voice_mean6'),('Transaction_Frequency_SCORE','orders_mean6'),('GROWTH_SCORE','growth_pct')]:
        references[feature]=[float(frame[raw].quantile(.05)),float(frame[raw].quantile(.95))]
    positive=frame.loc[frame.spend_weighted6>0,'spend_weighted6']
    references['BaseCLV']=float(positive.median()) if len(positive) else 1.
    return references


def apply_references(frame, refs, prefix=''):
    result=frame.copy()
    for feature,raw in [('ARPU_SCORE','weighted_arpu'),('DATA_USAGE_SCORE','data_mean6'),('VOICE_USAGE_SCORE','voice_mean6'),('Transaction_Frequency_SCORE','orders_mean6'),('GROWTH_SCORE','growth_pct')]:
        lower,upper=refs[feature]
        result[prefix+feature] = (1+9*(frame[raw]-lower)/(upper-lower)).clip(1,10) if upper>lower else 5.
    result[prefix+'CLV_SCORE']=(5+2*np.log10(frame.spend_weighted6.clip(lower=1e-9)/max(refs['BaseCLV'],1e-9))).clip(1,10)
    return result


def metrics(y, probabilities):
    predicted=(probabilities>=.5).astype(int)
    return {'rows':len(y),'positive_rate':float(np.mean(y)),
            'confusion_matrix':confusion_matrix(y,predicted,labels=[0,1]).tolist(),
            'matrix_labels':['No qualifying decline','Qualifying next-month decline'],
            'precision':float(precision_score(y,predicted,zero_division=0)),
            'recall':float(recall_score(y,predicted,zero_division=0)),
            'average_precision':float(average_precision_score(y,probabilities)) if np.sum(y)>0 else None,
            'roc_auc':float(roc_auc_score(y,probabilities)) if len(np.unique(y))==2 else None,
            'brier':float(brier_score_loss(y,probabilities))}


def train_predict(snapshots, panel, latest, run_dir):
    labeled=[]
    for frame in snapshots[:-1]:
        frame=frame.copy()
        frame['target']=targets(frame,panel,pd.Period(frame.snapshot_month.iloc[0],freq='M')+1)
        labeled.append(frame.loc[frame.target.notna()])
    history=pd.concat(labeled,ignore_index=True) if labeled else pd.DataFrame()
    current=snapshots[-1].copy()
    report={'target':'At least two active order/data/voice domains decline >=50% next month versus preceding three-month mean',
            'horizon_months':1,'threshold':.5,'status':'insufficient_training_data'}
    current['decline_probability']=np.nan
    current['prediction_status']='Insufficient training data'
    current['predicted_next_month']=str(latest+1)
    if history.empty: return current,report
    periods=sorted(history.snapshot_month.unique())
    if len(periods)<4: return current,report
    train=history.loc[history.snapshot_month<periods[-2]]
    validation=history.loc[history.snapshot_month==periods[-2]]
    test=history.loc[history.snapshot_month==periods[-1]]
    if len(train)<30 or train.target.nunique()!=2 or train.target.value_counts().min()<5 or test.empty:
        report['reason']='Need at least four labeled months, 30 training rows, and at least five examples of each class in training.'
        return current,report
    candidate=make_pipeline(StandardScaler(),LogisticRegression(max_iter=1000,random_state=42))
    candidate.fit(train[FEATURES],train.target.astype(int))
    candidate_scores=candidate.predict_proba(test[FEATURES])[:,1]
    candidate_test=metrics(test.target.astype(int).to_numpy(),candidate_scores)
    active_path=ROOT/'churn_model.pkl'
    champion=None
    champion_metrics=None
    if active_path.exists():
        saved=joblib.load(active_path)
        # Never evaluate a model trained on this test period (e.g. an older-month replay).
        if saved['train_through']<periods[-1]:
            champion=saved['pipeline']
            champion_metrics=metrics(test.target.astype(int).to_numpy(),champion.predict_proba(test[FEATURES])[:,1])
    promote = champion is None or (candidate_test['average_precision'] is not None and
              champion_metrics['average_precision'] is not None and
              candidate_test['average_precision']>=champion_metrics['average_precision']-.02 and
              candidate_test['brier']<=champion_metrics['brier']+.02)
    deployed=candidate if promote else champion
    joblib.dump({'pipeline':candidate,'train_through':periods[-3],'features':FEATURES},run_dir/'churn_candidate.pkl')
    if promote: joblib.dump({'pipeline':candidate,'train_through':periods[-3],'features':FEATURES},active_path)
    eligible=(current.history_months>=3)&(sum(current[d+'_mean3'].gt(0).astype(int) for d in ACTIVITY)>=2)
    current.loc[eligible,'decline_probability']=deployed.predict_proba(current.loc[eligible,FEATURES])[:,1] if eligible.any() else []
    current['prediction_status']=np.where(~eligible,'Insufficient prior activity',np.where(current.decline_probability>=.5,'Likely decline','Lower estimated decline risk'))
    report.update(status='trained',algorithm='StandardScaler + L2 logistic regression',
                  training_months=sorted(train.snapshot_month.unique()),validation_month=periods[-2],test_month=periods[-1],
                  candidate_test=candidate_test,champion_test=champion_metrics,promoted=promote,
                  validation=metrics(validation.target.astype(int).to_numpy(),candidate.predict_proba(validation[FEATURES])[:,1]) if len(validation) else None,
                  note='Fixed threshold 0.5; chronological validation/test. These are activity-decline labels, not cancellation outcomes. Same-customer recurrence across months is intentional.')
    return current,report


def run_monthly(payload):
    ROOT.mkdir(parents=True,exist_ok=True)
    if payload.get('confirm_complete') is not True:
        raise ValueError('Confirm that all three feeds are complete through the selected observation month. Missing feed data must not be labeled as inactivity.')
    try: as_of=pd.Period(payload['as_of_month'],freq='M')
    except Exception as exc: raise ValueError('as_of_month must be YYYY-MM.') from exc
    if str(as_of)!=payload['as_of_month']: raise ValueError('Use YYYY-MM.')
    if as_of>=pd.Timestamp.now(tz='UTC').tz_localize(None).to_period('M'): raise ValueError('Select a completed month before the current calendar month.')
    state_path=ROOT/'state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    if state.get('as_of_month') and str(as_of)<state['as_of_month']: raise ValueError('Monthly updates must not move backwards. Use a separate output folder for historical experiments.')
    ingestion=ingest(payload.get('sources',{}))
    panel, first_seen, months=aggregates(as_of)
    snapshots=[snapshot(panel,first_seen,month) for month in months[5:]]
    current=snapshots[-1]
    quarter=str(as_of.asfreq('Q'))
    ref_path=ROOT/'references'/f'{quarter}.json'
    if ref_path.exists(): references=json.loads(ref_path.read_text())
    else:
        # Build references from data before the quarter; no future-month leakage.
        prior=pd.Period(quarter,freq='Q').asfreq('M','start')-1
        ref_month=min(prior,as_of)
        reference_frames=[snapshot(panel,first_seen,ref_month-offset) for offset in [2,1,0]]
        ref_frame=pd.concat(reference_frames,ignore_index=True)
        if ref_frame.empty:
            ref_frame=current
            ref_month=as_of
        references={'quarter':quarter,'reference_month':str(ref_month),'global':fit_references(ref_frame),'peer':{},
                    'note':'Global and peer parameters remain fixed through this quarter; unseen groups use global references.'}
    scored=apply_references(current,references['global'])
    scaler=RobustScaler()
    X=scaler.fit_transform(scored[CLUSTER_FEATURES])
    if len(X)<3 or np.unique(X,axis=0).shape[0]<3: raise ValueError('Monthly k=3 needs at least three customers and three distinct feature vectors.')
    km=KMeans(n_clusters=3,n_init=10,random_state=42).fit(X)
    labels=km.labels_
    previous_path=ROOT/'latest_assignments.csv'
    mapping={}
    if previous_path.exists():
        old=pd.read_csv(previous_path,dtype={'MSISDN':'string'})
        overlap=pd.DataFrame({'MSISDN':current.MSISDN,'raw':labels}).merge(old,on='MSISDN')
        if len(overlap):
            matrix=pd.crosstab(overlap.raw,overlap.cluster_id).reindex(index=range(3),columns=range(3),fill_value=0).to_numpy()
            rows,cols=linear_sum_assignment(-matrix)
            mapping=dict(zip(rows.tolist(),cols.tolist()))
    if not mapping:
        order=scored.assign(raw=labels).groupby('raw')[CLUSTER_FEATURES].mean().mean(axis=1).sort_values().index
        mapping=dict(zip(order,range(3)))
    stable=np.array([mapping[int(label)] for label in labels])
    scored['cluster_id']=stable
    scored['cluster_label']=[f'Cluster {number}' for number in stable]
    for number in range(3):
        key=str(number)
        if key not in references['peer']:
            members=scored.loc[scored.cluster_id==number,'MSISDN']
            reference=snapshot(panel,first_seen,pd.Period(references['reference_month'],freq='M'))
            subset=reference.loc[reference.MSISDN.isin(members)]
            references['peer'][key]=fit_references(subset) if len(subset)>=3 else references['global']
        positions=scored.index[scored.cluster_id==number]
        peer=apply_references(scored.loc[positions],references['peer'][key],prefix='PEER_')
        for col in CLUSTER_FEATURES: scored.loc[positions,'PEER_'+col]=peer['PEER_'+col]
    run_id=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    run_dir=ROOT/'runs'/run_id
    run_dir.mkdir(parents=True)
    prediction,training=train_predict(snapshots,panel,as_of,run_dir)
    output=scored.merge(prediction[['MSISDN','decline_probability','prediction_status','predicted_next_month']],on='MSISDN',validate='one_to_one')
    output=output.sort_values(['decline_probability','cluster_id'],ascending=[False,True],na_position='last').reset_index(drop=True)
    output['complete_inactivity_current_month']=sum(output[d+'_current'] for d in ACTIVITY).eq(0)
    diagnostics=validate_clusters(X,labels,{raw:f'Cluster {stable_id}' for raw,stable_id in mapping.items()},payload.get('run_stability',True))
    for file in [run_dir/'customers.csv',ROOT/'latest_customers.csv']:
        output.to_csv(file,index=False)
    joblib.dump({'scaler':scaler,'kmeans':km,'cluster_id_map':mapping,'features':CLUSTER_FEATURES,'quarter':quarter},run_dir/'cluster_model.pkl')
    output[['MSISDN','cluster_id']].to_csv(previous_path,index=False)
    write_json(ref_path,references)
    report={'run_id':run_id,'as_of_month':str(as_of),'predicting_month':str(as_of+1),'quarter':quarter,
            'customers':len(output),'cluster_counts':output.cluster_id.value_counts().sort_index().to_dict(),
            'ingestion':ingestion,'clustering_validation':diagnostics,'learning':training,'references':references,
            'warnings':['Identical unkeyed corrected events cannot be distinguished from genuinely new events. Exact-overlap deduplication only.','Legacy ID cleaning removes the first two characters.'],
            'preview':output.head(100).to_dict(orient='records'),'download_url':'/monthly/download'}
    write_json(run_dir/'report.json',report)
    write_json(ROOT/'latest_report.json',report)
    write_json(state_path,{'as_of_month':str(as_of),'run_id':run_id})
    return json_safe(report)
