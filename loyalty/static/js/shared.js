// Translate display text only; keep API keys and column names unchanged.
const persianLabels = {
  "Update churn predictions": "به‌روزرسانی پیش‌بینی ریزش",
  "Evaluate adaptive clustering candidate": "ارزیابی مدل جدید خوشه‌بندی",
  "Inspect dataset": "بررسی داده‌ها",
  ": rows read and processed": ": داده‌های خوانده‌شده و پردازش‌شده",
  "Prepare model features": "آماده‌سازی و مقیاس‌بندی ویژگی‌ها",
  "Merge scores and cluster customers": "ادغام امتیازها و خوشه‌بندی سه‌گانه",
  "Assess risk from final scores": "ارزیابی خطر از امتیازهای نهایی",
  "Validate cluster quality and stability": "ارزیابی کیفیت و پایداری خوشه‌ها",
  "Validate input and execute operation": "اعتبارسنجی ورودی و اجرای عملیات",
  "Apply scoring references": "اعمال مرجع امتیازدهی",
  "Select the latest six months": "انتخاب داده‌های شش ماه اخیر",
  "Fit model": "برازش مدل",
  "Fit model and assign clusters": "برازش مدل و تخصیص خوشه‌ها",
  "Filter outliers and calculate ARPU":
    "برش مقادیر دورافتاده و محاسبه درآمد (ARPU)",
  "Predict three-month inactivity risk": "پیش‌بینی ریسک ریزش سه‌ماهه",
  "Update monthly learning": "به‌روزرسانی ماهانه",
  "Combine temporal stability scores": "ترکیب امتیاز نهایی پایداری",
  "The report limit has been reached. Please try again later.":
    "تعداد گزارش‌ها به حد مجاز رسیده؛ کمی بعد تلاش کنید.",
  "Read data file": "خواندن فایل داده",
  "Request not found. It may not have reached the server, or the server may have restarted.":
    "درخواست در سرور یافت نشد؛ ممکن است به سرور نرسیده یا سرور بازراه‌اندازی شده باشد.",
  "Save output file": "ذخیره فایل نتایج",
  "Save model": "ذخیره مدل",
  "Save report and configuration": "ذخیره گزارش و تنظیمات",
  "Save report and state": "ذخیره گزارش و وضعیت",
  rows: "ردیف",
  "Build shared monthly history": "ساخت تاریخچه ماهانه مشترک",
  "Build six-month features": "ساخت ویژگی‌های پنجره شش‌ماهه",
  "Processing failed. Check the server log.":
    "عملیات ناموفق بود؛ گزارش سرور را بررسی کنید.",
  "Calculate score distributions": "محاسبه آمار و توزیع امتیازها",
  "Predict activity decline probability": "محاسبه احتمال افت فعالیت",
  "Calculate customer lifetime value (CLV)": "محاسبه ارزش طول عمر مشتری (CLV)",
  "Calculate transaction frequency score": "محاسبه امتیاز تعداد تراکنش",
  "Calculate ARPU, CLV and growth scores": "محاسبه امتیاز درآمد، ارزش و رشد",
  "Calculate data usage score": "محاسبه امتیاز مصرف اینترنت",
  "Calculate voice usage score": "محاسبه امتیاز مکالمه",
  "Calculate purchase recency": "محاسبه تازگی خرید",
  "Calculate usage recency": "محاسبه تازگی مصرف",
  "Calculate three-month growth trend": "محاسبه روند رشد سه‌ماهه",
  "Calculate domain consistency": "محاسبه سازگاری یک حوزه",
  "Calculate consistency across four domains": "محاسبه شاخص سازگاری چهار حوزه",
  "Failed calculation": "محاسبه شکست‌خورده",
  "Calculate recent activity": "محاسبه فعالیت اخیر",
  "Calculate active months": "محاسبه ماه‌های فعالیت",
  "Calculate scoring references": "محاسبه مرجع امتیازدهی",
  "Calculate temporal stability": "محاسبه پایداری زمانی",
  "Actual test stage": "مرحله آزمایشی واقعی",
  "Invalid operation path or input.": "مسیر یا ورودی عملیات معتبر نیست.",
  "Ingest and clean source ": "ورود و پاک‌سازی منبع ",
  "Ingest, clean and deduplicate history":
    "ورود، پاک‌سازی و حذف هم‌پوشانی داده‌های تاریخی",
  "Operation input must be a JSON object.":
    "ورودی عملیات باید یک شیء JSON باشد.",
  "The processing response could not be read.": "پاسخ پردازش قابل خواندن نیست.",
  "Clean data and convert types": "پاک‌سازی و تبدیل نوع داده‌ها",
  "Operation report not found. The server may have restarted.":
    "گزارش عملیات موجود نیست؛ ممکن است سرور بازراه‌اندازی شده باشد.",
  "Another operation is running. Please wait until it finishes.":
    "یک عملیات در حال اجراست؛ منتظر پایان آن بمانید.",
  Loyal: "وفادار",
  Neutral: "میانه",
  "At-Risk/Churning": "در معرض خطر",
  "Limited (single-domain)": "داده محدود (تک‌حوزه‌ای)",
  High: "زیاد",
  Medium: "متوسط",
  Low: "کم",
  "Needs review": "نیازمند بررسی",
  "Insufficient evidence": "شواهد ناکافی",
  "Insufficient training data": "داده آموزشی ناکافی",
  "Insufficient prior activity": "فعالیت قبلی ناکافی",
  "Likely decline": "افت فعالیت محتمل",
  "Lower estimated decline risk": "خطر کمتر افت فعالیت",
  day: "روز",
  week: "هفته",
  month: "ماه",
  year: "سال",
  ARPU_SCORE: "امتیاز درآمد",
  CLV_SCORE: "امتیاز ارزش طول عمر",
  GROWTH_SCORE: "امتیاز رشد",
  DATA_USAGE_SCORE: "امتیاز مصرف اینترنت",
  VOICE_USAGE_SCORE: "امتیاز مکالمه",
  Transaction_Frequency_SCORE: "امتیاز تعداد تراکنش",
  TS_Score: "امتیاز پایداری زمانی",
  CI_Score: "امتیاز سازگاری",
  decline_probability: "احتمال افت فعالیت",
  risk_index: "شاخص خطر",
  "Prepare downloadable output": "آماده‌سازی فایل دانلود",
  "Save dataset report": "ذخیره گزارش داده‌ها",
  "Operation failed.": "عملیات ناموفق بود.",
  "No usable historical events through this month.":
    "تا پایان ماه انتخاب‌شده، رخداد تاریخی قابل استفاده‌ای وجود ندارد.",
  "All three sources need usable historical events.":
    "هر سه منبع باید رخداد تاریخی قابل استفاده داشته باشند.",
  "At least seven complete common-history months are needed. Provide the historical files for initial setup.":
    "برای شروع، حداقل هفت ماه تاریخچه مشترک کامل لازم است. فایل‌های تاریخی را وارد کنید.",
  "Confirm that all three feeds are complete through the selected observation month. Missing feed data must not be labeled as inactivity.":
    "کامل بودن هر سه منبع تا پایان ماه انتخاب‌شده را تأیید کنید. نبود داده نباید غیرفعال بودن مشتری تلقی شود.",
  "Select a completed month before the current calendar month.":
    "یک ماه کامل پیش از ماه جاری را انتخاب کنید.",
  "Use YYYY-MM.": "ماه را با قالب سال-ماه میلادی وارد کنید.",
  "as_of_month must be YYYY-MM.":
    "ماه مشاهده باید با قالب سال-ماه میلادی وارد شود.",
  "Monthly updates must not move backwards. Use a separate output folder for historical experiments.":
    "ماه به‌روزرسانی نباید از اجرای قبلی قدیمی‌تر باشد. برای آزمون تاریخی، پوشه خروجی جدا استفاده کنید.",
  "Monthly k=3 needs at least three customers and three distinct feature vectors.":
    "خوشه‌بندی ماهانه با سه گروه به حداقل سه مشتری با ویژگی‌های متفاوت نیاز دارد.",
  "Provide both the date column and usage column, or leave both empty.":
    "نام هر دو ستون تاریخ و مصرف را وارد کنید یا هر دو را خالی بگذارید.",
  "Frequency must be day, week or month.":
    "بازه تجمیع باید روزانه، هفتگی یا ماهانه باشد.",
  "Usage totals overflowed. Check the selected values.":
    "مجموع مصرف از محدوده عددی خارج شده است؛ مقادیر انتخاب‌شده را بررسی کنید.",
  PEER_ARPU_SCORE: "امتیاز همتایان: درآمد",
  PEER_CLV_SCORE: "امتیاز همتایان: ارزش طول عمر",
  PEER_GROWTH_SCORE: "امتیاز همتایان: رشد",
  PEER_DATA_USAGE_SCORE: "امتیاز همتایان: مصرف اینترنت",
  PEER_VOICE_USAGE_SCORE: "امتیاز همتایان: مکالمه",
  PEER_Transaction_Frequency_SCORE: "امتیاز همتایان: تعداد تراکنش",
  PEER_TS_Score: "امتیاز همتایان: پایداری زمانی",
  PEER_CI_Score: "امتیاز همتایان: سازگاری",
};
function persianLabel(value) {
  const text = String(value ?? "");
  if (Object.prototype.hasOwnProperty.call(persianLabels, text)) {
    return persianLabels[text];
  }
  // Translate the fixed message text while preserving actual column and file names.
  if (text.startsWith("Column not found: ")) {
    return "ستون پیدا نشد: " + text.slice("Column not found: ".length);
  }
  const sourceNames = {
    order: "خرید",
    data_cdr: "اینترنت",
    voice_cdr: "مکالمه",
  };
  if (text.startsWith("Ingest and clean source ")) {
    const source = text.slice("Ingest and clean source ".length);
    return "ورود و پاک‌سازی منبع " + (sourceNames[source] || source);
  }
  if (text.endsWith(": rows read and processed")) {
    const source = text.split(":")[0];
    return (
      (sourceNames[source] || source) + ": ردیف‌های خوانده‌شده و پردازش‌شده"
    );
  }
  if (text.includes("No such file or directory:")) {
    const filePath = text.split("No such file or directory:")[1].trim();
    return "فایل ورودی پیدا نشد: " + filePath;
  }
  if (text.startsWith("Unknown standard: ")) {
    return (
      "معیار امتیازدهی ناشناخته است: " + text.slice("Unknown standard: ".length)
    );
  }
  if (text.startsWith("Usecols do not match columns")) {
    const missingColumns = text.slice(text.lastIndexOf(":") + 1);
    return "این ستون‌ها در فایل ورودی پیدا نشدند: " + missingColumns;
  }
  return text;
}

if (typeof Chart !== "undefined")
  Chart.defaults.font.family = "Vazirmatn, Tahoma, sans-serif";
const chartInstances = {};

// Escape data before inserting it into HTML without modifying the original values.
function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        character
      ],
  );
}
// Display download links only for valid HTTP or HTTPS URLs.
function downloadButton(url, label = "دانلود خروجی") {
  if (!url) return "";
  const parsed = new URL(url, location.href);
  if (!["http:", "https:"].includes(parsed.protocol)) return "";
  return `<a class="download-btn" href="${escapeHtml(parsed.href)}" download>${escapeHtml(label)}</a>`;
}
// Destroy the previous chart before creating another one.
function replaceChart(canvasId, configuration) {
  if (chartInstances[canvasId]) {
    chartInstances[canvasId].destroy();
    delete chartInstances[canvasId];
  }
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  if (typeof Chart === "undefined") {
    canvas.replaceWith(document.createTextNode("نمودار در دسترس نیست."));
    return;
  }
  chartInstances[canvasId] = new Chart(canvas, configuration);
}
// Plot customer counts in each observed score bin.
function renderStatsChart(stats, canvasId) {
  if (!stats?.histogram) return;
  const edges = stats.histogram.bin_edges;
  replaceChart(canvasId, {
    type: "bar",
    data: {
      labels: edges.slice(0, -1).map((edge, i) => `${edge} - ${edges[i + 1]}`),
      datasets: [
        {
          label: persianLabel(stats.column),
          data: stats.histogram.counts,
          backgroundColor: "#11645b",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { title: { display: true, text: persianLabel(stats.column) } },
        y: {
          beginAtZero: true,
          title: { display: true, text: "کاربران" },
          ticks: { precision: 0 },
        },
      },
    },
  });
}
// Plot group membership counts and translate keys only for display.
function renderCountChart(counts, canvasId, label) {
  replaceChart(canvasId, {
    type: "bar",
    data: {
      labels: Object.keys(counts).map(persianLabel),
      datasets: [
        {
          label: label || "کاربران",
          data: Object.values(counts),
          backgroundColor: [
            "#11645b",
            "#556c9c",
            "#a66516",
            "#73827c",
            "#9a5363",
          ],
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { precision: 0 },
          title: { display: true, text: "کاربران" },
        },
      },
    },
  });
}
// Fill the existing card with customer counts, a chart and download links.
function renderSummary(data, target, prefix) {
  const distributions = data.distributions || {};
  const metricNames = Object.keys(distributions).filter(
    (name) => distributions[name],
  );
  const groupCounts = data.counts || {};
  const canvasId = prefix + "SummaryChart";

  // Select decline probability by default when available.
  let selectedMetric = metricNames[0];
  if (metricNames.includes("decline_probability")) {
    selectedMetric = "decline_probability";
  }

  let metricSelector = "";
  if (metricNames.length > 1) {
    const options = metricNames
      .map((name) => {
        const selected = name === selectedMetric ? "selected" : "";
        return `<option value="${escapeHtml(name)}" ${selected}>${escapeHtml(persianLabel(name))}</option>`;
      })
      .join("");
    metricSelector = `
      <label for="${prefix}Metric">معیار امتیاز</label>
      <select id="${prefix}Metric">${options}</select>`;
  }

  // Build HTML sections separately to keep conditional rendering readable.
  let chartContent =
    '<p class="empty-state">داده عددی برای رسم نمودار موجود نیست.</p>';
  if (metricNames.length > 0 || Object.keys(groupCounts).length > 0) {
    const chartLabel = escapeHtml(data.chartLabel || "توزیع نتایج");
    chartContent = `<canvas id="${canvasId}" aria-label="${chartLabel}" role="img"></canvas>`;
  }
  const count = Number(data.count || 0).toLocaleString("fa-IR");
  const countLabel = escapeHtml(data.countLabel || "کاربران امتیازدهی‌شده");

  target.innerHTML = `
    <section class="panel">
      <div class="result-summary">
        <div><span class="metric-label">${countLabel}</span><strong class="metric-value">${count}</strong></div>
        <div class="result-actions">
          ${downloadButton(data.download_url)}
          ${downloadButton(data.report_download_url, "دانلود گزارش")}
        </div>
      </div>
      ${metricSelector}
      <div class="summary-chart">${chartContent}</div>
    </section>`;

  if (metricNames.length > 0) {
    renderStatsChart(distributions[selectedMetric], canvasId);
  } else if (Object.keys(groupCounts).length > 0) {
    renderCountChart(groupCounts, canvasId, data.chartLabel);
  }

  const selector = document.getElementById(prefix + "Metric");
  if (selector) {
    selector.addEventListener("change", () => {
      renderStatsChart(distributions[selector.value], canvasId);
    });
  }
}
// Convert the scoring response into the shared result format.
function renderScoreSummary(data, target, prefix) {
  const score = data.score || {};
  renderSummary(
    {
      count: score.rows_scored,
      download_url: score.download_url,
      distributions:
        score.distributions ||
        (score.stats ? { [score.stats.column]: score.stats } : {}),
    },
    target,
    prefix,
  );
}
// Show a sending message until the server returns a job identifier.
function setLoading(targetStatusArea, targetResultsArea) {
  targetStatusArea = targetStatusArea || statusArea;
  targetResultsArea = targetResultsArea || resultsArea;
  delete targetStatusArea.dataset.jobStatus;
  targetStatusArea.innerHTML =
    '<div class="panel"><div class="loading"><div class="spinner"></div>در حال ارسال درخواست به سرور…</div></div>';
  targetResultsArea.innerHTML = "";
}
// Keep stage history and show a readable processing-error message.
function setError(error, targetStatusArea, targetResultsArea) {
  const status = targetStatusArea || statusArea;
  const results = targetResultsArea || resultsArea;
  const info = typeof error === "string" ? { message: error } : error;

  // Preserve previous stage durations when the server reports an error.
  let history = "";
  if (status.dataset.jobStatus === "failed") {
    history = status.querySelector(".progress-panel")?.outerHTML || "";
  }
  let locationHtml = "";
  if (info.location) {
    locationHtml = `<div class="error-loc">${escapeHtml(info.location)}</div>`;
  }
  let technicalDetails = "";
  if (info.trace) {
    technicalDetails = `
      <details><summary>جزئیات فنی</summary>
        <pre class="error-trace open">${escapeHtml(info.trace)}</pre>
      </details>`;
  }
  const message = persianLabel(
    info.message || "ورودی‌ها را بررسی و دوباره تلاش کنید.",
  );
  status.innerHTML = `
    ${history}
    <div class="panel"><div class="error-box" role="alert">
      <strong>عملیات ناموفق بود</strong>
      <p>${escapeHtml(message)}</p>
      ${locationHtml}
      ${technicalDetails}
    </div></div>`;
  results.innerHTML = "";
}
// Preserve the actual-duration panel after success.
function clearStatus(targetStatusArea) {
  const area = targetStatusArea || statusArea;
  if (!area.querySelector(".progress-panel")) area.innerHTML = "";
}
window.addEventListener("error", (event) => {
  if (event.message)
    setError({ message: event.message, trace: event.error?.stack });
});
window.addEventListener("unhandledrejection", (event) =>
  setError({ message: event.reason?.message || String(event.reason) }),
);
async function postJson(apiUrl, body) {
  return runTracked(apiUrl, body);
}

// Share three-column domain input handling between consistency and temporal stability.
function readDomainInputs(prefix, domainNames) {
  const domains = {};
  const missingDomains = [];
  for (const domain of domainNames) {
    const addressInput = document.querySelector(
      `.${prefix}-address[data-domain="${domain}"]`,
    );
    const inputs = Array.from(
      document.querySelectorAll(`.${prefix}-col[data-domain="${domain}"]`),
    );
    inputs.sort(
      (first, second) => Number(first.dataset.col) - Number(second.dataset.col),
    );
    const columns = inputs.map((input) => input.value);
    if (columns.some((column) => !column)) {
      missingDomains.push(domain);
      continue;
    }
    domains[domain] = {
      dataset_address: addressInput.value.trim() || undefined,
      columns: columns,
    };
  }
  return { domains: domains, missingDomains: missingDomains };
}

// Share request execution so button state and errors are handled consistently.
async function executeScoringRequest(
  apiUrl,
  body,
  button,
  status,
  results,
  renderResult,
) {
  button.disabled = true;
  setLoading(status, results);
  try {
    const data = await postJson(apiUrl, body);
    clearStatus(status);
    renderResult(data);
  } catch (error) {
    setError(
      {
        source: error.isBackendError ? "backend" : "frontend",
        message: error.message || String(error),
        location: error.location,
        trace: error.isBackendError ? error.trace : error.stack,
      },
      status,
      results,
    );
  } finally {
    button.disabled = false;
  }
}
