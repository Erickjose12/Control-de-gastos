const AUTH_DISABLED = false;

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
  monthlyControl: null,
  wedding: {
    budget: 0,
    expenses: [],
    categories: [],
  },
  house: {
    total: 0,
    count: 0,
    payments: [],
  },
  debts: {
    types: [],
    banks: [],
    accounts: [],
    debts: [],
    totalDebt: 0,
    totalAvailable: 0,
    minPaymentTotal: 0,
    count: 0,
  },
  ahorros: {
    banks: [],
    accounts: [],
    ahorros: [],
    totalBalance: 0,
    count: 0,
  },
  reports: {
    summary: {},
    trend: [],
    byCategory: [],
    byAccount: [],
    byPaymentMethod: [],
    topExpenses: [],
  },
  deleteTransactionId: null,
  deleteTransactionIds: [],
  weddingAttachmentExpenseId: null,
  weddingPaymentExpenseId: null,
  weddingAttachmentPaymentId: null,
  weddingDetailExpenseId: null,
  weddingAttachmentViewerExpenseId: null,
  houseAttachmentPaymentId: null,
  debtPaymentDebtId: null,
  debtAttachmentPaymentId: null,
  debtDetailDebtId: null,
  importDebtId: null,
  debtImportTransactions: [],
  ahorroDetailAhorroId: null,
  ahorroMovementAhorroId: null,
  theme: localStorage.getItem("finanzas-theme") || "dark",
  uiBound: false,
};

const DOLLAR_SALE_ACCOUNT = "BAC - Cuenta ahorro USD";
const SAVINGS_ACCOUNT = "Banrural - Cuenta ahorro";
const FUND_ACCOUNT = "GYT - Cuenta ahorro sueldo";
const AHORRO_TYPES = ["Ahorro", "Fondo"];

const fmtMoney = new Intl.NumberFormat("es-GT", {
  style: "currency",
  currency: "GTQ",
  currencyDisplay: "narrowSymbol",
});

const fmtUsd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

const $ = (id) => document.getElementById(id);

function currentUsdRate() {
  const value = Number($("importExchangeRate")?.value);
  return value > 0 ? value : 7.8;
}

function applyTheme(theme) {
  state.theme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = state.theme;
  localStorage.setItem("finanzas-theme", state.theme);
  $("themeToggleText").textContent = state.theme === "light" ? "Light" : "Dark";
  $("themeToggle").setAttribute("aria-label", state.theme === "light" ? "Cambiar a modo oscuro" : "Cambiar a modo claro");
  document.querySelector(".theme-toggle-icon").textContent = state.theme === "light" ? "\u2600" : "\u263E";
}

async function api(path, options = {}) {
  const skipAuthRedirect = options.skipAuthRedirect;
  const requestOptions = { ...options };
  delete requestOptions.skipAuthRedirect;
  const res = await fetch(path, requestOptions);
  if (res.status === 401 && !skipAuthRedirect && !AUTH_DISABLED) {
    showLogin();
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function showLogin() {
  if (AUTH_DISABLED) {
    hideLogin();
    return;
  }
  $("loginScreen").hidden = false;
  $("loginForm").elements.password.value = "";
  $("loginStatus").textContent = "";
}

function hideLogin() {
  $("loginScreen").hidden = true;
}

async function boot() {
  applyTheme(state.theme);
  hideLogin();
  const logoutBtn = $("logoutBtn");
  if (logoutBtn) logoutBtn.hidden = AUTH_DISABLED;
  const separator = document.querySelector(".brand-actions-separator");
  if (separator) separator.hidden = AUTH_DISABLED;
  try {
    await load();
  } catch (error) {
    console.error(error);
  }
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

function setHouseDefaultDate() {
  $("housePaymentForm").elements.paymentDate.value = defaultDateForSelectedMonth();
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

function truncateText(value, maxLength) {
  const text = String(value ?? "");
  return text.length > maxLength ? `${text.slice(0, maxLength).trimEnd()}…` : text;
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

function importMovementSide(row) {
  const type = row.suggested_type || "";
  if (["Ingreso", "Ahorro", "Venta USD"].includes(type)) return "credit";
  if (["Gasto", "Transferencia"].includes(type)) return "debit";
  return Number(row.amount || 0) < 0 ? "debit" : "credit";
}

function renderImportTotals() {
  const totals = state.imports.reduce(
    (summary, row) => {
      const amount = Math.abs(Number(row.amount || 0));
      if (importMovementSide(row) === "credit") {
        summary.credit += amount;
      } else {
        summary.debit += amount;
      }
      return summary;
    },
    { credit: 0, debit: 0 },
  );
  const net = totals.credit - totals.debit;
  $("importCreditTotal").textContent = fmtMoney.format(totals.credit);
  $("importDebitTotal").textContent = fmtMoney.format(totals.debit);
  $("importNetTotal").textContent = fmtMoney.format(net);
  $("importTotalCount").textContent = state.imports.length;
  $("importNetCard").classList.toggle("positive", net >= 0);
  $("importNetCard").classList.toggle("negative", net < 0);
}

async function load() {
  applyTheme(state.theme);
  state.meta = await api("/api/meta");
  if (state.meta.latestMonth) {
    $("monthInput").value = state.meta.latestMonth;
  }
  $("accountSelect").innerHTML = optionList(state.meta.accounts, "GYT - Cuenta ahorro sueldo");
  $("manualAccount").innerHTML = optionList([DOLLAR_SALE_ACCOUNT], DOLLAR_SALE_ACCOUNT);
  $("cashExpenseCategory").innerHTML = optionList(state.meta.expenseCategories, "Otros gastos");
  $("manualForm").elements.date.value = defaultDateForSelectedMonth();
  $("cashExpenseDate").value = defaultDateForSelectedMonth();
  setWeddingDefaultDates();
  setHouseDefaultDate();
  updateManualDefaults();
  if (!state.uiBound) {
    bindNavigation();
    bindImportUploader();
    state.uiBound = true;
  }
  await refreshAll();
}

async function refreshAll() {
  await Promise.all([
    loadImports(),
    loadDashboard(),
    loadMonthlyControl(),
    loadWedding(),
    loadHouse(),
    loadDebts(),
    loadAhorros(),
    loadReports(),
    loadImportExchangeRate(),
  ]);
}

async function loadAhorros() {
  state.ahorros = await api("/api/ahorros/state");
  renderAhorros();
}

async function loadDebts() {
  state.debts = await api("/api/debts/state");
  renderDebts();
}

async function loadImportExchangeRate() {
  const note = $("importExchangeRateNote");
  const input = $("importExchangeRate");
  try {
    const data = await api("/api/exchange-rate");
    if (!data.ok || !data.rate) throw new Error(data.message || "Sin tasa");
    input.value = data.rate.toFixed(4);
    note.innerHTML = `<strong>Tipo de cambio USD-GTQ actualizado: ${data.rate.toFixed(4)}</strong>`;
  } catch (error) {
    note.innerHTML = `<strong>Tipo de cambio USD-GTQ: ${Number(input.value).toFixed(4)} (sin conexion, valor de referencia)</strong>`;
    console.error(error);
  }
  if (state.debts?.debts?.length) renderDebts();
}

async function loadImports() {
  const query = state.importDebtId ? `?debtId=${encodeURIComponent(state.importDebtId)}` : "";
  state.imports = await api(`/api/imports${query}`);
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

async function loadHouse() {
  const month = $("monthInput").value;
  state.house = await api(`/api/house/state?month=${encodeURIComponent(month)}`);
  renderHouse();
}

async function loadReports() {
  const month = $("monthInput").value;
  state.reports = await api(`/api/reports?month=${encodeURIComponent(month)}`);
  renderReports();
}

function renderMonthlyControl() {
  const data = state.monthlyControl || {};
  const budget = Number(data.budget || 0);
  const remaining = Number(data.remaining || 0);
  $("monthlyBudgetKpi").textContent = fmtMoney.format(budget);
  $("monthlyDebitKpi").textContent = fmtMoney.format(Number(data.importedDebits || 0));
  $("monthlyRemainingKpi").textContent = fmtMoney.format(remaining);
  $("monthlyBudgetAmount").value = Number.isFinite(budget) ? budget.toFixed(2) : "0.00";
  $("monthlyRemainingCard").classList.toggle("negative", remaining < 0);
}

async function loadMonthlyControl() {
  const month = $("monthInput").value;
  state.monthlyControl = await api(`/api/monthly-control?month=${encodeURIComponent(month)}`);
  renderMonthlyControl();
}

async function refreshMonthlyData() {
  await Promise.all([loadDashboard(), loadMonthlyControl(), loadDebts(), loadAhorros()]);
}
function renderDashboard() {
  const data = state.dashboard;
  $("incomeKpi").textContent = fmtMoney.format(data.income);
  $("expenseKpi").textContent = fmtMoney.format(data.expenses);
  $("balanceKpi").textContent = fmtMoney.format(data.available);
  $("initialBalanceKpi").textContent = fmtMoney.format(data.initialBalance || 0);
  $("rateKpi").textContent = `${fmtMoney.format(data.savings)} / ${Math.round(data.savingsRate * 100)}%`;

  $("accountSummary").innerHTML =
    (data.byBank || []).length === 0
      ? `<p class="empty">Sin movimientos por banco en este mes.</p>`
      : data.byBank
          .map((item) => {
            const tone = item.net >= 0 ? "positive" : "negative";
            return `
              <div class="bank-summary-row">
                <div class="bank-summary-head">
                  <strong>${escapeHtml(item.bank)}</strong>
                  <span class="${tone}">${fmtMoney.format(item.net)}</span>
                </div>
                <div class="bank-summary-grid">
                  <span class="income"><small>Ingresos</small>${fmtMoney.format(item.income || 0)}</span>
                  <span class="expense"><small>Gastos</small>${fmtMoney.format(item.expenses || 0)}</span>
                </div>
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

function renderComparisonCard(label, metric, toneWhenUp = "positive") {
  const delta = Number(metric?.delta || 0);
  const percent = Number(metric?.percent || 0);
  const tone =
    delta === 0 ? "neutral" : delta > 0 ? toneWhenUp : toneWhenUp === "positive" ? "negative" : "positive";
  const sign = delta > 0 ? "+" : "";
  const percentText = delta === 0 ? "0%" : `${sign}${Math.round(percent * 100)}%`;
  return `
    <article class="comparison-card ${tone}">
      <span>${escapeHtml(label)}</span>
      <strong>${fmtMoney.format(metric?.current || 0)}</strong>
      <small>Antes: ${fmtMoney.format(metric?.previous || 0)}</small>
      <em>${sign}${fmtMoney.format(delta)} · ${percentText}</em>
    </article>`;
}

function renderReportGoals(wedding, house) {
  const cards = [];
  if (wedding.hasData) {
    const progress = Math.round(Number(wedding.progress || 0) * 100);
    const tone = Number(wedding.available || 0) >= 0 ? "positive" : "negative";
    cards.push(`
      <article class="report-bank-card">
        <div class="report-bank-card-head">
          <div>
            <strong>Boda</strong>
            <small>${progress}% ejecutado del presupuesto</small>
          </div>
          <div>
            <small>Presupuesto disponible</small>
            <span class="${tone}">${fmtMoney.format(wedding.available || 0)}</span>
          </div>
        </div>
        <div class="report-mini-track">
          <div class="report-mini-fill" style="width:${Math.min(100, Math.max(0, progress))}%"></div>
        </div>
        <div class="report-bank-metrics">
          <span class="expense"><small>Gastado</small>${fmtMoney.format(wedding.spent || 0)}</span>
          <span class="income"><small>Pagado</small>${fmtMoney.format(wedding.paid || 0)}</span>
          <span><small>Pendiente</small>${fmtMoney.format(wedding.pending || 0)}</span>
        </div>
      </article>`);
  }
  if (house.hasData) {
    const movementLabel = Number(house.count || 0) === 1 ? "pago" : "pagos";
    cards.push(`
      <article class="report-bank-card">
        <div class="report-bank-card-head">
          <div>
            <strong>Pago de la casa</strong>
            <small>${house.count || 0} ${movementLabel} este mes</small>
          </div>
          <span class="positive">${fmtMoney.format(house.total || 0)}</span>
        </div>
      </article>`);
  }
  $("reportGoalsPanel").hidden = cards.length === 0;
  $("reportGoalsSummary").innerHTML = cards.join("");
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

  const comparison = data.comparison || {};
  $("reportComparisonLabel").textContent =
    comparison.previousMonth && comparison.currentMonth
      ? `${reportMonthLabel(comparison.previousMonth)} vs. ${reportMonthLabel(comparison.currentMonth)}`
      : "Sin comparacion";
  $("reportComparison").innerHTML = `
    ${renderComparisonCard("Ingresos", comparison.income, "positive")}
    ${renderComparisonCard("Gastos", comparison.expenses, "negative")}
    ${renderComparisonCard("Ahorro", comparison.savings, "positive")}
    ${renderComparisonCard("Resultado", comparison.balance, "positive")}
  `;

  const banks = data.byBank || [];
  $("reportBankSummary").innerHTML =
    banks.length === 0
      ? `<p class="empty">Sin movimientos por banco en este mes.</p>`
      : banks
          .map((bank) => {
            const tone = Number(bank.net || 0) >= 0 ? "positive" : "negative";
            const movementLabel = Number(bank.count || 0) === 1 ? "movimiento" : "movimientos";
            return `
              <article class="report-bank-card">
                <div class="report-bank-card-head">
                  <div>
                    <strong>${escapeHtml(bank.bank)}</strong>
                    <small>${bank.count || 0} ${movementLabel}</small>
                  </div>
                  <span class="${tone}">${fmtMoney.format(bank.net || 0)}</span>
                </div>
                <div class="report-bank-metrics">
                  <span class="income"><small>Ingresos</small>${fmtMoney.format(bank.income || 0)}</span>
                  <span class="expense"><small>Gastos</small>${fmtMoney.format(bank.expenses || 0)}</span>
                  <span><small>Ahorro</small>${fmtMoney.format(bank.savings || 0)}</span>
                  <span><small>Transferencias</small>${fmtMoney.format(bank.transfers || 0)}</span>
                </div>
              </article>`;
          })
          .join("");

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

  renderReportBreakdown("reportAccountFlow", data.byAccount || [], "Sin movimientos por cuenta.");

  renderReportGoals(data.wedding || {}, data.house || {});

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

function exportReport(format) {
  const link = document.createElement("a");
  const extension = format === "pdf" ? "pdf" : "xlsx";
  link.href = `/api/reports/export?month=${encodeURIComponent(state.reports.month)}&format=${format}`;
  link.download = `reporte-financiero-${state.reports.month}.${extension}`;
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function printReport() {
  window.print();
}

function ahorroMovementLabel(type) {
  return type === "Ahorro" ? "Entrada" : "Salida";
}

function updateAhorroFormFields() {
  const isFondo = $("ahorroType").value === "Fondo";
  document.querySelectorAll("#ahorroForm .ahorro-fondo-only").forEach((el) => {
    el.hidden = !isFondo;
  });
}

function renderAhorroCard(ahorro) {
  const isFondo = ahorro.type === "Fondo";
  return `
    <div class="goal-card" data-ahorro-id="${ahorro.id}">
      <div class="goal-card-head">
        <div>
          <p class="goal-name">${escapeHtml(ahorro.name)}</p>
          <span class="goal-tag">${escapeHtml(isFondo ? "Fondo" : "Ahorro")} · ${escapeHtml(ahorro.account)}</span>
          <span class="goal-bank">${escapeHtml(ahorro.bank)}</span>
        </div>
      </div>
      <div class="debt-rows">
        <div class="debt-rowline"><span>Saldo actual</span><strong>${fmtMoney.format(ahorro.current_balance)}</strong></div>
        ${isFondo && ahorro.monthly_target ? `<div class="debt-rowline"><span>Aporte mensual esperado</span><strong>${fmtMoney.format(ahorro.monthly_target)}</strong></div>` : ""}
        <div class="debt-rowline"><span>${isFondo ? "Aportes registrados" : "Movimientos"}</span><strong>${ahorro.movements.length}</strong></div>
      </div>
      <div class="goal-actions">
        <button class="table-action" type="button" data-ahorro-action="detail">Ver informacion</button>
        <button class="table-action success-text" type="button" data-ahorro-action="movement">${isFondo ? "Registrar aporte" : "Registrar movimiento"}</button>
      </div>
    </div>`;
}

function renderAhorros() {
  const data = state.ahorros || { ahorros: [] };
  const ahorros = data.ahorros || [];
  $("ahorroTotalKpi").textContent = fmtMoney.format(data.totalBalance || 0);
  $("ahorroCountKpi").textContent = data.count || 0;
  $("ahorroType").innerHTML = optionList(data.types || AHORRO_TYPES, (data.types || AHORRO_TYPES)[0]);
  $("ahorroBank").innerHTML = optionList(data.banks || [], (data.banks || [])[0]);
  $("ahorroAccount").innerHTML = optionList(data.accounts || [], SAVINGS_ACCOUNT);
  updateAhorroFormFields();
  $("ahorroCount").textContent =
    ahorros.length === 0 ? "Sin ahorros registrados." : `${ahorros.length} registrado${ahorros.length === 1 ? "" : "s"}.`;

  const query = normalizeSearch($("ahorroSearch").value);
  const filtered = ahorros.filter((ahorro) =>
    matchesSearch([ahorro.name, ahorro.type, ahorro.bank, ahorro.account, fmtMoney.format(ahorro.current_balance)], query),
  );

  $("ahorroGrid").innerHTML =
    ahorros.length === 0
      ? `<p class="empty">Aun no hay ahorros registrados.</p>`
      : filtered.length === 0
        ? `<p class="empty">No hay ahorros que coincidan con la busqueda.</p>`
        : filtered.map((ahorro) => renderAhorroCard(ahorro)).join("");
}

function savingSaleRows() {
  const transactions = state.dashboard?.transactions || [];
  return transactions.filter((tx) => !tx.source_import_id && tx.type === "Venta USD");
}

function renderSavingSales() {
  const rows = savingSaleRows();
  const sales = rows.reduce((sum, tx) => sum + Number(tx.amount || 0), 0);
  const usdSales = rows.reduce((sum, tx) => sum + Number(tx.usd_amount || 0), 0);
  $("usdSaleKpi").textContent = fmtMoney.format(sales);
  $("usdSaleUsdKpi").textContent = fmtUsd.format(usdSales);
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
      ? `<tr><td class="empty" colspan="7">Sin ventas de dolares registradas en este mes.</td></tr>`
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
                <button class="table-action success-text" type="button" data-saving-action="view">Ver</button>
                <button class="table-action" type="button" data-saving-action="edit">Editar</button>
                ${
                  tx.attachment_path
                    ? `<button class="table-action success-text" type="button" data-saving-action="view-attachment" data-attachment-name="${escapeHtml(tx.attachment_name || "Boleta")}" data-attachment-mime="${escapeHtml(tx.attachment_mime || "")}">Ver boleta</button>
                       <button class="table-action" type="button" data-saving-action="attach">Cambiar</button>`
                    : `<button class="table-action" type="button" data-saving-action="attach">Adjuntar</button>`
                }
                <button class="table-action danger-text" type="button" data-saving-action="delete">Eliminar</button>
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
  renderImportTotals();
  renderImportWorkflow(filteredImports.length);
}

function renderImportWorkflow(filteredCount = state.imports.length) {
  const hasFile = Boolean($("fileInput")?.files?.length);
  const hasImports = state.imports.length > 0;
  $("importStepUpload").classList.toggle("active", !hasImports);
  $("importStepUpload").classList.toggle("done", hasImports);
  $("importStepReview").classList.toggle("active", hasImports);
  $("importStepReview").classList.toggle("done", false);
  $("importStepDone").classList.toggle("active", false);
  $("commitBtn").disabled = !hasImports;
  $("commitBtn").textContent = hasImports ? `Importar ${state.imports.length} registros` : "Importar registros";
  $("importReviewSummary").textContent = hasImports
    ? `${filteredCount} de ${state.imports.length} movimientos listos para guardar.`
    : "Selecciona el archivo para revisar los movimientos antes de guardarlos.";
  $("importSubmitBtn").textContent = hasFile ? "Revisar archivo" : "Selecciona un archivo";
  $("cancelImportBtn").hidden = !hasFile && !hasImports;
}

function renderWedding() {
  const data = state.wedding;
  const progress = Math.min(data.progress || 0, 1);
  const progressText = `${Math.round(progress * 100)}%`;
  const owed = Math.max(Number(data.pending ?? Number(data.spent || 0) - Number(data.paid || 0)), 0);
  $("weddingDashBudget").textContent = fmtMoney.format(data.budget || 0);
  $("weddingDashSpent").textContent = fmtMoney.format(owed);
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
          .map((expense) => {
            const needsPayment = Number(expense.pending_amount) > 0;
            const receiptsTone = needsPayment ? "success-text" : "warning-text";
            const documentTone = expense.has_attachment ? "info-text" : "success-text";
            return `
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
                <button class="table-action" type="button" data-wedding-action="detail">Ver informacion</button>
                <button class="table-action ${receiptsTone}" type="button" data-wedding-action="view-receipts">Ver boleta</button>
                <button class="table-action ${documentTone}" type="button" data-wedding-action="document">Ver documento</button>
              </td>
            </tr>`;
          })
          .join("");
}

function renderWeddingPaymentHistory(expenseId) {
  const expense = (state.wedding.expenses || []).find((entry) => String(entry.id) === String(expenseId));
  const payments = expense?.payments || [];
  $("weddingPaymentHistory").innerHTML =
    payments.length === 0
      ? `<p class="wedding-payment-history-empty">Aun no hay abonos registrados para este gasto.</p>`
      : payments
          .map(
            (payment) => `
              <div class="wedding-payment-row" data-wedding-payment-id="${payment.id}">
                <div class="wedding-payment-row-main">
                  <strong>${fmtMoney.format(payment.amount)}</strong>
                  <small>${escapeHtml(formatDisplayDate(payment.date))}${payment.note ? ` · ${escapeHtml(payment.note)}` : ""}</small>
                </div>
                <div class="wedding-payment-row-actions">
                  ${
                    payment.has_attachment
                      ? `<button class="table-action success-text" type="button" data-payment-action="view-attachment" data-attachment-name="${escapeHtml(payment.attachment_name || "Boleta")}" data-attachment-mime="${escapeHtml(payment.attachment_mime || "")}">Ver</button>
                         <button class="table-action" type="button" data-payment-action="attachment">Cambiar</button>`
                      : `<button class="table-action" type="button" data-payment-action="attachment">Adjuntar</button>`
                  }
                </div>
              </div>`,
          )
          .join("");
}

function renderHouse() {
  const data = state.house || { payments: [] };
  const payments = data.payments || [];
  $("houseTotalKpi").textContent = fmtMoney.format(data.total || 0);
  $("houseCountKpi").textContent = data.count || 0;

  const query = normalizeSearch($("houseSearch").value);
  const filtered = payments.filter((payment) =>
    matchesSearch(
      [
        payment.paymentDate,
        payment.description,
        fmtMoney.format(payment.amount),
        payment.attachment_name || "",
        payment.has_attachment ? "con archivo documento evidencia" : "sin archivo",
      ],
      query,
    ),
  );

  $("housePaymentsBody").innerHTML =
    payments.length === 0
      ? `<tr><td class="empty" colspan="5">Aun no hay pagos de casa registrados en este mes.</td></tr>`
      : filtered.length === 0
        ? `<tr><td class="empty" colspan="5">No hay pagos de casa que coincidan con la busqueda.</td></tr>`
        : filtered
          .map(
            (payment) => `
            <tr data-house-payment-id="${payment.id}">
              <td>${escapeHtml(formatDisplayDate(payment.paymentDate))}</td>
              <td>${escapeHtml(payment.description)}</td>
              <td class="money">${fmtMoney.format(payment.amount)}</td>
              <td>
                ${
                  payment.has_attachment
                    ? `<button class="table-action success-text" type="button" data-house-action="view-attachment" data-attachment-name="${escapeHtml(payment.attachment_name || "Archivo")}" data-attachment-mime="${escapeHtml(payment.attachment_mime || "")}">Ver</button>`
                    : `<span class="muted-text">Sin archivo</span>`
                }
              </td>
              <td class="actions-cell">
                <button class="table-action" type="button" data-house-action="attachment">${payment.has_attachment ? "Cambiar" : "Adjuntar"}</button>
                <button class="table-action danger-text" type="button" data-house-action="delete">Eliminar</button>
              </td>
            </tr>`,
          )
          .join("");
}

function debtDueInfo(debt) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  if (debt.due_day) {
    let due = new Date(today.getFullYear(), today.getMonth(), debt.due_day);
    if (due < today) due = new Date(today.getFullYear(), today.getMonth() + 1, debt.due_day);
    const days = Math.round((due - today) / (1000 * 60 * 60 * 24));
    const dueLabel = formatDisplayDate(due.toISOString().slice(0, 10));
    if (days === 0) return { label: "Vence hoy", tone: "soon", days };
    if (days <= 5) return { label: `Vence en ${days} dia${days === 1 ? "" : "s"} · ${dueLabel}`, tone: "soon", days };
    return { label: `Vence el ${dueLabel}`, tone: "ok", days };
  }
  if (debt.end_date) {
    const due = new Date(`${debt.end_date}T00:00:00`);
    const days = Math.round((due - today) / (1000 * 60 * 60 * 24));
    const dueLabel = formatDisplayDate(debt.end_date);
    if (days < 0) return { label: `Vencio el ${dueLabel}`, tone: "soon", days };
    if (days === 0) return { label: "Vence hoy", tone: "soon", days };
    if (days <= 5) return { label: `Vence en ${days} dia${days === 1 ? "" : "s"} · ${dueLabel}`, tone: "soon", days };
    return { label: `Vence el ${dueLabel}`, tone: "ok", days };
  }
  return { label: "Sin fecha de pago", tone: "none", days: null };
}

function renderDebtCard(debt) {
  const isCard = debt.type === "Tarjeta de credito";
  const isLoan = debt.type === "Prestamo";
  const due = debtDueInfo(debt);
  const alert = due.tone === "soon";
  let pct;
  let barColor;
  let progressLabel;
  if (isCard) {
    pct = Math.round((debt.utilization || 0) * 100);
    barColor = pct >= 70 ? "var(--red)" : pct >= 30 ? "var(--amber)" : "var(--green)";
    progressLabel = "Utilizacion";
  } else {
    pct = Math.round((debt.progress || 0) * 100);
    barColor = "var(--teal)";
    progressLabel = "Pagado";
  }
  const typeLabel = isCard ? "Tarjeta" : isLoan ? "Prestamo" : "Otro pago";
  const amountLabel = debt.is_other ? "Monto a pagar" : "Monto original";
  return `
    <div class="goal-card${alert ? " alert" : ""}" data-debt-id="${debt.id}">
      <div class="goal-card-head">
        <div>
          <p class="goal-name">${escapeHtml(debt.name)}</p>
          <span class="goal-tag">${escapeHtml(typeLabel)}</span>
          ${debt.bank ? `<span class="goal-bank">${escapeHtml(debt.bank)}</span>` : ""}
        </div>
        <span class="goal-pct">${pct}%</span>
      </div>
      <div class="goal-amounts" style="margin-bottom:5px;"><span class="target">${progressLabel}</span><span class="target">${pct}%</span></div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, pct)}%;background:${barColor};"></div></div>
      <div class="debt-rows">
        <div class="debt-rowline"><span>Saldo</span><strong>${fmtMoney.format(debt.current_balance)}</strong></div>
        ${isCard && debt.balance_usd ? `<div class="debt-rowline"><span>Saldo en USD</span><strong>${fmtUsd.format(debt.balance_usd)} <span class="muted-inline">(&asymp; ${fmtMoney.format(debt.balance_usd * currentUsdRate())})</span></strong></div>` : ""}
        ${isCard && debt.available !== null ? `<div class="debt-rowline"><span>Disponible</span><strong>${fmtMoney.format(debt.available)}</strong></div>` : ""}
        ${isCard && debt.available_usd !== null ? `<div class="debt-rowline"><span>Disponible USD</span><strong>${fmtUsd.format(debt.available_usd)}</strong></div>` : ""}
        ${!isCard && debt.original_amount ? `<div class="debt-rowline"><span>${amountLabel}</span><strong>${fmtMoney.format(debt.original_amount)}</strong></div>` : ""}
        ${isLoan && debt.monthly_payment ? `<div class="debt-rowline"><span>Cuota mensual</span><strong>${fmtMoney.format(debt.monthly_payment)}</strong></div>` : ""}
        ${debt.interest_rate ? `<div class="debt-rowline"><span>Tasa anual</span><strong>${debt.interest_rate}%</strong></div>` : ""}
        ${isLoan && debt.start_date ? `<div class="debt-rowline"><span>Fecha inicio</span><strong>${escapeHtml(formatDisplayDate(debt.start_date))}</strong></div>` : ""}
      </div>
      <span class="debt-due ${due.tone}">${escapeHtml(due.label)}</span>
      <div class="goal-actions">
        <button class="table-action" type="button" data-debt-action="detail">Ver informacion</button>
        <button class="table-action success-text" type="button" data-debt-action="pay">Registrar pago</button>
        ${isCard ? `<button class="table-action info-text" type="button" data-debt-action="import">Importar estado de cuenta</button>` : ""}
      </div>
    </div>`;
}

function renderDebts() {
  const data = state.debts || { debts: [] };
  const debts = data.debts || [];
  $("debtTotalKpi").textContent = fmtMoney.format(data.totalDebt || 0);
  $("debtBank").innerHTML = optionList(data.banks || [], (data.banks || [])[0]);
  $("debtPaymentAccount").innerHTML = optionList(data.accounts || [], (data.accounts || [])[0]);
  updateDebtFormFields();

  $("debtCount").textContent =
    debts.length === 0 ? "Sin deudas registradas." : `${debts.length} registrada${debts.length === 1 ? "" : "s"}.`;

  const query = normalizeSearch($("debtSearch").value);
  const filtered = debts.filter((debt) =>
    matchesSearch([debt.name, debt.type, debt.bank, fmtMoney.format(debt.current_balance)], query),
  );

  $("debtGrid").innerHTML =
    debts.length === 0
      ? `<p class="empty">Aun no hay deudas ni tarjetas registradas.</p>`
      : filtered.length === 0
        ? `<p class="empty">No hay deudas que coincidan con la busqueda.</p>`
        : filtered.map((debt) => renderDebtCard(debt)).join("");
}

function renderDebtPaymentHistory(debtId) {
  const debt = (state.debts.debts || []).find((entry) => String(entry.id) === String(debtId));
  const payments = debt?.payments || [];
  $("debtPaymentHistory").innerHTML =
    payments.length === 0
      ? `<p class="wedding-payment-history-empty">Aun no hay pagos registrados para esta deuda.</p>`
      : payments
          .map(
            (payment) => `
              <div class="wedding-payment-row" data-debt-payment-id="${payment.id}">
                <div class="wedding-payment-row-main">
                  <strong>${fmtMoney.format(payment.amount)}</strong>
                  <small>${escapeHtml(formatDisplayDate(payment.date))}${payment.note ? ` · ${escapeHtml(payment.note)}` : ""}</small>
                </div>
                <div class="wedding-payment-row-actions">
                  ${
                    payment.has_attachment
                      ? `<button class="table-action success-text" type="button" data-debt-payment-action="view-attachment" data-attachment-name="${escapeHtml(payment.attachment_name || "Boleta")}" data-attachment-mime="${escapeHtml(payment.attachment_mime || "")}">Ver</button>
                         <button class="table-action" type="button" data-debt-payment-action="attachment">Cambiar</button>`
                      : `<button class="table-action" type="button" data-debt-payment-action="attachment">Adjuntar</button>`
                  }
                </div>
              </div>`,
          )
          .join("");
}

function updateDebtFormFields() {
  const type = $("debtType").value;
  const isCard = type === "Tarjeta de credito";
  const isLoan = type === "Prestamo";
  const isOther = type === "Otro pago";
  document.querySelectorAll("#debtForm .debt-card-only").forEach((el) => {
    el.hidden = !isCard;
  });
  document.querySelectorAll("#debtForm .debt-loan-only").forEach((el) => {
    el.hidden = !isLoan;
  });
  document.querySelectorAll("#debtForm .debt-card-loan-only").forEach((el) => {
    el.hidden = isOther;
  });
  document.querySelectorAll("#debtForm .debt-loan-other-only").forEach((el) => {
    el.hidden = isCard;
  });
  $("debtAmountLabel").textContent = isOther ? "Monto a pagar" : "Monto del prestamo";
  $("debtEndDateLabel").textContent = isOther ? "Fecha limite de pago" : "Fecha fin del prestamo";
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

function updateManualDefaults() {
  $("manualAccount").innerHTML = optionList([DOLLAR_SALE_ACCOUNT], DOLLAR_SALE_ACCOUNT);
  $("cashExpenseCategory").innerHTML = optionList(state.meta.expenseCategories, "Otros gastos");
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
    movementsView: ["Gastos y deudas", "Gastos del mes, tarjetas, prestamos e importacion de estados de cuenta."],
    savingsAccountView: ["Ahorros", "Tus cuentas de ahorro y fondos, y su saldo actual."],
    savingsView: ["Venta dolares", "Seguimiento de ventas USD registradas manualmente."],
    weddingView: ["Gastos de boda", "Presupuesto, abonos y proveedores del evento."],
    houseView: ["Gastos de la casa", "Control de pagos, documentos y evidencias de la casa."],
    reportsView: ["Reportes", "Analiza tendencias, categorias y comportamiento mensual."],
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

function syncSelectedFileName() {
  const input = $("fileInput");
  const file = input.files?.[0];
  $("selectedFileName").textContent = file ? file.name : "o haz clic para seleccionar el archivo PDF o CSV";
  $("dropzoneTitle").textContent = file ? "Archivo listo para revisar" : "Arrastra tu estado de cuenta aqui";
  renderImportWorkflow();
}

function guessBankFromFileName(fileName) {
  const name = normalizeSearch(fileName);
  if (name.includes("banrural")) return "Banrural";
  if (name.includes("bac")) return "BAC";
  if (name.includes("banco industrial") || /\bbi\b/.test(name)) return "Banco Industrial";
  if (name.includes("gyt") || name.includes("g&t") || name.includes("continental")) return "GYT";
  return "";
}

function updateImportAccountForBank() {
  const bank = $("bankSelect").value;
  const preferred = {
    Banrural: "Banrural - Cuenta ahorro",
    BAC: "BAC - Cuenta ahorro USD",
    "Banco Industrial": "Banco Industrial - Cuenta ahorro",
    GYT: "GYT - Cuenta ahorro sueldo",
  }[bank];
  if (preferred) {
    $("accountSelect").innerHTML = optionList(state.meta.accounts, preferred);
  }
}

function bindImportUploader() {
  const dropzone = $("importDropzone");
  const fileInput = $("fileInput");
  const bankSelect = $("bankSelect");

  fileInput.addEventListener("change", () => {
    const guessedBank = guessBankFromFileName(fileInput.files?.[0]?.name || "");
    if (guessedBank) {
      bankSelect.value = guessedBank;
      updateImportAccountForBank();
    }
    syncSelectedFileName();
  });

  bankSelect.addEventListener("change", updateImportAccountForBank);

  ["dragenter", "dragover"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropzone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropzone.classList.remove("drag-over");
    });
  });

  dropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files?.[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
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
  state.weddingAttachmentPaymentId = null;
  state.weddingDetailExpenseId = null;
  state.weddingAttachmentViewerExpenseId = null;
  state.houseAttachmentPaymentId = null;
  state.debtPaymentDebtId = null;
  state.debtAttachmentPaymentId = null;
  state.debtDetailDebtId = null;
  state.importDebtId = null;
  state.ahorroDetailAhorroId = null;
  state.ahorroMovementAhorroId = null;
  if ($("weddingAttachmentViewer")) {
    $("weddingAttachmentViewer").innerHTML = "";
  }
  if ($("weddingAttachmentStatus")) {
    $("weddingAttachmentStatus").textContent = "";
  }
  if ($("debtAttachmentStatus")) {
    $("debtAttachmentStatus").textContent = "";
  }
}

const FLOW_IN_TYPES = new Set(["Ingreso", "Ahorro", "Venta USD"]);
const MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

function formatDetailDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ""));
  if (!match) return escapeHtml(value ?? "—");
  const [, year, month, day] = match;
  return `${Number(day)} ${MONTHS_ES[Number(month) - 1] || month} ${year}`;
}

function formatDetailDateTime(value) {
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(String(value ?? ""));
  if (!match) return formatDetailDate(value);
  return `${formatDetailDate(match[1])} · ${match[2]}`;
}

function detailItem(label, valueHtml) {
  return `
    <div class="detail-item">
      <span class="detail-item-label">${escapeHtml(label)}</span>
      <span class="detail-item-value">${valueHtml}</span>
    </div>`;
}

function showWeddingAttachment(expenseId, name, mime) {
  const url = `/api/wedding/expenses/${expenseId}/attachment`;
  $("weddingAttachmentViewTitle").textContent = name || "Documento adjunto";
  $("weddingAttachmentOpenLink").href = url;
  $("weddingAttachmentViewer").innerHTML = mime.startsWith("image/")
    ? `<img src="${url}" alt="${escapeHtml(name || "Documento adjunto")}" />`
    : `<iframe src="${url}" title="${escapeHtml(name || "Documento adjunto")}"></iframe>`;
  state.weddingAttachmentViewerExpenseId = expenseId;
  $("weddingAttachmentViewChangeBtn").hidden = false;
  openModal("weddingAttachmentViewModal");
}

function showWeddingPaymentAttachment(paymentId, name, mime) {
  const url = `/api/wedding/payments/${paymentId}/attachment`;
  $("weddingAttachmentViewTitle").textContent = name || "Documento adjunto";
  $("weddingAttachmentOpenLink").href = url;
  $("weddingAttachmentViewer").innerHTML = mime.startsWith("image/")
    ? `<img src="${url}" alt="${escapeHtml(name || "Documento adjunto")}" />`
    : `<iframe src="${url}" title="${escapeHtml(name || "Documento adjunto")}"></iframe>`;
  state.weddingAttachmentViewerExpenseId = null;
  $("weddingAttachmentViewChangeBtn").hidden = true;
  openModal("weddingAttachmentViewModal");
}

function showHouseAttachment(paymentId, name, mime) {
  const url = `/api/house/payments/${paymentId}/attachment`;
  $("weddingAttachmentViewTitle").textContent = name || "Documento adjunto";
  $("weddingAttachmentOpenLink").href = url;
  $("weddingAttachmentViewer").innerHTML = mime.startsWith("image/")
    ? `<img src="${url}" alt="${escapeHtml(name || "Documento adjunto")}" />`
    : `<iframe src="${url}" title="${escapeHtml(name || "Documento adjunto")}"></iframe>`;
  state.weddingAttachmentViewerExpenseId = null;
  $("weddingAttachmentViewChangeBtn").hidden = true;
  openModal("weddingAttachmentViewModal");
}

function showTransactionAttachment(transactionId, name, mime) {
  const url = `/api/transactions/${transactionId}/attachment`;
  $("weddingAttachmentViewTitle").textContent = name || "Boleta adjunta";
  $("weddingAttachmentOpenLink").href = url;
  $("weddingAttachmentViewer").innerHTML = mime.startsWith("image/")
    ? `<img src="${url}" alt="${escapeHtml(name || "Boleta adjunta")}" />`
    : `<iframe src="${url}" title="${escapeHtml(name || "Boleta adjunta")}"></iframe>`;
  state.weddingAttachmentViewerExpenseId = null;
  $("weddingAttachmentViewChangeBtn").hidden = true;
  openModal("weddingAttachmentViewModal");
}

async function showTransactionDetail(transactionId) {
  const tx = await api(`/api/transactions/${transactionId}`);
  const isInflow = FLOW_IN_TYPES.has(tx.type);
  const flow = isInflow ? "is-in" : "is-out";
  const sign = isInflow ? "+" : "−";
  const origin = tx.source_import_id ? `Importacion #${tx.source_import_id}` : "Registro manual";
  $("transactionDetail").innerHTML = `
    <div class="detail-hero">
      <span class="detail-type-chip ${flow}">${escapeHtml(tx.type)}</span>
      <div class="detail-hero-amount ${flow}">${sign} ${escapeHtml(fmtMoney.format(tx.amount))}</div>
      <p class="detail-hero-desc">${escapeHtml(tx.description || "Sin descripcion")}</p>
    </div>
    <div class="detail-list">
      ${detailItem("Fecha", formatDetailDate(tx.date))}
      ${detailItem("Categoria", `<span class="detail-tag">${escapeHtml(tx.category)}</span>`)}
      ${detailItem("Cuenta", escapeHtml(tx.account))}
      ${detailItem("Creado", formatDetailDateTime(tx.created_at))}
      ${detailItem("Origen", `<span class="detail-origin">${escapeHtml(origin)}</span>`)}
    </div>`;
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
  const editableTypes = tx.ahorro_id
    ? state.meta.transactionTypes
    : state.meta.transactionTypes.filter((type) => type !== "Ahorro");
  form.elements.type.innerHTML = optionList(editableTypes, tx.type);
  form.elements.account.innerHTML = optionList(state.meta.accounts, tx.account);
  form.elements.amount.value = tx.amount;
  form.elements.description.value = tx.description;
  openModal("editTransactionModal");
}

$("importForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  if (state.importDebtId) data.append("debtId", state.importDebtId);
  $("importStatus").textContent = "Importando...";
  try {
    const result = await api("/api/import", { method: "POST", body: data });
    $("importStatus").textContent = `Listo: ${result.count} movimientos cargados a revision.`;
    form.reset();
    $("accountSelect").innerHTML = optionList(state.meta.accounts, "GYT - Cuenta ahorro sueldo");
    syncSelectedFileName();
    await loadImports();
  } catch (error) {
    $("importStatus").textContent = readableError(error) || "No se pudo importar el archivo.";
    console.error(error);
  }
});

$("commitBtn").addEventListener("click", async () => {
  if (!state.imports.length) return;
  const result = await api("/api/imports/commit", {
    method: "POST",
    body: JSON.stringify({ debtId: state.importDebtId || null }),
  });
  $("importStatus").textContent = `Registrados ${result.count} movimientos.`;
  await loadImports();
  if (state.importDebtId) {
    await loadDebtCardTransactions(state.importDebtId);
  }
  await Promise.all([loadDebts(), refreshMonthlyData()]);
});

async function clearImportDraft(message = "Carga cancelada.") {
  const query = state.importDebtId ? `?debtId=${encodeURIComponent(state.importDebtId)}` : "";
  await api(`/api/imports${query}`, { method: "DELETE" });
  const form = $("importForm");
  form.reset();
  $("accountSelect").innerHTML = optionList(state.meta.accounts, "GYT - Cuenta ahorro sueldo");
  syncSelectedFileName();
  $("importStatus").textContent = message;
  await loadImports();
}

$("themeToggle").addEventListener("click", () => {
  applyTheme(state.theme === "light" ? "dark" : "light");
});

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form).entries());
  $("loginStatus").textContent = "Validando acceso...";
  try {
    const result = await api("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
      skipAuthRedirect: true,
    });
    if (!result.ok) throw new Error(result.message || "No se pudo iniciar sesion");
    $("loginStatus").textContent = "";
    hideLogin();
    await load();
  } catch (error) {
    $("loginStatus").textContent = readableError(error);
  }
});

$("logoutBtn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST", skipAuthRedirect: true });
  location.reload();
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

$("monthlyBudgetForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.target);
  const body = {
    month: $("monthInput").value,
    amount: Number(formData.get("amount") || 0),
  };
  const result = await api("/api/monthly-control", {
    method: "PUT",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json" },
  });
  state.monthlyControl = result;
  renderMonthlyControl();
  $("monthlyBudgetStatus").textContent = "Monto mensual guardado.";
});

$("cashExpenseForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.target);
  formData.set("type", "Gasto");
  formData.set("account", "Efectivo");
  if (!String(formData.get("description") || "").trim()) {
    formData.set("description", "Gasto en efectivo");
  }
  const result = await api("/api/transactions", {
    method: "POST",
    body: formData,
  });
  if (result.month) $("monthInput").value = result.month;
  $("cashExpenseStatus").textContent = "Gasto en efectivo guardado.";
  event.target.reset();
  $("cashExpenseDate").value = defaultDateForSelectedMonth();
  $("cashExpenseCategory").innerHTML = optionList(state.meta.expenseCategories, "Otros gastos");
  await refreshMonthlyData();
});
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
  $("cashExpenseDate").value = defaultDateForSelectedMonth();
  $("manualType").value = currentType;
  updateManualDefaults();
  await refreshMonthlyData();
});

function openAhorroEditForm(ahorro) {
  const form = $("ahorroForm");
  form.elements.id.value = ahorro.id;
  form.elements.type.value = ahorro.type;
  form.elements.name.value = ahorro.name;
  form.elements.bank.value = ahorro.bank;
  form.elements.account.value = ahorro.account;
  form.elements.initialBalance.value = ahorro.initial_balance;
  form.elements.monthlyTarget.value = ahorro.monthly_target;
  form.elements.type.disabled = (ahorro.movements || []).length > 0;
  updateAhorroFormFields();
  $("ahorroFormTitle").textContent = "Editar ahorro";
  $("ahorroSaveBtn").textContent = "Guardar cambios";
  $("ahorroCancelBtn").hidden = false;
  $("ahorroStatus").textContent = "";
  form.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetAhorroForm() {
  const form = $("ahorroForm");
  form.reset();
  form.elements.id.value = "";
  form.elements.type.disabled = false;
  updateAhorroFormFields();
  $("ahorroFormTitle").textContent = "Nuevo ahorro";
  $("ahorroSaveBtn").textContent = "Guardar";
  $("ahorroCancelBtn").hidden = true;
}

$("ahorroForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const ahorroId = form.elements.id.value;
  const data = {
    type: form.elements.type.value,
    name: form.elements.name.value,
    bank: form.elements.bank.value,
    account: form.elements.account.value,
    initialBalance: form.elements.initialBalance.value,
    monthlyTarget: form.elements.monthlyTarget.value,
  };
  $("ahorroStatus").textContent = ahorroId ? "Actualizando..." : "Guardando...";
  try {
    if (ahorroId) {
      state.ahorros = await api(`/api/ahorros/${ahorroId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      $("ahorroStatus").textContent = "Cambios guardados correctamente.";
    } else {
      state.ahorros = await api("/api/ahorros", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      $("ahorroStatus").textContent = "Ahorro guardado correctamente.";
    }
    resetAhorroForm();
    renderAhorros();
  } catch (error) {
    $("ahorroStatus").textContent = readableError(error);
  }
});

$("ahorroCancelBtn").addEventListener("click", () => {
  resetAhorroForm();
  $("ahorroStatus").textContent = "";
});

$("ahorroGrid").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-ahorro-action]");
  if (!button) return;
  const card = button.closest("[data-ahorro-id]");
  if (!card) return;
  const ahorroId = card.dataset.ahorroId;
  if (button.dataset.ahorroAction === "detail") {
    showAhorroDetail(ahorroId);
  } else if (button.dataset.ahorroAction === "movement") {
    openAhorroMovementForm(ahorroId);
  }
});

function openAhorroMovementForm(ahorroId) {
  const ahorro = (state.ahorros.ahorros || []).find((entry) => String(entry.id) === String(ahorroId));
  const isFondo = ahorro?.type === "Fondo";
  const form = $("ahorroMovementForm");
  form.reset();
  form.elements.ahorroId.value = ahorroId;
  form.elements.date.value = new Date().toISOString().slice(0, 10);
  form.elements.description.value = isFondo ? "Aporte mensual a fondo" : "";
  $("ahorroMovementDirectionField").hidden = isFondo;
  $("ahorroMovementTitle").textContent = isFondo ? "Registrar aporte" : "Registrar movimiento";
  state.ahorroMovementAhorroId = ahorroId;
  openModal("ahorroMovementModal");
}

$("ahorroMovementForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const ahorroId = form.elements.ahorroId.value;
  state.ahorros = await api(`/api/ahorros/${ahorroId}/movements`, {
    method: "POST",
    body: new FormData(form),
  });
  closeModals();
  renderAhorros();
  if (state.ahorroDetailAhorroId === ahorroId) {
    showAhorroDetail(ahorroId);
  }
});

function showAhorroDetail(ahorroId) {
  const ahorro = (state.ahorros.ahorros || []).find((entry) => String(entry.id) === String(ahorroId));
  if (!ahorro) return;
  state.ahorroDetailAhorroId = ahorroId;
  const isFondo = ahorro.type === "Fondo";
  $("ahorroDetail").innerHTML = `
    <div class="detail-hero">
      <div class="detail-hero-amount">${escapeHtml(fmtMoney.format(ahorro.current_balance))}</div>
      <p class="detail-hero-desc">${escapeHtml(ahorro.name)}</p>
    </div>
    <div class="detail-list">
      ${detailItem("Tipo", `<span class="detail-tag">${escapeHtml(isFondo ? "Fondo" : "Ahorro")}</span>`)}
      ${detailItem("Banco", escapeHtml(ahorro.bank))}
      ${detailItem("Cuenta", escapeHtml(ahorro.account))}
      ${detailItem("Saldo inicial", escapeHtml(fmtMoney.format(ahorro.initial_balance)))}
      ${isFondo && ahorro.monthly_target ? detailItem("Aporte mensual esperado", escapeHtml(fmtMoney.format(ahorro.monthly_target))) : ""}
    </div>`;
  renderAhorroDetailMovements(ahorro);
  openModal("ahorroDetailModal");
}

function renderAhorroDetailMovements(ahorro) {
  const movements = ahorro.movements || [];
  $("ahorroDetailMovementsCount").textContent = movements.length
    ? `${movements.length} movimiento${movements.length === 1 ? "" : "s"} registrado${movements.length === 1 ? "" : "s"}.`
    : "Sin movimientos registrados.";
  $("ahorroDetailMovementsBody").innerHTML = movements.length
    ? movements
        .map(
          (tx) => `
          <tr data-id="${tx.id}">
            <td>${escapeHtml(tx.date)}</td>
            <td>${escapeHtml(ahorroMovementLabel(tx.type))}</td>
            <td class="description">${escapeHtml(tx.description)}</td>
            <td class="money ${amountClassForType(tx.type)}">${fmtMoney.format(tx.amount)}</td>
            <td class="actions-cell">
              <button class="table-action success-text" type="button" data-savings-action="view">Ver</button>
              ${
                tx.attachment_path
                  ? `<button class="table-action success-text" type="button" data-savings-action="view-attachment" data-attachment-name="${escapeHtml(tx.attachment_name || "Boleta")}" data-attachment-mime="${escapeHtml(tx.attachment_mime || "")}">Ver boleta</button>`
                  : ""
              }
              <button class="table-action danger-text" type="button" data-savings-action="delete">Eliminar</button>
            </td>
          </tr>`,
        )
        .join("")
    : `<tr><td class="empty" colspan="5">Aun no hay movimientos registrados.</td></tr>`;
}

$("ahorroDetailMovementsBody").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-savings-action]");
  if (!button) return;
  const transactionId = button.closest("tr").dataset.id;
  if (button.dataset.savingsAction === "view") {
    await showTransactionDetail(transactionId);
  } else if (button.dataset.savingsAction === "view-attachment") {
    showTransactionAttachment(
      transactionId,
      button.dataset.attachmentName || "Boleta adjunta",
      button.dataset.attachmentMime || "",
    );
  } else if (button.dataset.savingsAction === "delete") {
    await askDeleteTransaction(transactionId);
  }
});

$("ahorroDetailMovementBtn").addEventListener("click", () => {
  const ahorroId = state.ahorroDetailAhorroId;
  if (!ahorroId) return;
  closeModals();
  openAhorroMovementForm(ahorroId);
});

$("ahorroDetailEditBtn").addEventListener("click", () => {
  const ahorroId = state.ahorroDetailAhorroId;
  const ahorro = (state.ahorros.ahorros || []).find((entry) => String(entry.id) === String(ahorroId));
  if (!ahorro) return;
  closeModals();
  openAhorroEditForm(ahorro);
});

$("ahorroDetailDeleteBtn").addEventListener("click", async () => {
  const ahorroId = state.ahorroDetailAhorroId;
  if (!ahorroId) return;
  closeModals();
  await api(`/api/ahorros/${ahorroId}`, { method: "DELETE" });
  await loadAhorros();
});

$("clearImportsBtn").addEventListener("click", async () => {
  await clearImportDraft("Bandeja limpia.");
});

$("cancelImportBtn").addEventListener("click", async () => {
  await clearImportDraft();
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
$("ahorroSearch").addEventListener("input", renderAhorros);
$("savingSaleSearch").addEventListener("input", renderSavingSales);
$("weddingSearch").addEventListener("input", renderWedding);
$("houseSearch").addEventListener("input", renderHouse);
$("exportReportExcelBtn").addEventListener("click", () => exportReport("xlsx"));
$("exportReportPdfBtn").addEventListener("click", () => exportReport("pdf"));
$("exportWeddingCsvBtn").addEventListener("click", () => {
  const link = document.createElement("a");
  link.href = "/api/wedding/export";
  link.download = `gastos-boda-${new Date().toISOString().slice(0, 10)}.xlsx`;
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
});

function downloadExport(path, filenamePrefix) {
  const month = $("monthInput").value || new Date().toISOString().slice(0, 7);
  const link = document.createElement("a");
  link.href = `${path}?month=${encodeURIComponent(month)}`;
  link.download = `${filenamePrefix}-${month}.xlsx`;
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

$("exportTransactionsBtn").addEventListener("click", () => downloadExport("/api/transactions/export", "movimientos"));
$("exportSavingsBtn").addEventListener("click", () => downloadExport("/api/ahorros/export", "ahorros"));
$("exportSalesBtn").addEventListener("click", () => downloadExport("/api/sales/export", "ventas-usd"));
$("exportHouseBtn").addEventListener("click", () => downloadExport("/api/house/export", "pago-casa"));

$("savingSaleBody").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-saving-action]");
  if (!button) return;
  const transactionId = button.closest("tr").dataset.id;
  if (button.dataset.savingAction === "view") {
    await showTransactionDetail(transactionId);
  } else if (button.dataset.savingAction === "edit") {
    await showEditTransaction(transactionId);
  } else if (button.dataset.savingAction === "view-attachment") {
    showTransactionAttachment(
      transactionId,
      button.dataset.attachmentName || "Boleta adjunta",
      button.dataset.attachmentMime || "",
    );
  } else if (button.dataset.savingAction === "attach") {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pdf,.png,.jpg,.jpeg,.jfif,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif,application/pdf,image/*";
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file) return;
      const payload = new FormData();
      payload.append("attachment", file);
      await api(`/api/transactions/${transactionId}/attachment`, {
        method: "POST",
        body: payload,
      });
      await refreshMonthlyData();
    });
    input.click();
  } else if (button.dataset.savingAction === "delete") {
    await askDeleteTransaction(transactionId);
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
  await loadReports();
});

function resetWeddingExpenseForm() {
  const form = $("weddingExpenseForm");
  form.reset();
  form.elements.id.value = "";
  setWeddingDefaultDates();
  $("weddingFormTitle").textContent = "Registrar gasto de boda";
  $("weddingSaveBtn").textContent = "Guardar gasto";
  $("weddingCancelBtn").hidden = true;
  $("weddingInitialPaymentField").hidden = false;
  $("weddingPaymentDateField").hidden = false;
  $("weddingInitialPaymentAttachmentField").hidden = false;
}

$("weddingExpenseForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const expenseId = form.elements.id.value;
  $("weddingStatus").textContent = expenseId ? "Actualizando gasto..." : "Guardando gasto...";
  try {
    if (expenseId) {
      const data = {
        description: form.elements.description.value,
        category: form.elements.category.value,
        date: form.elements.date.value,
        amount: form.elements.amount.value,
        vendor: form.elements.vendor.value,
      };
      state.wedding = await api(`/api/wedding/expenses/${expenseId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      $("weddingStatus").textContent = "Cambios guardados correctamente.";
    } else {
      state.wedding = await api("/api/wedding/expenses", {
        method: "POST",
        body: new FormData(form),
      });
      $("weddingStatus").textContent = "Gasto guardado correctamente.";
    }
    resetWeddingExpenseForm();
    renderWedding();
    await loadReports();
  } catch (error) {
    $("weddingStatus").textContent = readableError(error);
  }
});

$("weddingCancelBtn").addEventListener("click", () => {
  resetWeddingExpenseForm();
  $("weddingStatus").textContent = "";
});

$("housePaymentForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  $("houseStatus").textContent = "Guardando pago...";
  try {
    state.house = await api("/api/house/payments", {
      method: "POST",
      body: new FormData(form),
    });
    $("monthInput").value = form.elements.paymentDate.value.slice(0, 7);
    form.reset();
    setHouseDefaultDate();
    $("houseStatus").textContent = "Pago guardado correctamente.";
    renderHouse();
    await loadReports();
  } catch (error) {
    $("houseStatus").textContent = readableError(error);
  }
});

$("weddingExpensesBody").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-wedding-action]");
  if (!button) return;
  const row = button.closest("tr[data-wedding-expense-id]");
  if (!row) return;
  const expenseId = row.dataset.weddingExpenseId;
  if (button.dataset.weddingAction === "view-receipts") {
    openWeddingReceipts(expenseId);
  } else if (button.dataset.weddingAction === "document") {
    const expense = (state.wedding.expenses || []).find((entry) => String(entry.id) === String(expenseId));
    if (!expense) return;
    if (expense.has_attachment) {
      showWeddingAttachment(expenseId, expense.attachment_name || "Documento adjunto", expense.attachment_mime || "");
    } else {
      openWeddingAttachmentForm(expenseId);
    }
  } else if (button.dataset.weddingAction === "detail") {
    showWeddingExpenseDetail(expenseId);
  }
});

function openWeddingReceipts(expenseId) {
  const expense = (state.wedding.expenses || []).find((entry) => String(entry.id) === String(expenseId));
  state.weddingPaymentExpenseId = expenseId;
  renderWeddingPaymentHistory(expenseId);
  $("weddingReceiptsAddBtn").hidden = !(expense && Number(expense.pending_amount) > 0);
  openModal("weddingReceiptsModal");
}

function openWeddingPaymentForm(expenseId) {
  const form = $("weddingPaymentForm");
  form.reset();
  form.elements.expenseId.value = expenseId;
  form.elements.date.value = new Date().toISOString().slice(0, 10);
  state.weddingPaymentExpenseId = expenseId;
  openModal("weddingPaymentModal");
}

function openWeddingAttachmentForm(expenseId) {
  const form = $("weddingAttachmentForm");
  form.reset();
  $("weddingAttachmentStatus").textContent = "";
  state.weddingAttachmentExpenseId = expenseId;
  state.weddingAttachmentPaymentId = null;
  form.elements.expenseId.value = expenseId;
  openModal("weddingAttachmentModal");
}

function openWeddingEditForm(expense) {
  const form = $("weddingExpenseForm");
  form.elements.id.value = expense.id;
  form.elements.description.value = expense.description;
  form.elements.category.value = expense.category;
  form.elements.date.value = expense.date;
  form.elements.amount.value = expense.amount;
  form.elements.vendor.value = expense.vendor || "";
  $("weddingInitialPaymentField").hidden = true;
  $("weddingPaymentDateField").hidden = true;
  $("weddingInitialPaymentAttachmentField").hidden = true;
  $("weddingFormTitle").textContent = "Editar gasto de boda";
  $("weddingSaveBtn").textContent = "Guardar cambios";
  $("weddingCancelBtn").hidden = false;
  $("weddingStatus").textContent = "";
  form.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function deleteWeddingExpense(expenseId) {
  await api(`/api/wedding/expenses/${expenseId}`, { method: "DELETE" });
  await loadWedding();
  await loadReports();
}

function showWeddingExpenseDetail(expenseId) {
  const expense = (state.wedding.expenses || []).find((entry) => String(entry.id) === String(expenseId));
  if (!expense) return;
  state.weddingDetailExpenseId = expenseId;
  $("weddingExpenseDetail").innerHTML = `
    <div class="detail-hero">
      <span class="pill ${statusClass(expense.status)}">${escapeHtml(expense.status)}</span>
      <div class="detail-hero-amount">${escapeHtml(fmtMoney.format(expense.amount))}</div>
      <p class="detail-hero-desc">${escapeHtml(expense.description)}</p>
    </div>
    <div class="detail-list">
      ${detailItem("Vencimiento", escapeHtml(formatDisplayDate(expense.date)))}
      ${detailItem("Categoria", `<span class="detail-tag">${escapeHtml(expense.category)}</span>`)}
      ${detailItem("Proveedor", escapeHtml(expense.vendor || "-"))}
      ${detailItem("Total", escapeHtml(fmtMoney.format(expense.amount)))}
      ${detailItem("Abonado", escapeHtml(fmtMoney.format(expense.paid_amount)))}
      ${detailItem("Pendiente", escapeHtml(fmtMoney.format(expense.pending_amount)))}
    </div>`;
  openModal("weddingExpenseDetailModal");
}

$("weddingReceiptsAddBtn").addEventListener("click", () => {
  const expenseId = state.weddingPaymentExpenseId;
  if (!expenseId) return;
  closeModals();
  openWeddingPaymentForm(expenseId);
});

$("weddingDetailEditBtn").addEventListener("click", () => {
  const expenseId = state.weddingDetailExpenseId;
  const expense = (state.wedding.expenses || []).find((entry) => String(entry.id) === String(expenseId));
  if (!expense) return;
  closeModals();
  openWeddingEditForm(expense);
});

$("weddingDetailDeleteBtn").addEventListener("click", async () => {
  const expenseId = state.weddingDetailExpenseId;
  if (!expenseId) return;
  closeModals();
  await deleteWeddingExpense(expenseId);
});

$("debtType").addEventListener("change", updateDebtFormFields);
$("ahorroType").addEventListener("change", updateAhorroFormFields);

$("debtGrid").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-debt-action]");
  if (!button) return;
  const card = button.closest("[data-debt-id]");
  if (!card) return;
  const debtId = card.dataset.debtId;
  if (button.dataset.debtAction === "detail") {
    showDebtDetail(debtId);
  } else if (button.dataset.debtAction === "pay") {
    openDebtPaymentForm(debtId);
  } else if (button.dataset.debtAction === "import") {
    openDebtImport(debtId);
  }
});

function openDebtImport(debtId) {
  const debt = (state.debts.debts || []).find((item) => String(item.id) === String(debtId));
  state.importDebtId = debtId;
  $("debtImportTitle").textContent = debt ? `Importar estado de cuenta · ${debt.name}` : "Importar estado de cuenta";
  $("importForm").reset();
  $("importExchangeRate").value = "7.8000";
  $("accountSelect").innerHTML = optionList(state.meta.accounts, "GYT - Cuenta ahorro sueldo");
  $("importStatus").textContent = "";
  syncSelectedFileName();
  // Pre-selecciona el banco de la tarjeta si coincide con las opciones del importador.
  if (debt && $("bankSelect")) {
    const options = [...$("bankSelect").options].map((opt) => opt.value);
    if (options.includes(debt.bank)) {
      $("bankSelect").value = debt.bank;
      updateImportAccountForBank();
    }
  }
  loadImports();
  loadDebtCardTransactions(debtId);
  openModal("debtImportModal");
}

async function loadDebtCardTransactions(debtId) {
  try {
    const rows = await api(`/api/debts/${debtId}/transactions`);
    state.debtImportTransactions = rows;
    renderDebtCardTransactions();
  } catch (error) {
    console.error(error);
    state.debtImportTransactions = [];
    renderDebtCardTransactions();
  }
}

function renderDebtCardTransactions() {
  const rows = state.debtImportTransactions || [];
  const count = $("debtImportTxCount");
  if (count) {
    count.textContent = rows.length
      ? `${rows.length} gasto${rows.length === 1 ? "" : "s"} registrado${rows.length === 1 ? "" : "s"} en esta tarjeta.`
      : "Sin gastos registrados en esta tarjeta.";
  }
  const body = $("debtImportTxBody");
  if (!body) return;
  body.innerHTML = rows.length
    ? rows
        .map(
          (row) => `
          <tr data-transaction-id="${row.id}">
            <td>${escapeHtml(row.date)}</td>
            <td class="description">${escapeHtml(row.description)}</td>
            <td>${escapeHtml(row.category)}</td>
            <td class="money ${amountClassForType(row.type)}">${fmtMoney.format(row.amount)}</td>
            <td class="actions-cell">
              <button class="table-action danger-text" type="button" data-action="delete-debt-tx">Eliminar registro</button>
            </td>
          </tr>`,
        )
        .join("")
    : `<tr><td class="empty" colspan="5">Aun no hay gastos registrados para esta tarjeta.</td></tr>`;
}

$("debtImportTxBody").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action='delete-debt-tx']");
  if (!button) return;
  const transactionId = button.closest("tr").dataset.transactionId;
  await askDeleteTransaction(transactionId);
});

function openDebtPaymentForm(debtId) {
  const form = $("debtPaymentForm");
  form.reset();
  form.elements.debtId.value = debtId;
  form.elements.date.value = new Date().toISOString().slice(0, 10);
  $("debtPaymentAccount").innerHTML = optionList(state.debts.accounts || [], (state.debts.accounts || [])[0]);
  state.debtPaymentDebtId = debtId;
  openModal("debtPaymentModal");
}

function openDebtReceipts(debtId) {
  state.debtPaymentDebtId = debtId;
  renderDebtPaymentHistory(debtId);
  openModal("debtReceiptsModal");
}

function openDebtAttachmentForm(paymentId) {
  const form = $("debtAttachmentForm");
  form.reset();
  $("debtAttachmentStatus").textContent = "";
  state.debtAttachmentPaymentId = paymentId;
  openModal("debtAttachmentModal");
}

function openDebtEditForm(debt) {
  const form = $("debtForm");
  form.elements.id.value = debt.id;
  form.elements.type.value = debt.type;
  form.elements.name.value = debt.name;
  form.elements.bank.value = debt.bank ?? "";
  form.elements.creditLimit.value = debt.credit_limit ?? "";
  form.elements.creditLimitUsd.value = debt.credit_limit_usd ?? "";
  form.elements.originalAmount.value = debt.original_amount ?? "";
  form.elements.interestRate.value = debt.interest_rate ?? "";
  form.elements.statementDay.value = debt.statement_day ?? "";
  form.elements.dueDay.value = debt.due_day ?? "";
  form.elements.monthlyPayment.value = debt.monthly_payment ?? "";
  form.elements.startDate.value = debt.start_date ?? "";
  form.elements.endDate.value = debt.end_date ?? "";
  updateDebtFormFields();
  $("debtFormTitle").textContent = "Editar registro";
  $("debtSaveBtn").textContent = "Guardar cambios";
  $("debtCancelBtn").hidden = false;
  $("debtStatus").textContent = "";
  form.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetDebtForm() {
  const form = $("debtForm");
  form.reset();
  form.elements.id.value = "";
  updateDebtFormFields();
  $("debtFormTitle").textContent = "Nuevo registro";
  $("debtSaveBtn").textContent = "Guardar";
  $("debtCancelBtn").hidden = true;
}

async function deleteDebt(debtId) {
  await api(`/api/debts/${debtId}`, { method: "DELETE" });
  await loadDebts();
}

function showDebtDetail(debtId) {
  const debt = (state.debts.debts || []).find((entry) => String(entry.id) === String(debtId));
  if (!debt) return;
  state.debtDetailDebtId = debtId;
  const isCard = debt.type === "Tarjeta de credito";
  const isLoan = debt.type === "Prestamo";
  const typeLabel = isCard ? "Tarjeta de credito" : isLoan ? "Prestamo" : "Otro pago";
  const amountLabel = debt.is_other ? "Monto a pagar" : "Monto original";
  const due = debtDueInfo(debt);
  const rows = [detailItem("Tipo", `<span class="detail-tag">${escapeHtml(typeLabel)}</span>`)];
  if (debt.bank) rows.push(detailItem("Banco", escapeHtml(debt.bank)));
  rows.push(detailItem("Saldo actual", escapeHtml(fmtMoney.format(debt.current_balance))));
  if (isCard) {
    if (debt.balance_usd) {
      rows.push(
        detailItem(
          "Saldo en USD",
          `${escapeHtml(fmtUsd.format(debt.balance_usd))} <span class="muted-inline">(&asymp; ${escapeHtml(fmtMoney.format(debt.balance_usd * currentUsdRate()))})</span>`,
        ),
      );
    }
    if (debt.credit_limit) rows.push(detailItem("Limite de credito", escapeHtml(fmtMoney.format(debt.credit_limit))));
    if (debt.credit_limit_usd) rows.push(detailItem("Limite de credito $", escapeHtml(fmtUsd.format(debt.credit_limit_usd))));
    if (debt.available !== null) rows.push(detailItem("Disponible", escapeHtml(fmtMoney.format(debt.available))));
    if (debt.available_usd !== null) rows.push(detailItem("Disponible USD", escapeHtml(fmtUsd.format(debt.available_usd))));
    if (debt.statement_day) rows.push(detailItem("Dia de corte", String(debt.statement_day)));
  } else {
    if (debt.original_amount) rows.push(detailItem(amountLabel, escapeHtml(fmtMoney.format(debt.original_amount))));
    if (isLoan && debt.monthly_payment) rows.push(detailItem("Cuota mensual", escapeHtml(fmtMoney.format(debt.monthly_payment))));
    if (isLoan && debt.start_date) rows.push(detailItem("Fecha inicio", escapeHtml(formatDisplayDate(debt.start_date))));
  }
  if (debt.interest_rate) rows.push(detailItem("Tasa anual", `${debt.interest_rate}%`));
  rows.push(detailItem("Proximo pago", escapeHtml(due.label)));
  $("debtDetail").innerHTML = `
    <div class="detail-hero">
      <span class="pill ${isCard ? "partial" : "pending"}">${escapeHtml(typeLabel)}</span>
      <div class="detail-hero-amount">${escapeHtml(fmtMoney.format(debt.current_balance))}</div>
      <p class="detail-hero-desc">${escapeHtml(debt.name)}</p>
    </div>
    <div class="detail-list">${rows.join("")}</div>`;
  openModal("debtDetailModal");
}

$("debtPaymentHistory").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-debt-payment-action]");
  if (!button) return;
  const row = button.closest("div[data-debt-payment-id]");
  if (!row) return;
  const paymentId = row.dataset.debtPaymentId;
  if (button.dataset.debtPaymentAction === "view-attachment") {
    showDebtPaymentAttachment(
      paymentId,
      button.dataset.attachmentName || "Boleta",
      button.dataset.attachmentMime || "",
    );
  } else if (button.dataset.debtPaymentAction === "attachment") {
    openDebtAttachmentForm(paymentId);
  }
});

function showDebtPaymentAttachment(paymentId, name, mime) {
  const url = `/api/debts/payments/${paymentId}/attachment`;
  $("weddingAttachmentViewTitle").textContent = name || "Documento adjunto";
  $("weddingAttachmentOpenLink").href = url;
  $("weddingAttachmentViewer").innerHTML = mime.startsWith("image/")
    ? `<img src="${url}" alt="${escapeHtml(name || "Documento adjunto")}" />`
    : `<iframe src="${url}" title="${escapeHtml(name || "Documento adjunto")}"></iframe>`;
  state.weddingAttachmentViewerExpenseId = null;
  $("weddingAttachmentViewChangeBtn").hidden = true;
  openModal("weddingAttachmentViewModal");
}

$("debtReceiptsAddBtn").addEventListener("click", () => {
  const debtId = state.debtPaymentDebtId;
  if (!debtId) return;
  closeModals();
  openDebtPaymentForm(debtId);
});

$("debtDetailReceiptsBtn").addEventListener("click", () => {
  const debtId = state.debtDetailDebtId;
  if (!debtId) return;
  closeModals();
  openDebtReceipts(debtId);
});

$("debtDetailEditBtn").addEventListener("click", () => {
  const debtId = state.debtDetailDebtId;
  const debt = (state.debts.debts || []).find((entry) => String(entry.id) === String(debtId));
  if (!debt) return;
  closeModals();
  openDebtEditForm(debt);
});

$("debtDetailDeleteBtn").addEventListener("click", async () => {
  const debtId = state.debtDetailDebtId;
  if (!debtId) return;
  closeModals();
  await deleteDebt(debtId);
});

$("debtForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const debtId = form.elements.id.value;
  const data = {
    type: form.elements.type.value,
    name: form.elements.name.value,
    bank: form.elements.bank.value,
    creditLimit: form.elements.creditLimit.value,
    creditLimitUsd: form.elements.creditLimitUsd.value,
    originalAmount: form.elements.originalAmount.value,
    interestRate: form.elements.interestRate.value,
    statementDay: form.elements.statementDay.value,
    dueDay: form.elements.dueDay.value,
    monthlyPayment: form.elements.monthlyPayment.value,
    startDate: form.elements.startDate.value,
    endDate: form.elements.endDate.value,
  };
  $("debtStatus").textContent = debtId ? "Actualizando..." : "Guardando...";
  try {
    if (debtId) {
      state.debts = await api(`/api/debts/${debtId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      $("debtStatus").textContent = "Cambios guardados correctamente.";
    } else {
      state.debts = await api("/api/debts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      $("debtStatus").textContent = "Deuda guardada correctamente.";
    }
    resetDebtForm();
    renderDebts();
  } catch (error) {
    $("debtStatus").textContent = readableError(error);
  }
});

$("debtCancelBtn").addEventListener("click", () => {
  resetDebtForm();
  $("debtStatus").textContent = "";
});

$("debtPaymentForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const debtId = form.elements.debtId.value;
  state.debts = await api(`/api/debts/${debtId}/payments`, {
    method: "POST",
    body: new FormData(form),
  });
  closeModals();
  renderDebts();
  await refreshMonthlyData();
});

$("debtAttachmentForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const paymentId = state.debtAttachmentPaymentId;
  const file = form.elements.attachment.files[0];
  if (!file) return;
  $("debtAttachmentStatus").textContent = "Guardando archivo...";
  try {
    state.debts = await api(`/api/debts/payments/${paymentId}/attachment`, {
      method: "POST",
      body: new FormData(form),
    });
    $("debtAttachmentStatus").textContent = "";
    closeModals();
    renderDebts();
  } catch (error) {
    $("debtAttachmentStatus").textContent = readableError(error);
  }
});

$("debtSearch").addEventListener("input", renderDebts);

$("exportDebtsBtn").addEventListener("click", () => {
  const link = document.createElement("a");
  link.href = "/api/debts/export";
  link.download = `deudas-${new Date().toISOString().slice(0, 10)}.xlsx`;
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
});

$("weddingAttachmentForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const file = form.elements.attachment.files[0];
  if (!file) return;
  $("weddingAttachmentStatus").textContent = "Guardando archivo...";
  try {
    if (state.weddingAttachmentPaymentId) {
      const paymentId = state.weddingAttachmentPaymentId;
      state.wedding = await api(`/api/wedding/payments/${paymentId}/attachment`, {
        method: "POST",
        body: new FormData(form),
      });
      $("weddingAttachmentStatus").textContent = "";
      $("weddingAttachmentModal").hidden = true;
      state.weddingAttachmentPaymentId = null;
      renderWeddingPaymentHistory(state.weddingPaymentExpenseId);
      renderWedding();
    } else {
      const expenseId = form.elements.expenseId.value || state.weddingAttachmentExpenseId;
      state.wedding = await api(`/api/wedding/expenses/${expenseId}/attachment`, {
        method: "POST",
        body: new FormData(form),
      });
      $("weddingAttachmentStatus").textContent = "";
      closeModals();
      renderWedding();
    }
  } catch (error) {
    $("weddingAttachmentStatus").textContent = readableError(error);
  }
});

$("weddingPaymentHistory").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-payment-action]");
  if (!button) return;
  const row = button.closest("div[data-wedding-payment-id]");
  if (!row) return;
  const paymentId = row.dataset.weddingPaymentId;
  if (button.dataset.paymentAction === "view-attachment") {
    showWeddingPaymentAttachment(
      paymentId,
      button.dataset.attachmentName || "Boleta",
      button.dataset.attachmentMime || "",
    );
  } else if (button.dataset.paymentAction === "attachment") {
    const form = $("weddingAttachmentForm");
    form.reset();
    $("weddingAttachmentStatus").textContent = "";
    state.weddingAttachmentExpenseId = null;
    state.weddingAttachmentPaymentId = paymentId;
    openModal("weddingAttachmentModal");
  }
});

$("housePaymentsBody").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-house-action]");
  if (!button) return;
  const row = button.closest("tr[data-house-payment-id]");
  if (!row) return;
  const paymentId = row.dataset.housePaymentId;
  if (button.dataset.houseAction === "view-attachment") {
    showHouseAttachment(
      paymentId,
      button.dataset.attachmentName || "Documento adjunto",
      button.dataset.attachmentMime || "",
    );
  } else if (button.dataset.houseAction === "attachment") {
    const form = $("houseAttachmentForm");
    form.reset();
    $("houseAttachmentStatus").textContent = "";
    state.houseAttachmentPaymentId = paymentId;
    form.elements.paymentId.value = paymentId;
    openModal("houseAttachmentModal");
  } else if (button.dataset.houseAction === "delete") {
    await api(`/api/house/payments/${paymentId}`, { method: "DELETE" });
    await loadHouse();
    await loadReports();
  }
});

$("houseAttachmentForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const paymentId = form.elements.paymentId.value || state.houseAttachmentPaymentId;
  const file = form.elements.attachment.files[0];
  if (!file) return;
  $("houseAttachmentStatus").textContent = "Guardando archivo...";
  try {
    state.house = await api(`/api/house/payments/${paymentId}/attachment`, {
      method: "POST",
      body: new FormData(form),
    });
    $("houseAttachmentStatus").textContent = "";
    closeModals();
    renderHouse();
  } catch (error) {
    $("houseAttachmentStatus").textContent = readableError(error);
  }
});

$("weddingPaymentForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const expenseId = form.elements.expenseId.value;
  state.wedding = await api(`/api/wedding/expenses/${expenseId}/payments`, {
    method: "POST",
    body: new FormData(form),
  });
  closeModals();
  renderWedding();
  await loadReports();
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
  await refreshMonthlyData();
});

$("confirmDeleteBtn").addEventListener("click", async () => {
  const debtImportId = state.importDebtId;
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
  if (debtImportId) {
    // Borrar un gasto desde "Importar estado de cuenta" no debe cerrar ese modal.
    $("deleteTransactionModal").hidden = true;
    state.deleteTransactionId = null;
    state.deleteTransactionIds = [];
    await loadDebtCardTransactions(debtImportId);
    await loadDebts();
  } else {
    closeModals();
    await refreshMonthlyData();
  }
});

function closeAttachmentViewer() {
  $("weddingAttachmentViewModal").hidden = true;
  $("weddingAttachmentViewer").innerHTML = "";
}

$("weddingAttachmentViewChangeBtn").addEventListener("click", () => {
  const expenseId = state.weddingAttachmentViewerExpenseId;
  if (!expenseId) return;
  closeAttachmentViewer();
  openWeddingAttachmentForm(expenseId);
});

document.querySelectorAll("[data-close-modal]").forEach((element) => {
  if (element.closest("#weddingAttachmentViewModal")) {
    element.addEventListener("click", closeAttachmentViewer);
  } else if (element.closest("#deleteTransactionModal")) {
    element.addEventListener("click", () => {
      if (state.importDebtId) {
        // Cancelar el borrado desde "Importar estado de cuenta" no debe cerrar ese modal.
        $("deleteTransactionModal").hidden = true;
        state.deleteTransactionId = null;
        state.deleteTransactionIds = [];
      } else {
        closeModals();
      }
    });
  } else {
    element.addEventListener("click", closeModals);
  }
});

$("monthInput").addEventListener("change", () => {
  $("manualForm").elements.date.value = defaultDateForSelectedMonth();
  $("cashExpenseDate").value = defaultDateForSelectedMonth();
  setHouseDefaultDate();
  refreshMonthlyData();
  loadHouse();
  loadReports();
});

boot().catch((error) => {
  console.error(error);
  $("importStatus").textContent = "No se pudo cargar la app local.";
});




