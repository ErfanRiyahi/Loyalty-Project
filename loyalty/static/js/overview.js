const dsStatusArea = document.getElementById("dsStatusArea");
const dsResultsArea = document.getElementById("dsResultsArea");
const runDSBtn = document.getElementById("runDSBtn");

// Display basic statistics, column names and the time chart in the existing panels.
function renderDSResults(data) {
  const summary = data.dataset_overview || {};
  const series = data.time_series;
  const columns = summary.column_info || [];

  // Keep original column names for input suggestions.
  document.getElementById("profileColumnNames").innerHTML = columns
    .map((column) => {
      return `<option value="${escapeHtml(column.name)}"></option>`;
    })
    .join("");

  function metricCard(label, value) {
    const number = Number(value || 0).toLocaleString("fa-IR");
    return `<div class="profile-metric"><span>${label}</span><strong>${number}</strong></div>`;
  }
  let metrics = metricCard("ردیف‌ها", summary.rows);
  metrics += metricCard("ستون‌ها", summary.columns);
  metrics += metricCard("مقادیر تهی", summary.null_values);
  metrics += metricCard("ردیف‌های دارای مقدار تهی", summary.rows_with_nulls);
  metrics += metricCard("ردیف‌های تکراری", summary.duplicate_rows);
  if (summary.unique_users !== undefined) {
    metrics += metricCard("کاربران یکتا", summary.unique_users);
  }
  if (series) {
    metrics += metricCard("تاریخ‌های نامعتبر", summary.invalid_dates);
    metrics += metricCard("مقادیر مصرف نامعتبر", summary.invalid_usage);
    metrics += metricCard(
      "ردیف‌های استفاده‌شده در نمودار",
      summary.rows_used_in_chart,
    );
    metrics += metricCard(
      "ردیف‌های کنارگذاشته‌شده از نمودار",
      summary.rows_excluded_from_chart,
    );
  }

  const memory = (Number(summary.memory_bytes || 0) / 1048576).toFixed(2);
  let metadata = `حافظه: ${memory} مگابایت`;
  if (summary.date_range) {
    const firstDate = summary.date_range.start?.slice(0, 10) || "نامشخص";
    const lastDate = summary.date_range.end?.slice(0, 10) || "نامشخص";
    metadata += ` | بازه تاریخ: ${escapeHtml(firstDate)} - ${escapeHtml(lastDate)}`;
  }

  let chartContent =
    '<p class="empty-state">نام ستون تاریخ و میزان مصرف را در بالا وارد کنید و دوباره داده‌ها را بررسی کنید.</p>';
  if (series) {
    chartContent =
      '<p class="empty-state">ردیفی با تاریخ و میزان مصرف معتبر موجود نیست.</p>';
    if (series.points.length > 0) {
      const frequency = escapeHtml(persianLabel(series.frequency));
      chartContent = `
        <p class="compact-meta">${escapeHtml(series.usage_column)} | مجموع در هر ${frequency} | زمان UTC</p>
        <div class="summary-chart"><canvas id="profileTimeChart" role="img" aria-label="میزان مصرف در طول زمان"></canvas></div>`;
    }
  }

  const columnRows = columns
    .map((column) => {
      return `<tr><td>${escapeHtml(column.name)}</td><td>${escapeHtml(column.dtype)}</td><td>${column.nulls}</td><td>${column.null_percentage}%</td><td>${column.unique}</td></tr>`;
    })
    .join("");

  // Use the preview only for inspection; compute statistics and charts from all rows.
  const preview = summary.preview || [];
  let previewPanel = "";
  if (preview.length > 0) {
    const names = Object.keys(preview[0]);
    const headers = names
      .map((name) => `<th>${escapeHtml(name)}</th>`)
      .join("");
    const rows = preview
      .map((row) => {
        const cells = names
          .map((name) => `<td>${escapeHtml(row[name] ?? "تهی")}</td>`)
          .join("");
        return `<tr>${cells}</tr>`;
      })
      .join("");
    previewPanel = `
      <section class="panel"><h2>پنج ردیف نخست</h2>
        <div class="table-scroll"><table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table></div>
      </section>`;
  }

  dsResultsArea.innerHTML = `
    <section class="panel">
      <div class="result-summary"><h2>اطلاعات اولیه داده‌ها</h2>${downloadButton(data.download_url, "دانلود گزارش")}</div>
      <div class="profile-metrics">${metrics}</div>
      <p class="compact-meta">${metadata}</p>
    </section>
    <section class="panel"><h2>میزان مصرف در طول زمان</h2>${chartContent}</section>
    <section class="panel"><h2>ستون‌ها</h2>
      <div class="table-scroll"><table>
        <thead><tr><th>نام</th><th>نوع</th><th>تهی</th><th>درصد تهی</th><th>یکتا</th></tr></thead>
        <tbody>${columnRows}</tbody>
      </table></div>
    </section>
    ${previewPanel}`;
  if (series?.points.length) {
    replaceChart("profileTimeChart", {
      type: "line",
      data: {
        datasets: [
          {
            label: series.usage_column,
            data: series.points.map((point) => ({
              x: Date.parse(point.date),
              y: point.usage,
            })),
            borderColor: "#11645b",
            backgroundColor: "#11645b",
            pointRadius: series.points.length > 100 ? 1 : 3,
            tension: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) =>
                new Date(items[0].parsed.x).toISOString().slice(0, 10),
            },
          },
        },
        scales: {
          x: {
            type: "linear",
            title: { display: true, text: series.date_column },
            ticks: {
              maxTicksLimit: 6,
              callback: (value) => new Date(value).toISOString().slice(0, 10),
            },
          },
          y: { title: { display: true, text: "مجموع مصرف" } },
        },
      },
    });
  }
}
// Read both column names; the input file must be accessible to the Python server.
async function runDatasetOverview() {
  const path = document.getElementById("dsDatasetAddress").value.trim();
  const dateColumn = document.getElementById("dsDateColumn").value,
    usageColumn = document.getElementById("dsUsageColumn").value;
  if (!path) {
    setError("مسیر فایل داده را وارد کنید.", dsStatusArea, dsResultsArea);
    return;
  }
  if (Boolean(dateColumn) !== Boolean(usageColumn)) {
    setError(
      "نام هر دو ستون تاریخ و میزان مصرف را وارد کنید.",
      dsStatusArea,
      dsResultsArea,
    );
    return;
  }
  runDSBtn.disabled = true;
  setLoading(dsStatusArea, dsResultsArea);
  try {
    const data = await postJson(
      "/dataset_overview",
      {
        dataset_address: path,
        date_column: dateColumn || null,
        usage_column: usageColumn || null,
        user_column: document.getElementById("dsUserColumn").value || null,
        frequency: document.getElementById("dsFrequency").value,
      },
    );
    clearStatus(dsStatusArea);
    renderDSResults(data);
  } catch (error) {
    setError(
      { message: error.message, trace: error.trace },
      dsStatusArea,
      dsResultsArea,
    );
  } finally {
    runDSBtn.disabled = false;
  }
}
runDSBtn.addEventListener("click", runDatasetOverview);
