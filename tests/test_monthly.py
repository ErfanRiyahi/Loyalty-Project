import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from loyalty.services import monthly, churn_prediction as forecasting

class MonthlyTests(unittest.TestCase):
    def test_confirmation_and_month_guards(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting,'ROOT',Path(directory)):
            with self.assertRaises(ValueError):
                forecasting.run_prediction({'as_of_month':'2025-01'})
            with self.assertRaises(ValueError):
                forecasting.run_prediction({'as_of_month':'2099-01','confirm_complete':True})

    def test_overlap_quarter_alignment_and_temporal_training(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(forecasting,'ROOT',Path(directory)/'outputs'):
            root=Path(directory)
            orders=[];data=[];voice=[];event=0
            for index,month in enumerate(pd.period_range('2024-01','2025-09',freq='M')):
                for customer in range(40):
                    level=[10,10,1,1][(index+customer)%4]
                    identifier=f'98{9000000000+customer}'
                    date=str(month)+'-15 12:00:00'
                    for _ in range(level):
                        event+=1;orders.append([event,identifier,date,100+customer,30])
                    data.append([identifier,date,level*100+customer])
                    voice.append([identifier,date,level*100+customer])
            pd.DataFrame(orders,columns=['Id','MSISDN','PaidDateUtc','OrderTotal','OrderStatusId']).to_csv(root/'orders.csv',index=False)
            pd.DataFrame(data,columns=['SERVED_MSISDN','START_TIMESTAMP','ACTUAL_USAGE']).to_csv(root/'data.csv',index=False)
            pd.DataFrame(voice,columns=['Subscriber_MSISDN','Call_Date','Call_Duration']).to_csv(root/'voice.txt',sep='|',index=False)
            payload={'as_of_month':'2025-08','confirm_complete':True,'run_stability':False,
                     'sources':{'order':str(root/'orders.csv'),'data_cdr':str(root/'data.csv'),'voice_cdr':str(root/'voice.txt')}}
            first=forecasting.run_prediction(payload)
            second=forecasting.run_prediction(payload)
            for source in monthly.SOURCES:
                self.assertEqual(first['input_rows'][source],second['input_rows'][source])
            payload['as_of_month']='2025-09'
            third=forecasting.run_prediction(payload)
            self.assertEqual(third['learning']['status'],'insufficient_training_data')
            learning=third['learning']
            self.assertEqual(learning['horizon_months'],3)
            with self.assertRaises(ValueError):
                payload['as_of_month']='2025-07';forecasting.run_prediction(payload)

if __name__=='__main__': unittest.main()
