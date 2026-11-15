import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from loyalty.services import monthly

class MonthlyTests(unittest.TestCase):
    def test_confirmation_and_month_guards(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(monthly,'ROOT',Path(directory)):
            with self.assertRaisesRegex(ValueError,'Confirm'):
                monthly.run_monthly({'as_of_month':'2025-01'})
            with self.assertRaisesRegex(ValueError,'completed month'):
                monthly.run_monthly({'as_of_month':'2099-01','confirm_complete':True})

    def test_overlap_quarter_alignment_and_temporal_training(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(monthly,'ROOT',Path(directory)/'outputs'):
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
            first=monthly.run_monthly(payload)
            second=monthly.run_monthly(payload)
            self.assertEqual(first['references'],second['references'])
            for source in monthly.SOURCES:
                self.assertEqual(first['ingestion'][source]['stored_events'],second['ingestion'][source]['stored_events'])
            self.assertEqual([x['cluster_id'] for x in first['preview']],[x['cluster_id'] for x in second['preview']])
            payload['as_of_month']='2025-09'
            third=monthly.run_monthly(payload)
            self.assertEqual(first['references'],third['references'])
            self.assertEqual(set(third['cluster_counts']),{0,1,2})
            self.assertEqual(third['learning']['status'],'insufficient_training_data')
            learning=third['learning']
            self.assertEqual(learning['horizon_months'],3)
            self.assertTrue(all('PEER_CLV_SCORE' in row for row in third['preview']))
            with self.assertRaisesRegex(ValueError,'backwards'):
                payload['as_of_month']='2025-07';monthly.run_monthly(payload)

if __name__=='__main__': unittest.main()
