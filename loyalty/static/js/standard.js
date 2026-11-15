const columnsListEl = document.getElementById("columnsList");
const addColumnBtn = document.getElementById("addColumnBtn");
const runBtn = document.getElementById("runBtn");
const statusArea = document.getElementById("statusArea");
const resultsArea = document.getElementById("resultsArea");

let columnCount = 0;

// Create a column input and set its value as a property to avoid HTML injection.
function addColumnRow(value) {
  columnCount += 1;
  const row = document.createElement("div");
  row.className = "col-row";
  row.innerHTML = `
    <div class="order">${columnCount}</div>
    <input type="text" class="col-input" placeholder="e.g. MSISDN">
    <button type="button" class="remove-col" title="حذف ستون" aria-label="حذف ستون">×</button>
  `;
  row.querySelector(".col-input").value = value || "";
  row.querySelector(".col-input").setAttribute("aria-label", "نام ستون");
  row.querySelector(".col-input").placeholder = value || "نام ستون";
  row.querySelector(".remove-col").addEventListener("click", () => {
    row.remove();
    renumberColumns();
  });
  columnsListEl.appendChild(row);
}

function renumberColumns() {
  const rows = columnsListEl.querySelectorAll(".col-row");
  rows.forEach((row, i) => {
    row.querySelector(".order").textContent = i + 1;
  });
  columnCount = rows.length;
}

addColumnBtn.addEventListener("click", () => addColumnRow());

// Defaults come from the selected option, rendered from the shared backend schema.
const standardSelect = document.getElementById("standard");
// Fill the selected metric's file path and columns from shared settings.
function applyStandardDefaults() {
  const selected = standardSelect.selectedOptions[0];
  const address = document.getElementById("datasetAddress");
  address.value = selected.dataset.path;
  address.placeholder = selected.dataset.path;
  columnsListEl.replaceChildren();
  columnCount = 0;
  JSON.parse(selected.dataset.columns).forEach((value) => addColumnRow(value));
}
standardSelect.addEventListener("change", applyStandardDefaults);
applyStandardDefaults();

// Ignore empty inputs without trimming or correcting column names.
function getColumns() {
  return Array.from(columnsListEl.querySelectorAll(".col-input"))
    .map((i) => i.value)
    .filter((v) => v.length > 0);
}

function renderResults(data) {
  renderScoreSummary(data, resultsArea, "standard");
}

// Validate the form, then call the shared request function.
async function runAnalysis() {
  const apiUrl = document.getElementById("apiUrl").value.trim();
  const datasetAddress = document.getElementById("datasetAddress").value.trim();
  const columns = getColumns();
  const standard = document.getElementById("standard").value;

  if (!apiUrl) {
    setError("نشانی سرویس پردازش را وارد کنید.");
    return;
  }
  if (columns.length === 0) {
    setError("نام ستون‌های موردنیاز را وارد کنید.");
    return;
  }

  // Keep the existing API request structure while sharing repeated execution code.
  const body = {
    dataset_address: datasetAddress || undefined,
    required_columns: columns,
    standard: standard,
  };
  await executeScoringRequest(
    apiUrl,
    body,
    runBtn,
    statusArea,
    resultsArea,
    renderResults,
  );
}

runBtn.addEventListener("click", runAnalysis);
