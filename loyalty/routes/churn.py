from flask import Blueprint, request, jsonify, send_file, current_app
import pandas as pd
from ..common import OUTPUT_ROOT, json_safe
import json
from ..services.churn import assess_risk, DOMAIN_GROUPS

app = Blueprint('churn', __name__)

@app.post('/churn/assess')
def assess():
    try:
        payload = request.form if request.files else (request.get_json(silent=True) or {})
        method = payload.get('method', 'baseline')
        if 'file' in request.files:
            frame = pd.read_csv(request.files['file'].stream, dtype={'MSISDN': str})
            source = 'Uploaded final scored CSV'
        else:
            source = payload.get('dataset_address') or str(OUTPUT_ROOT / 'customer_segmentation_final.csv')
            frame = pd.read_csv(source, dtype={'MSISDN': str})
        output, columns = assess_risk(frame, method=method)
        path = OUTPUT_ROOT / 'churn_risk_assessment.csv'
        output.to_csv(path, index=False)
        preview = output.head(100).astype(object).where(pd.notna(output.head(100)), None)
        diagnostics = {'method': method, 'rows': len(output),
                       'score_columns': columns, 'counts': output['risk_band'].value_counts().to_dict(),
                       'accepted_band_share': float(output['decision_stable'].mean()) if method == 'domain_balanced' else None,
                       'review_share': float(output['risk_band'].eq('Needs review').mean()),
                       'insufficient_share': float(output['risk_band'].eq('Insufficient evidence').mean()),
                       'thresholds': {'medium': 34, 'high': 67},
                       'notice': 'Risk indices and missing-evidence bounds are not probabilities or statistical confidence intervals.'}
        diagnostics['method_version'] = 'score-risk-v2'
        diagnostics['created_at_utc'] = pd.Timestamp.now(tz='UTC').isoformat()
        if method == 'domain_balanced':
            diagnostics['score_groups'] = DOMAIN_GROUPS
            diagnostics['ablation'] = {
                'baseline_equal_score': output['baseline_risk_band'].value_counts().to_dict(),
                'group_balanced_without_review': output['point_risk_band'].value_counts().to_dict(),
                'group_balanced_with_review': output['risk_band'].value_counts().to_dict(),
                'note': 'Coverage and band counts only; no accuracy comparison without true outcomes.',
            }
        with open(OUTPUT_ROOT / 'churn_risk_diagnostics.json', 'w') as stream:
            json.dump(json_safe(diagnostics), stream, indent=2, allow_nan=False)
        return jsonify(json_safe({
            'method': method,
            'diagnostics': diagnostics,
            'notice': 'Risk index is not a churn probability or a forecast. No future outcomes were used.',
            'source': source, 'rows': len(output), 'score_columns': columns,
            'counts': output['risk_band'].value_counts().to_dict(),
            'preview': preview.to_dict(orient='records'),
            'download_url': '/churn/download',
        }))
    except (ValueError, FileNotFoundError, pd.errors.ParserError) as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        current_app.logger.exception('Risk assessment failed')
        return jsonify(error='Risk assessment failed. Check the server log.'), 500

@app.get('/churn/download')
def download():
    path = OUTPUT_ROOT / 'churn_risk_assessment.csv'
    if not path.exists():
        return jsonify(error='Run the risk assessment first.'), 404
    return send_file(path, as_attachment=True)
