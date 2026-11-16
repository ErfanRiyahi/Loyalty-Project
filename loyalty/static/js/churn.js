(() => {
  const button = document.getElementById("runChurnBtn");
  const status = document.getElementById("churnStatusArea");
  const results = document.getElementById("churnResultsArea");
  let page = 1;
  let selection = "at_risk", risk = "all", query = "";
  let controller;
  const states = {at_risk: "در معرض ریزش", churned: "ریزش رخ‌داده", review: "نیازمند بررسی؛ سابقهٔ کافی برای پیش‌بینی نیست", low: "ریسک پایین"};
  const levels = {high: "بالا", medium: "متوسط", low: "پایین", review: "نامشخص", none: "—"};
  async function load() {
    if (controller) controller.abort();
    controller = new AbortController();
    const requestController = controller;
    button.disabled = true;
    if (!status.querySelector(".progress-panel")) status.replaceChildren();
    status.querySelector(".list-loading")?.remove();
    const notice = document.createElement("p");
    notice.className = "list-loading";
    notice.textContent = "در حال خواندن فهرست مشتریان…";
    status.appendChild(notice);
    const params = new URLSearchParams({status: selection, risk, q: query, page, page_size: 25});
    try {
      const response = await fetch("/churn/customers?" + params, {cache: "no-store", signal: requestController.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "خواندن فهرست ممکن نشد.");
      notice.remove();
      render(data, params);
    } catch (error) {
      if (error.name !== "AbortError") {
        results.replaceChildren();
        notice.textContent = error.message;
      }
    } finally { if (controller === requestController) button.disabled = false; }
  }
  function render(data, params) {
    const counts = data.counts;
    const empty = selection === "at_risk" && data.model_status !== "trained"
      ? "مدل هنوز سابقهٔ کافی برای پیش‌بینی ندارد. فهرست «نیازمند بررسی» را برای نشانه‌های رفتاری ببینید."
      : "مشتری مطابق این فیلترها یافت نشد.";
    results.innerHTML = `<section class="panel">
      <p>آخرین ماه کامل: ${escapeHtml(data.as_of_month)} | افق پیش‌بینی تا: ${escapeHtml(data.forecast_through)}</p>
      <p>در معرض ریزش: ${counts.at_risk || 0} | ریزش رخ‌داده: ${counts.churned || 0} | نیازمند بررسی: ${counts.review || 0} | ریسک پایین: ${counts.low || 0}</p>
      ${data.model_status !== "trained" ? "<p>احتمال ریزش تا فراهم شدن سابقه و نمونه‌های کافی محاسبه نمی‌شود.</p>" : data.evaluation_status !== "held_out" ? "<p>مدل آموزش دیده است؛ سابقه برای ارزیابی مستقل زمانی هنوز کافی نیست.</p>" : ""}
      <form id="retentionFilters">
      <label for="retentionState">وضعیت مشتری</label><select id="retentionState"><option value="at_risk">در معرض ریزش</option><option value="churned">ریزش رخ‌داده</option><option value="review">نیازمند بررسی</option><option value="low">ریسک پایین</option><option value="all">همه</option></select>
      <label for="retentionRisk">سطح ریسک</label><select id="retentionRisk"><option value="all">همه</option><option value="high">بالا</option><option value="medium">متوسط</option><option value="low">پایین</option><option value="review">نامشخص</option></select>
      <label for="retentionSearch">جست‌وجوی شناسهٔ مشتری</label><input id="retentionSearch" type="search">
      <button class="add-col" type="submit">اعمال فیلتر</button></form>
      ${downloadButton("/churn/customers/download?" + params, "دانلود فهرست فیلترشده")}
      <p>دلایل رفتاری، مشاهدات ثبت‌شده هستند؛ عوامل مدل نشان می‌دهند جایگزینی کدام گروه ویژگی با مقدار معمول دادهٔ آموزش، ریسک را کاهش می‌دهد و علت قطعی ریزش نیستند.</p>
      <div class="table-scroll"><table><thead><tr><th>اولویت در گروه</th><th>شناسهٔ مشتری</th><th>وضعیت</th><th>ریسک</th><th>احتمال برآوردی</th><th>آخرین ماه فعالیت</th><th>ماه‌های متوالی بی‌فعالیت</th><th>نشانه‌های رفتاری</th><th>عوامل مدل</th></tr></thead><tbody>
      ${data.rows.length ? data.rows.map(row => `<tr><td>${row.priority}</td><td dir="ltr">${escapeHtml(row.MSISDN)}</td><td>${states[row.retention_status] || "—"}</td><td>${levels[row.risk_level] || "—"}</td><td>${row.churn_probability == null ? "محاسبه نشده" : (row.churn_probability * 100).toFixed(1) + "٪"}</td><td>${escapeHtml(row.last_active_month || "نامشخص")}</td><td>${row.consecutive_inactive_months}</td><td>${escapeHtml(row.risk_reasons || "—")}</td><td>${escapeHtml(row.model_factors || "—")}</td></tr>`).join("") : `<tr><td colspan="9">${empty}</td></tr>`}
      </tbody></table></div>
      <p>${data.total} مشتری | صفحهٔ ${data.page} از ${Math.max(1, Math.ceil(data.total / data.page_size))}</p>
      <button id="retentionPrevious" class="add-col" type="button" ${page <= 1 ? "disabled" : ""}>قبلی</button>
      <button id="retentionNext" class="add-col" type="button" ${page * data.page_size >= data.total ? "disabled" : ""}>بعدی</button>
      </section>`;
    document.getElementById("retentionState").value = selection;
    document.getElementById("retentionRisk").value = risk;
    document.getElementById("retentionSearch").value = query;
    document.getElementById("retentionFilters").addEventListener("submit", event => {
      event.preventDefault();
      selection = document.getElementById("retentionState").value;
      risk = document.getElementById("retentionRisk").value;
      query = document.getElementById("retentionSearch").value.trim();
      page = 1; load();
    });
    document.getElementById("retentionPrevious").addEventListener("click", () => { page--; load(); });
    document.getElementById("retentionNext").addEventListener("click", () => { page++; load(); });
  }
  const updateButton = document.getElementById("updateChurnBtn");
  const now = new Date(); now.setDate(1); now.setMonth(now.getMonth() - 1);
  document.getElementById("churnMonth").value = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}`;
  updateButton.addEventListener("click", async () => {
    updateButton.disabled = true;
    button.disabled = true;
    setLoading(status, results);
    try {
      await postJson("/churn/update", {
        as_of_month: document.getElementById("churnMonth").value,
        confirm_complete: document.getElementById("churnComplete").checked,
        sources: {order: document.getElementById("churnOrder").value.trim(), data_cdr: document.getElementById("churnData").value.trim(), voice_cdr: document.getElementById("churnVoice").value.trim()},
        columns: Object.fromEntries(["order","data_cdr","voice_cdr"].map(source => [source, Array.from(document.querySelectorAll(`.churn-col[data-source="${source}"]`), field => field.value)])),
      });
      page = 1; await load();
    } catch (error) { setError({message:error.message}, status, results); }
    finally { updateButton.disabled = false; button.disabled = false; }
  });
  button.addEventListener("click", () => { page = 1; load(); });
  // Legacy job recovery refreshes the current actionable list.
  window.renderChurnResults = () => load();
})();
