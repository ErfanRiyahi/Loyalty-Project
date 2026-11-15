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
    const data = await postJson("/cluster", {
      run_missing: false,
      run_stability: document.getElementById("clusterStability").checked,
    });

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
