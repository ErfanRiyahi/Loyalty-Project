const tabs = ["Standard", "CI", "TS", "DS", "Cluster", "Churn", "Monthly", "Settings"];
for (const name of tabs) {
  document.getElementById("tabBtn" + name).addEventListener("click", () => {
    for (const other of tabs) {
      document
        .getElementById("tabBtn" + other)
        .classList.toggle("active", name === other);
      document
        .getElementById("tab" + other)
        .classList.toggle("active", name === other);
      document
        .getElementById("tabBtn" + other)
        .setAttribute("aria-pressed", String(name === other));
    }
  });
}

let fieldCounter = 0;
for (const label of document.querySelectorAll("label")) {
  if (label.htmlFor || label.querySelector("input")) continue;
  let field = label.nextElementSibling;
  if (field?.matches("input,select")) {
    if (!field.id) field.id = "field-" + ++fieldCounter;
    label.htmlFor = field.id;
  }
}
for (const field of document.querySelectorAll(".domain-cols input")) {
  field.setAttribute(
    "aria-label",
    ["شناسه مشتری", "تاریخ", "مقدار"][Number(field.dataset.col)] +
      "؛ حوزه " +
      field.dataset.domain,
  );
}

for (const button of document.querySelectorAll(".tab-btn"))
  button.setAttribute(
    "aria-pressed",
    String(button.classList.contains("active")),
  );
