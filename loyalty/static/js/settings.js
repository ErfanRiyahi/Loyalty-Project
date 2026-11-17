(() => {
  const storageKey = "loyalty.input-defaults.v2";
  const legacyStorageKey = "loyalty.input-defaults.v1";
  const container = document.getElementById("defaultsFields");
  const status = document.getElementById("defaultsStatus");
  const entries = [];
  const excluded = new Set(["churnMonth", "churnComplete", "adaptiveMonth", "adaptiveConfirm"]);
  let serial = 0;

  function addSetting(parent, key, labelText, original, apply, field = null) {
    const label = document.createElement("label");
    const editor = field ? field.cloneNode(true) : document.createElement("input");
    editor.id = `default-input-${++serial}`;
    editor.dataset.defaultKey = key;
    editor.removeAttribute("class");
    editor.removeAttribute("name");
    if (editor.tagName === "INPUT") editor.type = field?.type === "checkbox" ? "checkbox" : "text";
    label.htmlFor = editor.id;
    label.textContent = labelText;
    const set = value => {
      if (editor.type === "checkbox") editor.checked = value;
      else editor.value = value;
    };
    set(original);
    parent.append(label, editor);
    entries.push({key, original, apply, set, editor});
  }

  for (const panel of document.querySelectorAll(".tab-panel:not(#tabSettings)")) {
    const section = document.createElement("div");
    section.className = "domain-block";
    const heading = document.createElement("h3");
    heading.textContent = document.getElementById(panel.id.replace("tab", "tabBtn")).textContent;
    section.appendChild(heading);
    container.appendChild(section);
    if (panel.id === "tabStandard") {
      for (const option of standardSelect.options) {
        const title = document.createElement("h4");
        title.textContent = option.textContent;
        section.appendChild(title);
        addSetting(section, `standard.${option.value}.path`, "مسیر فایل داده", option.dataset.path,
          value => { option.dataset.path = value; });
        JSON.parse(option.dataset.columns).forEach((value, index) => {
          addSetting(section, `standard.${option.value}.column.${index}`, ["شناسه مشتری", "تاریخ", "مقدار"][index], value,
            next => {
              const columns = JSON.parse(option.dataset.columns);
              columns[index] = next;
              option.dataset.columns = JSON.stringify(columns);
            });
        });
      }
    }
    const domainSections = new Map();
    const domainTitles = {data:"اینترنت",voice:"مکالمه",spend:"هزینه",txn:"تعداد تراکنش",order:"خریدها"};
    for (const field of panel.querySelectorAll("input, select")) {
      if (!field.id || excluded.has(field.id) || field.type === "file" || field.classList.contains("col-input") || field.id === "datasetAddress") continue;
      const label = Array.from(panel.querySelectorAll("label")).find(item => item.htmlFor === field.id || item.contains(field));
      let parent = section;
      if (["tabCI", "tabTS"].includes(panel.id) && field.dataset.domain) {
        const domain = field.dataset.domain;
        if (!domainSections.has(domain)) {
          const group = document.createElement("fieldset");
          group.className = "domain-block";
          const legend = document.createElement("legend");
          legend.textContent = domainTitles[domain] || domain;
          group.appendChild(legend);
          section.appendChild(group);
          domainSections.set(domain, group);
        }
        parent = domainSections.get(domain);
      }
      const domain = field.dataset.domain && parent === section ? ` (${domainTitles[field.dataset.domain] || field.dataset.domain})` : "";
      const columnTitle = field.dataset.col !== undefined ? ["شناسه مشتری", "تاریخ", "مقدار"][Number(field.dataset.col)] : null;
      const text = (columnTitle || label?.textContent.trim() || field.getAttribute("aria-label") || field.id) + domain;
      const original = field.type === "checkbox" ? field.checked : field.value;
      addSetting(parent, field.id, text, original, value => {
        if (field.type === "checkbox") field.checked = value;
        else field.value = value;
      }, field);
    }
  }

  function readSaved() {
    try {
      const current = localStorage.getItem(storageKey);
      const migrating = current === null;
      const saved = JSON.parse(current ?? localStorage.getItem(legacyStorageKey) ?? "{}");
      if (!saved || typeof saved !== "object" || Array.isArray(saved)) return {};
      // Preserve raw-source defaults when moving the old monthly form into Churn.
      for (const [key, value] of Object.entries(saved)) {
        if (key.startsWith("monthly")) {
          const next = "churn" + key.slice("monthly".length);
          if (!Object.hasOwn(saved, next)) saved[next] = value;
        }
      }
      if (migrating) {
        // Old domain columns all used the empty key, so their individual values are unrecoverable.
        // Preserve unambiguous paths and all explicitly identified settings.
        const paths = ["ci-address-data", "ci-address-voice", "ci-address-spend", "ci-address-txn", "ts-address-order", "ts-address-data", "ts-address-voice"];
        paths.forEach((key, index) => {
          const legacy = "field-" + (index + 1);
          if (!Object.hasOwn(saved, key) && typeof saved[legacy] === "string") saved[key] = saved[legacy];
        });
        const validKeys = new Set(entries.map(entry => entry.key));
        const migrated = Object.fromEntries(Object.entries(saved).filter(([key]) => validKeys.has(key)));
        localStorage.setItem(storageKey, JSON.stringify(migrated));
        if (Object.hasOwn(saved, "")) status.textContent = "تنظیمات قدیمی منتقل شد؛ نام ستون‌های سازگاری و پایداری زمانی که به‌اشتباه مشترک ذخیره شده بودند به پیش‌فرض صحیح برگشتند. نام‌های سفارشی را در صورت نیاز دوباره وارد و ذخیره کنید.";
        return migrated;
      }
      return saved;
    } catch {
      status.textContent = "خواندن پیش‌فرض‌های ذخیره‌شده ممکن نشد؛ مقادیر اصلی استفاده شد.";
      return {};
    }
  }
  function apply(values) {
    for (const entry of entries) {
      let value = Object.hasOwn(values, entry.key) ? values[entry.key] : entry.original;
      if (typeof value !== typeof entry.original || (entry.editor.tagName === "SELECT" && !Array.from(entry.editor.options).some(option => option.value === value))) value = entry.original;
      entry.set(value);
      entry.apply(value);
    }
    applyStandardDefaults();
    if (typeof updateClusterInputMode === "function") updateClusterInputMode();
  }
  apply(readSaved());
  document.getElementById("defaultsForm").addEventListener("submit", event => {
    event.preventDefault();
    const values = Object.fromEntries(entries.map(entry => [entry.key,
      entry.editor.type === "checkbox" ? entry.editor.checked : entry.editor.value]));
    try {
      localStorage.setItem(storageKey, JSON.stringify(values));
      apply(values);
      status.textContent = "پیش‌فرض‌ها ذخیره و در فرم‌ها اعمال شدند.";
    } catch {
      status.textContent = "ذخیره ممکن نشد؛ دسترسی مرورگر به حافظه محلی را بررسی کنید.";
    }
  });
  document.getElementById("resetDefaultsBtn").addEventListener("click", () => {
    try {
      localStorage.removeItem(storageKey);
      localStorage.removeItem(legacyStorageKey);
      apply({});
      status.textContent = "پیش‌فرض‌های اصلی بازیابی شدند.";
    } catch {
      status.textContent = "بازیابی ممکن نشد؛ دسترسی مرورگر به حافظه محلی را بررسی کنید.";
    }
  });
})();
