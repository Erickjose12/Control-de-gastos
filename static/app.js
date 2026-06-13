const state = {
  meta: { accounts: [], incomeCategories: [], expenseCategories: [] },
  imports: [],
  dashboard: null,
};

const fmtMoney = new Intl.NumberFormat("es-GT", {
  style: "currency",
  currency: "GTQ",
  currencyDisplay: "narrowSymbol",
});

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function optionList(values, selected) {
  return values
    .map((value) => `<option ${value === selected ? "selected" : ""}>${escapeHtml(value)}</option>`)
    .join("");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function load() {
  state.meta = await api("/api/meta");
  $("accountSelect").innerHTML = optionList(state.meta.accounts, "GYT - Cuenta sueldo");
  await refreshAll();
}

async function refreshAll() {
  await Promise.all([loadImports(), loadDashboard()]);
}

async function loadImports() {
  state.imports = await api("/api/imports");
  renderImports();
}

async function loadDashboard() {
  const month = $("monthInput").value;
  state.dashboard = await api(`/api/dashboard?month=${encodeURIComponent(month)}`);
  renderDashboard();
}

function renderDashboard() {
  const data = state.dashboard;
  $("incomeKpi").textContent = fmtMoney.format(data.income);
  $("expenseKpi").textContent = fmtMoney.format(data.expenses);
  $("balanceKpi").textContent = fmtMoney.format(data.balance);
  $("rateKpi").textContent = `${Math.round(data.savingsRate * 100)}%`;

  const max = Math.max(...data.byCategory.map(([, amount]) => amount), 0);
  $("categoryBars").innerHTML =
    data.byCategory.length === 0
      ? `<p class="empty">Sin gastos registrados en este mes.</p>`
      : data.byCategory
          .map(([category, amount]) => {
            const width = max ? Math.max(3, (amount / max) * 100) : 0;
            return `
              <div class="bar-row">
                <div class="bar-label">
                  <span>${escapeHtml(category)}</span>
                  <span>${fmtMoney.format(amount)}</span>
                </div>
                <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
              </div>`;
          })
          .join("");

  $("transactionsBody").innerHTML =
    data.transactions.length === 0
      ? `<tr><td class="empty" colspan="6">Sin movimientos registrados.</td></tr>`
      : data.transactions
          .map(
            (tx) => `
            <tr>
              <td>${escapeHtml(tx.date)}</td>
              <td>${escapeHtml(tx.type)}</td>
              <td>${escapeHtml(tx.category)}</td>
              <td>${escapeHtml(tx.account)}</td>
              <td class="description">${escapeHtml(tx.description)}</td>
              <td class="money">${fmtMoney.format(tx.amount)}</td>
            </tr>`,
          )
          .join("");
}

function renderImports() {
  const categories = [...state.meta.incomeCategories, ...state.meta.expenseCategories];
  $("importsBody").innerHTML =
    state.imports.length === 0
      ? `<tr><td class="empty" colspan="7">No hay movimientos importados pendientes.</td></tr>`
      : state.imports
          .map(
            (row) => `
            <tr data-id="${row.id}">
              <td>${escapeHtml(row.date)}</td>
              <td>
                <select data-field="account">${optionList(state.meta.accounts, row.account)}</select>
              </td>
              <td class="description">${escapeHtml(row.description)}</td>
              <td>
                <select data-field="suggested_type">
                  ${optionList(["Ingreso", "Gasto"], row.suggested_type)}
                </select>
              </td>
              <td>
                <select data-field="suggested_category">
                  ${optionList(categories, row.suggested_category)}
                </select>
              </td>
              <td class="money">${fmtMoney.format(row.amount)}</td>
              <td>
                <select data-field="action">
                  ${optionList(["Pendiente", "Pasar a Ingresos", "Pasar a Gastos", "Ignorar / transferencia", "Registrado"], row.action)}
                </select>
              </td>
            </tr>`,
          )
          .join("");
}

async function updateImport(id, field, value) {
  await api("/api/imports/update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, [field]: value }),
  });
  const row = state.imports.find((item) => item.id === Number(id));
  if (row) row[field] = value;
}

$("importForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  $("importStatus").textContent = "Importando...";
  try {
    const result = await api("/api/import", { method: "POST", body: data });
    $("importStatus").textContent = `Listo: ${result.count} movimientos cargados a revision.`;
    form.reset();
    $("accountSelect").innerHTML = optionList(state.meta.accounts, "GYT - Cuenta sueldo");
    await loadImports();
  } catch (error) {
    $("importStatus").textContent = "No se pudo importar el archivo.";
    console.error(error);
  }
});

$("importsBody").addEventListener("change", async (event) => {
  const select = event.target.closest("select[data-field]");
  if (!select) return;
  const tr = select.closest("tr[data-id]");
  await updateImport(tr.dataset.id, select.dataset.field, select.value);
});

$("commitBtn").addEventListener("click", async () => {
  const result = await api("/api/imports/commit", { method: "POST" });
  $("importStatus").textContent = `Registrados ${result.count} movimientos.`;
  await refreshAll();
});

$("clearImportsBtn").addEventListener("click", async () => {
  await api("/api/imports", { method: "DELETE" });
  $("importStatus").textContent = "Bandeja limpia.";
  await loadImports();
});

$("monthInput").addEventListener("change", loadDashboard);

load().catch((error) => {
  console.error(error);
  $("importStatus").textContent = "No se pudo cargar la app local.";
});
