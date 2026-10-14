// ---------- Consistency Index tab ----------
const ciStatusArea = document.getElementById('ciStatusArea');
const ciResultsArea = document.getElementById('ciResultsArea');
const runCIBtn = document.getElementById('runCIBtn');
const CI_DOMAINS = ['data', 'voice', 'spend', 'txn'];

function getCIDomainsPayload() {
  const domains = {};
  const missingDomains = [];

  CI_DOMAINS.forEach(domain => {
    const addressInput = document.querySelector(`.ci-address[data-domain="${domain}"]`);
    const colInputs = Array.from(document.querySelectorAll(`.ci-col[data-domain="${domain}"]`))
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

function renderCIResults(data) {
  const overview = data.dataset_overview || {};
  const score = data.score || {};
  const domainScores = score.domain_scores || {};

  let domainCardsHtml = '';
  CI_DOMAINS.forEach(domain => {
    if (domainScores[domain] !== undefined) {
      domainCardsHtml += `
        <div class="ci-domain-card">
          <div class="k">${escapeHtml(domain)}</div>
          <div class="v">${escapeHtml(String(domainScores[domain]))}</div>
        </div>`;
    }
  });

  let previewHtml = '';
  if (Array.isArray(overview.preview) && overview.preview.length > 0) {
    const cols = Object.keys(overview.preview[0]);
    previewHtml = `<table><thead><tr>${cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr></thead><tbody>`;
    overview.preview.slice(0, 8).forEach(row => {
      previewHtml += `<tr>${cols.map(c => `<td>${escapeHtml(String(row[c] ?? ''))}</td>`).join('')}</tr>`;
    });
    previewHtml += `</tbody></table>`;
  }

  ciResultsArea.innerHTML = `
    ${domainCardsHtml ? `
    <div class="panel">
      <h2>Per-domain scores</h2>
      <div class="ci-score-grid">${domainCardsHtml}</div>
    </div>` : ''}
    <div class="panel">
      <h2>Consistency Index</h2>
      <div class="score-card">
        <div>
          <div class="score-label">Result</div>
          <div class="score-value">${escapeHtml(String(score.value ?? '—'))}</div>
        </div>
        <div class="score-desc">${escapeHtml(score.description || 'No description returned by backend.')}</div>
      </div>
      ${previewHtml ? `<div style="margin-top:12px;">${previewHtml}</div>` : ''}
    </div>
    ${buildStatsPanelHtml(score.stats, 'ciStatsChart')}
  `;
  renderStatsChart(score.stats, 'ciStatsChart');
}

async function runConsistencyIndex() {
  const apiUrl = document.getElementById('ciApiUrl').value.trim();
  if (!apiUrl) { setError('Please provide the backend API URL.', ciStatusArea, ciResultsArea); return; }

  const { domains, missingDomains } = getCIDomainsPayload();
  if (missingDomains.length > 0) {
    setError(`Please fill in all 3 columns for: ${missingDomains.join(', ')}.`, ciStatusArea, ciResultsArea);
    return;
  }

  runCIBtn.disabled = true;
  setLoading(ciStatusArea, ciResultsArea, 'Computing consistency index across domains…');

  try {
    const data = await postJson(apiUrl, { domains: domains });

    clearStatus(ciStatusArea);
    try {
      renderCIResults(data);
    } catch (renderErr) {
      setError({ source: 'frontend', message: renderErr.message || String(renderErr), trace: renderErr.stack || null }, ciStatusArea, ciResultsArea);
    }
  } catch (err) {
    if (err && err.isBackendError) {
      setError({ source: 'backend', message: err.message, location: err.location, trace: err.trace }, ciStatusArea, ciResultsArea);
    } else {
      setError({ source: 'frontend', message: (err && err.message) || String(err), trace: err && err.stack ? err.stack : null }, ciStatusArea, ciResultsArea);
    }
  } finally {
    runCIBtn.disabled = false;
  }
}

runCIBtn.addEventListener('click', runConsistencyIndex);

