import sqlite3
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from loyalty.services import monthly


def test_custom_columns_preserve_status_identifiers_and_deduplication(tmp_path):
    paths = {}
    columns = {}
    for source in monthly.SOURCES:
        names = ['customer', 'when', 'amount']
        rows = [['980001', '2025-01-15', 17]]
        if source == 'order':
            names += ['state', 'event']
            rows = [['980001', '2025-01-15', 17, 30, 'one'],
                    ['980001', '2025-01-15', 19, 10, 'two']]
        path = tmp_path / f'{source}.csv'
        pd.DataFrame(rows, columns=names).to_csv(path, index=False)
        paths[source] = str(path)
        columns[source] = names
    with patch.object(monthly, 'ROOT', tmp_path / 'output'):
        first = monthly.ingest(paths, columns)
        second = monthly.ingest(paths, columns)
        assert first['order']['stored_events'] == second['order']['stored_events'] == 2
        with sqlite3.connect(monthly.ROOT / 'history.sqlite') as database:
            rows = database.execute('SELECT customer, value, successful FROM events WHERE source="order" ORDER BY value').fetchall()
        assert rows == [('0001', 17, 1), ('0001', 19, 0)]
        # Correcting an event with a custom event ID updates it rather than adding it.
        frame = pd.read_csv(paths['order'], dtype={'customer': str})
        frame.loc[0, 'amount'] = 23
        frame.to_csv(paths['order'], index=False)
        monthly.ingest(paths, columns)
        with sqlite3.connect(monthly.ROOT / 'history.sqlite') as database:
            assert database.execute('SELECT value FROM events WHERE event_key="id:one"').fetchone()[0] == 23


@pytest.mark.parametrize('schema', [['id', 'date'], ['id', 'date', ''], ['id', 'date', 'id'], 'invalid'])
def test_invalid_mapping_rejected_before_ingestion(tmp_path, schema):
    with patch.object(monthly, 'ROOT', tmp_path / 'output'):
        with pytest.raises(ValueError, match='data_cdr'):
            monthly.ingest({}, {'data_cdr': schema})
        assert not (monthly.ROOT / 'history.sqlite').exists()
