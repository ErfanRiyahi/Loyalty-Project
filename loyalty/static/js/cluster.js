// ---------- Cluster tab ----------
const clusterStatusArea = document.getElementById("clusterStatusArea");
const clusterResultsArea = document.getElementById("clusterResultsArea");
const runClusterBtn = document.getElementById("runClusterBtn");

const SEGMENT_COLORS = {
  Loyal: "#2ecc71",
  Neutral: "#f39c12",
  "At-Risk/Churning": "#e74c3c",
  "Limited (single-domain)": "#95a5a6",
};
function segmentColor(name) {
  return SEGMENT_COLORS[name] || "#7c8ba1";
}

function renderClusterResults(data) {
  renderSummary(
    {
      count: data.n_customers,
      countLabel: "کاربران پردازش‌شده",
      counts: data.segment_counts,
      chartLabel: "گروه‌های مشتریان",
      download_url: data.download_url,
      report_download_url: data.report_download_url,
    },
    clusterResultsArea,
    "cluster",
  );
}

async function runCluster() {
  runClusterBtn.disabled = true;
  setLoading(
    clusterStatusArea,
    clusterResultsArea,
    "در حال ارسال درخواست خوشه‌بندی…",
  );

  try {
    const payload = {
      input_mode: document.getElementById("clusterInputMode").value,
      run_missing: false,
      run_stability: document.getElementById("clusterStability").checked,
    };
    let body = payload;
    if (payload.input_mode === "custom") {
      payload.sources = {};
      body = new FormData();
      for (const field of document.querySelectorAll(".cluster-source-path")) {
        const key = field.dataset.source;
        const file = document.getElementById("cluster-file-" + key).files[0];
        if (file) body.append(key, file);
        else if (field.value.trim()) payload.sources[key] = field.value.trim();
        else throw new Error("مسیر یا فایل همهٔ معیارهای امتیازدهی را مشخص کنید.");
      }
      body.append("payload", JSON.stringify(payload));
    }
    const data = await runTracked("/cluster", body);

    clearStatus(clusterStatusArea);
    try {
      renderClusterResults(data);
    } catch (renderErr) {
      setError(
        {
          source: "frontend",
          message: renderErr.message || String(renderErr),
          trace: renderErr.stack || null,
        },
        clusterStatusArea,
        clusterResultsArea,
      );
    }
  } catch (err) {
    if (err && err.isBackendError) {
      setError(
        {
          source: "backend",
          message: err.message,
          location: err.location,
          trace: err.trace,
        },
        clusterStatusArea,
        clusterResultsArea,
      );
    } else {
      setError(
        {
          source: "frontend",
          message: (err && err.message) || String(err),
          trace: err && err.stack ? err.stack : null,
        },
        clusterStatusArea,
        clusterResultsArea,
      );
    }
  } finally {
    runClusterBtn.disabled = false;
  }
}

runClusterBtn.addEventListener("click", runCluster);

function buildClusterValidationHtml(
  validation,
  downloadUrl = "/cluster/validation/download",
) {
  return validation ? downloadButton(downloadUrl, "دانلود گزارش ارزیابی") : "";
}

function updateClusterInputMode() {
  document.getElementById("clusterCustomInputs").hidden = document.getElementById("clusterInputMode").value !== "custom";
}
document.getElementById("clusterInputMode").addEventListener("change", updateClusterInputMode);
async function refreshClusterSources() {
  const area = document.getElementById("clusterSourceInventory");
  try {
    const response = await fetch("/cluster/sources", {cache: "no-store"});
    if (!response.ok) throw new Error();
    const data = await response.json();
    const titles = {ARPU_CLV_GROWTH: "درآمد، ارزش طول عمر و رشد", DATA_USAGE: "مصرف اینترنت", VOICE_USAGE: "مکالمه", Transaction_Frequency: "تعداد تراکنش", TEMPORAL_STABILITY: "پایداری زمانی", CONSISTENCY_INDEX: "شاخص سازگاری"};
    area.innerHTML = `<div class="table-scroll"><table><thead><tr><th>معیار</th><th>مسیر آخرین خروجی</th><th>آخرین تغییر</th><th>وضعیت</th></tr></thead><tbody>${data.sources.map(source => `<tr><td>${escapeHtml(titles[source.standard] || source.standard)}</td><td dir="ltr">${escapeHtml(source.path)}</td><td>${source.modified_at ? escapeHtml(new Date(source.modified_at).toLocaleString("fa-IR")) : "—"}</td><td>${source.exists ? "آماده" : "هنوز تولید نشده"}</td></tr>`).join("")}</tbody></table></div>`;
  } catch { area.textContent = "خواندن فهرست آخرین فایل‌ها ممکن نشد؛ دوباره این بخش را باز کنید."; }
}
document.getElementById("tabBtnCluster").addEventListener("click", refreshClusterSources);
window.addEventListener("DOMContentLoaded", updateClusterInputMode);
refreshClusterSources();
