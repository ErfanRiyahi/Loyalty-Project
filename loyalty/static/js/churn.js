(() => {
 const button = document.getElementById('runChurnBtn');
 const status = document.getElementById('churnStatusArea');
 const results = document.getElementById('churnResultsArea');
 button.addEventListener('click', async () => {
  button.disabled = true;
  setLoading(status, results, 'Assessing final customer scores…');
  try {
   const file = document.getElementById('churnFile').files[0];
   const method = document.getElementById('churnMethod').value;
   let data;
   if (method === 'trained_monthly') {
    const response = await fetch('/monthly/status');
    data = await response.json();
    if (!response.ok || !data.run_id) throw new Error('Run Monthly Learning first.');
    clearStatus(status);
    const columns = ['MSISDN', 'cluster_id', 'decline_probability', 'prediction_status', 'predicted_next_month'];
    results.innerHTML = `<div class="panel"><h2>Next-month activity decline</h2><p>Observation month: ${escapeHtml(data.as_of_month)} · Prediction month: ${escapeHtml(data.predicting_month)} · Model: ${escapeHtml(data.learning.status)}.</p><p>${escapeHtml(data.learning.reason || data.learning.note || '')}</p><p>The target is a ≥50% drop in two previously active domains. A blank probability indicates insufficient training data or prior activity.</p><a href="/monthly/download">Download all predictions and cluster peer scores</a><div style="overflow-x:auto"><table><thead><tr>${columns.map(c=>`<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>${data.preview.map(row=>`<tr>${columns.map(c=>`<td>${escapeHtml(row[c]??'—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>`;
    return;
   }

   if (file) {
    const body = new FormData(); body.append('file', file); body.append('method', method);
    const response = await fetch('/churn/assess', {method: 'POST', body});
    data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Upload failed.');
   } else {
    data = await postJson('/churn/assess', {method, dataset_address: document.getElementById('churnPath').value.trim()});
   }
   clearStatus(status);
   const columns = data.method === 'domain_balanced'
    ? ['MSISDN', 'risk_index', 'point_risk_band', 'risk_band', 'baseline_risk_index', 'domains_used', 'risk_lower_bound', 'risk_upper_bound', 'leave_one_domain_out_min', 'leave_one_domain_out_max', 'risk_reasons']
    : ['MSISDN', 'risk_index', 'risk_band', 'scores_used', 'risk_reasons'];
   results.innerHTML = `<div class="panel"><h2>Risk assessment results</h2><p>${escapeHtml(data.notice)}</p>
    <p>Method: ${escapeHtml(data.method)}</p>
    ${data.method === 'domain_balanced' ? `<p>Bands surviving evidence checks: ${(100 * data.diagnostics.accepted_band_share).toFixed(1)}% · Needs review: ${(100 * data.diagnostics.review_share).toFixed(1)}%.</p><p>Point bands are provisional. Lower/upper bounds represent unknown evidence; they are not churn probabilities or confidence intervals.</p>` : ''}
    <p>${data.rows} customers · ${data.score_columns.length} score columns</p>
    <p>${Object.entries(data.counts).map(([key, value]) => `${escapeHtml(key)}: ${value}`).join(' · ')}</p>
    <a href="${data.download_url}">Download all customer risk results</a>
    <p>Top 100 customers, highest assessed risk first. Insufficient evidence rows have no risk index.</p>
    <div style="overflow-x:auto"><table><thead><tr>${columns.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead>
    <tbody>${data.preview.map(row => `<tr>${columns.map(c => `<td>${escapeHtml(row[c] ?? '—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>`;
  } catch (error) {
   setError({message: error.message}, status, results);
  } finally { button.disabled = false; }
 });
})();
