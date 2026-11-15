"""Check the two user constraints: Persian information and unchanged design."""
from pathlib import Path
import hashlib
from loyalty import create_app


def test_persian_information_and_existing_bilingual_tabs():
    client=create_app().test_client()
    page=client.get('/').text
    assert '<html lang="fa" dir="rtl">' in page
    for text in ['داشبورد وفاداری مشتریان','ستون تاریخ','ستون میزان مصرف','فایل خریدها','دانلود']:
        # Download actions appear after results, so their copy is checked in the JS source.
        if text=='دانلود':continue
        assert text in page
    assert 'Adaptive Learning' in page and 'Churn Prediction' in page
    shared=client.get('/static/js/shared.js').text
    progress=client.get('/static/js/progress.js').text
    assert 'دانلود خروجی' in shared and 'کاربران امتیازدهی‌شده' in shared
    assert 'زمان سپری‌شده کل' in progress and 'مدت اجرای مراحل' in progress
    assert 'remaining' not in progress.lower()
    assert 'readDomainInputs' in shared and 'executeScoringRequest' in shared


def test_design_assets_are_identical_to_the_approved_version():
    root=Path(__file__).resolve().parents[1]/'loyalty/static'
    expected={'css/dashboard.css': 'ebbb4d2df0162d418023d65044f68bbaa6d33b6bab57e78dc22429781d443bd3', 'brand/logo.svg': '3bb15be77b9430edd76a7f62441e6775276ad386e4fbc736dcd523e9e0c19846', 'fonts/Vazirmatn.woff2': 'e382101336c6eb32cfb31381c027d02d2e0354bad08f6a395d4088beb3db3d91', 'vendor/chart.umd.min.js': 'e9b0f875106021fb3d58120ad8ebdd3e7d32135a4452fd8918c72ac6475f2bd3'}
    for name,digest in expected.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
