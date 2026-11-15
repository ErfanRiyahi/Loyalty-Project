(() => {
  const button = document.getElementById("runMonthlyBtn");
  const status = document.getElementById("monthlyStatusArea");
  const results = document.getElementById("monthlyResultsArea");
  const now = new Date();
  now.setDate(1);
  now.setMonth(now.getMonth() - 1);
  document.getElementById("monthlyMonth").value =
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  button.addEventListener("click", async () => {
    button.disabled = true;
    setLoading(status, results);
    try {
      const data = await postJson("/monthly/update", {
        as_of_month: document.getElementById("monthlyMonth").value,
        confirm_complete: document.getElementById("monthlyComplete").checked,
        sources: {
          order: document.getElementById("monthlyOrder").value.trim(),
          data_cdr: document.getElementById("monthlyData").value.trim(),
          voice_cdr: document.getElementById("monthlyVoice").value.trim(),
        },
      });
      clearStatus(status);
      renderMonthly(data);
    } catch (error) {
      setError({ message: error.message }, status, results);
    } finally {
      button.disabled = false;
    }
  });
  // Use the full monthly API result rather than building charts from a limited preview.
  function renderMonthly(data) {
    renderSummary(
      {
        count: data.customers,
        distributions: data.distributions,
        counts: data.cluster_counts,
        chartLabel: "گروه‌های ماهانه مشتریان",
        download_url: data.download_url || "/monthly/download",
        report_download_url: data.report_download_url || "/monthly/report",
      },
      results,
      "monthly",
    );
  }
  window.renderMonthly = renderMonthly;
  fetch("/monthly/status")
    .then((response) => response.json())
    .then((data) => {
      if (data.run_id) renderMonthly(data);
    })
    .catch(() => {});
})();
