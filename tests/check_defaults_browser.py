"""Browser regression: run against a local app with python tests/check_defaults_browser.py URL.

Requires Playwright and its Chromium browser, separately from production dependencies.
"""
import json
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5000/'
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
    page = browser.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    page.wait_for_selector('#default-input-1', state='attached')
    assert page.evaluate('new Set(Array.from(document.querySelectorAll("[id]"), e=>e.id)).size === document.querySelectorAll("[id]").length')
    fields = page.locator('.ci-col, .ts-col, .ci-address, .ts-address').all()
    original = {field.get_attribute('id'): field.input_value() for field in fields}
    assert len(original) == 28 and '' not in original and None not in original
    # Every editor initially agrees with its real field, including the 21 column names.
    for key, value in original.items():
        assert page.locator(f'#defaultsFields [data-default-key="{key}"]').input_value() == value
    page.locator('#tabBtnSettings').click()
    assert page.locator('#defaultsFields fieldset').count() == 7
    custom = {}
    for index, (key, value) in enumerate(original.items()):
        custom[key] = f'/tmp/source-{index}.csv' if '-address-' in key else f'custom_column_{index}'
        page.locator(f'#defaultsFields [data-default-key="{key}"]').fill(custom[key])
    page.locator('#defaultsForm button[type="submit"]').click()
    for key, value in custom.items():
        assert page.locator('#'+key).input_value() == value
    page.reload()
    page.wait_for_selector('#default-input-1', state='attached')
    for key, value in custom.items():
        assert page.locator('#'+key).input_value() == value
        assert page.locator(f'#defaultsFields [data-default-key="{key}"]').input_value() == value
    # The API payload must preserve each domain's independently edited columns.
    captured = []
    def intercept(route):
        captured.append(route.request.post_data_json)
        route.fulfill(status=400, content_type='application/json', body='{"error":"Test request intercepted"}')
    page.route('**/jobs', intercept)
    for prefix, tab, button, path in [('ci','CI','runCIBtn','/consistency_index'), ('ts','TS','runTSBtn','/temporal_stability')]:
        page.locator('#tabBtn'+tab).click()
        page.locator('#'+button).click()
        page.wait_for_function('(id)=>!document.getElementById(id).disabled', arg=button)
        request = captured[-1]
        assert request['path'] == path
        for domain, entry in request['body']['domains'].items():
            assert entry['columns'] == [custom[f'{prefix}-col-{domain}-{i}'] for i in range(3)]
            assert entry['dataset_address'] == custom[f'{prefix}-address-{domain}']
    # Reproduce the old empty-key corruption without clearing unrelated valid settings.
    legacy = {'':'Call_Duration', 'field-1':'/tmp/preserved-data.csv',
              'field-5':'/tmp/preserved-orders.csv', 'standard.DATA_USAGE.column.2':'SavedUsage',
              'monthly-order-status':'SavedStatus'}
    page.evaluate('(value)=>{localStorage.removeItem("loyalty.input-defaults.v2");localStorage.setItem("loyalty.input-defaults.v1", JSON.stringify(value));}', legacy)
    page.reload();page.wait_for_selector('#default-input-1', state='attached')
    for key, value in original.items():
        if '-col-' in key: assert page.locator('#'+key).input_value() == value
    assert page.locator('#ci-address-data').input_value() == '/tmp/preserved-data.csv'
    assert page.locator('#ts-address-order').input_value() == '/tmp/preserved-orders.csv'
    assert page.locator('#churn-order-status').input_value() == 'SavedStatus'
    assert page.locator('#standard option[value="DATA_USAGE"]').get_attribute('data-columns') == json.dumps(['SERVED_MSISDN','START_TIMESTAMP','SavedUsage'], separators=(',',':'))
    migrated = page.evaluate('JSON.parse(localStorage.getItem("loyalty.input-defaults.v2"))')
    assert '' not in migrated and not any(key.startswith('field-') for key in migrated)
    page.locator('#tabBtnSettings').click();page.locator('#resetDefaultsBtn').click()
    page.reload();page.wait_for_selector('#default-input-1', state='attached')
    for key, value in original.items(): assert page.locator('#'+key).input_value() == value
    assert page.evaluate('localStorage.getItem("loyalty.input-defaults.v1")') is None
    assert not errors, errors
    browser.close()
print('PASS: independent domain defaults, save/apply/reload, real payloads, legacy repair/preservation, reset; no JS errors')
