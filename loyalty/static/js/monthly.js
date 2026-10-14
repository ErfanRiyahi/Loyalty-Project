(() => {
const button=document.getElementById('runMonthlyBtn');
const status=document.getElementById('monthlyStatusArea');
const results=document.getElementById('monthlyResultsArea');
const now=new Date();now.setDate(1);now.setMonth(now.getMonth()-1);
document.getElementById('monthlyMonth').value=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
button.addEventListener('click',async()=>{
 button.disabled=true;
 setLoading(status,results,'Reading history, updating clusters and evaluating next-month decline…');
 try {
 const data=await postJson('/monthly/update',{
  as_of_month:document.getElementById('monthlyMonth').value,
  confirm_complete:document.getElementById('monthlyComplete').checked,
  sources:{order:document.getElementById('monthlyOrder').value.trim(),data_cdr:document.getElementById('monthlyData').value.trim(),voice_cdr:document.getElementById('monthlyVoice').value.trim()}
 });
 clearStatus(status);renderMonthly(data);
 }catch(error){setError({message:error.message},status,results);}finally{button.disabled=false;}
});
function renderMonthly(data){
 const learning=data.learning;
 const metric=learning.candidate_test;
 const columns=['MSISDN','cluster_id','PEER_ARPU_SCORE','PEER_CLV_SCORE','PEER_GROWTH_SCORE','decline_probability','prediction_status','predicted_next_month'];
 const matrix=metric?`<h3>Chronological test: ${escapeHtml(learning.test_month)}</h3><p>Rows are actual labels; columns are predicted labels. 0 = no qualifying decline, 1 = decline.</p><table><thead><tr><th>Actual / Predicted</th><th>0</th><th>1</th></tr></thead><tbody>${metric.confusion_matrix.map((row,i)=>`<tr><th>${i}</th>${row.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table><p>Precision ${metric.precision.toFixed(3)} · Recall ${metric.recall.toFixed(3)} · Average precision ${metric.average_precision??'Unavailable'} · ROC-AUC ${metric.roc_auc??'Unavailable'} · Brier ${metric.brier.toFixed(3)}</p><p>Candidate promoted: ${learning.promoted?'Yes':'No; prior model retained'}. The confusion matrix evaluates the candidate, not necessarily the retained model.</p>`:'';
 results.innerHTML=`<div class="panel"><h2>${escapeHtml(data.as_of_month)} → ${escapeHtml(data.predicting_month)}</h2><p>${data.customers} customers · ${Object.entries(data.cluster_counts).map(([k,v])=>`Cluster ${k}: ${v}`).join(' · ')}</p><p>Quarter: ${escapeHtml(data.quarter)} · Learning: ${escapeHtml(learning.status)}</p><p>${escapeHtml(learning.reason||learning.note||'More historical labeled months are required.')}</p>${matrix}<p>Prediction means ≥50% activity decline in at least two previously active domains. It does not mean confirmed cancellation. Probabilities have not yet been calibrated on company data.</p><a href="/monthly/download">Download all customer predictions and peer scores</a></div>${buildClusterValidationHtml(data.clustering_validation, '/monthly/report')}<div class="panel"><h2>Customer preview</h2><div style="overflow-x:auto"><table><thead><tr>${columns.map(c=>`<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>${data.preview.map(row=>`<tr>${columns.map(c=>`<td>${escapeHtml(row[c]??'—')}</td>`).join('')}</tr>`).join('')}</tbody></table></div></div>`;
}
fetch('/monthly/status').then(r=>r.json()).then(data=>{if(data.run_id)renderMonthly(data);}).catch(()=>{});
})();
