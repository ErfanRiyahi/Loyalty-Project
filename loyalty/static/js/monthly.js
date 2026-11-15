(() => {
  const button = document.getElementById("runMonthlyBtn");
  const rollback = document.getElementById("adaptiveRollback");
  const status = document.getElementById("monthlyStatusArea");
  const results = document.getElementById("monthlyResultsArea");
  const now = new Date(); now.setDate(1); now.setMonth(now.getMonth()-1);
  document.getElementById("adaptiveMonth").value = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,"0")}`;
  function value(value) { return value == null ? "ناموجود" : Number(value).toFixed(3); }
  function render(data) {
    const decisions = {rolled_back:"نسخهٔ قبلی بازیابی شد", bootstrap:"اولین مدل فعال پذیرفته شد", promoted:"مدل جدید جایگزین شد", rejected:"مدل جدید پذیرفته نشد؛ نسخهٔ فعال حفظ شد"};
    const candidate = data.candidate || {}, incumbent = data.incumbent || {};
    results.innerHTML = `<section class="panel"><h2>${decisions[data.decision] || "وضعیت یادگیری تطبیقی"}</h2>
      <p>نسخهٔ فعال: ${escapeHtml(data.active_run_id || "هنوز مدلی پذیرفته نشده")}</p>
      ${data.as_of_month ? `<p>دورهٔ ارزیابی: ${escapeHtml(data.as_of_month)}</p>` : ""}
      ${data.candidate ? `<div class="table-scroll"><table><thead><tr><th>معیار روی نمونهٔ ارزیابی مشترک</th><th>مدل فعلی پیش از ارزیابی</th><th>مدل جدید</th></tr></thead><tbody><tr><td>جدایی خوشه‌ها (بیشتر بهتر)</td><td>${value(incumbent.silhouette)}</td><td>${value(candidate.silhouette)}</td></tr><tr><td>هم‌پوشانی خوشه‌ها (کمتر بهتر)</td><td>${value(incumbent.davies_bouldin)}</td><td>${value(candidate.davies_bouldin)}</td></tr></tbody></table></div><p>کمترین پایداری مدل جدید: ${value(data.stability?.ari_min)} | تعداد مشتریان ارزیابی: ${data.evaluation_rows}</p>` : ""}
      ${(data.reasons || []).map(reason=>`<p>${escapeHtml(reason)}</p>`).join("")}
      <p>این ارزیابی مربوط به کیفیت و پایداری گروه‌بندی است؛ به‌تنهایی به معنی بهبود نتیجهٔ کسب‌وکار نیست.</p>
      ${data.run_id ? downloadButton("/adaptive/report", "دانلود گزارش ارزیابی") : ""}
      ${data.active_run_id ? downloadButton("/adaptive/download", "دانلود خروجی نسخهٔ فعال") : ""}
      </section>`;
  }
  async function refresh(show=true) {
    const response = await fetch("/adaptive/status",{cache:"no-store"});
    if (!response.ok) throw new Error("خواندن وضعیت مدل ممکن نشد.");
    const data = await response.json(); rollback.disabled = !data.can_rollback;
    if (show && (data.run_id || data.active_run_id)) render(data);
  }
  button.addEventListener("click",async()=>{
    button.disabled=true; rollback.disabled=true; setLoading(status,results);
    try {
      const fields=Array.from(document.querySelectorAll(".adaptive-source"));
      const sources=Object.fromEntries(fields.map(field=>[field.dataset.source,field.value.trim()]));
      const custom=Object.values(sources).some(Boolean);
      if(custom && Object.values(sources).some(value=>!value)) throw new Error("مسیر هر شش فایل امتیازدهی را وارد کنید.");
      const data=await postJson("/adaptive/update",{as_of_month:document.getElementById("adaptiveMonth").value,confirm_scores:document.getElementById("adaptiveConfirm").checked,...(custom?{sources}:{})});
      clearStatus(status); render(data); await refresh(false);
    } catch(error){setError({message:error.message},status,results);}
    finally{button.disabled=false;}
  });
  rollback.addEventListener("click",async()=>{
    button.disabled=true;rollback.disabled=true;
    try {const data=await postJson("/adaptive/rollback",{});clearStatus(status);await refresh();status.textContent=`نسخهٔ ${data.active_run_id} بازیابی شد.`;}
    catch(error){setError({message:error.message},status,results);}
    finally{button.disabled=false;refresh(false).catch(()=>{});}
  });
  window.renderMonthly=data=>{render(data);refresh(false).catch(()=>{});};
  refresh().catch(error=>{status.textContent=error.message;});
})();
