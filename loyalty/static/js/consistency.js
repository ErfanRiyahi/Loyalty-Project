// ---------- Consistency Index tab ----------
const ciStatusArea = document.getElementById("ciStatusArea");
const ciResultsArea = document.getElementById("ciResultsArea");
const runCIBtn = document.getElementById("runCIBtn");
const CI_DOMAINS = ["data", "voice", "spend", "txn"];

// Keep this function name for the button handler and result recovery.
function getCIDomainsPayload() {
  return readDomainInputs("ci", CI_DOMAINS);
}

function renderCIResults(data) {
  renderScoreSummary(data, ciResultsArea, "ci");
}

async function runConsistencyIndex() {
  const apiUrl = document.getElementById("ciApiUrl").value.trim();
  if (!apiUrl) {
    setError("نشانی سرویس پردازش را وارد کنید.", ciStatusArea, ciResultsArea);
    return;
  }

  const { domains, missingDomains } = getCIDomainsPayload();
  if (missingDomains.length > 0) {
    setError(
      `هر سه ستون این حوزه‌ها را تکمیل کنید: ${missingDomains.join(", ")}.`,
      ciStatusArea,
      ciResultsArea,
    );
    return;
  }

  await executeScoringRequest(
    apiUrl,
    { domains: domains },
    runCIBtn,
    ciStatusArea,
    ciResultsArea,
    renderCIResults,
  );
}

runCIBtn.addEventListener("click", runConsistencyIndex);
