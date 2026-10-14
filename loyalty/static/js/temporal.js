// ---------- Temporal Stability tab ----------
const tsStatusArea = document.getElementById('tsStatusArea');
const tsResultsArea = document.getElementById('tsResultsArea');
const runTSBtn = document.getElementById('runTSBtn');
const TS_DOMAINS = ['order', 'data', 'voice'];

function getTSDomainsPayload() {
  const domains = {};
  const missingDomains = [];

  TS_DOMAINS.forEach(domain => {
    const addressInput = document.querySelector(`.ts-address[data-domain="${domain}"]`);
    const colInputs = Array.from(document.querySelectorAll(`.ts-col[data-domain="${domain}"]`))
      .sort((a, b) => Number(a.dataset.col) - Number(b.dataset.col));

    const address = addressInput.value.trim();
    const columns = colInputs.map(i => i.value.trim());

    if (columns.some(c => !c)) {
      missingDomains.push(domain);
      return;
    }
    domains[domain] = { dataset_address: address || undefined, columns: columns };
  });

  return { domains, missingDomains };
}

function renderTSResults(data) {
  const overview = data.dataset_overview || {};
  const score = data.score || {};

  let previewHtml = '';
  if (Array.isArray(overview.preview) && overview.preview.length > 0) {
    const cols = Object.keys(overview.preview[0]);
    previewHtml = `<table><thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>`;
    overview.preview.slice(0, 8).forEach(row => {
      previewHtml += `<tr>${cols.map(c => `<td>${escapeHtml(String(row[c] ?? ''))}</td>`).join('')}</tr>`;
    });
    previewHtml += `</tbody></table>`;
  }

  tsResultsArea.innerHTML = `
    <div class="panel">
      <h2>Temporal Stability</h2>
      <div class="score-card">
        <div>
          <div class="score-label">Result</div>
          <div class="score-value">${escapeHtml(String(score.value ?? '—'))}</div>
        </div>
        <div class="score-desc">${escapeHtml(score.description || 'No description returned by backend.')}</div>
      </div>
      ${previewHtml ? `<div style="margin-top:12px;">${previewHtml}</div>` : ''}
    </div>
    ${buildStatsPanelHtml(score.stats, 'tsStatsChart')}
  `;
  renderStatsChart(score.stats, 'tsStatsChart');
}

async function runTemporalStability() {
  const apiUrl = document.getElementById('tsApiUrl').value.trim();
  if (!apiUrl) { setError('Please provide the backend API URL.', tsStatusArea, tsResultsArea); return; }

  const { domains, missingDomains } = getTSDomainsPayload();
  if (missingDomains.length > 0) {
    setError(`Please fill in all 3 columns for: ${missingDomains.join(', ')}.`, tsStatusArea, tsResultsArea);
    return;
  }

  runTSBtn.disabled = true;
  setLoading(tsStatusArea, tsResultsArea, 'Computing temporal stability across domains…');

  try {
    const data = await postJson(apiUrl, { domains: domains });

    clearStatus(tsStatusArea);
    try {
      renderTSResults(data);
    } catch (renderErr) {
      setError({ source: 'frontend', message: renderErr.message || String(renderErr), trace: renderErr.stack || null }, tsStatusArea, tsResultsArea);
    }
  } catch (err) {
    if (err && err.isBackendError) {
      setError({ source: 'backend', message: err.message, location: err.location, trace: err.trace }, tsStatusArea, tsResultsArea);
    } else {
      setError({ source: 'frontend', message: (err && err.message) || String(err), trace: err && err.stack ? err.stack : null }, tsStatusArea, tsResultsArea);
    }
  } finally {
    runTSBtn.disabled = false;
  }
}

runTSBtn.addEventListener('click', runTemporalStability);

