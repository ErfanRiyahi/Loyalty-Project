/* Polling reads real server state; timers never generate progress. */
const operationPanels = {
  "/analyze": ["statusArea", "resultsArea", "runBtn"],
  "/consistency_index": ["ciStatusArea", "ciResultsArea", "runCIBtn"],
  "/temporal_stability": ["tsStatusArea", "tsResultsArea", "runTSBtn"],
  "/dataset_overview": ["dsStatusArea", "dsResultsArea", "runDSBtn"],
  "/cluster": ["clusterStatusArea", "clusterResultsArea", "runClusterBtn"],
  "/churn/assess": ["churnStatusArea", "churnResultsArea", "runChurnBtn"],
  "/churn/update": ["churnStatusArea", "churnResultsArea", "updateChurnBtn"],
  "/adaptive/update": ["monthlyStatusArea", "monthlyResultsArea", "runMonthlyBtn"],
  "/adaptive/rollback": ["monthlyStatusArea", "monthlyResultsArea", "adaptiveRollback"],
  "/monthly/update": [
    "monthlyStatusArea",
    "monthlyResultsArea",
    "runMonthlyBtn",
  ],
};
const activeOperations = new Map();
const seconds = (n) =>
  `${Number(n).toLocaleString("fa-IR", { maximumFractionDigits: 1 })} ثانیه`;
// Keep server error details available to the result renderer.
function jobError(data) {
  const e = new Error(data.error || "عملیات ناموفق بود.");
  e.isBackendError = true;
  e.location = data.file ? `${data.file}:${data.line || ""}` : "";
  e.trace = data.traceback;
  return e;
}
// Send the HTTP request and handle invalid responses and server errors separately.
async function jobJson(url, options = {}) {
  const response = await fetch(url, { ...options, cache: "no-store" });
  let data;
  try {
    data = await response.json();
  } catch (_) {
    throw new Error("پاسخ سرور قابل خواندن نیست.");
  }
  if (!response.ok) {
    const e = jobError(data);
    e.httpStatus = response.status;
    throw e;
  }
  return data;
}
// Display server-reported state without estimating progress.
function paintJob(job, path) {
  const area = document.getElementById(operationPanels[path][0]);
  const live = job.events.filter((event) => event.status === "running").at(-1);
  const success = job.status === "succeeded";
  area.innerHTML = `<section class="panel progress-panel" aria-label="وضعیت پردازش">
 <div class="progress-heading"><span class="eyebrow">وضعیت زنده سرور</span><strong>${success ? "انجام شد" : job.status === "failed" ? "ناموفق" : "در حال پردازش"}</strong></div>
 <h2>${escapeHtml(persianLabel(job.stage || (success ? "خروجی آماده است" : job.events.at(-1)?.label || "آماده‌سازی عملیات")))}</h2>
 ${job.status !== "failed" ? `<progress max="100" ${success ? 'value="100"' : ""} aria-label="پیشرفت عملیات"></progress>` : ""}
 <div class="progress-meta"><span>زمان سپری‌شده کل: ${seconds(job.elapsed_seconds)}</span>${live ? `<span>زمان مرحله جاری: ${seconds(live.elapsed_seconds)}</span>` : ""}</div>
 ${live?.completed_units != null ? `<p>${escapeHtml(persianLabel(live.description || ""))} - ${live.completed_units.toLocaleString("fa-IR")} ${escapeHtml(persianLabel(live.unit || "ردیف"))}</p>` : ""}
 <details open><summary>مدت اجرای مراحل (${job.events.length.toLocaleString("fa-IR")})</summary><ol class="stage-history">${job.events
   .slice(-50)
   .map(
     (event) =>
       `<li class="${event.status}"><span>${event.status === "completed" ? "✓" : event.status === "failed" ? "!" : "◌"} ${escapeHtml(persianLabel(event.label))}</span><bdi>${seconds(event.elapsed_seconds)}</bdi></li>`,
   )
   .join("")}</ol></details>
 <small class="job-id">شناسه عملیات: <bdi>${escapeHtml(job.operation_id)}</bdi></small></section>`;
  area.dataset.jobStatus = job.status;
  area.setAttribute("aria-busy", String(job.status === "running"));
  if (area.dataset.announcement !== `${job.status}:${job.stage}`) {
    area.dataset.announcement = `${job.status}:${job.stage}`;
    document.getElementById("operationAnnouncement").textContent = success
      ? "عملیات با موفقیت پایان یافت"
      : persianLabel(job.stage) || "عملیات ناموفق بود";
  }
}
// Reconnect to the same job instead of starting another calculation.
async function watchJob(base, id, path) {
  const area = document.getElementById(operationPanels[path][0]);
  let failures = 0;
  while (true) {
    let job;
    try {
      job = await jobJson(new URL("jobs/" + id, base));
      failures = 0;
    } catch (e) {
      if (e.httpStatus === 404) {
        sessionStorage.removeItem("loyalty-operation");
        throw e;
      }
      failures++;
      if (!area.querySelector(".connection-notice"))
        area.insertAdjacentHTML(
          "beforeend",
          '<p class="connection-notice" role="status">ارتباط قطع شده است؛ در حال اتصال دوباره به همان عملیات…</p>',
        );
      await new Promise((resolve) =>
        setTimeout(resolve, Math.min(1000 * failures, 10000)),
      );
      continue;
    }
    paintJob(job, path);
    if (job.status !== "running") {
      sessionStorage.removeItem("loyalty-operation");
      if (job.status === "failed") throw jobError(job.result || {});
      return job.result;
    }
    await new Promise((resolve) => setTimeout(resolve, 700));
  }
}
// Use a stable request key to prevent duplicate processing on retries.
async function runTracked(apiUrl, body) {
  const url = new URL(apiUrl, location.href),
    path = url.pathname;
  if (!operationPanels[path])
    throw new Error("نشانی این عملیات پشتیبانی نمی‌شود.");
  if (activeOperations.has(path)) return activeOperations.get(path);
  if (activeOperations.size)
    throw new Error("یک عملیات در حال اجراست؛ منتظر پایان آن بمانید.");
  const base = new URL("/", url),
    key = crypto.randomUUID();
  const promise = (async () => {
    let options = { method: "POST", headers: { "Idempotency-Key": key } };
    if (body instanceof FormData) {
      body.set("path", path);
      options.body = body;
    } else {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify({ path, body });
    }
    sessionStorage.setItem(
      "loyalty-operation",
      JSON.stringify({ base: base.href, key, path }),
    );
    let start;
    // Recover an uncertain start using the same idempotency key.
    while (true) {
      try {
        start = await jobJson(new URL("jobs", base), options);
        break;
      } catch (e) {
        if (e.httpStatus) {
          sessionStorage.removeItem("loyalty-operation");
          throw e;
        }
        document.getElementById(operationPanels[path][0]).innerHTML =
          '<div class="panel" role="status">ارتباط قطع شده است؛ در حال بازیابی همان درخواست قبلی…</div>';
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    }
    sessionStorage.setItem(
      "loyalty-operation",
      JSON.stringify({ base: base.href, id: start.operation_id, path }),
    );
    return await watchJob(base, start.operation_id, path);
  })();
  activeOperations.set(path, promise);
  try {
    return await promise;
  } finally {
    activeOperations.delete(path);
  }
}
window.addEventListener("DOMContentLoaded", async () => {
  let saved;
  try {
    saved = JSON.parse(sessionStorage.getItem("loyalty-operation"));
  } catch (_) {
    return;
  }
  if (!saved || !operationPanels[saved.path]) return;
  const [statusId, resultsId, buttonId] = operationPanels[saved.path];
  const tab = {
    "/analyze": "Standard",
    "/consistency_index": "CI",
    "/temporal_stability": "TS",
    "/dataset_overview": "DS",
    "/cluster": "Cluster",
    "/churn/assess": "Churn",
    "/monthly/update": "Monthly",
    "/churn/update": "Churn",
    "/adaptive/update": "Monthly",
    "/adaptive/rollback": "Monthly",
  }[saved.path];
  document.getElementById("tabBtn" + tab).click();
  const button = document.getElementById(buttonId);
  button.disabled = true;
  const renderers = {
    "/analyze": renderResults,
    "/consistency_index": renderCIResults,
    "/temporal_stability": renderTSResults,
    "/dataset_overview": renderDSResults,
    "/cluster": renderClusterResults,
    "/monthly/update": window.renderMonthly,
    "/adaptive/update": window.renderMonthly,
    "/adaptive/rollback": window.renderMonthly,
    "/churn/update": window.renderChurnResults,
    "/churn/assess": window.renderChurnResults,
  };
  const task = (async () => {
    if (!saved.id) {
      while (true) {
        try {
          saved.id = (
            await jobJson(new URL("jobs/request/" + saved.key, saved.base))
          ).operation_id;
          break;
        } catch (e) {
          if (e.httpStatus) {
            sessionStorage.removeItem("loyalty-operation");
            throw e;
          }
          await new Promise((r) => setTimeout(r, 2000));
        }
      }
    }
    return await watchJob(saved.base, saved.id, saved.path);
  })();
  activeOperations.set(saved.path, task);
  try {
    const data = await task;
    renderers[saved.path]?.(data);
  } catch (e) {
    setError(
      e.message,
      document.getElementById(statusId),
      document.getElementById(resultsId),
    );
  } finally {
    button.disabled = false;
    activeOperations.delete(saved.path);
  }
});
