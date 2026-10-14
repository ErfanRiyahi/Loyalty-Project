// ---------- Cluster tab ----------
const clusterStatusArea = document.getElementById('clusterStatusArea');
const clusterResultsArea = document.getElementById('clusterResultsArea');
const runClusterBtn = document.getElementById('runClusterBtn');

const SEGMENT_COLORS = {
  'Loyal': '#2ecc71',
  'Neutral': '#f39c12',
  'At-Risk/Churning': '#e74c3c',
  'Limited (single-domain)': '#95a5a6'
};
function segmentColor(name) {
  return SEGMENT_COLORS[name] || '#7c8ba1';
}

function renderClusterResults(data) {
  const total = data.n_customers || 1;
  const counts = data.segment_counts || {};
  const sortedSegments = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  let barsHtml = '';
  sortedSegments.forEach(([name, count]) => {
    const pct = (count / total * 100).toFixed(1);
    barsHtml += `
      <div class="segment-row">
        <div class="seg-name"><span class="swatch" style="background:${segmentColor(name)}"></span>${escapeHtml(name)}</div>
        <div class="seg-bar-bg"><div class="seg-bar-fill" style="width:${pct}%;background:${segmentColor(name)}"></div></div>
        <div class="seg-count">${count.toLocaleString()} (${pct}%)</div>
      </div>`;
  });

  const profile = data.cluster_profile || {};
  const clusterNames = Object.keys(profile);
  const featureNames = clusterNames.length ? Object.keys(profile[clusterNames[0]]) : [];

  let profileTableHtml = '';
  if (clusterNames.length) {
    profileTableHtml = `<table><thead><tr><th>Feature</th>${clusterNames.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>`;
    featureNames.forEach(f => {
      profileTableHtml += `<tr><td>${escapeHtml(f)}</td>${clusterNames.map(c => `<td>${profile[c][f]}</td>`).join('')}</tr>`;
    });
    profileTableHtml += `</tbody></table>`;
  }

  clusterResultsArea.innerHTML = `
    <div class="panel">
      <h2>Segment distribution</h2>
      ${barsHtml || '<div class="hint">No segments returned.</div>'}
      <div class="tier-note">
        ${data.n_multi_domain?.toLocaleString() ?? '—'} customers had enough domains to be clustered
        (At-Risk / Neutral / Loyal); ${data.n_single_domain?.toLocaleString() ?? '—'} had only one
        domain and fall into the Limited group instead.
      </div>
      <div style="margin-top:14px;"><canvas id="clusterDistChart" height="160"></canvas></div>
    </div>
    <div class="panel">
      <h2>Clustering quality</h2>
      <div class="kv"><span class="k">Silhouette</span><span>${data.silhouette ?? '—'}</span></div>
      <div class="kv"><span class="k">Davies-Bouldin</span><span>${data.davies_bouldin ?? '—'}</span></div>
      <div class="hint">Silhouette closer to 1 and Davies-Bouldin closer to 0 both mean better-separated clusters.</div>
    </div>
    ${buildClusterValidationHtml(data.validation)}
    ${profileTableHtml ? `
    <div class="panel">
      <h2>Cluster profile (mean feature values)</h2>
      ${profileTableHtml}
    </div>` : ''}
    <div class="panel">
      <h2>Output</h2>
      <div class="hint">Full per-customer segments were written to <code>${escapeHtml(data.output_file || 'customer_segmentation_final.csv')}</code> in the outputs folder.</div>
    </div>
  `;

  if (chartInstances['clusterDistChart']) chartInstances['clusterDistChart'].destroy();
  const canvas = document.getElementById('clusterDistChart');
  if (canvas && sortedSegments.length && typeof Chart !== 'undefined') {
    chartInstances['clusterDistChart'] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: sortedSegments.map(([name]) => name),
        datasets: [{
          label: 'Customers',
          data: sortedSegments.map(([, count]) => count),
          backgroundColor: sortedSegments.map(([name]) => segmentColor(name))
        }]
      },
      options: {
        indexAxis: 'y',
        plugins: { legend: { display: false } },
        scales: { x: { beginAtZero: true, ticks: { precision: 0 } } }
      }
    });
  }
}

async function runCluster() {
  const apiUrl = document.getElementById('clusterApiUrl').value.trim();
  if (!apiUrl) { setError('Please provide the backend API URL.', clusterStatusArea, clusterResultsArea); return; }



  runClusterBtn.disabled = true;
  setLoading(clusterStatusArea, clusterResultsArea, 'Merging domains and clustering customers…');

  try {
    const data = await postJson(apiUrl, { run_missing: false, run_stability: document.getElementById('clusterStability').checked });

    clearStatus(clusterStatusArea);
    try {
      renderClusterResults(data);
    } catch (renderErr) {
      setError({ source: 'frontend', message: renderErr.message || String(renderErr), trace: renderErr.stack || null }, clusterStatusArea, clusterResultsArea);
    }
  } catch (err) {
    if (err && err.isBackendError) {
      setError({ source: 'backend', message: err.message, location: err.location, trace: err.trace }, clusterStatusArea, clusterResultsArea);
    } else {
      setError({ source: 'frontend', message: (err && err.message) || String(err), trace: err && err.stack ? err.stack : null }, clusterStatusArea, clusterResultsArea);
    }
  } finally {
    runClusterBtn.disabled = false;
  }
}

runClusterBtn.addEventListener('click', runCluster);

function buildClusterValidationHtml(validation, downloadUrl = '/cluster/validation/download') {
  if (!validation) return '';
  const number = value => value == null ? 'Unavailable' : Number(value).toFixed(3);
  const stability = validation.stability;
  const rows = validation.cluster_sizes.map(item => `<tr>
    <td>${escapeHtml(item.label)}</td><td>${item.count}</td><td>${(100 * item.share).toFixed(1)}%</td>
    <td>${item.silhouette_sample_count}</td><td>${number(item.mean_silhouette)}</td>
    <td>${item.negative_silhouette_share == null ? 'Unavailable' : (100 * item.negative_silhouette_share).toFixed(1) + '%'}</td></tr>`).join('');
  return `<div class="panel"><h2>Cluster validation (k=3)</h2>
    <p>Calinski–Harabasz: <strong>${number(validation.calinski_harabasz)}</strong> — higher generally indicates better separation for comparable runs.</p>
    <p>${escapeHtml(validation.silhouette_method)}. ${validation.silhouette_sample_size} of ${validation.n_clustered} clustered customers evaluated for silhouette.</p>
    <div style="overflow-x:auto"><table><thead><tr><th>Cluster</th><th>Customers</th><th>Share</th><th>Sampled</th><th>Mean silhouette</th><th>Negative silhouette</th></tr></thead><tbody>${rows}</tbody></table></div>
    <h3>Stability across subsamples</h3>
    <p>${escapeHtml(stability.status)} · ${stability.successful_runs}/${stability.requested_runs} successful refits · ${stability.train_rows} training rows per refit.</p>
    <p>ARI mean: ${number(stability.ari_mean)} · minimum: ${number(stability.ari_min)} · standard deviation: ${number(stability.ari_std)}.</p>
    <p class="hint">ARI near 1 means similar partitions despite resampling and arbitrary cluster IDs. ${escapeHtml(stability.note)}</p>
    <p>${escapeHtml(validation.external_validation.reason)}</p>
    ${validation.warnings.map(message => `<p>${escapeHtml(message)}</p>`).join('')}
    <a href="${escapeHtml(downloadUrl)}">Download latest validation report (JSON)</a>
  </div>`;
}
