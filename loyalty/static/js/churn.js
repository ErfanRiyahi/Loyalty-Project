(() => {
  const button = document.getElementById("runChurnBtn");
  const status = document.getElementById("churnStatusArea");
  const results = document.getElementById("churnResultsArea");
  const methodInput = document.getElementById("churnMethod");
  function updateInputs() {
    const trained = methodInput.value === "trained_monthly";
    document.getElementById("churnFile").disabled = trained;
    document.getElementById("churnPath").disabled = trained;
  }
  methodInput.addEventListener("change", updateInputs);
  updateInputs();
  button.addEventListener("click", async () => {
    button.disabled = true;
    setLoading(status, results);
    try {
      const method = methodInput.value;
      if (method === "trained_monthly") {
        const response = await fetch("/monthly/status");
        const data = await response.json();
        if (!response.ok || !data.run_id)
          throw new Error("ابتدا یادگیری ماهانه را اجرا کنید.");
        clearStatus(status);
        renderTrainedPrediction(data);
        return;
      }
      const file = document.getElementById("churnFile").files[0];
      let data;
      if (file) {
        const body = new FormData();
        body.append("file", file);
        body.append("method", method);
        data = await runTracked("/churn/assess", body);
      } else
        data = await postJson("/churn/assess", {
          method,
          dataset_address: document.getElementById("churnPath").value.trim(),
        });
      clearStatus(status);
      renderChurnResults(data);
    } catch (error) {
      setError({ message: error.message }, status, results);
    } finally {
      button.disabled = false;
    }
  });
  // Read the latest monthly model without training a new one.
  function renderTrainedPrediction(data) {
    const probability = data.distributions?.decline_probability;
    renderSummary(
      {
        count: data.customers,
        countLabel: "کاربران ارزیابی‌شده",
        distributions: probability ? { decline_probability: probability } : {},
        counts: data.prediction_counts || data.cluster_counts,
        chartLabel: data.prediction_counts
          ? "وضعیت پیش‌بینی"
          : "گروه‌های مشتریان",
        download_url: data.download_url || "/monthly/download",
        report_download_url: data.report_download_url || "/monthly/report",
      },
      results,
      "prediction",
    );
  }
  // Display grouped risk indices; these are not confirmed churn probabilities.
  function renderChurnResults(data) {
    renderSummary(
      {
        count: data.rows,
        countLabel: "کاربران ارزیابی‌شده",
        counts: data.counts,
        chartLabel: "گروه‌های ارزیابی خطر",
        download_url: data.download_url,
        report_download_url: data.report_download_url,
      },
      results,
      "risk",
    );
  }
  window.renderChurnResults = renderChurnResults;
})();
