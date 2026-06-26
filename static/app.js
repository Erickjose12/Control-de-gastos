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
  recurring: {
    items: [],
    categories: [],
    accounts: [],
    summary: {},
  },
  reports: {
    summary: {},
    trend: [],
    byCategory: [],
    byAccount: [],
    byPaymentMethod: [],
    topExpenses: [],
    wedding: {
      total: 0,
      paid: 0,
      pending: 0,
      count: 0,
      expenses: [],
    },
  },
  exchangeRate: null,
  deleteTransactionId: null,
  deleteTransactionIds: [],
  weddingAttachmentExpenseId: null,
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

function readableError(error) {
  const text = String(error?.message || error || "Ocurrio un error");
  const match = text.match(/<p>Message:\s*([^<]+)<\/p>/i);
  return match ? match[1].replaceAll("..", ".") : text;
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
  await Promise.all([loadImports(), loadDashboard(), loadWedding(), loadRecurring(), loadReports()]);
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

async function loadRecurring() {
  const month = $("monthInput").value;
  state.recurring = await api(`/api/recurring/state?month=${encodeURIComponent(month)}`);
  $("recurringCategory").innerHTML = optionList(state.recurring.categories, "Suscripciones");
  $("recurringAccount").innerHTML = optionList(state.recurring.accounts, "TC");
  renderRecurring();
}

async function loadReports() {
  const month = $("monthInput").value;
  state.reports = await api(`/api/reports?month=${encodeURIComponent(month)}`);
  renderReports();
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
  renderSavingSales();
}

function recurringStatus(item) {
  if (!item.active) return ["Inactivo", "muted-pill"];
  if (!item.is_due) return [item.next_due_date ? "Programado" : "Sin fecha", "pill partial"];
  if (item.paid) return ["Pagado", "pill paid"];
  return ["Pendiente", "pill pending"];
}

function renderRecurring() {
  const summary = state.recurring.summary || {};
  const monthly = Number(summary.monthlyEquivalent || 0);
  const provision = Number(summary.annualProvision || 0);
  const paid = Number(summary.paidThisMonth || 0);
  const pending = Number(summary.pendingThisMonth || 0);
  $("recurringMonthlyKpi").textContent = fmtMoney.format(monthly);
  $("recurringProvisionKpi").textContent = fmtMoney.format(provision);
  $("recurringPaidKpi").textContent = fmtMoney.format(paid);
  $("recurringPendingKpi").textContent = fmtMoney.format(pending);
  $("recurringDashMonthly").textContent = fmtMoney.format(monthly);
  $("recurringDashProvision").textContent = fmtMoney.format(provision);
  $("recurringDashPaid").textContent = fmtMoney.format(paid);
  $("recurringDashPending").textContent = fmtMoney.format(pending);

  const query = normalizeSearch($("recurringSearch").value);
  const rows = state.recurring.items || [];
  const filtered = rows.filter((item) =>
    matchesSearch(
      [item.name, item.category, item.account, item.frequency, item.next_due_date || "", item.active ? "Activo" : "Inactivo"],
      query,
    ),
  );
  $("recurringBody").innerHTML =
    rows.length === 0
      ? `<tr><td class="empty" colspan="9">Aun no hay gastos recurrentes.</td></tr>`
      : filtered.length === 0
        ? `<tr><td class="empty" colspan="9">No hay gastos que coincidan con la busqueda.</td></tr>`
        : filtered
            .map((item) => {
              const [statusText, statusClass] = recurringStatus(item);
              const paidLabel = item.paid ? "Desmarcar pago" : "Marcar pagado";
              return `
                <tr data-recurring-id="${item.id}">
                  <td><strong>${escapeHtml(item.name)}</strong></td>
                  <td>${escapeHtml(item.category)}</td>
                  <td>${escapeHtml(item.account)}</td>
                  <td>${escapeHtml(item.frequency)}</td>
                  <td class="money">${fmtMoney.format(item.amount)}</td>
                  <td class="money">${fmtMoney.format(item.monthly_equivalent)}</td>
                  <td>${escapeHtml(item.next_due_date || "Sin fecha")}</td>
                  <td><span class="${statusClass}">${statusText}</span></td>
                  <td class="actions-cell">
                    <button class="table-action success-text" type="button" data-recurring-action="paid" ${item.is_due ? "" : "disabled"}>${paidLabel}</button>
                    <button class="table-action" type="button" data-recurring-action="edit">Editar</button>
                    <button class="table-action danger-text" type="button" data-recurring-action="delete">Eliminar</button>
                  </td>
                </tr>`;
            })
            .join("");
}

function resetRecurringForm() {
  const form = $("recurringForm");
  form.reset();
  form.elements.id.value = "";
  $("recurringCategory").innerHTML = optionList(state.recurring.categories, "Suscripciones");
  $("recurringAccount").innerHTML = optionList(state.recurring.accounts, "TC");
  $("recurringFormTitle").textContent = "Registrar gasto recurrente";
  $("recurringSaveBtn").textContent = "Guardar gasto";
  $("recurringCancelBtn").hidden = true;
}

function reportMonthLabel(month) {
  if (!month) return "";
  const [year, monthNumber] = month.split("-").map(Number);
  return new Intl.DateTimeFormat("es-GT", { month: "short" })
    .format(new Date(year, monthNumber - 1, 1))
    .replace(".", "");
}

function renderReportBreakdown(targetId, rows, emptyText) {
  const total = rows.reduce((sum, [, amount]) => sum + Math.abs(Number(amount || 0)), 0);
  $(targetId).innerHTML =
    rows.length === 0
      ? `<p class="empty">${emptyText}</p>`
      : rows
          .map(([label, amount]) => {
            const numericAmount = Number(amount || 0);
            const width = total ? Math.max(4, (Math.abs(numericAmount) / total) * 100) : 0;
            const tone = numericAmount >= 0 ? "positive" : "negative";
            return `
              <div class="report-breakdown-row">
                <div class="report-breakdown-head">
                  <span>${escapeHtml(label)}</span>
                  <strong class="${tone}">${fmtMoney.format(numericAmount)}</strong>
                </div>
                <div class="report-mini-track">
                  <div class="report-mini-fill ${tone}" style="width:${width}%"></div>
                </div>
              </div>`;
          })
          .join("");
}

function renderReports() {
  const data = state.reports;
  const summary = data.summary || {};
  $("reportIncomeKpi").textContent = fmtMoney.format(summary.income || 0);
  $("reportExpenseKpi").textContent = fmtMoney.format(summary.expenses || 0);
  $("reportSavingsKpi").textContent = `${fmtMoney.format(summary.savings || 0)} / ${Math.round(
    Number(summary.savingsRate || 0) * 100,
  )}%`;
  $("reportBalanceKpi").textContent = fmtMoney.format(summary.balance || 0);

  const expenseChange = Number(summary.expenseChange || 0);
  $("reportExpenseChange").textContent =
    expenseChange === 0
      ? "Sin cambio vs. mes anterior"
      : `${expenseChange > 0 ? "+" : ""}${Math.round(expenseChange * 100)}% gastos vs. mes anterior`;
  $("reportExpenseChange").className = `report-change ${expenseChange > 0 ? "negative" : "positive"}`;

  const trend = data.trend || [];
  const maxValue = Math.max(
    ...trend.flatMap((row) => [Number(row.income || 0), Number(row.expenses || 0), Number(row.savings || 0)]),
    1,
  );
  $("reportTrendChart").innerHTML = trend
    .map((row) => {
      const incomeHeight = (Number(row.income || 0) / maxValue) * 100;
      const expenseHeight = (Number(row.expenses || 0) / maxValue) * 100;
      const savingsHeight = (Number(row.savings || 0) / maxValue) * 100;
      return `
        <div class="report-month-group" title="${escapeHtml(row.month)}">
          <div class="report-columns">
            <span class="report-column income" style="height:${incomeHeight}%"></span>
            <span class="report-column expense" style="height:${expenseHeight}%"></span>
            <span class="report-column saving" style="height:${savingsHeight}%"></span>
          </div>
          <strong>${escapeHtml(reportMonthLabel(row.month))}</strong>
        </div>`;
    })
    .join("");

  const categories = data.byCategory || [];
  const maxCategory = Math.max(...categories.map(([, amount]) => Number(amount)), 0);
  $("reportCategoryBars").innerHTML =
    categories.length === 0
      ? `<p class="empty">Sin gastos por categoria en este mes.</p>`
      : categories
          .map(([category, amount]) => {
            const width = maxCategory ? Math.max(4, (Number(amount) / maxCategory) * 100) : 0;
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

  renderReportBreakdown(
    "reportPaymentMethods",
    data.byPaymentMethod || [],
    "Sin gastos recurrentes configurados.",
  );
  renderReportBreakdown("reportAccountFlow", data.byAccount || [], "Sin movimientos por cuenta.");

  const wedding = data.wedding || {};
  $("reportWeddingTotal").textContent = fmtMoney.format(wedding.total || 0);
  $("reportWeddingPaid").textContent = fmtMoney.format(wedding.paid || 0);
  $("reportWeddingPending").textContent = fmtMoney.format(wedding.pending || 0);
  $("reportWeddingCount").textContent = `${wedding.count || 0} ${
    Number(wedding.count || 0) === 1 ? "registro" : "registros"
  }`;
  const weddingExpenses = wedding.expenses || [];
  $("reportWeddingExpenses").innerHTML =
    weddingExpenses.length === 0
      ? `<tr><td class="empty" colspan="7">Sin gastos de boda registrados en este mes.</td></tr>`
      : weddingExpenses
          .map(
            (expense) => `
              <tr>
                <td>${escapeHtml(expense.date)}</td>
                <td class="description">${escapeHtml(expense.description)}</td>
                <td>${escapeHtml(expense.category)}</td>
                <td>${escapeHtml(expense.vendor || "-")}</td>
                <td class="money">${fmtMoney.format(expense.amount)}</td>
                <td class="money amount-income">${fmtMoney.format(expense.paid)}</td>
                <td class="money amount-saving">${fmtMoney.format(expense.pending)}</td>
              </tr>`,
          )
          .join("");

  const topExpenses = data.topExpenses || [];
  $("reportTopExpenses").innerHTML =
    topExpenses.length === 0
      ? `<tr><td class="empty" colspan="5">Sin gastos registrados en este mes.</td></tr>`
      : topExpenses
          .map(
            (expense) => `
              <tr>
                <td>${escapeHtml(expense.date)}</td>
                <td class="description">${escapeHtml(expense.description)}</td>
                <td>${escapeHtml(expense.category)}</td>
                <td>${escapeHtml(expense.account)}</td>
                <td class="money amount-expense">${fmtMoney.format(expense.amount)}</td>
              </tr>`,
          )
          .join("");
}

function exportReportCsv() {
  const link = document.createElement("a");
  link.href = `/api/reports/export?month=${encodeURIComponent(state.reports.month)}`;
  link.download = `reporte-financiero-${state.reports.month}.csv`;
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function savingSaleRows() {
  const transactions = state.dashboard?.transactions || [];
  return transactions.filter((tx) => !tx.source_import_id && ["Ahorro", "Venta USD"].includes(tx.type));
}

function renderSavingSales() {
  const rows = savingSaleRows();
  const savings = rows.filter((tx) => tx.type === "Ahorro").reduce((sum, tx) => sum + Number(tx.amount || 0), 0);
  const sales = rows.filter((tx) => tx.type === "Venta USD").reduce((sum, tx) => sum + Number(tx.amount || 0), 0);
  $("savingManualKpi").textContent = fmtMoney.format(savings);
  $("usdSaleKpi").textContent = fmtMoney.format(sales);
  $("savingSaleTotalKpi").textContent = fmtMoney.format(savings + sales);
  $("savingSaleCountKpi").textContent = rows.length;

  const query = normalizeSearch($("savingSaleSearch").value);
  const filteredRows = rows.filter((tx) =>
    matchesSearch(
      [tx.date, tx.type, tx.category, tx.account, tx.description, fmtMoney.format(tx.amount)],
      query,
    ),
  );

  $("savingSaleBody").innerHTML =
    rows.length === 0
      ? `<tr><td class="empty" colspan="7">Sin ahorros o ventas manuales en este mes.</td></tr>`
      : filteredRows.length === 0
        ? `<tr><td class="empty" colspan="7">No hay registros que coincidan con la busqueda.</td></tr>`
        : filteredRows
          .map(
            (tx) => `
            <tr data-id="${tx.id}">
              <td>${escapeHtml(tx.date)}</td>
              <td>${escapeHtml(tx.type)}</td>
              <td>${escapeHtml(tx.category)}</td>
              <td>${escapeHtml(tx.account)}</td>
              <td class="description">${escapeHtml(tx.description)}</td>
              <td class="money ${amountClassForType(tx.type)}">${fmtMoney.format(tx.amount)}</td>
              <td class="actions-cell">
                ${
                  tx.attachment_path
                    ? `<button class="table-action success-text" type="button" data-saving-action="view-attachment" data-attachment-name="${escapeHtml(tx.attachment_name || "Boleta")}" data-attachment-mime="${escapeHtml(tx.attachment_mime || "")}">Ver</button>`
                    : `<span class="muted-pill">Sin archivo</span>`
                }
              </td>
            </tr>`,
          )
          .join("");
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
        expense.attachment_mime || "",
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
                    ? `<button class="table-action success-text" type="button" data-wedding-action="view-attachment" data-attachment-name="${escapeHtml(expense.attachment_name || "Archivo")}" data-attachment-mime="${escapeHtml(expense.attachment_mime || "")}">Ver</button>
                       <button class="table-action" type="button" data-wedding-action="attachment">Cambiar</button>`
                    : `<button class="table-action" type="button" data-wedding-action="attachment">Adjuntar</button>`
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
    recurringView: ["Gastos recurrentes", "Controla pagos mensuales, suscripciones y renovaciones anuales."],
    savingsView: ["Ahorro/Venta", "Seguimiento de ahorros y ventas USD registrados manualmente."],
    reportsView: ["Reportes", "Analiza tendencias, categorias y comportamiento mensual."],
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
  state.weddingAttachmentExpenseId = null;
  if ($("weddingAttachmentViewer")) {
    $("weddingAttachmentViewer").innerHTML = "";
  }
  if ($("weddingAttachmentStatus")) {
    $("weddingAttachmentStatus").textContent = "";
  }
}

function detailRow(label, value) {
  return `
    <div class="detail-label">${escapeHtml(label)}</div>
    <div class="detail-value">${escapeHtml(value)}</div>`;
}

function showWeddingAttachment(expenseId, name, mime) {
  const url = `/api/wedding/expenses/${expenseId}/attachment`;
  $("weddingAttachmentViewTitle").textContent = name || "Documento adjunto";
  $("weddingAttachmentOpenLink").href = url;
  $("weddingAttachmentViewer").innerHTML = mime.startsWith("image/")
    ? `<img src="${url}" alt="${escapeHtml(name || "Documento adjunto")}" />`
    : `<iframe src="${url}" title="${escapeHtml(name || "Documento adjunto")}"></iframe>`;
  openModal("weddingAttachmentViewModal");
}

function showTransactionAttachment(transactionId, name, mime) {
  const url = `/api/transactions/${transactionId}/attachment`;
  $("weddingAttachmentViewTitle").textContent = name || "Boleta adjunta";
  $("weddingAttachmentOpenLink").href = url;
  $("weddingAttachmentViewer").innerHTML = mime.startsWith("image/")
    ? `<img src="${url}" alt="${escapeHtml(name || "Boleta adjunta")}" />`
    : `<iframe src="${url}" title="${escapeHtml(name || "Boleta adjunta")}"></iframe>`;
  openModal("weddingAttachmentViewModal");
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
  const formData = new FormData(form);
  const data = Object.fromEntries(formData.entries());
  $("manualStatus").textContent = "Guardando movimiento...";
  await api("/api/transactions", {
    method: "POST",
    body: formData,
  });
  $("manualStatus").textContent = "Movimiento manual guardado.";
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
$("savingSaleSearch").addEventListener("input", renderSavingSales);
$("recurringSearch").addEventListener("input", renderRecurring);
$("weddingSearch").addEventListener("input", renderWedding);
$("exportReportBtn").addEventListener("click", exportReportCsv);

$("recurringForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  const expenseId = data.id;
  delete data.id;
  data.month = $("monthInput").value;
  const saveButton = $("recurringSaveBtn");
  const originalLabel = saveButton.textContent;
  saveButton.disabled = true;
  saveButton.textContent = expenseId ? "Guardando cambios..." : "Guardando...";
  $("recurringStatus").textContent = expenseId ? "Actualizando gasto..." : "Guardando gasto...";
  try {
    await api(expenseId ? `/api/recurring/expenses/${expenseId}` : "/api/recurring/expenses", {
      method: expenseId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    await loadRecurring();
    resetRecurringForm();
    $("recurringStatus").textContent = expenseId
      ? "Cambios guardados correctamente."
      : "Gasto recurrente guardado.";
  } catch (error) {
    $("recurringStatus").textContent = `No se pudo guardar: ${readableError(error)}`;
  } finally {
    saveButton.disabled = false;
    if (form.elements.id.value) {
      saveButton.textContent = "Guardar cambios";
    } else {
      saveButton.textContent = originalLabel === "Guardar cambios" ? "Guardar gasto" : originalLabel;
    }
  }
});

$("recurringCancelBtn").addEventListener("click", () => {
  resetRecurringForm();
  $("recurringStatus").textContent = "";
});

$("recurringBody").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-recurring-action]");
  if (!button) return;
  const row = button.closest("tr[data-recurring-id]");
  const expenseId = Number(row?.dataset.recurringId);
  const item = state.recurring.items.find((entry) => Number(entry.id) === expenseId);
  if (!item) return;
  if (button.dataset.recurringAction === "paid") {
    state.recurring = await api(`/api/recurring/expenses/${expenseId}/toggle-paid`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ month: $("monthInput").value }),
    });
    renderRecurring();
  } else if (button.dataset.recurringAction === "edit") {
    const form = $("recurringForm");
    form.elements.id.value = item.id;
    form.elements.name.value = item.name;
    form.elements.category.innerHTML = optionList(state.recurring.categories, item.category);
    form.elements.account.innerHTML = optionList(state.recurring.accounts, item.account);
    form.elements.amount.value = item.amount;
    form.elements.frequency.value = item.frequency;
    form.elements.nextDueDate.value = item.next_due_date || "";
    form.elements.active.value = item.active ? "1" : "0";
    $("recurringFormTitle").textContent = "Editar gasto recurrente";
    $("recurringSaveBtn").textContent = "Guardar cambios";
    $("recurringCancelBtn").hidden = false;
    $("recurringStatus").textContent = "";
    form.scrollIntoView({ behavior: "smooth", block: "start" });
  } else if (button.dataset.recurringAction === "delete") {
    if (!window.confirm(`Eliminar "${item.name}" del control de gastos recurrentes?`)) return;
    await api(`/api/recurring/expenses/${expenseId}`, { method: "DELETE" });
    await loadRecurring();
  }
});

$("savingSaleBody").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-saving-action]");
  if (!button) return;
  const transactionId = button.closest("tr").dataset.id;
  if (button.dataset.savingAction === "view-attachment") {
    showTransactionAttachment(
      transactionId,
      button.dataset.attachmentName || "Boleta adjunta",
      button.dataset.attachmentMime || "",
    );
  }
});

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
  $("weddingStatus").textContent = "Guardando gasto...";
  try {
    state.wedding = await api("/api/wedding/expenses", {
      method: "POST",
      body: new FormData(form),
    });
    form.reset();
    setWeddingDefaultDates();
    $("weddingStatus").textContent = "Gasto guardado correctamente.";
    renderWedding();
  } catch (error) {
    $("weddingStatus").textContent = readableError(error);
  }
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
  } else if (button.dataset.weddingAction === "view-attachment") {
    showWeddingAttachment(
      expenseId,
      button.dataset.attachmentName || "Documento adjunto",
      button.dataset.attachmentMime || "",
    );
  } else if (button.dataset.weddingAction === "attachment") {
    const form = $("weddingAttachmentForm");
    form.reset();
    $("weddingAttachmentStatus").textContent = "";
    state.weddingAttachmentExpenseId = expenseId;
    form.elements.expenseId.value = expenseId;
    openModal("weddingAttachmentModal");
  } else if (button.dataset.weddingAction === "delete") {
    await api(`/api/wedding/expenses/${expenseId}`, { method: "DELETE" });
    await loadWedding();
  }
});

$("weddingAttachmentForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const expenseId = form.elements.expenseId.value || state.weddingAttachmentExpenseId;
  const file = form.elements.attachment.files[0];
  if (!file) return;
  $("weddingAttachmentStatus").textContent = "Guardando archivo...";
  try {
    state.wedding = await api(`/api/wedding/expenses/${expenseId}/attachment`, {
      method: "POST",
      body: new FormData(form),
    });
    $("weddingAttachmentStatus").textContent = "";
    closeModals();
    renderWedding();
  } catch (error) {
    $("weddingAttachmentStatus").textContent = readableError(error);
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
  loadRecurring();
  loadReports();
});

load().catch((error) => {
  console.error(error);
  $("importStatus").textContent = "No se pudo cargar la app local.";
});
