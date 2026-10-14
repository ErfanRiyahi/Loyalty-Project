// ---------- Dataset Overview tab ----------
const dsStatusArea = document.getElementById('dsStatusArea');
const dsResultsArea = document.getElementById('dsResultsArea');
const runDSBtn = document.getElementById('runDSBtn');

function renderDSResults(data) {
  const overview = data.dataset_overview || {};
  const numericStats = data.numeric_stats || {};
  const columnInfo = overview.column_info || [];

  let colInfoHtml = '';
  if (columnInfo.length > 0) {
    colInfoHtml = `<table><thead><tr><th>Column</th><th>Type</th><th>Missing</th><th>Unique</th></tr></thead><tbody>`;
    columnInfo.forEach(c => {
      colInfoHtml += `<tr><td>${escapeHtml(c.name)}</td><td>${escapeHtml(c.dtype)}</td><td>${c.missing}</td><td>${c.unique}</td></tr>`;
    });
    colInfoHtml += `</tbody></table>`;
  }

  let previewHtml = '';
  if (Array.isArray(overview.preview) && overview.preview.length > 0) {
    const cols = Object.keys(overview.preview[0]);
    previewHtml = `<table><thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>`;
    overview.preview.slice(0, 5).forEach(row => {
      previewHtml += `<tr>${cols.map(c => `<td>${escapeHtml(String(row[c] ?? ''))}</td>`).join('')}</tr>`;
    });
    previewHtml += `</tbody></table>`;
  }

  let numericPanelsHtml = '';
  Object.keys(numericStats).forEach((col, i) => {
    numericPanelsHtml += buildStatsPanelHtml(numericStats[col], `dsStatsChart_${i}`);
  });

  dsResultsArea.innerHTML = `
    <div class="panel">
      <h2>Shape</h2>
      <div class="kv"><span class="k">Rows</span><span>${overview.rows ?? '—'}</span></div>
      <div class="kv"><span class="k">Columns</span><span>${overview.columns ?? '—'}</span></div>
    </div>
    ${colInfoHtml ? `
    <div class="panel">
      <h2>Columns</h2>
      ${colInfoHtml}
    </div>` : ''}
    ${previewHtml ? `
    <div class="panel">
      <h2>Preview (first 5 rows)</h2>
      ${previewHtml}
    </div>` : ''}
    ${numericPanelsHtml}
  `;

  Object.keys(numericStats).forEach((col, i) => {
    renderStatsChart(numericStats[col], `dsStatsChart_${i}`);
  });
}

async function runDatasetOverview() {
  const apiUrl = document.getElementById('dsApiUrl').value.trim();
  const datasetAddress = document.getElementById('dsDatasetAddress').value.trim();
  const columnsRaw = document.getElementById('dsColumns').value.trim();
  const columns = columnsRaw ? columnsRaw.split(',').map(c => c.trim()).filter(c => c) : null;

  if (!apiUrl) { setError('Please provide the backend API URL.', dsStatusArea, dsResultsArea); return; }
  if (!datasetAddress) { setError('Please provide a dataset address.', dsStatusArea, dsResultsArea); return; }

  runDSBtn.disabled = true;
  setLoading(dsStatusArea, dsResultsArea, 'Profiling dataset…');

  try {
    const body = { dataset_address: datasetAddress };
    if (columns) body.columns = columns;

    const data = await postJson(apiUrl, body);

    clearStatus(dsStatusArea);
    try {
      renderDSResults(data);
    } catch (renderErr) {
      setError({ source: 'frontend', message: renderErr.message || String(renderErr), trace: renderErr.stack || null }, dsStatusArea, dsResultsArea);
    }
  } catch (err) {
    if (err && err.isBackendError) {
      setError({ source: 'backend', message: err.message, location: err.location, trace: err.trace }, dsStatusArea, dsResultsArea);
    } else {
      setError({ source: 'frontend', message: (err && err.message) || String(err), trace: err && err.stack ? err.stack : null }, dsStatusArea, dsResultsArea);
    }
  } finally {
    runDSBtn.disabled = false;
  }
}

runDSBtn.addEventListener('click', runDatasetOverview);

