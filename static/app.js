const state = {
  meta: {
    accounts: [],
    incomeCategories: [],
    expenseCategories: [],
    savingsCategories: [],
    transferCategories: [],
    categories: [],
    transactionTypes: [],
  },
  imports: [],
  dashboard: null,
  wedding: {
    budget: 0,
    expenses: [],
    categories: [],
  },
  exchangeRate: null,
  deleteTransactionId: null,
  deleteTransactionIds: [],
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

function defaultDateForSelectedMonth() {
  const selectedMonth = $("monthInput").value;
  const today = new Date().toISOString().slice(0, 10);
  if (!selectedMonth) return today;
  return today.startsWith(selectedMonth) ? today : `${selectedMonth}-01`;
}

function setWeddingDefaultDates() {
  const today = new Date().toISOString().slice(0, 10);
  $("weddingExpenseForm").elements.date.value = today;
  $("weddingExpenseForm").elements.paymentDate.value = today;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function shortDescription(value) {
  return String(value ?? "").slice(0, 75).trimEnd();
}

function normalizeSearch(value) {
  return String(value ?? "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();
}

function matchesSearch(values, query) {
  if (!query) return true;
  return normalizeSearch(values.join(" ")).includes(query);
}

function amountClassForType(type) {
  return {
    Ingreso: "amount-income",
    Gasto: "amount-expense",
    Ahorro: "amount-saving",
    "Venta USD": "amount-income",
    Transferencia: "amount-transfer",
  }[type] || "";
}

async function load() {
  state.meta = await api("/api/meta");
  if (state.meta.latestMonth) {
    $("monthInput").value = state.meta.latestMonth;
  }
  $("accountSelect").innerHTML = optionList(state.meta.accounts, "GYT - Cuenta ahorro sueldo");
  $("manualAccount").innerHTML = optionList(state.meta.accounts, "Banrural - Cuenta ahorro");
  $("manualForm").elements.date.value = defaultDateForSelectedMonth();
  setWeddingDefaultDates();
  updateManualDefaults();
  bindNavigation();
  await refreshAll();
}

async function refreshAll() {
  await Promise.all([loadImports(), loadDashboard(), loadWedding()]);
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

async function loadWedding() {
  state.wedding = await api("/api/wedding/state");
  renderWedding();
}

function renderDashboard() {
  const data = state.dashboard;
  $("incomeKpi").textContent = fmtMoney.format(data.income);
  $("expenseKpi").textContent = fmtMoney.format(data.expenses);
  $("balanceKpi").textContent = fmtMoney.format(data.balance);
  $("rateKpi").textContent = `${fmtMoney.format(data.savings)} / ${Math.round(data.savingsRate * 100)}%`;

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

  $("accountSummary").innerHTML =
    data.byAccount.length === 0
      ? `<p class="empty">Sin movimientos por cuenta en este mes.</p>`
      : data.byAccount
          .map(([account, amount]) => {
            const tone = amount >= 0 ? "positive" : "negative";
            const description = amount >= 0 ? "Entrada neta del mes" : "Salida neta del mes";
            return `
              <div class="account-row">
                <span>
                  ${escapeHtml(account)}
                  <small>${description}</small>
                </span>
                <strong class="${tone}">${fmtMoney.format(amount)}</strong>
              </div>`;
          })
          .join("");

  const transactionQuery = normalizeSearch($("transactionsSearch").value);
  const filteredTransactions = data.transactions.filter((tx) =>
    matchesSearch(
      [
        tx.date,
        tx.type,
        tx.category,
        tx.account,
        tx.description,
        fmtMoney.format(tx.amount),
        tx.source_import_id ? "Importado" : "Manual",
      ],
      transactionQuery,
    ),
  );

  $("transactionsBody").innerHTML =
    data.transactions.length === 0
      ? `<tr><td class="empty" colspan="9">Sin movimientos registrados.</td></tr>`
      : filteredTransactions.length === 0
        ? `<tr><td class="empty" colspan="9">No hay movimientos que coincidan con la busqueda.</td></tr>`
        : filteredTransactions
          .map(
            (tx) => `
            <tr data-transaction-id="${tx.id}">
              <td class="select-cell">
                <input class="transaction-check" type="checkbox" value="${tx.id}" aria-label="Seleccionar movimiento" />
              </td>
              <td>${escapeHtml(tx.date)}</td>
              <td>${escapeHtml(tx.type)}</td>
              <td>${escapeHtml(tx.category)}</td>
              <td>${escapeHtml(tx.account)}</td>
              <td class="description">${escapeHtml(tx.description)}</td>
              <td class="money ${amountClassForType(tx.type)}">${fmtMoney.format(tx.amount)}</td>
              <td>${tx.source_import_id ? "Importado" : "Manual"}</td>
              <td class="actions-cell">
                <button class="table-action success-text" type="button" data-action="view">Ver</button>
                <button class="table-action" type="button" data-action="edit">Editar</button>
                <button class="table-action danger-text" type="button" data-action="delete">Eliminar</button>
              </td>
            </tr>`,
          )
          .join("");
  updateBulkDeleteState();
}

function renderImports() {
  const importQuery = normalizeSearch($("importsSearch").value);
  const filteredImports = state.imports.filter((row) =>
    matchesSearch(
      [
        row.date,
        row.account,
        row.description,
        row.suggested_type,
        row.suggested_category,
        fmtMoney.format(row.amount),
      ],
      importQuery,
    ),
  );

  $("importsBody").innerHTML =
    state.imports.length === 0
      ? `<tr><td class="empty" colspan="6">No hay movimientos importados pendientes.</td></tr>`
      : filteredImports.length === 0
        ? `<tr><td class="empty" colspan="6">No hay movimientos importados que coincidan con la busqueda.</td></tr>`
        : filteredImports
          .map(
            (row) => `
            <tr data-id="${row.id}">
              <td>${escapeHtml(row.date)}</td>
              <td>${escapeHtml(row.account)}</td>
              <td class="description">${escapeHtml(row.description)}</td>
              <td>${escapeHtml(row.suggested_type)}</td>
              <td>${escapeHtml(row.suggested_category)}</td>
              <td class="money ${amountClassForType(row.suggested_type)}">${fmtMoney.format(row.amount)}</td>
            </tr>`,
          )
          .join("");
}

function renderWedding() {
  const data = state.wedding;
  const progress = Math.min(data.progress || 0, 1);
  const progressText = `${Math.round(progress * 100)}%`;
  $("weddingDashBudget").textContent = fmtMoney.format(data.budget || 0);
  $("weddingDashSpent").textContent = fmtMoney.format(data.spent || 0);
  $("weddingDashPaid").textContent = fmtMoney.format(data.paid || 0);
  $("weddingDashAvailable").textContent = fmtMoney.format(data.available || 0);
  $("weddingDashProgress").textContent = progressText;
  $("weddingDashBar").style.width = `${progress * 100}%`;

  $("weddingBudgetInput").value = data.budget || 0;
  $("weddingCategory").innerHTML = optionList(data.categories || [], "Lugar");

  const query = normalizeSearch($("weddingSearch").value);
  const expenses = (data.expenses || []).filter((expense) =>
    matchesSearch(
      [
        expense.date,
        expense.description,
        expense.category,
        expense.vendor,
        expense.status,
        fmtMoney.format(expense.amount),
        fmtMoney.format(expense.paid_amount),
        fmtMoney.format(expense.pending_amount),
        expense.attachment_name || "",
        expense.has_attachment ? "con archivo documento evidencia" : "sin archivo",
      ],
      query,
    ),
  );

  $("weddingExpensesBody").innerHTML =
    data.expenses.length === 0
      ? `<tr><td class="empty" colspan="9">Aun no hay gastos de boda registrados.</td></tr>`
      : expenses.length === 0
        ? `<tr><td class="empty" colspan="9">No hay gastos de boda que coincidan con la busqueda.</td></tr>`
        : expenses
          .map(
            (expense) => `
            <tr data-wedding-expense-id="${expense.id}">
              <td>${escapeHtml(formatDisplayDate(expense.date))}</td>
              <td>${escapeHtml(expense.description)}</td>
              <td>${escapeHtml(expense.category)}</td>
              <td>${escapeHtml(expense.vendor || "-")}</td>
              <td class="money">${fmtMoney.format(expense.amount)}</td>
              <td class="money">${fmtMoney.format(expense.paid_amount)}</td>
              <td class="money">${fmtMoney.format(expense.pending_amount)}</td>
              <td><span class="pill ${statusClass(expense.status)}">${escapeHtml(expense.status)}</span></td>
              <td class="actions-cell">
                ${
                  expense.has_attachment
                    ? `<a class="table-action success-text" href="/api/wedding/expenses/${expense.id}/attachment" target="_blank" rel="noopener">Ver archivo</a>`
                    : `<button class="table-action" type="button" disabled>Sin archivo</button>`
                }
                <button class="table-action" type="button" data-wedding-action="payment">Abonar</button>
                <button class="table-action danger-text" type="button" data-wedding-action="delete">Eliminar</button>
              </td>
            </tr>`,
          )
          .join("");
}

function formatDisplayDate(value) {
  if (!value) return "-";
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function statusClass(status) {
  return {
    Pagado: "paid",
    Abonado: "partial",
    Pendiente: "pending",
  }[status] || "pending";
}

function defaultAccountForType(type) {
  if (type === "Ahorro" || type === "Venta USD") return "Banrural - Cuenta ahorro";
  if (type === "Ingreso") return "GYT - Cuenta ahorro sueldo";
  if (type === "Gasto") return "GYT - Tarjeta credito";
  return "GYT - Cuenta ahorro sueldo";
}

function updateManualDefaults() {
  const type = $("manualType").value;
  $("manualAccount").innerHTML = optionList(state.meta.accounts, defaultAccountForType(type));
  if (type === "Venta USD") {
    loadExchangeRate();
  }
}

async function loadExchangeRate() {
  try {
    const data = await api("/api/exchange-rate");
    if (!data.ok || !data.rate) throw new Error(data.message || "Sin tasa");
    state.exchangeRate = data.rate;
    const input = $("exchangeRateInput");
    if (!input.value || Number(input.value) <= 0.0001) {
      input.value = data.rate.toFixed(4);
    }
    $("importStatus").textContent = `Tipo de cambio USD-GTQ actualizado: ${data.rate.toFixed(4)}`;
    calculateGtqFromUsd();
  } catch (error) {
    $("importStatus").textContent = "No pude obtener el tipo de cambio. Podes ingresarlo manualmente.";
    console.error(error);
  }
}

function calculateGtqFromUsd() {
  const form = $("manualForm");
  const usd = Number(form.elements.usdAmount.value || 0);
  const rate = Number(form.elements.exchangeRate.value || 0);
  if (usd > 0 && rate > 0) {
    form.elements.amount.value = (usd * rate).toFixed(2);
  }
}

function setActiveView(viewId) {
  document.querySelectorAll(".view-section").forEach((section) => {
    section.classList.toggle("active", section.id === viewId);
  });
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewId);
  });
  const titles = {
    summaryView: ["Dashboard", "Resumen mensual de ingresos, gastos y ahorro."],
    movementsView: ["Movimientos financieros", "Importa estados de cuenta, registra ajustes y revisa movimientos."],
    weddingView: ["Gastos de boda", "Presupuesto, abonos y proveedores del evento."],
  };
  const [title, subtitle] = titles[viewId] || titles.summaryView;
  $("viewTitle").textContent = title;
  $("viewSubtitle").textContent = subtitle;
}

function bindNavigation() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => setActiveView(button.dataset.view));
  });
  document.querySelectorAll("[data-view-shortcut]").forEach((button) => {
    button.addEventListener("click", () => setActiveView(button.dataset.viewShortcut));
  });
}

function openModal(id) {
  $(id).hidden = false;
}

function closeModals() {
  document.querySelectorAll(".modal").forEach((modal) => {
    modal.hidden = true;
  });
  state.deleteTransactionId = null;
  state.deleteTransactionIds = [];
}

function detailRow(label, value) {
  return `
    <div class="detail-label">${escapeHtml(label)}</div>
    <div class="detail-value">${escapeHtml(value)}</div>`;
}

async function showTransactionDetail(transactionId) {
  const tx = await api(`/api/transactions/${transactionId}`);
  $("transactionDetail").innerHTML = [
    detailRow("Fecha", tx.date),
    detailRow("Tipo", tx.type),
    detailRow("Categoria", tx.category),
    detailRow("Cuenta", tx.account),
    detailRow("Descripcion", tx.description),
    detailRow("Monto", fmtMoney.format(tx.amount)),
    detailRow("Creado", tx.created_at),
    detailRow("Origen", tx.source_import_id ? `Importacion #${tx.source_import_id}` : "Registro manual"),
  ].join("");
  openModal("viewTransactionModal");
}

async function askDeleteTransaction(transactionId) {
  const tx = await api(`/api/transactions/${transactionId}`);
  state.deleteTransactionId = transactionId;
  state.deleteTransactionIds = [Number(transactionId)];
  $("deleteTransactionText").textContent = `Vas a eliminar "${tx.description}" por ${fmtMoney.format(tx.amount)}. Esta accion no se puede deshacer.`;
  openModal("deleteTransactionModal");
}

function selectedTransactionIds() {
  return [...document.querySelectorAll(".transaction-check:checked")].map((input) => Number(input.value));
}

function updateBulkDeleteState() {
  const ids = selectedTransactionIds();
  const hasRows = document.querySelectorAll(".transaction-check").length > 0;
  const allSelected = hasRows && ids.length === document.querySelectorAll(".transaction-check").length;
  $("deleteSelectedBtn").disabled = ids.length === 0;
  $("selectAllTransactions").checked = allSelected;
  $("selectAllTransactions").indeterminate = ids.length > 0 && !allSelected;
}

function askDeleteSelectedTransactions() {
  const ids = selectedTransactionIds();
  if (ids.length === 0) return;
  state.deleteTransactionId = null;
  state.deleteTransactionIds = ids;
  $("deleteTransactionText").textContent = `Vas a eliminar ${ids.length} movimientos seleccionados. Esta accion no se puede deshacer.`;
  openModal("deleteTransactionModal");
}

async function showEditTransaction(transactionId) {
  const tx = await api(`/api/transactions/${transactionId}`);
  const form = $("editTransactionForm");
  form.elements.id.value = tx.id;
  form.elements.date.value = tx.date;
  form.elements.type.innerHTML = optionList(state.meta.transactionTypes, tx.type);
  form.elements.account.innerHTML = optionList(state.meta.accounts, tx.account);
  form.elements.amount.value = tx.amount;
  form.elements.description.value = tx.description;
  openModal("editTransactionModal");
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
    $("accountSelect").innerHTML = optionList(state.meta.accounts, "GYT - Cuenta ahorro sueldo");
    await loadImports();
  } catch (error) {
    $("importStatus").textContent = "No se pudo importar el archivo.";
    console.error(error);
  }
});

$("commitBtn").addEventListener("click", async () => {
  const result = await api("/api/imports/commit", { method: "POST" });
  $("importStatus").textContent = `Registrados ${result.count} movimientos.`;
  if (result.month) {
    $("monthInput").value = result.month;
  }
  await refreshAll();
  setActiveView("summaryView");
});

$("manualType").addEventListener("change", updateManualDefaults);
$("manualForm").elements.usdAmount.addEventListener("input", () => {
  const form = $("manualForm");
  const usd = Number(form.elements.usdAmount.value || 0);
  if (usd > 0 && $("manualType").value !== "Venta USD") {
    $("manualType").value = "Venta USD";
    updateManualDefaults();
  }
  calculateGtqFromUsd();
});
$("exchangeRateInput").addEventListener("input", calculateGtqFromUsd);

$("manualForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  await api("/api/transactions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  $("importStatus").textContent = "Movimiento manual guardado.";
  if (data.date) {
    $("monthInput").value = data.date.slice(0, 7);
  }
  const currentType = $("manualType").value;
  form.reset();
  $("manualForm").elements.date.value = defaultDateForSelectedMonth();
  $("manualType").value = currentType;
  updateManualDefaults();
  await loadDashboard();
});

$("clearImportsBtn").addEventListener("click", async () => {
  await api("/api/imports", { method: "DELETE" });
  $("importStatus").textContent = "Bandeja limpia.";
  await loadImports();
});

$("transactionsBody").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest("tr[data-transaction-id]");
  if (!row) return;
  const transactionId = row.dataset.transactionId;
  if (button.dataset.action === "view") {
    await showTransactionDetail(transactionId);
  } else if (button.dataset.action === "edit") {
    await showEditTransaction(transactionId);
  } else if (button.dataset.action === "delete") {
    await askDeleteTransaction(transactionId);
  }
});

$("transactionsBody").addEventListener("change", (event) => {
  if (!event.target.closest(".transaction-check")) return;
  updateBulkDeleteState();
});

$("selectAllTransactions").addEventListener("change", (event) => {
  document.querySelectorAll(".transaction-check").forEach((input) => {
    input.checked = event.currentTarget.checked;
  });
  updateBulkDeleteState();
});

$("deleteSelectedBtn").addEventListener("click", askDeleteSelectedTransactions);

$("importsSearch").addEventListener("input", renderImports);
$("transactionsSearch").addEventListener("input", renderDashboard);
$("weddingSearch").addEventListener("input", renderWedding);

$("weddingBudgetForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const budget = Number($("weddingBudgetInput").value || 0);
  state.wedding = await api("/api/wedding/budget", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ budget }),
  });
  renderWedding();
});

$("weddingExpenseForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  state.wedding = await api("/api/wedding/expenses", {
    method: "POST",
    body: new FormData(form),
  });
  form.reset();
  setWeddingDefaultDates();
  renderWedding();
});

$("weddingExpensesBody").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-wedding-action]");
  if (!button) return;
  const row = button.closest("tr[data-wedding-expense-id]");
  if (!row) return;
  const expenseId = row.dataset.weddingExpenseId;
  if (button.dataset.weddingAction === "payment") {
    const form = $("weddingPaymentForm");
    form.reset();
    form.elements.expenseId.value = expenseId;
    form.elements.date.value = new Date().toISOString().slice(0, 10);
    openModal("weddingPaymentModal");
  } else if (button.dataset.weddingAction === "delete") {
    await api(`/api/wedding/expenses/${expenseId}`, { method: "DELETE" });
    await loadWedding();
  }
});

$("weddingPaymentForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  const expenseId = data.expenseId;
  delete data.expenseId;
  state.wedding = await api(`/api/wedding/expenses/${expenseId}/payments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  closeModals();
  renderWedding();
});

$("editTransactionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  const transactionId = data.id;
  delete data.id;
  await api(`/api/transactions/${transactionId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  closeModals();
  await loadDashboard();
});

$("confirmDeleteBtn").addEventListener("click", async () => {
  if (state.deleteTransactionIds.length > 1) {
    await api("/api/transactions/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: state.deleteTransactionIds }),
    });
  } else if (state.deleteTransactionIds.length === 1) {
    await api(`/api/transactions/${state.deleteTransactionIds[0]}`, { method: "DELETE" });
  } else if (state.deleteTransactionId) {
    await api(`/api/transactions/${state.deleteTransactionId}`, { method: "DELETE" });
  } else {
    return;
  }
  closeModals();
  await loadDashboard();
});

document.querySelectorAll("[data-close-modal]").forEach((element) => {
  element.addEventListener("click", closeModals);
});

$("monthInput").addEventListener("change", () => {
  $("manualForm").elements.date.value = defaultDateForSelectedMonth();
  loadDashboard();
});

load().catch((error) => {
  console.error(error);
  $("importStatus").textContent = "No se pudo cargar la app local.";
});
