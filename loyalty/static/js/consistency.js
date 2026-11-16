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
  const diagnostics = data.score?.diagnostics;
  if (!diagnostics) return;
  const titles = {data:"اینترنت",voice:"مکالمه",spend:"هزینه",txn:"تعداد تراکنش"};
  const report = diagnostics.domains || {};
  const warnings = (diagnostics.warnings || []).map(item => `<p>${escapeHtml(item.message)}</p>`).join("");
  const rows = CI_DOMAINS.filter(key => report[key]).map(key => { const value = report[key]; return `<tr><td>${titles[key] || escapeHtml(key)}</td><td>${value.input_rows}</td><td>${value.input_customers}</td><td>${value.scored_customers}</td><td>${escapeHtml(value.window_start || "—")} تا ${escapeHtml(value.window_end || "—")}</td><td>${value.observed_months}</td></tr>`; }).join("");
  ciResultsArea.insertAdjacentHTML("afterbegin", `<section class="panel ci-coverage">
    <h2>${diagnostics.output_customers === 0 ? "شاخص نهایی برای هیچ مشتری محاسبه نشد" : "پوشش داده‌های شاخص سازگاری"}</h2>
    ${warnings}
    <p>فقط مشتریان مشترک در هر چهار حوزه وارد نتیجهٔ نهایی می‌شوند. تعداد مشترک پس از پاک‌سازی: ${diagnostics.common_customers}؛ تعداد ماه‌های مشترک: ${diagnostics.common_months.length}.</p>
    <div class="table-scroll"><table><thead><tr><th>حوزه</th><th>ردیف ورودی</th><th>مشتری یکتای ورودی</th><th>مشتری پس از پاک‌سازی و محاسبه</th><th>بازهٔ مؤثر</th><th>ماه دارای داده</th></tr></thead><tbody>${rows}</tbody></table></div>
    <details><summary>جزئیات تطبیق شناسه‌ها</summary><p>${escapeHtml(diagnostics.identifier_policy)}</p><ul>${diagnostics.pairwise_common_customers.map(item=>`<li>${titles[item.first]} و ${titles[item.second]}: ${item.count} مشتری مشترک</li>`).join("")}</ul></details>
    ${downloadButton(data.score.report_download_url,"دانلود گزارش پوشش داده‌ها")}
    </section>`);
}

async function runConsistencyIndex() {
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
    "/consistency_index",
    { domains: domains },
    runCIBtn,
    ciStatusArea,
    ciResultsArea,
    renderCIResults,
  );
}

runCIBtn.addEventListener("click", runConsistencyIndex);
