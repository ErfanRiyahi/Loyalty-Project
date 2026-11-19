"""Exercise the public stages, independently of legacy compatibility modules."""
from unittest.mock import patch
import joblib
import pandas as pd
from loyalty.services import churn_prediction as churn
from test_retention import make_history


def test_public_stages_train_and_reuse_a_saved_model(tmp_path):
    months,panel,_=make_history()
    first_seen=panel.groupby('MSISDN').month.min()
    features=[churn.build_features(panel,first_seen,month) for month in months[5:]]
    assert features[-1][churn.FEATURES].shape==(40,17)
    bundle,report=churn.load_or_train_model(features,panel,months[-1])
    assert report['model_source']=='initial_training'
    output=churn.predict_customers(features[-1],bundle)
    assert len(output)==40
    assert output.loc[output.consecutive_inactive_months>=3,'churn_probability'].isna().all()
    path=tmp_path/'active.pkl';joblib.dump(bundle,path)
    with patch.object(churn.HistGradientBoostingClassifier,'fit',side_effect=AssertionError('Saved model must not be retrained')):
        loaded,report=churn.load_or_train_model(features,panel,months[-1],model_path=path)
        reused=churn.predict_customers(features[-1],loaded)
    assert report['model_source']=='existing'
    pd.testing.assert_frame_equal(output,reused)


def test_no_model_means_review_not_an_invented_probability():
    months,panel,_=make_history()
    first_seen=panel.groupby('MSISDN').month.min()
    features=churn.build_features(panel,first_seen,months[7])
    bundle,report=churn.load_or_train_model([features],panel,months[7])
    assert bundle is None and report['status']=='insufficient_training_data'
    output=churn.predict_customers(features,bundle)
    assert output.churn_probability.isna().all()
    assert set(output.retention_status)<= {'review','churned'}
