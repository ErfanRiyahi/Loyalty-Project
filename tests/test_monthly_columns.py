"""CSV inputs are plain DataFrames and each execution is independent."""
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from loyalty.services import churn_prediction as churn


def csv_sources(tmp_path, rows=None):
    paths={};columns={}
    for source in churn.SOURCES:
        names=['customer','when','amount']
        values=rows if rows is not None else [['980001',str(month)+'-15',17] for month in pd.period_range('2024-01','2024-09',freq='M')]
        if source=='order':
            names += ['state','event']
            values=[record+[30,str(index)] for index,record in enumerate(values)]
        path=tmp_path/(source+'.csv')
        pd.DataFrame(values,columns=names).to_csv(path,index=False)
        paths[source]=str(path);columns[source]=names
    return paths,columns


def test_load_returns_three_raw_dataframes_without_filesystem_state(tmp_path):
    paths,columns=csv_sources(tmp_path,[['000123','2024-01-15',17],['000124','bad','bad']])
    with patch.object(sqlite3,'connect',side_effect=AssertionError('No database should be opened')):
        orders,internet,calls=churn.load_data(paths,columns)
    for frame in [orders,internet,calls]:
        assert isinstance(frame,pd.DataFrame) and len(frame)==2
        assert frame.customer.tolist()==['000123','000124']
        assert frame.when.iloc[1]=='bad'  # Reading does not silently clean rows.
    assert not list(tmp_path.rglob('*.sqlite'))


def test_custom_columns_status_filtering_and_order_id_correction(tmp_path):
    paths,columns=csv_sources(tmp_path)
    frame=pd.read_csv(paths['order'],dtype={'customer':str,'event':str})
    frame=pd.concat([frame,pd.DataFrame([['980001','2024-09-15',50,30,'8'],['980001','2024-09-15',60,10,'cancelled']],columns=frame.columns)],ignore_index=True)
    frame.to_csv(paths['order'],index=False)
    tables=churn.load_data(paths,columns)
    panel,first,months=churn.build_monthly_activity(*tables,'2024-09',columns)
    assert panel.loc[panel.month=='2024-09','orders'].iloc[0]==1
    assert panel.data.eq(17).all() and panel.voice.eq(17).all()
    assert first.index.tolist()==['980001'] and len(months)==9


def test_repeated_runs_do_not_accumulate_and_replaced_csvs_define_population(tmp_path):
    paths,columns=csv_sources(tmp_path)
    payload={'as_of_month':'2024-09','confirm_complete':True,'sources':paths,'columns':columns}
    with patch.object(sqlite3,'connect',side_effect=AssertionError('No database should be opened')):
        first=churn.run_prediction(payload,root=tmp_path/'outputs')
        second=churn.run_prediction(payload,root=tmp_path/'outputs')
        assert first['input_rows']==second['input_rows']
        before=pd.read_csv(tmp_path/'outputs'/'runs'/second['run_id']/'retention.csv',dtype={'MSISDN':str})
        for path in paths.values():
            table=pd.read_csv(path,dtype={'customer':str,'event':str})
            table['customer']='customer-B';table.to_csv(path,index=False)
        third=churn.run_prediction(payload,root=tmp_path/'outputs')
        after=pd.read_csv(tmp_path/'outputs'/'runs'/third['run_id']/'retention.csv',dtype={'MSISDN':str})
    assert before.MSISDN.tolist()==['980001']
    assert after.MSISDN.tolist()==['customer-B']
    assert not list(tmp_path.rglob('*.sqlite'))


@pytest.mark.parametrize('schema',[['id','date'],['id','date',''],['id','date','id'],'invalid',None])
def test_invalid_mapping_rejected_before_reading(schema):
    with pytest.raises(ValueError,match='data_cdr'):
        churn.load_data({}, {'data_cdr':schema})


def test_invalid_rows_are_filtered_during_monthly_preparation(tmp_path):
    paths,columns=csv_sources(tmp_path)
    tables=churn.load_data(paths,columns)
    for index in range(3):
        extra=pd.DataFrame([['bad-id','bad',12],['', '2024-09-15',5],['negative','2024-09-15',-1]],columns=['customer','when','amount'])
        if index==0:extra=extra.assign(state=30,event=['a','b','c'])
        tables=list(tables);tables[index]=pd.concat([tables[index],extra],ignore_index=True)
    panel,_,_=churn.build_monthly_activity(*tables,'2024-09',columns)
    assert panel.MSISDN.unique().tolist()==['980001']
