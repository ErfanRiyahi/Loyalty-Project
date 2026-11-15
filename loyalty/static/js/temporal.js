// ---------- Temporal Stability tab ----------
const tsStatusArea = document.getElementById("tsStatusArea");
const tsResultsArea = document.getElementById("tsResultsArea");
const runTSBtn = document.getElementById("runTSBtn");
const TS_DOMAINS = ["order", "data", "voice"];

// Keep this function name for the button handler and result recovery.
function getTSDomainsPayload() {
  return readDomainInputs("ts", TS_DOMAINS);
}

function renderTSResults(data) {
  renderScoreSummary(data, tsResultsArea, "ts");
}

async function runTemporalStability() {
  const apiUrl = document.getElementById("tsApiUrl").value.trim();
  if (!apiUrl) {
    setError("نشانی سرویس پردازش را وارد کنید.", tsStatusArea, tsResultsArea);
    return;
  }

  const { domains, missingDomains } = getTSDomainsPayload();
  if (missingDomains.length > 0) {
    setError(
      `هر سه ستون این حوزه‌ها را تکمیل کنید: ${missingDomains.join(", ")}.`,
      tsStatusArea,
      tsResultsArea,
    );
    return;
  }

  await executeScoringRequest(
    apiUrl,
    { domains: domains },
    runTSBtn,
    tsStatusArea,
    tsResultsArea,
    renderTSResults,
  );
}

runTSBtn.addEventListener("click", runTemporalStability);
