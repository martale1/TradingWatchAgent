import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, Bot, LineChart, MessageSquare, Newspaper, PauseCircle, PlayCircle, RefreshCw, Send, TrendingDown, TrendingUp, Wallet, X } from "lucide-react";
import "./styles.css";

const API = "http://127.0.0.1:8000";
const EURO = "\u20ac";

function eur(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/d";
  return `${Number(value).toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${EURO}`;
}

function pct(value, signed = true) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/d";
  const sign = signed && Number(value) > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(2)}%`;
}

function price(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/d";
  return Number(value).toLocaleString("it-IT", { maximumFractionDigits: 4 });
}

function quotedPrice(value, currency = "") {
  const formatted = price(value);
  return formatted === "n/d" || !currency ? formatted : `${formatted} ${currency}`;
}

function dateOnly(value) {
  if (!value) return "data non disponibile";
  const parts = String(value).slice(0, 10).split("-");
  return parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : String(value);
}

function numeric(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function parseLevel(value) {
  if (!value) return null;
  const cleaned = String(value).replace(",", ".").replace(/[^\d.-]/g, "");
  const n = Number(cleaned);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function levelsFromCondition(condition = "") {
  const text = cleanText(condition).toLowerCase();
  const number = "([0-9]+(?:[,.][0-9]+)?)";
  const unit = "\\s*(?:eur|euro|gbp|p|\\u20ac)?";
  const triggerPatterns = [
    new RegExp(`(?:chiusura\\s+)?(?:sopra|oltre|superamento|breakout)\\s*(?:a|di)?${unit}${number}`, "i"),
    new RegExp(`(?:ingresso|trigger)\\s*(?:solo\\s+)?(?:su|a|sopra|oltre)?\\s*(?:chiusura\\s+)?(?:sopra|oltre)?${unit}${number}`, "i"),
  ];
  const supportPatterns = [
    new RegExp(`(?:supporto|stop|invalidazione)\\s*(?:a|di|del|sotto)?${unit}${number}`, "i"),
    new RegExp(`(?:mantenendo|tenuta\\s+(?:del\\s+)?supporto|tenuta)\\s*(?:a|di)?${unit}${number}`, "i"),
    new RegExp(`(?:sotto|perdita\\s+di)${unit}${number}`, "i"),
  ];

  function firstMatch(patterns) {
    for (const pattern of patterns) {
      const match = text.match(pattern);
      const level = parseLevel(match?.[1]);
      if (level) return level;
    }
    return null;
  }

  return {
    trigger: firstMatch(triggerPatterns),
    support: firstMatch(supportPatterns),
  };
}

function cleanText(value) {
  return String(value || "")
    .replaceAll("Ã¢â€šÂ¬", EURO)
    .replaceAll("â‚¬", EURO)
    .replaceAll("Ã¨", "e")
    .replaceAll("Ã©", "e")
    .replaceAll("Ã ", "a")
    .replaceAll("Ã²", "o")
    .replaceAll("Ã¹", "u")
    .replaceAll("Ã¬", "i")
    .replaceAll("Â°", "deg");
}

function compactErrorMessage(value) {
  const text = cleanText(value);
  const maxChars = 260;
  const firstUsefulLine = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith("[agent]") && !line.startsWith("[chart-tool]"));
  const base = firstUsefulLine || text;
  if (base.length <= maxChars) return base;
  return `${base.slice(0, maxChars).trim()}...`;
}

function renderInline(text) {
  const parts = cleanText(text).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

function MarkdownMessage({ content }) {
  const lines = cleanText(content).split(/\r?\n/);
  const elements = [];
  let listItems = [];

  function flushList() {
    if (!listItems.length) return;
    elements.push(
      <ul key={`ul-${elements.length}`} className="markdownList">
        {listItems.map((item, index) => <li key={index}>{renderInline(item)}</li>)}
      </ul>
    );
    listItems = [];
  }

  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      return;
    }
    const bullet = trimmed.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      listItems.push(bullet[1]);
      return;
    }
    flushList();
    if (trimmed.startsWith("### ")) {
      elements.push(<h4 key={index}>{renderInline(trimmed.slice(4))}</h4>);
    } else if (trimmed.startsWith("## ")) {
      elements.push(<h3 key={index}>{renderInline(trimmed.slice(3))}</h3>);
    } else if (trimmed.match(/^\d+\.\s+/)) {
      elements.push(<p key={index} className="numberedLine">{renderInline(trimmed)}</p>);
    } else {
      elements.push(<p key={index}>{renderInline(trimmed)}</p>);
    }
  });
  flushList();
  return <div className="markdownMessage">{elements}</div>;
}

function dateTime(value) {
  if (!value) return "n/d";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function yfinanceReadTime(value) {
  if (!value) return "non letta";
  return dateTime(value);
}

function shortDate(value) {
  const parts = String(value || "").split("-");
  if (parts.length < 3) return String(value || "");
  return `${parts[2]}/${parts[1]}`;
}

function signedClass(value) {
  const n = Number(value);
  if (n > 0) return "positive";
  if (n < 0) return "negative";
  return "neutral";
}

const SCENARIO_PRIORITY = {
  BUY_CANDIDATE: 50,
  TRIGGER_MET: 45,
  CONFIRMED: 40,
  CONFIRMING: 35,
  NEAR_TRIGGER: 25,
  WAIT: 10,
};

const STATUS_PRIORITY = {
  met: 30,
  waiting: 20,
  invalidated: 5,
};

function conditionPriority(item) {
  const scenario = String(item?.scenario_state || "").toUpperCase();
  const status = String(item?.status || "").toLowerCase();
  const updated = Date.parse(item?.updated_at || item?.created_at || "") || 0;
  return [
    SCENARIO_PRIORITY[scenario] || 0,
    STATUS_PRIORITY[status] || 0,
    updated,
  ];
}

function compareConditionPriority(a, b) {
  const pa = conditionPriority(a);
  const pb = conditionPriority(b);
  for (let index = 0; index < pa.length; index += 1) {
    if (pa[index] !== pb[index]) return pa[index] - pb[index];
  }
  return 0;
}

function uniqueConditionsByTicker(rows = []) {
  const best = new Map();
  rows.forEach((item) => {
    const ticker = String(item?.ticker || "").trim().toUpperCase();
    if (!ticker) return;
    const current = best.get(ticker);
    if (!current || compareConditionPriority(item, current) > 0) {
      best.set(ticker, item);
    }
  });
  return Array.from(best.values());
}

async function api(path, options = {}) {
  const { timeoutMs = 30000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    signal: controller.signal,
    ...fetchOptions,
  }).finally(() => window.clearTimeout(timeout));
  if (!response.ok) {
    let text = await response.text();
    try {
      const parsed = JSON.parse(text);
      text = parsed.detail?.output || parsed.detail || text;
    } catch {
      // Keep raw response text.
    }
    const error = new Error(compactErrorMessage(text || `Errore HTTP ${response.status}`));
    error.fullOutput = cleanText(text || "");
    throw error;
  }
  const data = await response.json();
  return normalizeData(data);
}

function dashboardStorageKey(portfolioId) {
  return `dashboardSnapshot:${String(portfolioId || "main")}`;
}

const DASHBOARD_SNAPSHOT_VERSION = 2;

function normalizeDashboardPayload(payload) {
  if (!payload || typeof payload !== "object") return payload;
  return {
    ...payload,
    dashboard_schema_version: DASHBOARD_SNAPSHOT_VERSION,
    exit_conditions: (payload.exit_conditions || []).map((row) => ({
      ...row,
      stop_action_code: row.stop_level !== null && row.stop_level !== undefined
        ? (row.stop_action_code || "sell_all")
        : null,
      take_profit_action_code: row.take_profit_level !== null && row.take_profit_level !== undefined
        ? (row.take_profit_action_code || "reduce_position")
        : null,
      take_profit_percent: row.take_profit_level !== null && row.take_profit_level !== undefined
        ? (row.take_profit_percent || 30)
        : null,
      take_profit_action_known: row.take_profit_level !== null && row.take_profit_level !== undefined,
    })),
  };
}

function readDashboardSnapshot(portfolioId) {
  try {
    const value = window.localStorage.getItem(dashboardStorageKey(portfolioId));
    if (!value) return null;
    const stored = JSON.parse(value);
    return normalizeDashboardPayload(stored.payload || stored);
  } catch {
    return null;
  }
}

function saveDashboardSnapshot(portfolioId, payload) {
  try {
    window.localStorage.setItem(dashboardStorageKey(portfolioId), JSON.stringify({
      version: DASHBOARD_SNAPSHOT_VERSION,
      payload: normalizeDashboardPayload(payload),
    }));
  } catch {
    // The backend cache remains available if browser storage is disabled or full.
  }
}

function normalizeData(value) {
  if (typeof value === "string") return cleanText(value);
  if (Array.isArray(value)) return value.map(normalizeData);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalizeData(item)]));
  }
  return value;
}

function Metric({ label, value, delta, icon, valueTone, subtitle, emphasis = "" }) {
  const valueToneClass = valueTone ? `metricValue${valueTone[0].toUpperCase()}${valueTone.slice(1)}` : "";
  return (
    <div className={`metric ${emphasis ? `metric-${emphasis}` : ""}`.trim()}>
      <div className="metricLabel">{icon}{label}</div>
      <div className={`metricValue ${valueToneClass}`.trim()}>{value}</div>
      {delta !== undefined && <div className={`metricDelta ${signedClass(delta)}`}>{pct(delta)}</div>}
      {subtitle && <div className="metricSubtitle">{subtitle}</div>}
    </div>
  );
}

function NewsButton({ ticker, compact = false }) {
  const symbol = String(ticker || "").trim().toUpperCase();
  if (!symbol) return null;
  return (
    <button
      className={`miniButton newsTickerButton ${compact ? "compactNewsButton" : ""}`.trim()}
      onClick={(event) => {
        event.stopPropagation();
        window.dispatchEvent(new CustomEvent("open-ticker-news", { detail: { ticker: symbol } }));
      }}
      title={`Ultime news salvate o ricerca live per ${symbol}`}
    >
      <Newspaper size={15} /> {compact ? "" : "News"}
    </button>
  );
}

function QuickNewsPanel({ ticker, onClose }) {
  const [state, setState] = useState({ loading: true, error: "", items: [] });
  const [stream, setStream] = useState({ running: false, phase: "", logs: [], report: "", error: "" });
  const eventSourceRef = useRef(null);

  async function loadSaved() {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const params = new URLSearchParams({ limit: "20", query: ticker });
      const data = await api(`/api/news/reports?${params.toString()}`, { timeoutMs: 60000 });
      const exactItems = (data.items || []).filter(
        (item) => String(item.ticker || "").trim().toUpperCase() === ticker,
      );
      setState({ loading: false, error: "", items: exactItems });
    } catch (error) {
      setState({ loading: false, error: friendlyNewsError(error, `News salvate ${ticker}`), items: [] });
    }
  }

  function runLive() {
    if (eventSourceRef.current) eventSourceRef.current.close();
    setStream({ running: true, phase: "Avvio ricerca news...", logs: [], report: "", error: "" });
    const es = new EventSource(`${API}/api/news/live-stream?ticker=${encodeURIComponent(ticker)}&force=1`);
    eventSourceRef.current = es;
    es.addEventListener("phase", (event) => {
      setStream((current) => ({ ...current, phase: event.data }));
    });
    es.addEventListener("log", (event) => {
      setStream((current) => ({ ...current, logs: [...current.logs, event.data].slice(-12) }));
    });
    es.addEventListener("report", (event) => {
      setStream((current) => ({ ...current, report: event.data }));
    });
    es.addEventListener("done", () => {
      setStream((current) => ({ ...current, running: false, phase: "Ricerca completata." }));
      es.close();
      eventSourceRef.current = null;
      loadSaved();
    });
    es.addEventListener("error", (event) => {
      const message = event.data || "Ricerca interrotta. Controlla Chrome/ChatGPT e riprova.";
      setStream((current) => ({ ...current, running: false, error: message }));
      es.close();
      eventSourceRef.current = null;
    });
    es.onerror = () => {
      setStream((current) => current.running
        ? { ...current, running: false, error: current.error || "Connessione alla ricerca news interrotta." }
        : current);
      es.close();
      eventSourceRef.current = null;
    };
  }

  useEffect(() => {
    loadSaved();
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, [ticker]);

  const latest = state.items[0];
  const report = cleanText(stream.report || latest?.report || "");
  return (
    <div className="modalBackdrop" onMouseDown={onClose}>
      <section className="quickNewsPanel" onMouseDown={(event) => event.stopPropagation()}>
        <div className="quickNewsHeader">
          <div>
            <span>News del titolo</span>
            <h2><Newspaper size={22} /> {ticker}</h2>
          </div>
          <button className="iconButton" onClick={onClose}><X size={18} /> Chiudi</button>
        </div>
        <div className="quickNewsActions">
          <button className="primaryButton" onClick={runLive} disabled={stream.running}>
            {stream.running ? "Ricerca in corso..." : "Cerca news ora"}
          </button>
          <button className="iconButton" onClick={loadSaved} disabled={state.loading}>
            <RefreshCw size={16} /> Ricarica salvate
          </button>
        </div>
        {stream.phase && <div className="newsLiveStatus infoState">{stream.phase}</div>}
        {stream.error && <div className="error">{stream.error}</div>}
        {state.error && <div className="error">{state.error}</div>}
        {stream.logs.length > 0 && (
          <div className="quickNewsProgress">
            {stream.logs.map((line, index) => <div key={`${index}-${line}`}>{line}</div>)}
          </div>
        )}
        {state.loading && <div className="mutedBox">Recupero le ultime news salvate per {ticker}...</div>}
        {!state.loading && !latest && !stream.report && (
          <div className="mutedBox">
            Nessuna news salvata per {ticker}. Premi <b>Cerca news ora</b> per crearne una.
          </div>
        )}
        {(latest || stream.report) && (
          <article className={`newsCard ${latest?.status || ""}`}>
            <div className="newsCardHeader">
              <div>
                <h3>Ultimo report disponibile</h3>
                <div className="newsMeta">
                  <span>{latest?.updated_at ? formatLogDateTime(latest.updated_at) : "appena cercato"}</span>
                  {latest?.path && <span>{latest.path}</span>}
                </div>
              </div>
              {latest?.status_label && <span className={`newsBadge ${latest.status}`}>{latest.status_label}</span>}
            </div>
            <div className="quickNewsReport">
              {report || "Report ricevuto ma privo di testo."}
            </div>
          </article>
        )}
        {state.items.length > 1 && (
          <div className="quickNewsArchiveNote">
            Altri {state.items.length - 1} report salvati sono disponibili nella pagina News.
          </div>
        )}
      </section>
    </div>
  );
}

function AgentRunStatus({ state = {}, stats = {}, tokenUsage = {}, playwrightHealth = {} }) {
  const status = state.status || "never_run";
  const statusClass = status === "ok" ? "positive" : status === "running" ? "warning" : status === "error" || status === "stale" ? "negative" : "neutral";
  const statusLabel = status === "never_run" ? "mai eseguito" : status === "stale" ? "run appesa" : status;
  const schedulerDisabled = state.scheduler_state === "Disabled" || state.scheduler_enabled === false;
  const primaryNextRun = state.scheduler_enabled && state.scheduler_next_run_at
    ? state.scheduler_next_run_at
    : state.next_scheduled_expected_at;
  const primaryNextRunTime = primaryNextRun ? new Date(primaryNextRun).getTime() : null;
  const primaryNextRunIsOverdue = Boolean(primaryNextRunTime && primaryNextRunTime < Date.now());
  const scheduleClass = schedulerDisabled || state.running_state_is_stale ? "negative" : primaryNextRunIsOverdue ? "warning" : "neutral";
  const scheduleText = schedulerDisabled
    ? "Scheduler disabilitato"
    : primaryNextRun
      ? dateTime(primaryNextRun)
      : "Non schedulato";
  const scheduleBadge = schedulerDisabled
    ? "task disabled"
    : state.running_state_is_stale
      ? "run appesa"
      : primaryNextRunIsOverdue
        ? "in ritardo"
        : "";
  return (
    <section className="agentStatus">
      <div>
        <span className="agentStatusLabel">Stato agente</span>
        <strong className={`pill ${statusClass}`}>{statusLabel}</strong>
      </div>
      <div>
        <span>Ultimo file analisi AI</span>
        <b>{dateTime(state.last_stock_analysis_at)}</b>
        <small className="agentScheduleDetail">
          Grafico analizzato via Playwright/ChatGPT, quando richiesto dall'agente.
        </small>
      </div>
      <div>
        <span>Portafoglio e trigger</span>
        <b>{stats.positionsCount || 0} posizioni / {stats.monitoredCount || 0} trigger</b>
        <small className="agentScheduleDetail">
          Titoli gia in portafoglio e condizioni operative da rivalutare.
        </small>
      </div>
      <div>
        <span>Prossimo scheduled expected</span>
        <b>{scheduleText}</b>
        {state.scheduler_next_run_at && schedulerDisabled && (
          <small className="agentScheduleDetail">Task Windows: {dateTime(state.scheduler_next_run_at)}</small>
        )}
        {scheduleBadge && (
          <em className={`agentScheduleBadge ${scheduleClass}`}>
            {scheduleBadge}
          </em>
        )}
      </div>
      <div><span>Intervallo</span><b>{state.interval_minutes || 30} min</b></div>
      <div>
        <span>Universo controllato</span>
        <b>
          {stats.ftseMibCount || 0} FTSE MIB / {stats.commoditiesCount || 0} materie prime / {stats.etfCount || 0} ETF
        </b>
        <small className="agentScheduleDetail">
          Strumenti disponibili per scanner tecnico e selezione candidati.
        </small>
      </div>
      <div><span>Ultimo ciclo agente completato</span><b>{dateTime(state.last_completed_at)}</b></div>
      <div><span>Modalita</span><b>{state.last_mode || "n/d"}</b></div>
      <div className="tokenUsageStatus">
        <span>Token OpenAI oggi</span>
        <b>{Number(tokenUsage.today?.total_tokens || 0).toLocaleString("it-IT")}</b>
        <small className="agentScheduleDetail">
          Input {Number(tokenUsage.today?.input_tokens || 0).toLocaleString("it-IT")} ·
          Output {Number(tokenUsage.today?.output_tokens || 0).toLocaleString("it-IT")} ·
          {Number(tokenUsage.today?.runs || 0).toLocaleString("it-IT")} run
        </small>
        {tokenUsage.today?.cached_input_tokens > 0 && (
          <small className="agentScheduleDetail">
            Di cui input in cache: {Number(tokenUsage.today.cached_input_tokens).toLocaleString("it-IT")}
          </small>
        )}
        {tokenUsage.today?.avg_input_tokens_per_request > 0 && (
          <small className="agentScheduleDetail">
            Media input/richiesta: {Number(tokenUsage.today.avg_input_tokens_per_request).toLocaleString("it-IT")}
            {tokenUsage.today?.max_request_input_tokens > 0
              ? ` · picco ${Number(tokenUsage.today.max_request_input_tokens).toLocaleString("it-IT")}`
              : ""}
          </small>
        )}
      </div>
      {playwrightHealth.status === "error" && (
        <div className="agentStatusError">
          <span>Playwright / ChatGPT non operativo</span>
          <b>{playwrightHealth.message}</b>
          <small className="agentScheduleDetail">
            {playwrightHealth.ticker ? `${playwrightHealth.ticker} · ` : ""}
            rilevato {dateTime(playwrightHealth.last_error_at)}
          </small>
        </div>
      )}
      {state.last_error && <div className="agentStatusError"><span>Errore ultima run</span><b>{state.last_error}</b></div>}
    </section>
  );
}

function TokenUsagePanel({ usage = {} }) {
  const rows = usage.daily || [];
  return (
    <section className="panel tokenUsagePanel">
      <div className="sectionHeader">
        <div>
          <h2>Consumo token OpenAI</h2>
          <p>Conteggio effettivo dell’Agents SDK, suddiviso per giorno.</p>
        </div>
        <span>{usage.tracking_started_at ? `Attivo dal ${dateTime(usage.tracking_started_at)}` : "Parte dalla prossima run"}</span>
      </div>
      {!rows.length ? (
        <div className="emptyState">Nessun consumo registrato dopo l’attivazione del contatore.</div>
      ) : (
        <div className="tokenUsageTableWrap">
          <table className="tokenUsageTable">
            <thead>
              <tr>
                <th>Giorno</th>
                <th>Run</th>
                <th>Richieste</th>
                <th>Input</th>
                <th>Cache</th>
                <th>Output</th>
                <th>Totale</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 7).map((row) => (
                <tr key={row.date}>
                  <td>{new Date(`${row.date}T12:00:00`).toLocaleDateString("it-IT")}</td>
                  <td>{Number(row.runs || 0).toLocaleString("it-IT")}</td>
                  <td>{Number(row.requests || 0).toLocaleString("it-IT")}</td>
                  <td>{Number(row.input_tokens || 0).toLocaleString("it-IT")}</td>
                  <td>{Number(row.cached_input_tokens || 0).toLocaleString("it-IT")}</td>
                  <td>{Number(row.output_tokens || 0).toLocaleString("it-IT")}</td>
                  <td><strong>{Number(row.total_tokens || 0).toLocaleString("it-IT")}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Positions({ rows = [], onChart, performance = {} }) {
  const totalValue = Number(performance.total_value || 0);
  const positionsValue = Number(performance.positions_value || 0);
  const totalPnl = Number(performance.total_pnl || 0);
  const totalPnlPct = Number(performance.total_pnl_pct || 0);
  return (
    <section className="panel portfolioHoldingsPanel">
      <div className="portfolioHoldingsHeader">
        <div>
          <h2>Portafoglio</h2>
          <span>{rows.length} posizioni aperte</span>
        </div>
        <div className="portfolioHoldingsTotals">
          <div>
            <span>Valore posizioni</span>
            <strong>{eur(positionsValue)}</strong>
          </div>
          <div>
            <span>P/L portafoglio</span>
            <strong className={signedClass(totalPnl)}>{eur(totalPnl)}</strong>
          </div>
          <div>
            <span>P/L %</span>
            <strong className={signedClass(totalPnlPct)}>{pct(totalPnlPct)}</strong>
          </div>
        </div>
      </div>
      <div className="tableWrap portfolioHoldingsTableWrap">
        <table className="portfolioHoldingsTable">
          <thead>
            <tr>
              <th>Titolo</th>
              <th>Quantità</th>
              <th>Prezzo medio<br />di carico</th>
              <th>Ultima<br />chiusura</th>
              <th>Valore di mercato</th>
              <th>Variazione</th>
              <th>Peso</th>
              <th aria-label="Azioni"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.ticker}>
                <td>
                  <div className="portfolioTitleCell">
                    <span className="portfolioTickerMark">{String(row.ticker || "?").slice(0, 1)}</span>
                    <span className="portfolioTitleText">
                      <strong>{row.name || row.ticker}</strong>
                      {row.name && row.name !== row.ticker && <small>{row.ticker}</small>}
                    </span>
                    <NewsButton ticker={row.ticker} compact />
                  </div>
                </td>
                <td>{price(row.virtual_quantity)}</td>
                <td>{price(row.entry_price)}</td>
                <td>
                  <strong>{price(row.current_price)}</strong>
                  <small className={signedClass(row.daily_change_pct)}>Seduta {pct(row.daily_change_pct)}</small>
                </td>
                <td><strong>{eur(row.market_value)}</strong></td>
                <td className="portfolioVariationCell">
                  <strong className={signedClass(row.pnl)}>{eur(row.pnl)}</strong>
                  <span className={signedClass(row.pnl_pct)}>{pct(row.pnl_pct)}</span>
                </td>
                <td>
                  <span
                    className={`pill ${totalValue > 0 && (Number(row.market_value) / Number(totalValue)) * 100 > 12 ? "negative" : "neutral"}`}
                    title="Valore corrente della posizione diviso per il patrimonio totale, cash incluso"
                  >
                    {totalValue > 0 ? pct((Number(row.market_value) / Number(totalValue)) * 100, false) : "n/d"}
                  </span>
                </td>
                <td className="rowActions">
                  <button className="miniButton" onClick={() => onChart({ ticker: row.ticker, current_price: row.current_price, entry_price: row.entry_price, opened_at: row.opened_at, support_level: null, condition: "Posizione in portafoglio" })}><LineChart size={15} /> Grafico</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PortfolioPerformanceChart({ data = {} }) {
  const rows = data.history || [];
  const latest = data.latest || rows[rows.length - 1];
  const width = 1040;
  const height = 280;
  const pad = { top: 24, right: 40, bottom: 48, left: 86 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const values = rows.map((row) => Number(row.total_value)).filter((value) => Number.isFinite(value));
  const chartValues = values.length ? values : [0, 1];
  const pnlValues = rows.map((row) => Number(row.total_pnl_pct)).filter((value) => Number.isFinite(value));
  const min = Math.min(...chartValues);
  const max = Math.max(...chartValues);
  const span = max - min || 1;
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.08;
  const x = (index) => pad.left + (rows.length <= 1 ? plotW / 2 : (index / (rows.length - 1)) * plotW);
  const y = (value) => pad.top + ((yMax - value) / (yMax - yMin)) * plotH;
  const path = rows
    .map((row, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(Number(row.total_value)).toFixed(2)}`)
    .join(" ");
  const ticks = Array.from({ length: 4 }, (_, index) => yMin + ((yMax - yMin) / 3) * index);
  const dateTicks = rows
    .map((row, index) => ({ ...row, index }))
    .filter((row, index) => index === 0 || index === rows.length - 1 || index % Math.max(1, Math.round(rows.length / 5)) === 0);
  const snapshotTickLabel = (timestamp) => {
    const formatted = dateTime(timestamp);
    return formatted.slice(0, 10);
  };
  const lastDaily = latest?.daily_return_pct;
  const best = data.best_daily_snapshot;
  const worst = data.worst_daily_snapshot;

  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Rendimento portafoglio</h2>
        <span>{rows.length ? `${rows.length} giorni disponibili` : "storico non ancora disponibile"}</span>
      </div>
      <div className="performanceHistoryStats">
        <div><span>Valore ultimo giorno</span><b>{eur(latest?.total_value)}</b></div>
        <div><span>P/L totale a oggi</span><b className={signedClass(latest?.total_pnl)}>{eur(latest?.total_pnl)} ({pct(latest?.total_pnl_pct)})</b></div>
        <div><span>Rendimento giornaliero</span><b className={signedClass(lastDaily)}>{pct(lastDaily)}</b></div>
        <div><span>Range giornaliero storico</span><b>{pct(worst?.daily_return_pct)} / {pct(best?.daily_return_pct)}</b></div>
      </div>
      {!rows.length ? (
        <div className="emptyState">Lo storico verra creato dai prossimi calcoli performance o run periodici.</div>
      ) : (
        <svg className="portfolioHistoryChart" viewBox={`0 0 ${width} ${height}`} role="img">
          <rect x="0" y="0" width={width} height={height} rx="8" />
          {ticks.map((tick) => (
            <g key={tick} className="gridLine">
              <line x1={pad.left} x2={pad.left + plotW} y1={y(tick)} y2={y(tick)} />
              <text x={pad.left - 12} y={y(tick) + 4} textAnchor="end">{eur(tick).replace(` ${EURO}`, "")}</text>
            </g>
          ))}
          {dateTicks.map((tick) => (
            <g key={`${tick.timestamp}-${tick.index}`} className="dateTick">
              <line x1={x(tick.index)} x2={x(tick.index)} y1={pad.top + plotH} y2={pad.top + plotH + 7} />
              <text x={x(tick.index)} y={height - 18}>{snapshotTickLabel(tick.timestamp)}</text>
            </g>
          ))}
          <path className={pnlValues[pnlValues.length - 1] >= 0 ? "portfolioLine positiveLine" : "portfolioLine negativeLine"} d={path} />
          {rows.map((row, index) => (
            <circle
              key={`${row.timestamp}-${index}`}
              cx={x(index)}
              cy={y(Number(row.total_value))}
              r={index === rows.length - 1 ? 5 : 3}
              className={Number(row.total_pnl_pct) >= 0 ? "historyDotPositive" : "historyDotNegative"}
            >
              <title>{dateTime(row.timestamp)} - {eur(row.total_value)} - P/L {pct(row.total_pnl_pct)} - giorno {pct(row.daily_return_pct)}</title>
            </circle>
          ))}
        </svg>
      )}
    </section>
  );
}

function ExitConditions({ rows = [], onChart }) {
  if (!rows.length) {
    return (
      <section className="panel">
        <h2>Piano di uscita</h2>
        <div className="emptyState">Nessuna posizione aperta da gestire.</div>
      </section>
    );
  }
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Piano di uscita</h2>
        <span>Stop, target e segnali operativi sulle posizioni gia in portafoglio</span>
      </div>
      <div className="exitGrid">
        {rows.map((row) => {
          const stopDistance = Number(row.distance_to_stop_pct);
          const targetDistance = Number(row.distance_to_take_profit_pct);
          const hasStopDistance = row.distance_to_stop_pct !== null && row.distance_to_stop_pct !== undefined;
          const hasTargetDistance = row.distance_to_take_profit_pct !== null && row.distance_to_take_profit_pct !== undefined;
          const stopText = !hasStopDistance
            ? "Distanza non disponibile"
            : stopDistance >= 0
              ? `Lo stop e ${pct(stopDistance, false)} sotto il prezzo attuale`
              : `STOP VIOLATO: prezzo ${pct(Math.abs(stopDistance), false)} sotto il livello`;
          const targetText = !hasTargetDistance
            ? (row.target_unavailable_reason || "Take profit operativo non definito")
            : targetDistance < 0
              ? `Il target e ${pct(Math.abs(targetDistance), false)} sopra il prezzo attuale`
              : `Target superato di ${pct(targetDistance, false)}`;
          const stopTriggerAction = row.stop_action_code === "sell_all"
            ? "Vendita totale automatica della posizione."
            : (row.stop_trigger_action || "Azione non ancora determinata.");
          const takeProfitTriggerAction = row.take_profit_trigger_action
            || (row.take_profit_level !== null && row.take_profit_level !== undefined
              ? `Vendita parziale automatica del ${row.take_profit_percent || 30}%.`
              : null);
          const stopBreached = hasStopDistance && stopDistance < 0;
          const actionNow = stopBreached && row.stop_action_code === "sell_all"
            ? "Vendita totale automatica della posizione."
            : row.status === "TAKE PROFIT" || row.status === "TAKE PROFIT ESEGUITO"
              ? row.primary_action
              : "Nessuna operazione. Posizione mantenuta sotto osservazione.";
          const nextAction = row.stop_action_code === "sell_all"
            ? `Se il prezzo raggiunge o scende sotto ${price(row.stop_level)}, il sistema vende tutta la posizione.`
            : `Il livello ${price(row.stop_level)} e solo un riferimento tecnico: non ha ancora un'operazione associata.`;
          return (
          <div className="exitCard" key={row.ticker}>
            <div className="triggerHeader">
              <strong>{row.ticker}</strong>
              <span className={`status ${row.status_kind}`}>{row.status}</span>
            </div>
            <div className="exitPositionSnapshot">
              <div><span>Ultima chiusura</span><strong>{quotedPrice(row.current_price, row.price_currency)}</strong><small>Seduta {dateOnly(row.price_as_of)} · {pct(row.daily_change_pct)}</small></div>
              <div><span>Prezzo medio</span><strong>{quotedPrice(row.entry_price, row.price_currency)}</strong><small>Prezzo di carico</small></div>
              <div><span>P/L posizione</span><strong className={signedClass(row.pnl_pct)}>{pct(row.pnl_pct)}</strong><small>Dal prezzo medio</small></div>
            </div>
            <div className="triggerGrid exitLevelGrid">
              <div className={stopDistance < 0 ? "levelViolated" : ""}>
                <span>{row.stop_action_code === "sell_all" ? "Stop automatico" : "Livello di uscita"}</span><b>{quotedPrice(row.stop_level, row.price_currency)}</b><small>{stopText}. Fonte: {row.stop_source || "non disponibile"}.</small>
                <em className="levelAction knownAction">Quando scatta: {stopTriggerAction}</em>
              </div>
              <div><span>Take profit operativo</span><b>{quotedPrice(row.take_profit_level, row.price_currency)}</b><small>{targetText}</small>
                {!row.take_profit_level && row.resistance_level && <small>Resistenza tecnica nota: {quotedPrice(row.resistance_level, row.price_currency)}</small>}
                {takeProfitTriggerAction && <em className={`levelAction ${row.take_profit_action_known ? "knownAction" : "pendingAction"}`}>Quando scatta: {takeProfitTriggerAction}</em>}
              </div>
            </div>
            <div className={`exitDecision ${row.status_kind}`}>
              <span>Cosa fa il sistema adesso</span>
              <strong>{actionNow}</strong>
              <small>{nextAction}</small>
            </div>
            <p className="condition">{row.explanation}</p>
            <div className="sourceLine">Fonte livelli: {row.source}{row.analysis_updated_at ? ` · aggiornata ${dateTime(row.analysis_updated_at)}` : ""}</div>
            <div className="cardActions">
              <button
                className="chartButton"
                onClick={() => onChart({
                  ticker: row.ticker,
                  current_price: row.current_price,
                  entry_price: row.entry_price,
                  opened_at: row.opened_at,
                  trigger_level: row.take_profit_level,
                  support_level: row.stop_level,
                  trigger_distance_pct: row.distance_to_take_profit_pct,
                  condition: `Uscita: stop ${price(row.stop_level)} / take profit ${price(row.take_profit_level)}. ${row.primary_action}`,
                })}
              >
                <LineChart size={16} /> Grafico uscita
              </button>
              <NewsButton ticker={row.ticker} />
            </div>
          </div>
          );
        })}
      </div>
    </section>
  );
}

function TriggerCard({ item, onChart, isInPortfolio = false, entryPrice = null }) {
  const progress = item.trigger_progress ?? 0;
  const missing = item.trigger_distance_pct === null || item.trigger_distance_pct === undefined ? null : -item.trigger_distance_pct;
  const triggerLabel = isInPortfolio ? "Trigger incremento" : "Trigger ingresso";
  const actionLabel = isInPortfolio ? "Incremento/ribilanciamento" : "Ingresso";
  const priceThresholdMet = Number(item.trigger_distance_pct) >= 0;
  const scenarioState = String(item.scenario_state || "WAIT").toUpperCase();
  const operationLabels = {
    buy_virtual_position: "ACQUISTO ESEGUITO",
    reduce_virtual_position: "VENDITA PARZIALE ESEGUITA",
    sell_virtual_position: "VENDITA TOTALE ESEGUITA",
  };
  const evaluationText = scenarioState === "BUY_CANDIDATE"
    ? "Confermata: controlli tecnici, grafico e news superati"
    : scenarioState === "CONFIRMING"
      ? "In corso: servono grafico e news"
      : scenarioState === "NEAR_TRIGGER"
        ? "Parziale: condizioni non ancora sufficienti"
        : priceThresholdMet
          ? "NON ESEGUITA dopo il superamento del prezzo"
          : "In attesa del trigger";
  const decisionText = item.last_decision_reason
    || (scenarioState === "BUY_CANDIDATE"
      ? "Da trasformare in una decisione operativa"
      : isInPortfolio ? "Nessuna decisione presa" : "Nessuna decisione di acquisto presa");
  const nextStep = priceThresholdMet && scenarioState === "WAIT"
    ? isInPortfolio
      ? "Al prossimo ciclo: verificare chiusura e volumi; se validi, analizzare grafico e news e decidere MANTIENI oppure INCREMENTA."
      : "Al prossimo ciclo: verificare chiusura e volumi; se validi, analizzare grafico e news e decidere ACQUISTA oppure NON ACQUISTARE."
    : scenarioState === "CONFIRMING"
      ? isInPortfolio
        ? "Completare grafico e news, poi decidere MANTIENI oppure INCREMENTA."
        : "Completare grafico e news, poi decidere ACQUISTA oppure NON ACQUISTARE."
      : scenarioState === "BUY_CANDIDATE"
        ? isInPortfolio
          ? "Decidere esplicitamente se mantenere o incrementare, applicando i limiti di rischio."
          : "Creare e validare la proposta di acquisto con il risk manager."
        : "Continuare il monitoraggio fino al verificarsi delle condizioni complete.";
  const scenarioKind = item.scenario_state === "BUY_CANDIDATE"
    ? "positive"
    : item.scenario_state === "CONFIRMING" || item.scenario_state === "NEAR_TRIGGER"
      ? "warning"
      : item.scenario_state === "INVALIDATED"
        ? "negative"
        : "neutral";
  return (
    <div className="triggerCard">
      <div className="triggerHeader">
        <strong>{item.ticker}</strong>
        <span className={`status ${item.trigger_status_kind}`}>{item.trigger_status}</span>
      </div>
      {isInPortfolio && (
        <div className="positionContext">
          Gia in portafoglio: questo box non e il P/L, serve per decidere se incrementare o ribilanciare.
        </div>
      )}
      {!isInPortfolio && (
        <div className="entryContext">
          Non è in portafoglio: questa scheda può produrre soltanto ACQUISTO oppure NESSUN ACQUISTO.
        </div>
      )}
      {item.scenario_state && (
        <div className="scenarioLine">
          <span className={`status ${scenarioKind}`}>{item.scenario_state}</span>
          {item.volume_ratio !== null && item.volume_ratio !== undefined && <em>Vol/MA10 {item.volume_ratio}x</em>}
        </div>
      )}
      {item.daily_bar_complete === false && (
        <div className="positionContext">
          Seduta in corso: prezzo e volume giornaliero sono provvisori. La conferma viene effettuata dopo la chiusura.
        </div>
      )}
      <div className="triggerGrid">
        <div><span>Prezzo attuale</span><b>{price(item.current_price)}</b></div>
        <div><span>Oggi</span><b className={signedClass(item.daily_change_pct)}>{pct(item.daily_change_pct)}</b></div>
        <div><span>{triggerLabel}</span><b>{price(item.trigger_level)}</b></div>
        <div><span>Supporto/stop</span><b>{price(item.support_level)}</b></div>
        <div><span>Distanza trigger</span><b className={signedClass(item.trigger_distance_pct)}>{pct(item.trigger_distance_pct)}</b></div>
      </div>
      <div className="rangeLabels"><span>Supporto</span><span>Trigger</span></div>
      <div className="progress"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
      <p className="small">
        {item.trigger_distance_pct >= 0
          ? `Prezzo sopra il trigger di ${pct(item.trigger_distance_pct, false)}.`
          : missing !== null
            ? `Mancano ${pct(missing, false)} al trigger di ${actionLabel.toLowerCase()}.`
            : "Distanza dal trigger non disponibile."}
      </p>
      <div className="conditionAudit">
        <div><span>1 · Evento rilevato</span><strong>{priceThresholdMet ? "SOGLIA PREZZO SUPERATA" : "TRIGGER NON RAGGIUNTO"}</strong></div>
        <div><span>2 · Verifica completa</span><strong>{evaluationText}</strong><small>Ultima valutazione: {dateTime(item.last_entry_scenario_eval_at)}</small></div>
        <div><span>3 · Decisione su questa condizione</span><strong>{decisionText}</strong></div>
        <div>
          <span>4 · Ultima operazione reale sul titolo</span>
          <strong>{item.last_portfolio_operation ? operationLabels[item.last_portfolio_operation.action] || item.last_portfolio_operation.action : "NESSUNA OPERAZIONE"}</strong>
          {item.last_portfolio_operation && <small>{dateTime(item.last_portfolio_operation.at)} · Non necessariamente causata dal trigger corrente.</small>}
        </div>
        <div className="nextStep"><span>5 · Cosa farà il sistema su questo trigger</span><strong>{nextStep}</strong></div>
      </div>
      <p className="condition">{item.condition}</p>
      {item.scenario_reason && <p className="small scenarioReason">{item.scenario_reason}</p>}
      <div className="cardActions">
        <button className="chartButton" onClick={() => onChart({ ...item, entry_price: entryPrice })}><LineChart size={16} /> Apri grafico trigger</button>
        <NewsButton ticker={item.ticker} />
      </div>
    </div>
  );
}

function marketGroupForCondition(row) {
  const market = `${row.market || ""} ${row.asset_class || ""} ${row.source || ""} ${row.condition || ""}`.toLowerCase();
  const ticker = String(row.ticker || "").toUpperCase();
  if (market.includes(" etf") || market.includes("etf") || ticker === "ROBO.MI") {
    return "etf";
  }
  if (market.includes("materie") || market.includes("commodity") || market.includes("etc") || market.includes("etn")) {
    return "commodities";
  }
  if (market.includes("ftse") || market.includes("mib") || row.ticker?.endsWith(".MI")) {
    return "ftse";
  }
  return "other";
}

function MonitoringGroup({ title, subtitle, rows, onChart, positionTickers, positionEntries }) {
  if (!rows.length) return null;
  const near = rows.filter((row) => row.trigger_distance_pct !== null && Math.abs(row.trigger_distance_pct) <= 3);
  return (
    <div className="monitoringGroup">
      <div className="monitoringGroupHeader">
        <div>
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <span>{rows.length} trigger | {near.length} vicini entro +/-3%</span>
      </div>
      <div className="cardsGrid">
        {rows.map((item) => (
          <TriggerCard
            key={item.id || item.ticker}
            item={item}
            onChart={onChart}
            isInPortfolio={positionTickers.has(String(item.ticker || "").toUpperCase())}
            entryPrice={positionEntries.get(String(item.ticker || "").toUpperCase())}
          />
        ))}
      </div>
    </div>
  );
}

function CompactTriggerTable({ rows, onChart, positionTickers }) {
  if (!rows.length) return <div className="emptyState">Nessun trigger in attesa.</div>;
  return (
    <div className="tableWrap compactTriggerTable">
      <table>
        <thead><tr><th>Ticker</th><th>Contesto</th><th>Prezzo</th><th>Trigger</th><th>Distanza</th><th>Stato</th><th /></tr></thead>
        <tbody>
          {rows.map((item) => {
            const held = positionTickers.has(String(item.ticker || "").toUpperCase());
            return (
              <tr key={item.id || item.ticker}>
                <td className="ticker">{item.ticker}</td>
                <td>{held ? "Gia in portafoglio" : marketGroupForCondition(item).toUpperCase()}</td>
                <td>{price(item.current_price)}</td>
                <td>{price(item.trigger_level)}</td>
                <td className={signedClass(item.trigger_distance_pct)}>{pct(item.trigger_distance_pct)}</td>
                <td><span className={`pill ${item.trigger_status_kind || "neutral"}`}>{item.trigger_status}</span></td>
                <td><button className="miniButton" onClick={() => onChart(item)}><LineChart size={14} /> Grafico</button></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Monitoring({ rows = [], positions = [], onChart }) {
  const uniqueRows = uniqueConditionsByTicker(rows);
  const positionTickers = new Set(positions.map((row) => String(row.ticker || "").toUpperCase()));
  const positionEntries = new Map(positions.map((row) => [String(row.ticker || "").toUpperCase(), row.entry_price]));
  const isHeld = (row) => positionTickers.has(String(row.ticker || "").toUpperCase());
  const needsDecision = (row) => {
    const state = String(row.scenario_state || "").toUpperCase();
    const hasDistance = row.trigger_distance_pct !== null && row.trigger_distance_pct !== undefined;
    return (hasDistance && Number(row.trigger_distance_pct) >= 0) || ["CONFIRMING", "BUY_CANDIDATE"].includes(state);
  };
  const needsAttention = (row) => {
    const distance = Number(row.trigger_distance_pct);
    const state = String(row.scenario_state || "").toUpperCase();
    return needsDecision(row) || state === "NEAR_TRIGGER" || (Number.isFinite(distance) && Math.abs(distance) <= 1);
  };
  const decisionRows = uniqueRows.filter(needsDecision).sort((a, b) => Number(b.trigger_distance_pct || 0) - Number(a.trigger_distance_pct || 0));
  const heldAttention = uniqueRows.filter((row) => isHeld(row) && needsAttention(row) && !needsDecision(row));
  const entryAttention = uniqueRows.filter((row) => !isHeld(row) && needsAttention(row) && !needsDecision(row));
  const waiting = uniqueRows.filter((row) => !needsAttention(row)).sort((a, b) => Number(b.trigger_distance_pct || -999) - Number(a.trigger_distance_pct || -999));
  return (
    <section className="panel">
      <div className="sectionHeader">
        <div>
          <h2>Coda decisionale</h2>
          <span>Qui compaiono prima le condizioni che richiedono una verifica o una decisione reale.</span>
        </div>
        <span>{decisionRows.length} da decidere · {heldAttention.length + entryAttention.length} vicini · {waiting.length} in attesa</span>
      </div>
      <div className="decisionSummary">
        <div className={decisionRows.length ? "urgent" : "ok"}><span>Decisione richiesta</span><strong>{decisionRows.length}</strong><small>Soglia superata o conferma avanzata</small></div>
        <div><span>Posizioni da sorvegliare</span><strong>{heldAttention.length}</strong><small>Possibile gestione della posizione</small></div>
        <div><span>Nuovi ingressi vicini</span><strong>{entryAttention.length}</strong><small>Non ancora acquistabili</small></div>
      </div>
      <MonitoringGroup
        title="Da verificare e decidere ora"
        subtitle="Il prezzo ha superato la soglia o la conferma e gia in corso. Nessuna operazione e implicita: ogni scheda mostra cosa e stato davvero fatto."
        rows={decisionRows}
        onChart={onChart}
        positionTickers={positionTickers}
        positionEntries={positionEntries}
      />
      <MonitoringGroup
        title="Posizioni gia in portafoglio vicine a una decisione"
        subtitle="Queste condizioni possono portare a mantenere, incrementare, ridurre o vendere; non sono segnali automatici di acquisto."
        rows={heldAttention}
        onChart={onChart}
        positionTickers={positionTickers}
        positionEntries={positionEntries}
      />
      <MonitoringGroup
        title="Nuovi ingressi vicini"
        subtitle="Titoli non posseduti che si stanno avvicinando alle condizioni minime di valutazione."
        rows={entryAttention}
        onChart={onChart}
        positionTickers={positionTickers}
        positionEntries={positionEntries}
      />
      <details className="waitingTriggers">
        <summary><span>Tutti gli altri trigger in attesa</span><b>{waiting.length}</b></summary>
        <p>Vista compatta di archivio: non richiedono un'azione adesso.</p>
        <CompactTriggerTable rows={waiting} onChart={onChart} positionTickers={positionTickers} />
      </details>
      {!uniqueRows.length && <div className="okBox">Nessuna condizione monitorata.</div>}
    </section>
  );
}

function Watchlist({ rows = [], reload, onChart, portfolioId = "main" }) {
  const [ticker, setTicker] = useState("");
  const [reason, setReason] = useState("");
  const [entryCondition, setEntryCondition] = useState("");
  const [priority, setPriority] = useState("normal");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [conditionDrafts, setConditionDrafts] = useState({});
  const [aiStatus, setAiStatus] = useState("");

  async function addItem(event) {
    event.preventDefault();
    if (!ticker.trim()) return;
    setBusy("add");
    setMessage("");
    try {
      await api(`/api/watchlist?portfolio_id=${encodeURIComponent(portfolioId)}`, {
        method: "POST",
        body: JSON.stringify({ ticker, reason, priority, entry_condition: entryCondition }),
      });
      setTicker("");
      setReason("");
      setEntryCondition("");
      setPriority("normal");
      setMessage("Titolo aggiunto alla watchlist.");
      reload();
    } catch (error) {
      setMessage(`Errore: ${error.message}`);
    } finally {
      setBusy("");
    }
  }

  async function saveCondition(row) {
    const draft = conditionDrafts[row.ticker] ?? row.entry_condition ?? "";
    setBusy(`condition-${row.ticker}`);
    setMessage("");
    try {
      await api(`/api/watchlist?portfolio_id=${encodeURIComponent(portfolioId)}`, {
        method: "POST",
        body: JSON.stringify({
          ticker: row.ticker,
          name: row.name || "",
          market: row.market || "",
          reason: row.reason || "",
          priority: row.priority || "normal",
          tags: row.tags || [],
          entry_condition: draft,
        }),
      });
      setMessage(`Condizione ingresso salvata per ${row.ticker}.`);
      reload();
    } catch (error) {
      setMessage(`Errore: ${error.message}`);
    } finally {
      setBusy("");
    }
  }

  async function removeItem(symbol) {
    setBusy(symbol);
    setMessage("");
    try {
      await api(
        `/api/watchlist/${encodeURIComponent(symbol)}?portfolio_id=${encodeURIComponent(portfolioId)}`,
        { method: "DELETE" },
      );
      setMessage(`${symbol} rimosso dalla watchlist.`);
      reload();
    } catch (error) {
      setMessage(`Errore: ${error.message}`);
    } finally {
      setBusy("");
    }
  }

  async function analyzeEntryConditions() {
    if (!rows.length) {
      setMessage("Watchlist vuota: aggiungi almeno un titolo.");
      return;
    }
    setBusy("ai-watchlist");
    setMessage("");
    setAiStatus("Analisi AI via Playwright in corso: genero grafici, leggo conferma visuale e imposto i trigger...");
    try {
      const result = await api(
        `/api/agent/analyze-watchlist-entry-conditions?portfolio_id=${encodeURIComponent(portfolioId)}`,
        {
        method: "POST",
        body: JSON.stringify({}),
        timeoutMs: 1800000,
        },
      );
      setAiStatus(result.answer || result.output || "Analisi completata.");
      reload();
    } catch (error) {
      setAiStatus(`Errore analisi AI watchlist: ${error.message}`);
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Watchlist manuale</h2>
        <div className="sectionActions">
          <span>Titoli da analizzare anche se non selezionati dallo scanner</span>
          <button onClick={analyzeEntryConditions} disabled={!!busy || !rows.length}>
            AI imposta condizioni
          </button>
        </div>
      </div>
      <form className="watchlistForm" onSubmit={addItem}>
        <label>Ticker<input value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} placeholder="es. VOD.L" /></label>
        <label>Priorita
          <select value={priority} onChange={(event) => setPriority(event.target.value)}>
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="low">Low</option>
          </select>
        </label>
        <label className="reasonInput">Motivo<input value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Perche vuoi seguirlo..." /></label>
        <label className="entryInput">Condizione ingresso<input value={entryCondition} onChange={(event) => setEntryCondition(event.target.value)} placeholder="es. chiusura sopra 121 con volumi..." /></label>
        <button disabled={!!busy || !ticker.trim()}>Aggiungi</button>
      </form>
      {message && <p className="small">{message}</p>}
      {aiStatus && (
        <div className={`watchlistAiStatus ${busy === "ai-watchlist" ? "running" : ""}`}>
          <strong>{busy === "ai-watchlist" ? "Analisi in corso" : "Risultato analisi AI"}</strong>
          <p>{aiStatus}</p>
        </div>
      )}
      {!rows.length ? (
        <div className="emptyState">Watchlist vuota.</div>
      ) : (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Priorita</th>
                <th>Motivo</th>
                <th>Condizione ingresso</th>
                <th>Aggiunto</th>
                <th>Azioni</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.ticker}>
                  <td className="ticker">{row.ticker}</td>
                  <td><span className={`pill ${row.priority === "high" ? "warning" : "neutral"}`}>{row.priority || "normal"}</span></td>
                  <td className="reason">{row.reason || "n/d"}</td>
                  <td className="entryConditionCell">
                    <textarea
                      value={conditionDrafts[row.ticker] ?? row.entry_condition ?? ""}
                      onChange={(event) => setConditionDrafts((current) => ({ ...current, [row.ticker]: event.target.value }))}
                      placeholder="Trigger da monitorare..."
                    />
                    <button className="miniButton" onClick={() => saveCondition(row)} disabled={busy === `condition-${row.ticker}`}>
                      Salva
                    </button>
                  </td>
                  <td>{dateTime(row.added_at)}</td>
                  <td className="rowActions">
                    <button className="miniButton" onClick={() => onChart({ ticker: row.ticker, condition: row.entry_condition || row.reason || "Watchlist manuale" })}><LineChart size={15} /> Grafico</button>
                    <NewsButton ticker={row.ticker} />
                    <button className="miniButton" onClick={() => removeItem(row.ticker)} disabled={busy === row.ticker}><X size={15} /> Rimuovi</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="small">
        Nel monitor ogni 30 minuti l'agente legge anche questa lista e puo creare condizioni monitorate o proposte se un titolo diventa interessante.
      </p>
    </section>
  );
}

function MarketScanner({
  title,
  subtitle,
  marketKey,
  rows = [],
  monitoredRows = [],
  positions = [],
  scanEndpoint,
  countLabel,
  emptyText,
  universeColumns = [],
  chartCondition,
  onChart,
}) {
  const [limit, setLimit] = useState(8);
  const [scan, setScan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [universeRows, setUniverseRows] = useState([]);
  const [universeMessage, setUniverseMessage] = useState("");
  const [manualTicker, setManualTicker] = useState("");
  const [manualName, setManualName] = useState("");
  const [manualDescription, setManualDescription] = useState("");
  const [importPath, setImportPath] = useState("");
  const [replaceImport, setReplaceImport] = useState(false);
  const [activateImport, setActivateImport] = useState(false);
  const minOperationalScore = 5;

  async function loadUniverse() {
    if (!marketKey) return;
    try {
      const result = await api(`/api/markets/${marketKey}/universe`);
      setUniverseRows(result.items || []);
    } catch (error) {
      setUniverseMessage(`Lista mercato non disponibile: ${error.message}`);
    }
  }

  useEffect(() => {
    loadUniverse();
  }, [marketKey]);

  const activeUniverseRows = universeRows.length
    ? universeRows.filter((item) => item.active !== false)
    : rows;

  async function runScan() {
    setBusy(true);
    setMessage(`Scansione ${title} in corso: scarico dati, calcolo indicatori e score...`);
    try {
      const result = await api(scanEndpoint, {
        method: "POST",
        body: JSON.stringify({ limit: Number(limit) || 8, universe_limit: 0 }),
        timeoutMs: 900000,
      });
      setScan(result);
      setMessage(`Scansione completata: ${result.count || 0} strumenti validi, ${result.errors?.length || 0} errori.`);
    } catch (error) {
      setMessage(`Errore scansione ${title}: ${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function addInstrument() {
    if (!marketKey || !manualTicker.trim()) return;
    setUniverseMessage(`Aggiungo ${manualTicker.trim().toUpperCase()} alla lista ${title}...`);
    try {
      await api(`/api/markets/${marketKey}/instrument`, {
        method: "POST",
        body: JSON.stringify({
          ticker: manualTicker.trim().toUpperCase(),
          name: manualName.trim(),
          description: manualDescription.trim(),
          active: true,
        }),
      });
      setManualTicker("");
      setManualName("");
      setManualDescription("");
      setUniverseMessage("Strumento aggiunto e attivato.");
      await loadUniverse();
    } catch (error) {
      setUniverseMessage(`Errore aggiunta strumento: ${error.message}`);
    }
  }

  async function toggleInstrument(row) {
    if (!marketKey || !row?.ticker) return;
    const nextActive = row.active === false;
    try {
      await api(`/api/markets/${marketKey}/instrument/${encodeURIComponent(row.ticker)}`, {
        method: "PATCH",
        body: JSON.stringify({ active: nextActive }),
      });
      setUniverseMessage(`${row.ticker} ${nextActive ? "attivato" : "disattivato"} nello scope operativo.`);
      await loadUniverse();
    } catch (error) {
      setUniverseMessage(`Errore aggiornamento ${row.ticker}: ${error.message}`);
    }
  }

  async function removeInstrument(row) {
    if (!marketKey || !row?.ticker) return;
    try {
      await api(`/api/markets/${marketKey}/instrument/${encodeURIComponent(row.ticker)}`, { method: "DELETE" });
      setUniverseMessage(`${row.ticker} rimosso dalla lista configurata.`);
      await loadUniverse();
    } catch (error) {
      setUniverseMessage(`Errore rimozione ${row.ticker}: ${error.message}`);
    }
  }

  async function importExcel() {
    if (!marketKey || !importPath.trim()) return;
    setUniverseMessage(`Import Excel in corso per ${title}...`);
    try {
      const result = await api(`/api/markets/${marketKey}/import-excel`, {
        method: "POST",
        body: JSON.stringify({
          path: importPath.trim(),
          replace: replaceImport,
          activate: activateImport,
        }),
        timeoutMs: 120000,
      });
      setUniverseMessage(`Import completato: ${result.imported || 0} righe importate, ${result.active_count || 0} attive.`);
      await loadUniverse();
    } catch (error) {
      setUniverseMessage(`Errore import Excel: ${error.message}`);
    }
  }

  const scanCandidates = scan?.candidates || [];
  const scanRows = scan?.scanned_rows || [];
  const uniqueMonitoredRows = useMemo(() => uniqueConditionsByTicker(monitoredRows), [monitoredRows]);
  const monitoredByTicker = useMemo(() => {
    const map = new Map();
    uniqueMonitoredRows.forEach((item) => {
      if (item.ticker) map.set(String(item.ticker).toUpperCase(), item);
    });
    return map;
  }, [uniqueMonitoredRows]);
  const positionByTicker = useMemo(() => {
    const map = new Map();
    positions.forEach((item) => {
      if (item.ticker) map.set(String(item.ticker).toUpperCase(), item);
    });
    return map;
  }, [positions]);
  const candidateByTicker = useMemo(() => {
    const map = new Map();
    scanCandidates.forEach((item) => {
      if (item.ticker) map.set(String(item.ticker).toUpperCase(), item);
    });
    return map;
  }, [scanCandidates]);
  const rowByTicker = useMemo(() => {
    const map = new Map();
    activeUniverseRows.forEach((item) => {
      if (item.ticker) map.set(String(item.ticker).toUpperCase(), item);
    });
    return map;
  }, [activeUniverseRows]);
  const mergedRows = useMemo(() => {
    const map = new Map();
    activeUniverseRows.forEach((item) => map.set(String(item.ticker || "").toUpperCase(), { ...item }));
    scanRows.forEach((item) => {
      const ticker = String(item.ticker || "").toUpperCase();
      map.set(ticker, { ...(map.get(ticker) || {}), ...item });
    });
    scanCandidates.forEach((item) => {
      const ticker = String(item.ticker || "").toUpperCase();
      map.set(ticker, { ...(map.get(ticker) || {}), ...item });
    });
    monitoredRows.forEach((item) => {
      const ticker = String(item.ticker || "").toUpperCase();
      const base = map.get(ticker);
      if (base) map.set(ticker, { ...base, monitored: item });
    });
    return Array.from(map.values()).filter((item) => item.ticker);
  }, [activeUniverseRows, scanRows, scanCandidates, monitoredRows]);
  const monitoredInUniverse = uniqueMonitoredRows.filter((item) => rowByTicker.has(String(item.ticker || "").toUpperCase()));
  const nearMonitored = monitoredInUniverse.filter((item) => item.trigger_distance_pct !== null && item.trigger_distance_pct !== undefined && Math.abs(item.trigger_distance_pct) <= 3);
  const hasScore = (item) => item.score !== null && item.score !== undefined && item.score !== "";
  const isHeldTicker = (ticker) => positionByTicker.has(String(ticker || "").toUpperCase());
  const isOperationalCandidate = (item) => (
    item &&
    item.liquidity_ok !== false &&
    Number(item.score || 0) >= minOperationalScore &&
    !isHeldTicker(item.ticker)
  );
  const scannedRows = mergedRows
    .filter((item) => hasScore(item))
    .sort((a, b) => Number(b.score || 0) - Number(a.score || 0));
  const liquidScannedRows = scannedRows.filter((item) => item.liquidity_ok !== false);
  const lowLiquidityScannedRows = scannedRows.filter((item) => item.liquidity_ok === false);
  const visibleCandidates = scanCandidates.length
    ? scanCandidates.filter(isOperationalCandidate)
    : liquidScannedRows.filter(isOperationalCandidate).slice(0, Number(limit) || 8);
  const heldScannerRows = (scanCandidates.length ? scanCandidates : liquidScannedRows)
    .filter((item) => item.liquidity_ok !== false && isHeldTicker(item.ticker));
  const liquidCandidates = visibleCandidates.filter((item) => item.liquidity_ok !== false);
  const bestCandidate = visibleCandidates[0];
  const filteredRows = mergedRows.filter((item) => {
    const text = `${item.ticker || ""} ${item.name || ""} ${item.sector || ""} ${item.industry || ""} ${item.market || ""}`.toLowerCase();
    if (query.trim() && !text.includes(query.trim().toLowerCase())) return false;
    const ticker = String(item.ticker || "").toUpperCase();
    if (filter === "monitored") return monitoredByTicker.has(ticker);
    if (filter === "candidates") return isOperationalCandidate(item);
    if (filter === "liquid") return (candidateByTicker.has(ticker) || hasScore(item)) && item.liquidity_ok !== false;
    if (filter === "illiquid") return (candidateByTicker.has(ticker) || hasScore(item)) && item.liquidity_ok === false;
    return true;
  });
  const filterOptions = [
    ["all", "Tutti"],
    ["monitored", "Monitorati"],
    ["candidates", "Nuovi candidati"],
    ["liquid", "Liquidi"],
    ["illiquid", "Liquidita bassa"],
  ];

  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>{title}</h2>
        <div className="sectionActions">
          <span>{activeUniverseRows.length} attivi / {universeRows.length || rows.length} totali</span>
          <label className="inlineControl">Top
            <input type="number" min="3" max="30" value={limit} onChange={(event) => setLimit(event.target.value)} />
          </label>
          <button onClick={runScan} disabled={busy || !activeUniverseRows.length}>
            {busy ? "Scansione..." : `Scansiona ${title}`}
          </button>
        </div>
      </div>
      {subtitle && <p className="marketSubtitle">{subtitle}</p>}
      {message && <div className={`scanMessage ${busy ? "running" : ""}`}>{message}</div>}

      {marketKey && (
        <div className="marketListManager">
          <div className="listManagerHeader">
            <div>
              <h3>Gestione lista mercato</h3>
              <p>Aggiungi strumenti a mano oppure importa un Excel, poi seleziona quali restano nello scope operativo.</p>
            </div>
            <span>{activeUniverseRows.length} attivi</span>
          </div>
          <div className="listManagerForms">
            <div className="listManagerForm">
              <b>Aggiunta manuale</b>
              <input value={manualTicker} onChange={(event) => setManualTicker(event.target.value)} placeholder="Ticker, es. ROBO.MI" />
              <input value={manualName} onChange={(event) => setManualName(event.target.value)} placeholder="Nome" />
              <input value={manualDescription} onChange={(event) => setManualDescription(event.target.value)} placeholder="Descrizione o motivo" />
              <button onClick={addInstrument} disabled={!manualTicker.trim()}>Aggiungi attivo</button>
            </div>
            <div className="listManagerForm importForm">
              <b>Import da Excel</b>
              <input value={importPath} onChange={(event) => setImportPath(event.target.value)} placeholder="Percorso file .xlsx sul PC" />
              <label><input type="checkbox" checked={replaceImport} onChange={(event) => setReplaceImport(event.target.checked)} /> Sostituisci lista configurata</label>
              <label><input type="checkbox" checked={activateImport} onChange={(event) => setActivateImport(event.target.checked)} /> Attiva subito gli importati</label>
              <button onClick={importExcel} disabled={!importPath.trim()}>Importa Excel</button>
            </div>
          </div>
          {universeMessage && <div className="universeMessage">{universeMessage}</div>}
          <div className="universeSelection">
            {(universeRows.length ? universeRows : rows).slice(0, 120).map((item) => (
              <div className={`universeSelectionRow ${item.active === false ? "disabled" : ""}`} key={item.ticker}>
                <label>
                  <input type="checkbox" checked={item.active !== false} onChange={() => toggleInstrument(item)} />
                  <span>{item.ticker}</span>
                </label>
                <em>{item.name || item.description || "n/d"}</em>
                <NewsButton ticker={item.ticker} compact />
                {universeRows.length > 0 && <button className="miniButton" onClick={() => removeInstrument(item)}>Rimuovi</button>}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="marketOverview">
        <article className="marketKpi">
          <span>Universo</span>
          <strong>{activeUniverseRows.length}</strong>
          <small>{countLabel}</small>
        </article>
        <article className="marketKpi">
          <span>Monitorati</span>
          <strong>{monitoredInUniverse.length}</strong>
          <small>{nearMonitored.length} vicini entro +/-3%</small>
        </article>
        <article className="marketKpi">
          <span>Score disponibili</span>
          <strong>{scannedRows.length || "n/d"}</strong>
          <small>{scannedRows.length ? `${liquidScannedRows.length} liquidi, ${lowLiquidityScannedRows.length} esclusi per liquidita` : "premi Scansiona per aggiornare"}</small>
        </article>
        <article className="marketKpi highlight">
          <span>Migliore candidato</span>
          <strong>{bestCandidate?.ticker || "n/d"}</strong>
          <small>{bestCandidate ? `score ${bestCandidate.score} | oggi ${pct(bestCandidate.change_1d_pct)}` : "nessuno scan recente"}</small>
        </article>
      </div>

      {visibleCandidates.length > 0 && (
        <>
          <h3>Nuovi candidati operativi liquidi dopo scanner</h3>
          <div className="cardsGrid commoditiesGrid">
            {visibleCandidates.map((item) => (
              <div className="commodityCard" key={item.ticker}>
                <div className="commodityCardHeader">
                  <div>
                    <b>{item.ticker}</b>
                    <span>{item.name}</span>
                  </div>
                  <div className="badgeStack">
                    <span className={`scoreBadge ${Number(item.score) >= 7 ? "good" : Number(item.score) >= 4 ? "warning" : "neutral"}`}>score {item.score}</span>
                    <span className={`scoreBadge ${item.liquidity_ok === false ? "bad" : "good"}`}>
                      {item.liquidity_ok === false ? "liquidita bassa" : "liquidita ok"}
                    </span>
                  </div>
                </div>
                <div className="commodityStats">
                  <div><span>Prezzo</span><b>{price(item.close)}</b></div>
                  <div><span>Oggi</span><b className={signedClass(item.change_1d_pct)}>{pct(item.change_1d_pct)}</b></div>
                  <div><span>RSI</span><b>{price(item.rsi)}</b></div>
                  <div><span>ADX</span><b>{price(item.adx)}</b></div>
                  <div><span>Vol MA10</span><b>{Number(item.avg_volume || item.volume_ma10 || 0).toLocaleString("it-IT", { maximumFractionDigits: 0 })}</b></div>
                  <div><span>Turnover</span><b>{eur(item.turnover_eur)}</b></div>
                  <div><span>Supporto</span><b>{price(item.support_10)}</b></div>
                  <div><span>Resistenza</span><b>{price(item.resistance_10)}</b></div>
                </div>
                <div className="signalLists">
                  <p><strong>Ragioni:</strong> {(item.reasons || []).join("; ") || "n/d"}</p>
                  <p><strong>Rischi:</strong> {(item.risks || []).join("; ") || "n/d"}</p>
                </div>
                <div className="cardActions">
                  <button className="chartButton" onClick={() => onChart({
                    ticker: item.ticker,
                    condition: chartCondition(item),
                  })}><LineChart size={16} /> Grafico</button>
                  <NewsButton ticker={item.ticker} />
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {heldScannerRows.length > 0 && (
        <div className="heldScannerPanel">
          <div>
            <h3>Posizioni gia in portafoglio rilevate dallo scanner</h3>
            <p>
              Questi titoli non sono nuovi ingressi: lo scanner li considera tecnicamente interessanti,
              ma vanno letti nella sezione Portafoglio e Condizioni di uscita.
            </p>
          </div>
          <div className="heldScannerList">
            {heldScannerRows.map((item) => (
              <button
                key={item.ticker}
                className="heldScannerItem"
                onClick={() => onChart({
                  ticker: item.ticker,
                  condition: chartCondition(item),
                })}
              >
                <strong>{item.ticker}</strong>
                <span>score {item.score} | oggi {pct(item.change_1d_pct)}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="marketToolbar">
        <div>
          <h3>Vista operativa universo</h3>
          <p>Filtra per stato operativo, liquidita o cerca direttamente un ticker.</p>
        </div>
        <div className="marketFilters">
          <div className="segmentedControl">
            {filterOptions.map(([id, label]) => (
              <button key={id} className={filter === id ? "active" : ""} onClick={() => setFilter(id)}>
                {label}
              </button>
            ))}
          </div>
          <input
            className="marketSearch"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={`Cerca in ${title}...`}
          />
        </div>
      </div>
      {!activeUniverseRows.length ? (
        <div className="emptyState">{emptyText}</div>
      ) : (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                {universeColumns.map((column) => <th key={column.key}>{column.label}</th>)}
                <th>Stato</th>
                <th>Score</th>
                <th>Trigger / liquidita</th>
                <th>Azioni</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((row) => {
                const ticker = String(row.ticker || "").toUpperCase();
                const monitored = monitoredByTicker.get(ticker);
                const inPortfolio = positionByTicker.has(ticker);
                const isCandidate = isOperationalCandidate(row);
                const scannedButWeak = hasScore(row) && row.liquidity_ok !== false && !isCandidate && !inPortfolio;
                return (
                  <tr key={row.ticker}>
                    {universeColumns.map((column) => (
                      <td key={column.key} className={column.key === "ticker" ? "ticker" : ""}>
                        {column.render ? column.render(row) : row[column.key] || "n/d"}
                      </td>
                    ))}
                    <td>
                      <div className="statusStack">
                        {monitored && <span className={`status ${monitored.trigger_status_kind || "warning"}`}>{monitored.trigger_status || "monitorato"}</span>}
                        {inPortfolio && <span className="status portfolio">in portafoglio</span>}
                        {isCandidate && <span className="status positive">nuovo candidato</span>}
                        {hasScore(row) && row.liquidity_ok === false && <span className="status danger">escluso liquidita</span>}
                        {scannedButWeak && <span className="status neutral">score sotto soglia</span>}
                        {!monitored && !inPortfolio && !isCandidate && !hasScore(row) && <span className="status neutral">universo</span>}
                      </div>
                    </td>
                    <td>
                      {hasScore(row) ? (
                        <div className="scoreCell">
                          <b>{row.score}</b>
                          <span className={signedClass(row.change_1d_pct)}>{pct(row.change_1d_pct)}</span>
                        </div>
                      ) : "n/d"}
                    </td>
                    <td className="operationalCell">
                      {monitored ? (
                        <>
                          <b>{price(monitored.trigger_level)}</b>
                          <span>{monitored.trigger_distance_pct !== null && monitored.trigger_distance_pct !== undefined ? `${pct(monitored.trigger_distance_pct)} dal trigger` : "trigger monitorato"}</span>
                        </>
                      ) : inPortfolio ? (
                        <>
                          <b>posizione aperta</b>
                          <span>Gestire da Portafoglio e Condizioni di uscita; non e un nuovo ingresso.</span>
                        </>
                      ) : isCandidate ? (
                        <>
                          <b>{row.liquidity_ok === false ? "liquidita bassa" : "liquidita ok"}</b>
                          <span>{(row.reasons || []).slice(0, 2).join("; ") || "segnali tecnici"}</span>
                        </>
                      ) : scannedButWeak ? (
                        <>
                          <b>non operativo</b>
                          <span>Score {row.score} sotto soglia {minOperationalScore}; resta visibile solo come risultato scanner.</span>
                        </>
                      ) : (
                        <span>Da valutare con scanner</span>
                      )}
                    </td>
                    <td className="rowActions">
                      <button className="miniButton" onClick={() => onChart({
                        ticker: row.ticker,
                        condition: monitored?.condition || chartCondition(row) || row.name || title,
                      })}><LineChart size={15} /> Grafico</button>
                      <NewsButton ticker={row.ticker} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {activeUniverseRows.length > 0 && filteredRows.length === 0 && <div className="emptyState">Nessuno strumento corrisponde ai filtri impostati.</div>}
      <p className="small">
        Questo mercato entra nello stesso funnel operativo: scanner tecnico, short-list dei candidati interessanti, approfondimento selettivo e solo poi trigger/proposte.
      </p>
    </section>
  );
}

function FtseMib({ rows = [], monitoredRows = [], positions = [], onChart }) {
  return (
    <MarketScanner
      title="FTSE MIB"
      subtitle="Azioni italiane dello stesso universo finora chiamato MIB30 nel codice storico."
      marketKey="ftse_mib"
      rows={rows}
      monitoredRows={monitoredRows}
      positions={positions}
      scanEndpoint="/api/ftse-mib/scan"
      countLabel="titoli disponibili"
      emptyText="File validtickers_IT_MIB30_with_sector.xlsx non trovato o vuoto."
      universeColumns={[
        { key: "ticker", label: "Ticker" },
        { key: "name", label: "Nome" },
        { key: "sector", label: "Settore" },
        { key: "industry", label: "Industry" },
      ]}
      chartCondition={(item) => `FTSE MIB. Trigger tecnico: chiusura sopra ${price(item.resistance_10)} con volumi; supporto ${price(item.support_10)}.`}
      onChart={onChart}
    />
  );
}

function Commodities({ rows = [], monitoredRows = [], positions = [], onChart }) {
  return (
    <MarketScanner
      title="Materie prime"
      subtitle="ETC/ETN e strumenti legati a commodity caricati da MateriePrime.xlsx."
      marketKey="commodities"
      rows={rows}
      monitoredRows={monitoredRows}
      positions={positions}
      scanEndpoint="/api/commodities/scan"
      countLabel="strumenti da MateriePrime.xlsx"
      emptyText="File MateriePrime.xlsx non trovato o vuoto."
      universeColumns={[
        { key: "ticker", label: "Ticker" },
        { key: "name", label: "Nome" },
        {
          key: "last_yfinance_read_at",
          label: "Ultima lettura yfinance",
          render: (item) => yfinanceReadTime(item.last_yfinance_read_at || item.scan_updated_at),
        },
      ]}
      chartCondition={(item) => `Materia prima / ETC. Trigger tecnico: chiusura sopra ${price(item.resistance_10)} con volumi; supporto ${price(item.support_10)}.`}
      onChart={onChart}
    />
  );
}

function Etfs({ rows = [], monitoredRows = [], positions = [], onChart }) {
  return (
    <MarketScanner
      title="ETF"
      subtitle="ETF tematici configurati manualmente. Per ora include ROBO.MI, Robotics and Automation."
      marketKey="etfs"
      rows={rows}
      monitoredRows={monitoredRows}
      positions={positions}
      scanEndpoint="/api/etfs/scan"
      countLabel="ETF configurati"
      emptyText="Nessun ETF configurato."
      universeColumns={[
        { key: "ticker", label: "Ticker" },
        { key: "name", label: "Nome" },
        { key: "description", label: "Descrizione" },
      ]}
      chartCondition={(item) => `ETF. Trigger tecnico: chiusura sopra ${price(item.resistance_10)} con volumi; supporto ${price(item.support_10)}.`}
      onChart={onChart}
    />
  );
}

function PriceChart({ prices = [], triggerLevel, supportLevel, entryPrice, entryDate, mode = "candles" }) {
  const [hoverIndex, setHoverIndex] = useState(null);
  const width = 1040;
  const height = 500;
  const pad = { top: 34, right: 142, bottom: 70, left: 88 };
  const plotW = width - pad.left - pad.right;
  const volumeH = 64;
  const volumeGap = 14;
  const pricePlotH = height - pad.top - pad.bottom - volumeH - volumeGap;
  const volumeTop = pad.top + pricePlotH + volumeGap;
  const plotBottom = volumeTop + volumeH;
  const priceValues = prices
    .flatMap((row) => [row.open, row.high, row.low, row.close].map(Number))
    .filter((value) => !Number.isNaN(value));
  const closeValues = prices.map((row) => Number(row.close)).filter((value) => !Number.isNaN(value));
  const volumeValues = prices.map((row) => Number(row.volume)).filter((value) => !Number.isNaN(value) && value > 0);
  const maxVolume = Math.max(...volumeValues, 1);
  const levels = [triggerLevel, supportLevel, entryPrice].map(Number).filter((value) => !Number.isNaN(value) && value > 0);
  const min = Math.min(...priceValues, ...levels);
  const max = Math.max(...priceValues, ...levels);
  const span = max - min || 1;
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.08;
  const x = (index) => pad.left + (prices.length <= 1 ? 0 : (index / (prices.length - 1)) * plotW);
  const y = (value) => pad.top + ((yMax - value) / (yMax - yMin)) * pricePlotH;
  const volumeY = (value) => plotBottom - (Number(value || 0) / maxVolume) * volumeH;
  const candleW = Math.max(3, Math.min(12, plotW / Math.max(prices.length, 1) * 0.58));
  const volumeW = Math.max(2, Math.min(9, plotW / Math.max(prices.length, 1) * 0.72));
  const path = prices
    .map((row, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(Number(row.close)).toFixed(2)}`)
    .join(" ");
  const area = `${path} L ${pad.left + plotW} ${pad.top + pricePlotH} L ${pad.left} ${pad.top + pricePlotH} Z`;
  const ticks = Array.from({ length: 5 }, (_, index) => yMin + ((yMax - yMin) / 4) * index);
  const last = prices[prices.length - 1];
  const first = prices[0];
  const hover = hoverIndex === null ? last : prices[hoverIndex];
  const hoverX = hover ? x(hoverIndex === null ? prices.length - 1 : hoverIndex) : null;
  const hoverOpen = hover ? Number(hover.open) : null;
  const hoverClose = hover ? Number(hover.close) : null;
  const hoverDailyPct = hoverOpen && hoverClose && Number.isFinite(hoverOpen) && Number.isFinite(hoverClose) && hoverOpen !== 0
    ? ((hoverClose - hoverOpen) / hoverOpen) * 100
    : null;
  const rightLabelItems = [
    { key: "trigger", value: Number(triggerLevel) },
    { key: "support", value: Number(supportLevel) },
    { key: "entry", value: Number(entryPrice) },
    { key: "price", value: last ? Number(last.close) : NaN },
  ]
    .filter((item) => Number.isFinite(item.value) && item.value > 0)
    .map((item) => ({ ...item, lineY: y(item.value), labelY: y(item.value) + 4 }))
    .sort((a, b) => a.labelY - b.labelY);
  const minimumLabelGap = 18;
  rightLabelItems.forEach((item, index) => {
    const minimumY = index === 0 ? pad.top + 8 : rightLabelItems[index - 1].labelY + minimumLabelGap;
    item.labelY = Math.max(item.labelY, minimumY);
  });
  const labelOverflow = rightLabelItems.length
    ? rightLabelItems[rightLabelItems.length - 1].labelY - (pad.top + pricePlotH - 4)
    : 0;
  if (labelOverflow > 0) {
    rightLabelItems.forEach((item) => { item.labelY -= labelOverflow; });
  }
  const rightLabelLayout = Object.fromEntries(rightLabelItems.map((item) => [item.key, item]));
  const bandTop = Number(triggerLevel) > 0 ? y(Number(triggerLevel)) : null;
  const bandBottom = Number(supportLevel) > 0 ? y(Number(supportLevel)) : null;
  const dateTicks = prices
    .map((row, index) => ({ ...row, index }))
    .filter((row, index) => {
      if (index === 0 || index === prices.length - 1) return true;
      const previous = prices[index - 1];
      if (!previous) return false;
      if (prices.length <= 45) return index % 5 === 0;
      return String(row.date || "").slice(0, 7) !== String(previous.date || "").slice(0, 7);
    });
  const entryDay = String(entryDate || "").slice(0, 10);
  const entryIndex = entryDay
    ? prices.findIndex((row) => String(row.date || "").slice(0, 10) === entryDay)
    : -1;

  function LevelLine({ value, label, className, layoutKey }) {
    const level = Number(value);
    if (Number.isNaN(level) || level <= 0) return null;
    const ly = y(level);
    const labelY = rightLabelLayout[layoutKey]?.labelY ?? ly + 4;
    return (
      <g className={className}>
        <line x1={pad.left} x2={pad.left + plotW} y1={ly} y2={ly} />
        {Math.abs(labelY - (ly + 4)) > 2 && (
          <line className="levelLabelConnector" x1={pad.left + plotW} x2={pad.left + plotW + 9} y1={ly} y2={labelY - 4} />
        )}
        <text x={pad.left + plotW + 12} y={labelY}>{label} {price(level)}</text>
      </g>
    );
  }

  if (!prices.length) return <div className="chartEmpty">Nessun dato prezzo disponibile.</div>;

  return (
    <svg
      className="priceChart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      onMouseMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        const localX = ((event.clientX - box.left) / box.width) * width;
        const ratio = Math.max(0, Math.min(1, (localX - pad.left) / plotW));
        setHoverIndex(Math.round(ratio * (prices.length - 1)));
      }}
      onMouseLeave={() => setHoverIndex(null)}
    >
      <defs>
        <linearGradient id="priceArea" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#2563eb" stopOpacity="0.22" />
          <stop offset="100%" stopColor="#2563eb" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <rect x="0" y="0" width={width} height={height} rx="8" />
      {ticks.map((tick) => (
        <g key={tick} className="gridLine">
          <line x1={pad.left} x2={pad.left + plotW} y1={y(tick)} y2={y(tick)} />
          <text x={pad.left - 14} y={y(tick) + 4} textAnchor="end">{price(tick)}</text>
        </g>
      ))}
      {dateTicks.map((tick) => (
        <g key={`${tick.date}-${tick.index}`} className="dateTick">
          <line x1={x(tick.index)} x2={x(tick.index)} y1={plotBottom} y2={plotBottom + 7} />
          <text x={x(tick.index)} y={height - 28}>{shortDate(tick.date)}</text>
        </g>
      ))}
      {bandTop !== null && bandBottom !== null && (
        <rect
          className="triggerBand"
          x={pad.left}
          y={Math.min(bandTop, bandBottom)}
          width={plotW}
          height={Math.abs(bandBottom - bandTop)}
        />
      )}
      {entryIndex >= 0 && (
        <g className="entryDateMarker">
          <line x1={x(entryIndex)} x2={x(entryIndex)} y1={pad.top} y2={plotBottom} />
          <circle cx={x(entryIndex)} cy={y(Number(entryPrice))} r="5" />
          <rect x={Math.min(x(entryIndex) + 8, pad.left + plotW - 142)} y={pad.top + 8} width="142" height="25" rx="6" />
          <text x={Math.min(x(entryIndex) + 16, pad.left + plotW - 134)} y={pad.top + 25}>INGRESSO {shortDate(entryDay)}</text>
        </g>
      )}
      {mode === "line" ? (
        <>
          <path className="areaPath" d={area} />
          <path className="pricePath" d={path} />
        </>
      ) : (
        <g className="candles">
          {prices.map((row, index) => {
            const open = Number(row.open);
            const high = Number(row.high);
            const low = Number(row.low);
            const close = Number(row.close);
            if ([open, high, low, close].some((value) => Number.isNaN(value))) return null;
            const up = close >= open;
            const bodyY = Math.min(y(open), y(close));
            const bodyH = Math.max(2, Math.abs(y(open) - y(close)));
            return (
              <g key={`${row.date}-${index}`} className={up ? "candleUp" : "candleDown"}>
                <line x1={x(index)} x2={x(index)} y1={y(high)} y2={y(low)} />
                <rect x={x(index) - candleW / 2} y={bodyY} width={candleW} height={bodyH} rx="1.5" />
              </g>
            );
          })}
        </g>
      )}
      <g className="inlineVolumes">
        <line x1={pad.left} x2={pad.left + plotW} y1={plotBottom} y2={plotBottom} />
        <text x={pad.left - 14} y={volumeTop + 12} textAnchor="end">Vol</text>
        {prices.map((row, index) => {
          const open = Number(row.open);
          const close = Number(row.close);
          const volume = Number(row.volume);
          if (Number.isNaN(volume) || volume <= 0) return null;
          const up = !Number.isNaN(open) && !Number.isNaN(close) ? close >= open : true;
          const barY = volumeY(volume);
          return (
            <rect
              key={`volume-${row.date}-${index}`}
              className={up ? "volumeUp" : "volumeDown"}
              x={x(index) - volumeW / 2}
              y={barY}
              width={volumeW}
              height={Math.max(1, plotBottom - barY)}
              rx="1"
            />
          );
        })}
      </g>
      <LevelLine value={triggerLevel} label="TRIGGER" className="triggerLine" layoutKey="trigger" />
      <LevelLine value={supportLevel} label="SUPPORTO" className="supportLine" layoutKey="support" />
      <LevelLine value={entryPrice} label="INGRESSO" className="entryLine" layoutKey="entry" />
      {last && (
        <g className="lastPoint">
          <circle cx={x(prices.length - 1)} cy={y(Number(last.close))} r="5" />
          {Math.abs((rightLabelLayout.price?.labelY ?? y(Number(last.close))) - (y(Number(last.close)) + 4)) > 2 && (
            <line className="levelLabelConnector" x1={pad.left + plotW} x2={pad.left + plotW + 9} y1={y(Number(last.close))} y2={(rightLabelLayout.price?.labelY ?? y(Number(last.close))) - 4} />
          )}
          <text x={pad.left + plotW + 12} y={rightLabelLayout.price?.labelY ?? y(Number(last.close)) + 4}>PREZZO {price(last.close)}</text>
        </g>
      )}
      {hover && hoverX !== null && (
        <g className="hoverLayer">
          <line x1={hoverX} x2={hoverX} y1={pad.top} y2={plotBottom} />
          <circle cx={hoverX} cy={y(Number(hover.close))} r="4" />
          <g transform={`translate(${Math.min(hoverX + 12, width - 190)} ${pad.top + 12})`}>
            <rect width="170" height="76" rx="8" />
            <text x="10" y="22">{hover.date}</text>
            <text x="10" y="44">Close {price(hover.close)}</text>
            <text x="10" y="64" className={hoverDailyPct !== null && hoverDailyPct >= 0 ? "tooltipPositive" : "tooltipNegative"}>
              Giorno {pct(hoverDailyPct)}
            </text>
          </g>
        </g>
      )}
      <g className="axisLabels">
        <text x={pad.left} y={height - 8}>{first?.date}</text>
        <text x={pad.left + plotW} y={height - 8} textAnchor="end">{last?.date}</text>
      </g>
    </svg>
  );
}

function TechnicalChart({ prices = [], type }) {
  const width = 1040;
  const height = 430;
  const pad = { top: 34, right: 96, bottom: 66, left: 88 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const configs = {
    volume: {
      title: "Volumi + medie",
      series: [
        { key: "volume", label: "Volume", color: "#64748b", kind: "bar", signedBy: "close" },
        { key: "vol_ma5", label: "MA5", color: "#f97316" },
        { key: "vol_ma10", label: "MA10", color: "#2563eb" },
      ],
      yMin: 0,
    },
    oscillators: {
      title: "RSI / Stocastico / Williams %R",
      series: [
        { key: "rsi", label: "RSI", color: "#f59e0b" },
        { key: "stoch_k", label: "Stoch K", color: "#2563eb" },
        { key: "stoch_d", label: "Stoch D", color: "#ef4444" },
        { key: "williams_r", label: "Williams %R", color: "#0ea5e9" },
      ],
      guides: [
        { value: 70, label: "70", color: "#60a5fa" },
        { value: 50, label: "50", color: "#f59e0b" },
        { value: 30, label: "30", color: "#22c55e" },
        { value: -20, label: "W -20", color: "#0ea5e9" },
        { value: -80, label: "W -80", color: "#0ea5e9" },
      ],
      yMin: -100,
      yMax: 100,
    },
    macd: {
      title: "MACD / Signal / Histogram",
      series: [
        { key: "macd_hist", label: "Histogram", color: "#16a34a", negativeColor: "#ef4444", kind: "barZero" },
        { key: "macd", label: "MACD", color: "#2563eb" },
        { key: "macd_signal", label: "Signal", color: "#ef4444" },
      ],
      guides: [{ value: 0, label: "0", color: "#94a3b8" }],
    },
    adx: {
      title: "ADX + DI",
      series: [
        { key: "adx", label: "ADX", color: "#16a34a" },
        { key: "plus_di", label: "DI+", color: "#2563eb" },
        { key: "minus_di", label: "DI-", color: "#f97316" },
      ],
      guides: [{ value: 25, label: "25 trend", color: "#ef4444" }],
      yMin: 0,
    },
  };
  const config = configs[type] || configs.volume;
  const values = prices
    .flatMap((row) => config.series.map((serie) => numeric(row[serie.key])))
    .filter((value) => value !== null);
  if (!prices.length || !values.length) return <div className="chartEmpty">Nessun dato tecnico disponibile.</div>;

  const guideValues = (config.guides || []).map((guide) => guide.value);
  const min = config.yMin ?? Math.min(...values, ...guideValues);
  const max = config.yMax ?? Math.max(...values, ...guideValues);
  const span = max - min || 1;
  const yMin = config.yMin ?? min - span * 0.12;
  const yMax = config.yMax ?? max + span * 0.12;
  const x = (index) => pad.left + (prices.length <= 1 ? 0 : (index / (prices.length - 1)) * plotW);
  const y = (value) => pad.top + ((yMax - value) / (yMax - yMin)) * plotH;
  const ticks = Array.from({ length: 5 }, (_, index) => yMin + ((yMax - yMin) / 4) * index);
  const barW = Math.max(2, Math.min(13, plotW / Math.max(prices.length, 1) * 0.62));
  const dateTicks = prices
    .map((row, index) => ({ ...row, index }))
    .filter((row, index) => {
      if (index === 0 || index === prices.length - 1) return true;
      const previous = prices[index - 1];
      if (!previous) return false;
      if (prices.length <= 45) return index % 5 === 0;
      return String(row.date || "").slice(0, 7) !== String(previous.date || "").slice(0, 7);
    });

  function linePath(serie) {
    return prices
      .map((row, index) => ({ value: numeric(row[serie.key]), index }))
      .filter((point) => point.value !== null)
      .map((point, index) => `${index === 0 ? "M" : "L"} ${x(point.index).toFixed(2)} ${y(point.value).toFixed(2)}`)
      .join(" ");
  }

  return (
    <svg className="priceChart technicalChart" viewBox={`0 0 ${width} ${height}`} role="img">
      <rect x="0" y="0" width={width} height={height} rx="8" />
      <text className="chartTitle" x={pad.left} y="22">{config.title}</text>
      {ticks.map((tick) => (
        <g key={tick} className="gridLine">
          <line x1={pad.left} x2={pad.left + plotW} y1={y(tick)} y2={y(tick)} />
          <text x={pad.left - 14} y={y(tick) + 4} textAnchor="end">{price(tick)}</text>
        </g>
      ))}
      {(config.guides || []).map((guide) => (
        <g key={guide.label} className="guideLine">
          <line x1={pad.left} x2={pad.left + plotW} y1={y(guide.value)} y2={y(guide.value)} style={{ stroke: guide.color }} />
          <text x={pad.left + plotW + 10} y={y(guide.value) + 4}>{guide.label}</text>
        </g>
      ))}
      {dateTicks.map((tick) => (
        <g key={`${tick.date}-${tick.index}`} className="dateTick">
          <line x1={x(tick.index)} x2={x(tick.index)} y1={pad.top + plotH} y2={pad.top + plotH + 7} />
          <text x={x(tick.index)} y={height - 26}>{shortDate(tick.date)}</text>
        </g>
      ))}
      {config.series.map((serie) => {
        if (serie.kind === "bar" || serie.kind === "barZero") {
          const zeroY = serie.kind === "barZero" ? y(0) : y(0);
          return (
            <g key={serie.key} className="indicatorBars">
              {prices.map((row, index) => {
                const value = numeric(row[serie.key]);
                if (value === null) return null;
                const up = serie.signedBy ? Number(row.close) >= Number(row.open) : value >= 0;
                const top = Math.min(y(value), zeroY);
                const heightValue = Math.max(1, Math.abs(zeroY - y(value)));
                return (
                  <rect
                    key={`${serie.key}-${row.date}`}
                    x={x(index) - barW / 2}
                    y={top}
                    width={barW}
                    height={heightValue}
                    fill={up ? serie.color : (serie.negativeColor || "#ef4444")}
                  />
                );
              })}
            </g>
          );
        }
        return <path key={serie.key} className="indicatorLine" d={linePath(serie)} style={{ stroke: serie.color }} />;
      })}
      <g className="legend">
        {config.series.map((serie, index) => (
          <g key={serie.key} transform={`translate(${pad.left + index * 140} ${height - 14})`}>
            <line x1="0" x2="18" y1="0" y2="0" style={{ stroke: serie.color }} />
            <text x="24" y="4">{serie.label}</text>
          </g>
        ))}
      </g>
    </svg>
  );
}

function ChartModal({ item, onClose }) {
  const [state, setState] = useState({ loading: true, error: "", prices: [] });
  const [auditState, setAuditState] = useState(null);
  const [period, setPeriod] = useState("6mo");
  const [mode, setMode] = useState("candles");
  const [view, setView] = useState("price");
  const ticker = item?.ticker;

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setState({ loading: true, error: "", prices: [] });
    api(`/api/chart/${encodeURIComponent(ticker)}?period=${period}&interval=1d`)
      .then((result) => {
        if (!cancelled) setState({ loading: false, error: "", prices: result.prices || [] });
      })
      .catch((error) => {
        if (!cancelled) setState({ loading: false, error: error.message, prices: [] });
      });
    return () => { cancelled = true; };
  }, [ticker, period]);

  useEffect(() => {
    if (!item || item.entry_audit || !item.portfolio_id || !ticker) {
      setAuditState(item?.entry_audit || null);
      return;
    }
    let cancelled = false;
    const query = new URLSearchParams({ ticker });
    if (item.current_price != null) query.set("current_price", item.current_price);
    if (item.entry_price != null) query.set("entry_price", item.entry_price);
    api(`/api/portfolios/${encodeURIComponent(item.portfolio_id)}/exit-conditions?${query.toString()}`, { timeoutMs: 4000 })
      .then((result) => {
        const row = (result.exit_conditions || []).find(
          (candidate) => String(candidate.ticker || "").toUpperCase() === String(ticker).toUpperCase(),
        );
        if (!cancelled) setAuditState(row?.entry_audit || null);
      })
      .catch(() => { if (!cancelled) setAuditState(null); });
    return () => { cancelled = true; };
  }, [item, ticker]);

  if (!item) return null;
  const parsedLevels = levelsFromCondition(item.condition || "");
  const triggerLevel = numeric(item.trigger_level) || parsedLevels.trigger;
  const supportLevel = numeric(item.support_level) || parsedLevels.support;
  const entryPrice = numeric(item.entry_price);
  const entryDate = item.opened_at;
  const lastPrice = state.prices.length ? numeric(state.prices[state.prices.length - 1]?.close) : null;
  const currentPrice = numeric(item.current_price) || lastPrice;
  const distance = numeric(item.trigger_distance_pct)
    ?? (currentPrice && triggerLevel ? ((triggerLevel - currentPrice) / currentPrice) * 100 : null);
  const parsedNote = (!numeric(item.trigger_level) && parsedLevels.trigger) || (!numeric(item.support_level) && parsedLevels.support);
  const entryAudit = item.entry_audit || auditState;
  return (
    <div className="modalBackdrop" onClick={onClose}>
      <div className="chartModal" onClick={(event) => event.stopPropagation()}>
        <div className="modalHeader">
          <div>
            <h2><LineChart size={22} /> Grafico {ticker}</h2>
            <p>{item.condition || "Prezzo e livelli operativi"}</p>
          </div>
          <button className="iconOnly" onClick={onClose} aria-label="Chiudi"><X size={20} /></button>
        </div>
        <div className="chartSummary">
          <span>Prezzo attuale <b>{price(currentPrice)}</b></span>
          {entryPrice && <span>Prezzo ingresso <b>{price(entryPrice)}</b></span>}
          {entryDate && <span>Data ingresso <b>{dateTime(entryDate)}</b></span>}
          <span>Trigger <b>{price(triggerLevel)}</b></span>
          <span>Supporto/stop <b>{price(supportLevel)}</b></span>
          <span>Distanza trigger <b className={signedClass(distance)}>{pct(distance)}</b></span>
        </div>
        {parsedNote && (
          <div className="chartLevelNote">
            Livelli letti dalla condizione ingresso e disegnati sul grafico prezzo.
          </div>
        )}
        {entryAudit?.available && (
          <details className="entryAudit">
            <summary>Perché è stato acquistato · verifica condizioni registrate</summary>
            <div className="entryAuditBody">
              <p className="entryAuditCondition"><strong>Condizione originale</strong>{entryAudit.condition || "Condizione non registrata"}</p>
              <div className="entryAuditGrid">
                <span><small>Decisione</small><b>{entryAudit.scenario_type || "n/d"}</b></span>
                <span><small>Data ordine</small><b>{dateTime(entryAudit.confirmed_at)}</b></span>
                <span><small>Prezzo osservato</small><b>{price(entryAudit.observed_price)}</b></span>
                <span><small>Prezzo eseguito</small><b>{price(entryAudit.entry_price)}</b></span>
                <span><small>Trigger</small><b>{price(entryAudit.trigger)}</b></span>
                <span><small>Supporto</small><b>{price(entryAudit.support)}</b></span>
                <span><small>Area ingresso</small><b>{entryAudit.entry_area_min != null || entryAudit.entry_area_max != null ? `${price(entryAudit.entry_area_min)} – ${price(entryAudit.entry_area_max)}` : "n/d"}</b></span>
                <span><small>Volume effettivo</small><b>{entryAudit.volume_ratio != null ? `${Number(entryAudit.volume_ratio).toFixed(3)}× MA10` : "n/d"}</b></span>
                <span><small>Ritmo intraday</small><b>{entryAudit.intraday_volume_pace_ratio != null ? `${Number(entryAudit.intraday_volume_pace_ratio).toFixed(3)}× MA10` : "n/d"}</b></span>
                <span><small>Volume richiesto</small><b>{entryAudit.required_volume_ratio != null ? `${Number(entryAudit.required_volume_ratio).toFixed(2)}× MA10` : "n/d"}</b></span>
                <span><small>Grafico confermava ingresso</small><b>{entryAudit.chart_entry_confirmed === true ? "Sì" : entryAudit.chart_entry_confirmed === false ? "No" : "Non registrato"}</b></span>
                <span><small>News negative</small><b>{entryAudit.news_negative === true ? "Sì" : entryAudit.news_negative === false ? "No" : "Non registrato"}</b></span>
                <span><small>Controllo rischio</small><b>{entryAudit.risk_allowed === true ? `Superato${entryAudit.risk_amount != null ? ` · ${eur(entryAudit.risk_amount)}` : ""}` : entryAudit.risk_allowed === false ? "Bloccato" : "Non registrato"}</b></span>
                <span><small>ID proposta</small><b>{entryAudit.proposal_id || "n/d"}</b></span>
              </div>
              <p><strong>Esito tecnico registrato</strong>{entryAudit.scenario_reason || "n/d"}</p>
              <p><strong>Motivazione ordine</strong>{entryAudit.reason || "n/d"}</p>
              <em>{entryAudit.data_note}</em>
            </div>
          </details>
        )}
        <div className="chartToolbar">
          <div className="segmented">
            {[["5d", "5g"], ["1mo", "1m"], ["3mo", "3m"], ["6mo", "6m"], ["1y", "1a"], ["2y", "2a"]].map(([value, label]) => (
              <button key={value} className={period === value ? "active" : ""} onClick={() => setPeriod(value)}>{label}</button>
            ))}
          </div>
          <div className="segmented">
            <button className={mode === "candles" ? "active" : ""} onClick={() => setMode("candles")}>Candele</button>
            <button className={mode === "line" ? "active" : ""} onClick={() => setMode("line")}>Linea</button>
          </div>
          <div className="segmented chartViews">
            {[
              ["all", "Tutti"],
              ["price", "Prezzo"],
              ["volume", "Volumi"],
              ["oscillators", "RSI/Stoch/W%R"],
              ["macd", "MACD"],
              ["adx", "ADX"],
            ].map(([id, label]) => (
              <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>{label}</button>
            ))}
          </div>
        </div>
        {state.loading && <div className="chartStatus">Caricamento storico prezzi...</div>}
        {state.error && <div className="error">{state.error}</div>}
        {!state.loading && !state.error && (
          view === "all" ? (
            <div className="allChartsStack">
              <div>
                <h3>Prezzo</h3>
                <PriceChart prices={state.prices} triggerLevel={triggerLevel} supportLevel={supportLevel} entryPrice={entryPrice} entryDate={entryDate} mode={mode} />
              </div>
              <div>
                <h3>Volumi</h3>
                <TechnicalChart prices={state.prices} type="volume" />
              </div>
              <div>
                <h3>RSI / Stocastico / Williams %R</h3>
                <TechnicalChart prices={state.prices} type="oscillators" />
              </div>
              <div>
                <h3>MACD</h3>
                <TechnicalChart prices={state.prices} type="macd" />
              </div>
              <div>
                <h3>ADX</h3>
                <TechnicalChart prices={state.prices} type="adx" />
              </div>
            </div>
          ) : view === "price"
            ? <PriceChart prices={state.prices} triggerLevel={triggerLevel} supportLevel={supportLevel} entryPrice={entryPrice} entryDate={entryDate} mode={mode} />
            : <TechnicalChart prices={state.prices} type={view} />
        )}
      </div>
    </div>
  );
}

function Actions({ rows = [] }) {
  return (
    <section className="panel">
      <h2>Azioni agente recenti</h2>
      <div className="tableWrap">
        <table>
          <thead><tr><th>Quando</th><th>Stato</th><th>Azione</th><th>Ticker</th><th>Motivo</th></tr></thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.confirmed_at || row.rejected_at || row.created_at}</td>
                <td><span className={`pill ${row.status === "confirmed" ? "positive" : "neutral"}`}>{row.status}</span></td>
                <td>{row.action}</td>
                <td>
                  <div className="tickerWithAction">
                    <span className="ticker">{row.ticker}</span>
                    <NewsButton ticker={row.ticker} compact />
                  </div>
                </td>
                <td className="reason">{row.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Chat({ portfolioId = "main" }) {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Ciao, sono Autonomous Trading Agent. Chiedimi stato, performance, condizioni o nuove analisi." },
  ]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  async function send(message = text) {
    if (!message.trim() || busy) return;
    const next = [...messages, { role: "user", content: message }];
    setMessages(next);
    setText("");
    setBusy(true);
    try {
      const result = await api("/api/agent/chat", {
        method: "POST",
        body: JSON.stringify({ message, history: messages, portfolio_id: portfolioId }),
        timeoutMs: 900000,
      });
      setMessages([...next, { role: "assistant", content: result.answer }]);
    } catch (error) {
      setMessages([...next, { role: "assistant", content: `Errore: ${error.message}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel chatPanel">
      <h2><MessageSquare size={20} /> Chat agente</h2>
      <div className="quickActions">
        {["mostra stato operativo", "mostra performance", "rivaluta condizioni monitorate"].map((item) => (
          <button key={item} onClick={() => send(item)} disabled={busy}>{item}</button>
        ))}
      </div>
      <div className="messages">
        {messages.map((message, index) => (
          <div key={index} className={`message ${message.role}`}>
            <MarkdownMessage content={message.content} />
          </div>
        ))}
        {busy && (
          <div className="message assistant pending">
            <div className="typingDots"><span /> <span /> <span /></div>
            <p>Sto analizzando la richiesta. Se servono grafici, scan o agent tool posso impiegare qualche minuto.</p>
          </div>
        )}
      </div>
      <form className="chatInput" onSubmit={(event) => { event.preventDefault(); send(); }}>
        <input value={text} onChange={(event) => setText(event.target.value)} placeholder="Scrivi all'agente..." />
        <button disabled={busy}><Send size={18} /></button>
      </form>
    </section>
  );
}

function DeepPortfolioReport({ report }) {
  if (!report) return null;
  const items = report.items || [];
  const portfolio = report.portfolio || {};
  const reportTime = report.saved_at || report.finished_at || report.generated_at || report.created_at;
  const actionLabel = {
    hold: "Mantieni",
    mantieni: "Mantieni",
    reduce: "Riduci",
    riduci: "Riduci",
    sell: "Vendi",
    vendi: "Vendi",
    protect: "Proteggi",
    proteggi: "Proteggi",
  };

  return (
    <div className="deepReport">
      <div className="deepReportHeader">
        <div>
          <h3>Report analisi portafoglio</h3>
          {reportTime && <p className="deepReportTimestamp">Ultima analisi: <strong>{dateTime(reportTime)}</strong></p>}
          <p>{report.summary || "Analisi completata."}</p>
        </div>
        <div className="deepReportTotals">
          <span>Valore <strong>{eur(portfolio.total_value)}</strong></span>
          <span className={signedClass(portfolio.pnl)}>P/L <strong>{eur(portfolio.pnl)}</strong> ({pct(portfolio.pnl_pct)})</span>
          <span>Cash <strong>{eur(portfolio.cash)}</strong></span>
        </div>
      </div>
      <div className="deepReportGrid">
        {items.map((item) => {
          const decision = item.decision || {};
          const perf = item.performance || {};
          const position = item.position || {};
          const technical = item.technical || {};
          const levels = decision.levels || {};
          const action = String(decision.action || "hold").toLowerCase();
          const actionText = actionLabel[action] || decision.action || "Da valutare";
          return (
            <article key={item.ticker} className={`deepReportCard ${signedClass(perf.pnl)}`}>
              <div className="deepReportCardTop">
                <h4>{item.ticker}</h4>
                <span className={`actionBadge ${action}`}>{actionText}</span>
              </div>
              <div className="deepReportMetrics">
                <span><small>Investito</small><strong>{eur(position.invested_amount)}</strong></span>
                <span><small>Quantita</small><strong>{price(position.quantity)}</strong></span>
                <span><small>Entry</small><strong>{price(position.entry_price)}</strong></span>
                <span><small>Prezzo</small><strong>{price(perf.current_price)}</strong></span>
                <span className={signedClass(perf.pnl)}><small>P/L</small><strong>{eur(perf.pnl)}</strong></span>
                <span className={signedClass(perf.pnl_pct)}><small>P/L %</small><strong>{pct(perf.pnl_pct)}</strong></span>
                <span className={signedClass(perf.daily_change_pct)}><small>Oggi</small><strong>{pct(perf.daily_change_pct)}</strong></span>
                <span><small>Valore</small><strong>{eur(perf.market_value)}</strong></span>
              </div>
              <div className="deepReportLevels">
                <span>Supporto <strong>{price(technical.support || levels.support)}</strong></span>
                <span>Resistenza <strong>{price(technical.resistance || levels.resistance)}</strong></span>
                <span>RSI <strong>{price(technical.rsi)}</strong></span>
                <span>ADX <strong>{price(technical.adx)}</strong></span>
              </div>
              <p className="deepReportReason">{decision.reason || "Nessuna motivazione disponibile."}</p>
              {item.proposal?.id && (
                <p className="deepReportProposal">
                  Proposta: <strong>{item.proposal.id}</strong> ({item.proposal.action || "azione n/d"})
                </p>
              )}
              {item.applied && (
                <p className="deepReportApplied">Operazione applicata: {item.applied.action || "azione"} {item.applied.amount ? eur(item.applied.amount) : ""}</p>
              )}
              <details>
                <summary>File e anteprima analisi</summary>
                <div className="deepReportFiles">
                  {item.chart_analysis_file && <span>Grafico AI: {item.chart_analysis_file}</span>}
                  {item.news_file && <span>News: {item.news_file}</span>}
                </div>
                {item.chart_preview && <pre>{cleanText(item.chart_preview).slice(0, 900)}</pre>}
                {item.news_preview && <pre>{cleanText(item.news_preview).slice(0, 700)}</pre>}
              </details>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function Controls({ reload, portfolioId = "main" }) {
  const [scanLimit, setScanLimit] = useState(5);
  const [maxTradePct, setMaxTradePct] = useState(25);
  const [telegramSettings, setTelegramSettings] = useState({
    monitoring_mode: "always",
    send_performance_alerts: true,
    max_monitoring_items: 5,
  });
  const [autonomySettings, setAutonomySettings] = useState({
    portfolio_action_mode: "full_auto",
    notify_telegram: true,
  });
  const [busy, setBusy] = useState("");
  const [log, setLog] = useState("");
  const [deepReport, setDeepReport] = useState(null);
  const [status, setStatus] = useState({
    state: "idle",
    label: "Pronto",
    detail: "Nessuna operazione in corso.",
    startedAt: null,
    finishedAt: null,
    percent: 0,
    events: [],
  });
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (status.state !== "running") return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [status.state]);

  useEffect(() => {
    async function loadTelegramSettings() {
      try {
        const result = await api(`/api/telegram/settings?portfolio_id=${encodeURIComponent(portfolioId)}`);
        setTelegramSettings(result.settings || telegramSettings);
      } catch (error) {
        setLog(`Errore caricamento impostazioni Telegram: ${error.message}`);
      }
    }
    loadTelegramSettings();
  }, [portfolioId]);

  useEffect(() => {
    async function loadAutonomySettings() {
      try {
        const result = await api(`/api/autonomy/settings?portfolio_id=${encodeURIComponent(portfolioId)}`);
        setAutonomySettings(result.settings || autonomySettings);
      } catch (error) {
        setLog(`Errore caricamento configurazione autonomia: ${error.message}`);
      }
    }
    loadAutonomySettings();
  }, [portfolioId]);

  useEffect(() => {
    async function loadLatestDeepReport() {
      try {
        const result = await api(
          `/api/portfolio/deep-analysis/latest?portfolio_id=${encodeURIComponent(portfolioId)}`,
        );
        setDeepReport(result.report || null);
      } catch (error) {
        // Il report e opzionale: se non esiste ancora, la pagina resta pulita.
      }
    }
    loadLatestDeepReport();
  }, [portfolioId]);

  function elapsedLabel(startedAt, finishedAt) {
    if (!startedAt) return "";
    const end = finishedAt || now;
    const seconds = Math.max(0, Math.floor((end - startedAt) / 1000));
    const minutes = Math.floor(seconds / 60);
    const rest = seconds % 60;
    return minutes ? `${minutes}m ${String(rest).padStart(2, "0")}s` : `${rest}s`;
  }

  async function run(path, body, label) {
    const startedAt = Date.now();
    setBusy(label);
    setLog("");
    setDeepReport(null);
    setNow(startedAt);
    setStatus({
      state: "running",
      label,
      detail: `Esecuzione ${label} in corso. Attendo risposta dal backend/agente...`,
      startedAt,
      finishedAt: null,
      percent: 8,
      events: [],
    });
    try {
      const result = await api(path, { method: "POST", body: JSON.stringify(body || {}), timeoutMs: 900000 });
      setLog(result.output || result.message || JSON.stringify(result, null, 2));
      setStatus({
        state: "done",
        label,
        detail: `Operazione ${label} completata.`,
        startedAt,
        finishedAt: Date.now(),
        percent: 100,
        events: [],
      });
      reload();
    } catch (error) {
      setLog(
        error.fullOutput
          ? `Errore sintetico: ${error.message}\n\nDettaglio completo disponibile nel tab Run log.`
          : error.message
      );
      setStatus({
        state: "error",
        label,
        detail: `Errore durante ${label}: ${error.message}`,
        startedAt,
        finishedAt: Date.now(),
        percent: 100,
        events: [],
      });
    } finally {
      setBusy("");
    }
  }

  async function runDeepPortfolioAnalysis() {
    const label = "analisi profonda portafoglio";
    const startedAt = Date.now();
    setBusy(label);
    setLog("");
    setDeepReport(null);
    setNow(startedAt);
    setStatus({
      state: "running",
      label,
      detail: "Creo il job e carico le posizioni aperte...",
      startedAt,
      finishedAt: null,
      percent: 1,
      events: [],
    });
    try {
      const created = await api("/api/portfolio/deep-analysis", {
        method: "POST",
        body: JSON.stringify({
          max_positions: 10,
          create_proposals: true,
          auto_apply: ["protective", "full_auto"].includes(autonomySettings.portfolio_action_mode),
          telegram: autonomySettings.notify_telegram,
          portfolio_id: portfolioId,
        }),
      });
      if (!created.job_id) throw new Error("Il backend non ha restituito il job_id.");

      while (true) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const job = await api(`/api/portfolio/deep-analysis/${created.job_id}`);
        setStatus({
          state: job.state === "completed" ? "done" : job.state,
          label,
          detail: job.message || "Analisi in corso...",
          stage: job.stage,
          ticker: job.ticker,
          current: job.current,
          total: job.total,
          percent: Number.isFinite(job.percent) ? job.percent : 5,
          events: job.events || [],
          startedAt,
          finishedAt: ["completed", "error"].includes(job.state) ? Date.now() : null,
        });
        if (job.state === "completed") {
          setDeepReport(job.result || null);
          setLog(job.result?.summary || "Analisi approfondita completata.");
          reload();
          break;
        }
        if (job.state === "error") {
          throw new Error(job.error || job.message || "Analisi approfondita fallita.");
        }
      }
    } catch (error) {
      setLog(error.message);
      setStatus((current) => ({
        ...current,
        state: "error",
        detail: `Errore durante ${label}: ${error.message}`,
        percent: 100,
        finishedAt: Date.now(),
      }));
    } finally {
      setBusy("");
    }
  }

  async function saveTelegramSettings(nextSettings = telegramSettings) {
    const startedAt = Date.now();
    setBusy("telegram-settings");
    setLog("");
    setStatus({
      state: "running",
      label: "telegram settings",
      detail: "Salvataggio impostazioni Telegram...",
      startedAt,
      finishedAt: null,
    });
    try {
      const result = await api(`/api/telegram/settings?portfolio_id=${encodeURIComponent(portfolioId)}`, {
        method: "POST",
        body: JSON.stringify(nextSettings),
      });
      setTelegramSettings(result.settings || nextSettings);
      setLog(JSON.stringify(result.settings || nextSettings, null, 2));
      setStatus({
        state: "done",
        label: "telegram settings",
        detail: "Impostazioni Telegram salvate.",
        startedAt,
        finishedAt: Date.now(),
      });
    } catch (error) {
      setLog(error.message);
      setStatus({
        state: "error",
        label: "telegram settings",
        detail: `Errore salvataggio Telegram: ${error.message}`,
        startedAt,
        finishedAt: Date.now(),
      });
    } finally {
      setBusy("");
    }
  }

  async function saveAutonomySettings(nextSettings = autonomySettings) {
    const startedAt = Date.now();
    setBusy("autonomy-settings");
    setStatus({
      state: "running",
      label: "configurazione autonomia",
      detail: "Salvataggio regole operative del portafoglio virtuale...",
      startedAt,
      finishedAt: null,
    });
    try {
      const result = await api(`/api/autonomy/settings?portfolio_id=${encodeURIComponent(portfolioId)}`, {
        method: "POST",
        body: JSON.stringify(nextSettings),
      });
      setAutonomySettings(result.settings || nextSettings);
      setLog(`Configurazione salvata: ${result.settings?.portfolio_action_mode || nextSettings.portfolio_action_mode}`);
      setStatus({
        state: "done",
        label: "configurazione autonomia",
        detail: "Regole operative salvate e attive anche per i run schedulati.",
        startedAt,
        finishedAt: Date.now(),
      });
    } catch (error) {
      setLog(error.message);
      setStatus({
        state: "error",
        label: "configurazione autonomia",
        detail: `Errore salvataggio autonomia: ${error.message}`,
        startedAt,
        finishedAt: Date.now(),
      });
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="panel">
      <h2>Controlli</h2>
      <div className="controlRow">
        <label>Top candidati<input type="number" value={scanLimit} min="1" max="40" onChange={(e) => setScanLimit(e.target.value)} /></label>
        <label>Max auto trade %<input type="number" value={maxTradePct} min="1" max="100" onChange={(e) => setMaxTradePct(e.target.value)} /></label>
      </div>
      <div className="actions">
        <button
          onClick={() => run(
            "/api/agent/run-once",
            {
              scan_limit: scanLimit,
              max_auto_trade_pct: maxTradePct,
              portfolio_id: portfolioId,
            },
            "monitor SDK",
          )}
          disabled={!!busy}
        >
          Run monitor SDK
        </button>
        <button
          onClick={runDeepPortfolioAnalysis}
          disabled={!!busy}
        >
          Analisi profonda portafoglio
        </button>
        <button
          onClick={() => run(
            "/api/playwright-monitor/run",
            {
              limit: scanLimit,
              deep_limit: 2,
              universe_limit: 0,
              telegram: true,
              portfolio_id: portfolioId,
            },
            "monitor Playwright",
          )}
          disabled={!!busy}
        >
          Monitor via ChatGPT Web
        </button>
        <button
          onClick={() => run(
            `/api/telegram/monitoring?portfolio_id=${encodeURIComponent(portfolioId)}`,
            {},
            "telegram",
          )}
          disabled={!!busy}
        >
          Telegram monitoraggio
        </button>
        <button
          onClick={() => run(
            `/api/telegram/performance?portfolio_id=${encodeURIComponent(portfolioId)}`,
            {},
            "performance",
          )}
          disabled={!!busy}
        >
          Telegram performance
        </button>
      </div>
      <p className="controlHint">
        Il monitor manuale considera tutto lo scope disponibile; "Top candidati" indica solo quanti migliori risultati sintetizzare dopo lo scan. Il monitor SDK usa OpenAI API key per orchestrare le decisioni. Il monitor Playwright usa ChatGPT nel browser per gli approfondimenti e riduce il consumo token API.
        L'analisi profonda portafoglio lavora sulle posizioni aperte. I monitor completi applicano la stessa policy anche a nuovi ingressi, incrementi e ribilanciamenti.
      </p>
      <div className="settingsBox">
        <div>
          <h3>Autonomia sul portafoglio virtuale</h3>
          <p>
            Stabilisce cosa puo fare l'agente su tutto il portafoglio virtuale: nuovi acquisti,
            incrementi, riduzioni, vendite e ribilanciamenti. Ogni decisione viene registrata nei log.
          </p>
        </div>
        <div className="autonomyModes">
          {[
            ["confirmation", "Conferma sempre", "Ogni acquisto, incremento, riduzione, vendita o ribilanciamento resta pending finche l'utente non conferma."],
            ["protective", "Protezione automatica", "Puo ridurre o vendere automaticamente su rischio confermato. Nuovi ingressi e incrementi richiedono conferma."],
            ["full_auto", "Autonomia completa", "Puo comprare, incrementare, ridurre, vendere e ribilanciare automaticamente il portafoglio virtuale."],
          ].map(([value, label, description]) => (
            <button
              key={value}
              className={autonomySettings.portfolio_action_mode === value ? "selectedMode" : ""}
              onClick={() => {
                const next = { ...autonomySettings, portfolio_action_mode: value };
                setAutonomySettings(next);
                saveAutonomySettings(next);
              }}
              disabled={!!busy}
            >
              <strong>{label}</strong>
              <span>{description}</span>
            </button>
          ))}
        </div>
        <label className="checkboxLabel">
          <input
            type="checkbox"
            checked={autonomySettings.notify_telegram}
            onChange={(event) => {
              const next = { ...autonomySettings, notify_telegram: event.target.checked };
              setAutonomySettings(next);
              saveAutonomySettings(next);
            }}
          />
          Notifica su Telegram le operazioni applicate e le nuove proposte che richiedono conferma
        </label>
      </div>
      <div className="settingsBox">
        <div>
          <h3>Notifiche Telegram</h3>
          <p>Decidi quando il monitor schedulato deve mandare messaggi automatici.</p>
        </div>
        <div className="telegramModes">
          {[
            ["always", "Invia sempre", "Riepilogo a ogni run schedulato."],
            ["changes", "Solo variazioni", "Invia se cambiano condizioni, proposte o portafoglio."],
            ["portfolio_changes", "Solo portafoglio", "Invia solo se entra o esce un titolo oppure cambia la quantita di una posizione."],
            ["alerts", "Solo alert", "Invia solo se ci sono alert di performance o trigger."],
            ["disabled", "Disattivato", "Nessun riepilogo automatico, manuale ancora disponibile."],
          ].map(([value, label, description]) => (
            <button
              key={value}
              className={telegramSettings.monitoring_mode === value ? "selectedMode" : ""}
              onClick={() => {
                const next = { ...telegramSettings, monitoring_mode: value };
                setTelegramSettings(next);
                saveTelegramSettings(next);
              }}
              disabled={!!busy}
            >
              <strong>{label}</strong>
              <span>{description}</span>
            </button>
          ))}
        </div>
        <div className="controlRow compact">
          <label>Max trigger nel messaggio
            <input
              type="number"
              min="3"
              max="12"
              value={telegramSettings.max_monitoring_items}
              onChange={(event) => setTelegramSettings({ ...telegramSettings, max_monitoring_items: event.target.value })}
            />
          </label>
          <label className="checkboxLabel">
            <input
              type="checkbox"
              checked={telegramSettings.send_performance_alerts}
              onChange={(event) => setTelegramSettings({ ...telegramSettings, send_performance_alerts: event.target.checked })}
            />
            Alert performance abilitati
          </label>
          <button onClick={() => saveTelegramSettings()} disabled={!!busy}>Salva Telegram</button>
        </div>
      </div>
      <div className={`runStatusBar ${status.state}`}>
        <div className="runStatusTop">
          <span className="runStatusState">{status.state === "running" ? "In corso" : status.state === "done" ? "Completato" : status.state === "error" ? "Errore" : "Idle"}</span>
          <strong>{status.label}</strong>
          <span>{elapsedLabel(status.startedAt, status.finishedAt)}</span>
        </div>
        <div className="runProgress" aria-hidden="true">
          <span style={{ width: `${Math.max(0, Math.min(100, status.percent || 0))}%` }} />
        </div>
        <p>{status.detail}</p>
        {status.state === "running" && status.total > 0 && (
          <div className="runCurrentStep">
            <strong>{status.current}/{status.total}</strong>
            <span>{status.ticker || "Portafoglio"}</span>
            <span>{status.stage?.replaceAll("_", " ")}</span>
          </div>
        )}
        {status.events?.length > 0 && (
          <div className="runEventLog" aria-live="polite">
            {status.events.slice(-12).map((event, index) => (
              <div key={`${event.timestamp}-${index}`} className={event.stage === "error" ? "eventError" : ""}>
                <time>{event.timestamp ? event.timestamp.slice(11, 19) : "--:--:--"}</time>
                <strong>{event.ticker || "Sistema"}</strong>
                <span>{event.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      <DeepPortfolioReport report={deepReport} />
      {log && <pre className="log">{log}</pre>}
    </section>
  );
}

function NewsReports() {
  const [state, setState] = useState({ loading: true, error: "", data: null });
  const [archiveState, setArchiveState] = useState({ message: "", error: "" });
  const [query, setQuery] = useState("");
  const [onlyRelevant, setOnlyRelevant] = useState(false);
  const [expanded, setExpanded] = useState({});
  const [liveTicker, setLiveTicker] = useState("");
  // SSE streaming state for news
  const [newsStream, setNewsStream] = useState({
    running: false, ticker: "", phase: "", logs: [], report: "", savedFile: "", error: "", startedAt: "",
  });
  // SSE streaming state for charts
  const [chartStream, setChartStream] = useState({
    running: false, ticker: "", phase: "", logs: [], report: "", savedFile: "", error: "", startedAt: "",
  });
  const newsEsRef = React.useRef(null);
  const chartEsRef = React.useRef(null);
  const newsLogRef = React.useRef(null);
  const chartLogRef = React.useRef(null);

  // Scroll log boxes to bottom on new content
  React.useEffect(() => {
    if (newsLogRef.current) newsLogRef.current.scrollTop = newsLogRef.current.scrollHeight;
  }, [newsStream.logs]);
  React.useEffect(() => {
    if (chartLogRef.current) chartLogRef.current.scrollTop = chartLogRef.current.scrollHeight;
  }, [chartStream.logs]);

  function classifyLog(line) {
    const l = line.toLowerCase();
    if (!line.trim()) return "logEmpty";
    if (l.includes("errore") || l.includes("error") || l.includes("timeout") || l.includes("traceback")) return "logError";
    if (l.includes("risposta chatgpt") || l.includes("risposta in corso") || l.includes("report salvato") || l.includes("analisi completata")) return "logSuccess";
    if (l.includes("attendo") || l.includes("in corso") || l.includes("avvio") || l.includes("preparo") || l.includes("genero") || l.includes("scarico")) return "logActive";
    if (l.includes("campo prompt") || l.includes("prompt inserito") || l.includes("allego") || l.includes("invio")) return "logSend";
    return "logNeutral";
  }

  function inferPhase(logs, kind) {
    const combined = logs.join(" ").toLowerCase();
    if (kind === "news") {
      if (combined.includes("risposta chatgpt") || combined.includes("report salvato")) return { step: 3, label: "Report salvato ✓" };
      if (combined.includes("risposta in corso") || combined.includes("attendo la risposta")) return { step: 2, label: "ChatGPT sta rispondendo..." };
      if (combined.includes("prompt inserito") || combined.includes("campo prompt")) return { step: 1, label: "Prompt inviato a ChatGPT" };
      if (combined.includes("avvio") || combined.includes("connett") || combined.includes("subprocess")) return { step: 0, label: "Connessione a Chrome in corso..." };
      return { step: 0, label: "Inizializzazione..." };
    } else {
      if (combined.includes("report news salvato") || combined.includes("analisi completata") || combined.includes("analysis saved")) return { step: 3, label: "Analisi salvata ✓" };
      if (combined.includes("risposta in corso") || combined.includes("attendo risposta chatgpt")) return { step: 2, label: "ChatGPT analizza i grafici..." };
      if (combined.includes("allego immagini") || combined.includes("prompt inserito")) return { step: 1, label: "Grafici inviati a ChatGPT" };
      if (combined.includes("genero grafici") || combined.includes("grafici creati") || combined.includes("subprocess")) return { step: 0, label: "Generazione grafici tecnici..." };
      return { step: 0, label: "Inizializzazione..." };
    }
  }

  const NEWS_STEPS = ["Connessione Chrome", "Invio prompt ChatGPT", "Attesa risposta", "Report salvato"];
  const CHART_STEPS = ["Generazione grafici", "Upload su ChatGPT", "Analisi visuale", "Analisi salvata"];

  function renderLiveStream(stream, kind, logRef) {
    if (!stream.running && !stream.error && !stream.report && stream.logs.length === 0) return null;
    const steps = kind === "news" ? NEWS_STEPS : CHART_STEPS;
    const { step: currentStep, label: phaseLabel } = inferPhase(stream.logs, kind);
    const isDone = !stream.running && !stream.error && stream.logs.length > 0;
    const hasError = Boolean(stream.error);
    const panelClass = hasError ? "streamPanel error" : isDone ? "streamPanel done" : "streamPanel running";

    return (
      <div className={panelClass}>
        <div className="streamHeader">
          <div className="streamTitle">
            {stream.running && <span className="streamSpinner" />}
            {hasError && <span className="streamIcon error">✗</span>}
            {isDone && !hasError && <span className="streamIcon done">✓</span>}
            <strong>{kind === "news" ? "News live" : "Analisi grafico"} {stream.ticker}</strong>
            {stream.startedAt && <span className="streamTime">{formatLogDateTime(stream.startedAt)}</span>}
          </div>
          <div className="streamSteps">
            {steps.map((label, i) => (
              <span
                key={label}
                className={`streamStep ${
                  isDone || i < currentStep ? "done" : i === currentStep && stream.running ? "active" : "waiting"
                }`}
              >
                {label}
              </span>
            ))}
          </div>
        </div>

        {stream.phase && stream.running && (
          <p className="streamPhase">{stream.phase}</p>
        )}
        {hasError && <p className="streamError">{stream.error}</p>}

        {stream.logs.length > 0 && (
          <div className="streamLogBox" ref={logRef}>
            {stream.logs.map((line, i) => (
              <div key={i} className={`streamLogLine ${classifyLog(line)}`}>{line || "\u00a0"}</div>
            ))}
          </div>
        )}

        {stream.report && (
          <div className="streamReport">
            <div className="streamReportHeader">
              <strong>📄 Report {kind === "news" ? "news" : "analisi tecnica"}</strong>
              {stream.savedFile && <span className="streamSavedFile">{stream.savedFile}</span>}
            </div>
            <pre className="streamReportText">{stream.report}</pre>
          </div>
        )}
      </div>
    );
  }

  function runLiveNews(tickerArg = "") {
    const ticker = String(tickerArg || liveTicker || "").trim().toUpperCase();
    if (!ticker) {
      setNewsStream((s) => ({ ...s, error: "Inserisci un ticker, es. VOD.L o CPR.MI.", running: false }));
      return;
    }
    // Close any previous SSE connection
    if (newsEsRef.current) { newsEsRef.current.close(); newsEsRef.current = null; }
    setLiveTicker(ticker);
    setQuery(ticker);
    setNewsStream({ running: true, ticker, phase: "Avvio ricerca...", logs: [], report: "", savedFile: "", error: "", startedAt: new Date().toISOString() });

    const url = `${API}/api/news/live-stream?ticker=${encodeURIComponent(ticker)}&force=1`;
    const es = new EventSource(url);
    newsEsRef.current = es;

    es.addEventListener("phase", (ev) => {
      setNewsStream((s) => ({ ...s, phase: ev.data }));
    });
    es.addEventListener("log", (ev) => {
      setNewsStream((s) => ({ ...s, logs: [...s.logs, ev.data] }));
    });
    es.addEventListener("heartbeat", () => {}); // keep-alive, ignore
    es.addEventListener("report", (ev) => {
      setNewsStream((s) => ({ ...s, report: ev.data }));
    });
    es.addEventListener("saved", (ev) => {
      setNewsStream((s) => ({ ...s, savedFile: ev.data }));
    });
    es.addEventListener("done", () => {
      setNewsStream((s) => ({ ...s, running: false, phase: "" }));
      es.close(); newsEsRef.current = null;
      loadNews({ queryOverride: ticker });
    });
    es.addEventListener("error", (ev) => {
      const msg = ev.data || "Errore durante la ricerca news. Verifica che Chrome sia aperto con debug remoto (porta 9222).";
      setNewsStream((s) => ({ ...s, running: false, phase: "", error: msg }));
      es.close(); newsEsRef.current = null;
    });
    es.onerror = () => {
      // SSE connection closed or error without explicit event
      setNewsStream((s) => s.running ? { ...s, running: false, phase: "", error: s.error || "Connessione SSE interrotta." } : s);
      es.close(); newsEsRef.current = null;
    };
  }

  function runLiveChart(tickerArg = "") {
    const ticker = String(tickerArg || liveTicker || "").trim().toUpperCase();
    if (!ticker) {
      setChartStream((s) => ({ ...s, error: "Inserisci un ticker, es. VOD.L, A2A.MI.", running: false }));
      return;
    }
    if (chartEsRef.current) { chartEsRef.current.close(); chartEsRef.current = null; }
    setLiveTicker(ticker);
    setQuery(ticker);
    setChartStream({ running: true, ticker, phase: "Avvio analisi grafico...", logs: [], report: "", savedFile: "", error: "", startedAt: new Date().toISOString() });

    const url = `${API}/api/charts/live-stream?ticker=${encodeURIComponent(ticker)}&force=1`;
    const es = new EventSource(url);
    chartEsRef.current = es;

    es.addEventListener("phase", (ev) => {
      setChartStream((s) => ({ ...s, phase: ev.data }));
    });
    es.addEventListener("log", (ev) => {
      setChartStream((s) => ({ ...s, logs: [...s.logs, ev.data] }));
    });
    es.addEventListener("heartbeat", () => {});
    es.addEventListener("report", (ev) => {
      setChartStream((s) => ({ ...s, report: ev.data }));
    });
    es.addEventListener("saved", (ev) => {
      setChartStream((s) => ({ ...s, savedFile: ev.data }));
    });
    es.addEventListener("done", () => {
      setChartStream((s) => ({ ...s, running: false, phase: "" }));
      es.close(); chartEsRef.current = null;
    });
    es.addEventListener("error", (ev) => {
      const msg = ev.data || "Errore durante l'analisi grafico. Verifica che Chrome sia aperto (porta 9222).";
      setChartStream((s) => ({ ...s, running: false, phase: "", error: msg }));
      es.close(); chartEsRef.current = null;
    });
    es.onerror = () => {
      setChartStream((s) => s.running ? { ...s, running: false, phase: "", error: s.error || "Connessione SSE interrotta." } : s);
      es.close(); chartEsRef.current = null;
    };
  }

  async function loadNews(options = {}) {
    const silent = Boolean(options.silent);
    const effectiveQuery = options.queryOverride ?? query;
    if (!silent) {
      setState((current) => ({ ...current, loading: true, error: "" }));
      setArchiveState({
        message: "Rileggo i report news gia salvati in output/stock_ai. Questa azione non apre Playwright.",
        error: "",
      });
    }
    const params = new URLSearchParams({ limit: "200" });
    if (effectiveQuery.trim()) params.set("query", effectiveQuery.trim());
    if (onlyRelevant) params.set("relevant_only", "true");
    try {
      const data = await api(`/api/news/reports?${params.toString()}`, { timeoutMs: 60000 });
      setState({ loading: false, error: "", data });
      if (!silent) {
        const count = data.count || 0;
        const latest = data.latest_updated_at ? formatLogDateTime(data.latest_updated_at) : "n/d";
        setArchiveState({
          message: `Archivio ricaricato: ${count} report salvati letti. Ultimo aggiornamento file: ${latest}.`,
          error: "",
        });
      }
    } catch (error) {
      setState({ loading: false, error: "", data: null });
      setArchiveState({ message: "", error: friendlyNewsError(error, "Ricarica archivio news") });
    }
  }

  useEffect(() => { loadNews(); }, [onlyRelevant]);


  const data = state.data || {};
  const items = data.items || [];

  return (
    <section className="panel newsPage">
      <div className="sectionHeader">
        <div>
          <h2><Newspaper size={22} /> News cercate</h2>
          <span>Archivio dei report salvati e ricerca live on demand via Playwright/ChatGPT.</span>
        </div>
        <div className="sectionActions">
          <button className="iconButton" onClick={() => loadNews()} disabled={state.loading}>
            <RefreshCw size={16} /> {state.loading ? "Rileggo archivio..." : "Ricarica archivio"}
          </button>
        </div>
      </div>
      {(archiveState.message || archiveState.error) && (
        <div className={`newsLiveStatus ${archiveState.error ? "errorState" : "infoState"}`}>
          <strong>{archiveState.error ? "Archivio news:" : "Archivio news"}</strong>{" "}
          {archiveState.error || archiveState.message}
        </div>
      )}

      <div className="newsLivePanel">
        <div className="newsLiveCopy">
          <strong>Analisi on demand via Playwright</strong>
          <span>
            Avvia news live o lettura visuale del grafico per un singolo ticker usando ChatGPT nel browser.
            Ogni azione mostra il progresso in tempo reale linea per linea. Assicurarsi che Chrome sia aperto su ChatGPT.
          </span>
        </div>
        <div className="newsLiveForm">
          <input
            value={liveTicker}
            onChange={(event) => setLiveTicker(event.target.value.toUpperCase())}
            onKeyDown={(event) => {
              if (event.key === "Enter") runLiveNews();
            }}
            placeholder="Ticker, es. CPR.MI, VOD.L, ROBO.MI"
            disabled={newsStream.running || chartStream.running}
          />
          <button className="primaryButton" onClick={() => runLiveNews()} disabled={newsStream.running || chartStream.running}>
            {newsStream.running ? <><span className="btnSpinner" /> Ricerca in corso...</> : "🔍 Cerca news live"}
          </button>
          <button className="iconButton" onClick={() => runLiveChart()} disabled={newsStream.running || chartStream.running}>
            {chartStream.running ? <><span className="btnSpinner" /> Grafico in corso...</> : "📈 Analizza grafico live"}
          </button>
        </div>
        {renderLiveStream(newsStream, "news", newsLogRef)}
        {renderLiveStream(chartStream, "chart", chartLogRef)}
      </div>

      <div className="newsFilters">
        <input
          className="newsSearch"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") loadNews();
          }}
          placeholder="Cerca ticker o testo nel report..."
        />
        <label className="checkInline">
          <input type="checkbox" checked={onlyRelevant} onChange={(event) => setOnlyRelevant(event.target.checked)} />
          Solo news rilevanti
        </label>
      </div>

      {state.data && (
        <div className="marketOverview newsOverview">
          <div className="marketKpi">
            <span>Report salvati</span>
            <strong>{data.count || 0}</strong>
            <small>Letti da {data.root || "output/stock_ai"}</small>
          </div>
          <div className="marketKpi highlight">
            <span>News rilevanti</span>
            <strong>{data.relevant_count || 0}</strong>
            <small>Report con notizie potenzialmente utili.</small>
          </div>
          <div className="marketKpi">
            <span>Senza novita</span>
            <strong>{data.no_relevant_count || 0}</strong>
            <small>Report che dichiarano nessuna news rilevante.</small>
          </div>
          <div className="marketKpi">
            <span>Ultimo aggiornamento</span>
            <strong>{data.latest_updated_at ? formatLogDateTime(data.latest_updated_at) : "n/d"}</strong>
            <small>Data di modifica del file news piu recente.</small>
          </div>
        </div>
      )}

      {state.error && <div className="error">{state.error}</div>}
      {state.loading && <div className="mutedBox">Carico report news salvati...</div>}
      {!state.loading && !state.error && (
        <div className="newsList">
          {items.length === 0 && (
            <div className="mutedBox">
              Nessun report news trovato. Le news compaiono qui dopo una ricerca live o una analisi Playwright che salva il file news del ticker.
            </div>
          )}
          {items.map((item) => {
            const isExpanded = Boolean(expanded[item.ticker]);
            const fullReport = cleanText(item.report);
            const sourceText = isExpanded
              ? fullReport
              : (Array.isArray(item.summary_lines) && item.summary_lines.length ? item.summary_lines.join("\n") : item.preview);
            const lines = cleanText(sourceText)
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean)
              .slice(0, isExpanded ? 140 : 10);
            const canExpand = fullReport.length > cleanText(sourceText).length || lines.length >= 10;
            return (
              <article className={`newsCard ${item.status}`} key={`${item.ticker}-${item.updated_at}`}>
                <div className="newsCardHeader">
                  <div>
                    <h3>{item.ticker}</h3>
                    <div className="newsMeta">
                      <span>{formatLogDateTime(item.updated_at)}</span>
                      <span>{item.path}</span>
                    </div>
                  </div>
                  <span className={`newsBadge ${item.status}`}>{item.status_label}</span>
                </div>
                {item.headline && <p className="newsHeadline">{cleanText(item.headline)}</p>}
                <div className="newsReadable">
                  {lines.length === 0 && <p className="newsLine">Report vuoto.</p>}
                  {lines.map((line, index) => {
                    const isHeading = /REPORT|News rilevanti|Target price|Supporti|Resistenze|Sintesi|Fonti|Data/i.test(line);
                    const isBullet = /^[-\u2022]\s*/.test(line);
                    return (
                      <p
                        className={`newsLine ${isHeading ? "newsLineHeading" : ""} ${isBullet ? "newsLineBullet" : ""}`}
                        key={`${item.ticker}-line-${index}`}
                      >
                        {line.replace(/^[-\u2022]\s*/, "")}
                      </p>
                    );
                  })}
                </div>
                <div className="newsActions">
                  <button
                    className="iconButton compactButton"
                    onClick={() => runLiveNews(item.ticker)}
                    disabled={newsStream.running || chartStream.running}
                  >
                    Aggiorna live
                  </button>
                  <button
                    className="iconButton compactButton"
                    onClick={() => runLiveChart(item.ticker)}
                    disabled={newsStream.running || chartStream.running}
                  >
                    Analizza grafico
                  </button>
                  {canExpand && (
                    <button
                      className="iconButton compactButton"
                      onClick={() => setExpanded((current) => ({ ...current, [item.ticker]: !isExpanded }))}
                    >
                      {isExpanded ? "Nascondi dettaglio" : "Mostra dettaglio"}
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

function friendlyNewsError(error, action) {
  const raw = cleanText(error?.message || String(error || ""));
  const lower = raw.toLowerCase();
  if (raw === "Not Found" || lower.includes("errore http 404") || lower.includes("not found")) {
    return `${action}: endpoint backend non trovato. Probabilmente il frontend sta parlando con un backend FastAPI non aggiornato: riavvia il backend e poi ricarica la pagina.`;
  }
  if (lower.includes("failed to fetch") || lower.includes("networkerror") || lower.includes("load failed")) {
    return `${action}: backend non raggiungibile su ${API}. Verifica che FastAPI sia avviato.`;
  }
  if (lower.includes("aborted") || lower.includes("timeout")) {
    return `${action}: timeout. Playwright/ChatGPT potrebbe essere ancora in attesa nel browser; controlla Chrome e il tab Run log.`;
  }
  return `${action}: ${raw || "errore non specificato"}`;
}

function safeLogText(value) {
  return String(value || "")
    .replace(/\u0000/g, "")
    .replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, "")
    .replace(/[\u0001-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "");
}

function formatLogDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "data non disponibile";
  return date.toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function LogBlock({ value, fallback, className = "log runLog" }) {
  const text = safeLogText(value);
  return <pre className={className}>{text || fallback}</pre>;
}

function RunLogs() {
  const [state, setState] = useState({ loading: true, error: "", data: null });
  const [lines, setLines] = useState(300);
  const [clearing, setClearing] = useState(false);
  const loadingRef = useRef(false);

  async function loadLogs(options = {}) {
    if (loadingRef.current) return;
    loadingRef.current = true;
    const silent = Boolean(options.silent);
    if (!silent) setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const data = await api(`/api/run-logs?lines=${lines}`);
      setState({ loading: false, error: "", data });
    } catch (error) {
      const message = error.name === "AbortError"
        ? "Timeout nel caricamento dei log. Il backend sta impiegando troppo tempo a rispondere."
        : error.message;
      setState((current) => ({ loading: false, error: message, data: current.data }));
    } finally {
      loadingRef.current = false;
    }
  }

  useEffect(() => { loadLogs(); }, []);
  useEffect(() => {
    const timer = window.setInterval(() => loadLogs({ silent: true }), 3000);
    return () => window.clearInterval(timer);
  }, [lines]);

  async function clearLogs() {
    if (!window.confirm("Vuoi svuotare tutti i log di esecuzione? Portafoglio, condizioni e analisi salvate non verranno toccati.")) return;
    setClearing(true);
    try {
      await api("/api/run-logs/clear", { method: "POST", body: JSON.stringify({}) });
      await loadLogs();
    } catch (error) {
      setState((current) => ({ ...current, error: error.message }));
    } finally {
      setClearing(false);
    }
  }

  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Run log</h2>
        <div className="sectionActions">
          <span className="autoRefreshHint">Auto refresh 3s</span>
          <label className="logLinesControl">Righe
            <input type="number" min="50" max="2000" value={lines} onChange={(event) => setLines(event.target.value)} />
          </label>
          <button className="iconButton" onClick={loadLogs} disabled={state.loading}><RefreshCw size={16} /> Aggiorna log</button>
          <button className="iconButton dangerButton" onClick={clearLogs} disabled={state.loading || clearing}>
            <X size={16} /> {clearing ? "Pulisco..." : "Pulisci log"}
          </button>
        </div>
      </div>
      {state.loading && <div className="chartStatus">Caricamento log run...</div>}
      {state.error && <div className="error">{state.error}</div>}
      {state.data && (
        <div className="runLogsGrid">
          {(state.data.agent_run_state?.last_warning || state.data.agent_run_state?.last_error) && (
            <div className="runLogNotice">
              <strong>Stato agente</strong>
              {state.data.agent_run_state?.last_error && <p>Errore: {state.data.agent_run_state.last_error}</p>}
              {state.data.agent_run_state?.last_warning && <p>Nota: {state.data.agent_run_state.last_warning}</p>}
            </div>
          )}
          <div>
            <h3>Journal aggregato dei run</h3>
            <LogBlock value={state.data.combined_run_log} fallback="Nessun log disponibile." />
          </div>
          {Array.isArray(state.data.log_files) && (
            <div className="logFileSummary">
              <h3>File log tracciati</h3>
              <div className="logFileGrid">
                {state.data.log_files.map((file) => (
                  <div className={`logFileCard ${file.size > 0 ? "hasContent" : "emptyLogFile"}`} key={file.name}>
                    <strong>{file.name}</strong>
                    <span>{file.exists ? `${file.size} byte` : "non creato"}</span>
                    <small>{file.updated_at ? formatLogDateTime(file.updated_at * 1000) : "mai aggiornato"}</small>
                  </div>
                ))}
              </div>
            </div>
          )}
          <details>
            <summary>Dettaglio run-journal.log</summary>
            <LogBlock value={state.data.run_journal_log} fallback="Nessun run registrato nel journal dopo l'ultima pulizia." />
          </details>
          <details>
            <summary>Dettaglio manual-optimized-run.log</summary>
            <LogBlock value={state.data.manual_optimized_log} fallback="Nessun run manuale ottimizzato registrato." />
          </details>
          <details>
            <summary>Dettaglio web-agent.log</summary>
            <LogBlock value={state.data.web_agent_log} fallback="Nessuna richiesta web agente registrata." />
          </details>
          <details>
            <summary>Dettaglio scheduled-monitor.log</summary>
            <LogBlock value={state.data.scheduled_log} fallback="Nessun output disponibile." />
          </details>
          <details>
            <summary>Dettaglio scheduled-monitor.err.log</summary>
            <LogBlock value={state.data.scheduled_err} fallback="Nessun errore disponibile." className="log runLog errorLog" />
          </details>
          <details>
            <summary>Dettaglio telegram-agent.log</summary>
            <LogBlock value={state.data.telegram_agent_log} fallback="Nessun log Telegram disponibile." />
          </details>
        </div>
      )}
    </section>
  );
}

function PortfoliosSummary({ selectedId = "main", onSelect, onChart }) {
  const [state, setState] = useState({
    loading: true,
    error: "",
    data: null,
  });

  async function loadSummary() {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const data = await api("/api/portfolios-summary", { timeoutMs: 120000 });
      setState({ loading: false, error: "", data });
    } catch (error) {
      setState({ loading: false, error: error.message, data: null });
    }
  }

  useEffect(() => {
    loadSummary();
  }, []);

  async function openPositionChart(portfolio, position) {
    const fallback = {
      ticker: position.ticker,
      portfolio_id: portfolio.portfolio_id,
      current_price: position.current_price,
      entry_price: position.entry_price,
      opened_at: position.opened_at,
      condition: `Posizione nel portafoglio ${portfolio.name}`,
    };
    onChart(fallback);
    try {
      const query = new URLSearchParams({ ticker: position.ticker });
      if (position.current_price != null) query.set("current_price", position.current_price);
      if (position.entry_price != null) query.set("entry_price", position.entry_price);
      if (position.pnl_pct != null) query.set("pnl_pct", position.pnl_pct);
      const levels = await api(
        `/api/portfolios/${encodeURIComponent(portfolio.portfolio_id)}/exit-conditions?${query.toString()}`,
        { timeoutMs: 4000 },
      );
      const exitRow = (levels.exit_conditions || []).find(
        (item) => String(item.ticker || "").toUpperCase() === String(position.ticker || "").toUpperCase(),
      );
      if (exitRow) {
        onChart({
          ...fallback,
          current_price: exitRow.current_price ?? position.current_price,
          entry_price: exitRow.entry_price ?? position.entry_price,
          opened_at: exitRow.opened_at ?? position.opened_at,
          trigger_level: exitRow.take_profit_level,
          support_level: exitRow.stop_level,
          trigger_distance_pct: exitRow.distance_to_take_profit_pct,
          condition: `Uscita: stop ${price(exitRow.stop_level)} / take profit ${price(exitRow.take_profit_level)}. ${exitRow.primary_action || "Nessun trigger di uscita immediato."}`,
        });
      }
    } catch (_error) {
      // Il grafico resta comunque disponibile con i dati presenti nel riepilogo.
    }
  }

  const data = state.data || {};
  const totals = data.totals || {};
  const rows = data.items || [];

  return (
    <section className="portfolioSummaryPage">
      <div className="portfolioSummaryTitle">
        <div>
          <h2>Riepilogo portafogli</h2>
          <p>Confronto aggiornato dei portafogli virtuali indipendenti.</p>
        </div>
        <button className="iconButton" onClick={loadSummary} disabled={state.loading}>
          <RefreshCw size={16} className={state.loading ? "spinning" : ""} />
          {state.loading ? "Aggiorno..." : "Aggiorna riepilogo"}
        </button>
      </div>

      {state.error && <div className="error">{state.error}</div>}

      <div className="portfolioSummaryTotals">
        <Metric label="Portafogli" value={String(data.count ?? 0)} subtitle={`${data.active_count || 0} attivi`} />
        <Metric label="Capitale virtuale" value={eur(totals.initial_capital)} />
        <Metric
          label="Patrimonio complessivo"
          value={eur(totals.total_value)}
          delta={totals.pnl_pct}
          valueTone={signedClass(totals.pnl)}
        />
        <Metric label="Valore titoli" value={eur(totals.positions_value)} emphasis="positions" />
        <Metric label="Cash complessivo" value={eur(totals.cash)} emphasis="cash" />
        <Metric
          label="P/L complessivo"
          value={eur(totals.pnl)}
          delta={totals.pnl_pct}
          valueTone={signedClass(totals.pnl)}
        />
      </div>

      <div className="portfolioSummaryGrid">
        {rows.map((row) => (
          <article
            className={`portfolioSummaryCard ${row.portfolio_id === selectedId ? "selected" : ""}`}
            key={row.portfolio_id}
          >
            <div className="portfolioSummaryCardHead">
              <div>
                <span className="portfolioSummaryEyebrow">{row.risk_profile}</span>
                <h3>{row.name}</h3>
              </div>
              <span className={`portfolioState ${row.status}`}>{row.status}</span>
            </div>
            {row.description && <p className="portfolioSummaryDescription">{row.description}</p>}
            <div className="portfolioSummaryValue">
              <small>Patrimonio corrente</small>
              <strong>{eur(row.total_value)}</strong>
              <span className={signedClass(row.pnl)}>
                {eur(row.pnl)} · {pct(row.pnl_pct)}
              </span>
            </div>
            <div className="portfolioSummaryStats">
              <span><small>Cash</small><strong>{eur(row.cash)}</strong><em>{pct(row.cash_pct, false)}</em></span>
              <span><small>Titoli</small><strong>{eur(row.positions_value)}</strong><em>{pct(row.exposure_pct, false)}</em></span>
              <span><small>Posizioni</small><strong>{row.positions_count}</strong><em>{row.quote_errors_count ? `${row.quote_errors_count} prezzi mancanti` : "prezzi aggiornati"}</em></span>
            </div>
            <div className="portfolioSummaryPositions">
              <div className="portfolioSummaryPositionsHead">
                <strong>Titoli in portafoglio</strong>
                <span>Valore · rendimento</span>
              </div>
              {(row.positions || []).length ? (
                <div className="portfolioSummaryPositionsList">
                  {(row.positions || []).map((position) => (
                    <button
                      type="button"
                      className="portfolioSummaryPosition"
                      key={position.ticker}
                      title={`Apri grafico ${position.ticker}`}
                      onClick={() => openPositionChart(row, position)}
                    >
                      <div>
                        <strong>{position.ticker}</strong>
                        {position.daily_change_pct != null && (
                          <small className={signedClass(position.daily_change_pct)}>
                            oggi {pct(position.daily_change_pct)}
                          </small>
                        )}
                      </div>
                      <div>
                        <strong>{eur(position.market_value)}</strong>
                        <small className={signedClass(position.pnl)}>
                          {eur(position.pnl)} · {pct(position.pnl_pct)}
                        </small>
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <span className="portfolioSummaryEmpty">Nessun titolo in portafoglio</span>
              )}
            </div>
            <div className="portfolioSummaryMarkets">
              {(row.allowed_markets || []).map((market) => <span key={market}>{market.replaceAll("_", " ")}</span>)}
            </div>
            <button
              className={row.portfolio_id === selectedId ? "selectedPortfolioButton" : ""}
              onClick={() => onSelect(row.portfolio_id)}
            >
              {row.portfolio_id === selectedId ? "Portafoglio selezionato" : "Apri portafoglio"}
            </button>
          </article>
        ))}
      </div>

      {!state.loading && !rows.length && <div className="mutedBox">Nessun portafoglio disponibile.</div>}
      {data.note && <p className="portfolioSummaryNote">{data.note}</p>}
    </section>
  );
}

function PortfolioManager({
  config = {},
  registry = {},
  selectedId = "main",
  onSelect,
  onDeleted,
  reload,
}) {
  const [draft, setDraft] = useState(config);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");

  useEffect(() => {
    setDraft(config);
    setDeleteConfirmation("");
  }, [config]);

  function toggleList(key, value, checked) {
    setDraft((current) => ({
      ...current,
      [key]: checked
        ? [...new Set([...(current[key] || []), value])]
        : (current[key] || []).filter((item) => item !== value),
    }));
  }

  async function save() {
    setBusy("save");
    setMessage("");
    try {
      const payload = {
        name: draft.name,
        description: draft.description || "",
        risk_profile: draft.risk_profile,
        risk_limits: draft.risk_limits || {},
        allowed_markets: draft.allowed_markets || [],
        allowed_asset_classes: draft.allowed_asset_classes || [],
        allow_leveraged: Boolean(draft.allow_leveraged),
        excluded_tickers: draft.excluded_tickers || [],
        excluded_sectors: draft.excluded_sectors || [],
      };
      await api(`/api/portfolios/${encodeURIComponent(selectedId)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      setMessage("Configurazione portafoglio salvata.");
      await reload();
    } catch (error) {
      setMessage(`Errore: ${error.message}`);
    } finally {
      setBusy("");
    }
  }

  async function changeStatus(status) {
    setBusy(status);
    setMessage("");
    try {
      const action = status === "active" ? "activate" : "pause";
      await api(`/api/portfolios/${encodeURIComponent(selectedId)}/${action}`, {
        method: "POST",
      });
      setMessage(status === "active" ? "Portafoglio attivato." : "Portafoglio sospeso.");
      await reload();
    } catch (error) {
      setMessage(`Errore: ${error.message}`);
    } finally {
      setBusy("");
    }
  }

  async function deleteSelectedPortfolio() {
    if (selectedId === "main" || deleteConfirmation !== selectedId) return;
    setBusy("delete");
    setMessage("");
    try {
      const result = await api(`/api/portfolios/${encodeURIComponent(selectedId)}`, {
        method: "DELETE",
        body: JSON.stringify({ confirmation: deleteConfirmation }),
        timeoutMs: 30000,
      });
      if (!result.directory_removed || !result.registry_removed) {
        throw new Error("Il backend non ha verificato la rimozione completa.");
      }
      window.localStorage.removeItem(dashboardStorageKey(selectedId));
      setDeleteConfirmation("");
      setMessage(`Portafoglio ${selectedId} eliminato completamente (${result.removed_items_count} elementi rimossi).`);
      await onDeleted(selectedId, result);
    } catch (error) {
      setMessage(`Errore: ${error.message}`);
    } finally {
      setBusy("");
    }
  }

  const profiles = registry.risk_profiles || {};
  return (
    <section className="panel portfolioManager">
      <div className="portfolioManagerHeader">
        <div>
          <h2>Gestione portafogli</h2>
          <p>Ogni portafoglio mantiene capitale, posizioni, trigger e regole indipendenti.</p>
        </div>
        <span className={`portfolioState ${config.status || "active"}`}>
          {config.status || "active"}
        </span>
      </div>

      <div className="portfolioCards">
        {(registry.items || []).map((item) => (
          <button
            key={item.id}
            className={item.id === selectedId ? "selectedPortfolioCard" : ""}
            onClick={() => onSelect(item.id)}
          >
            <strong>{item.name}</strong>
            <span>{item.risk_profile} · {eur(item.initial_capital)}</span>
            <small>{item.status}</small>
          </button>
        ))}
      </div>

      <div className="portfolioEditGrid">
        <label>
          <span>Nome</span>
          <input value={draft.name || ""} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </label>
        <label>
          <span>Profilo</span>
          <select
            value={draft.risk_profile || "balanced"}
            onChange={(event) => {
              const profile = event.target.value;
              setDraft({
                ...draft,
                risk_profile: profile,
                risk_limits: profiles[profile] || draft.risk_limits,
              });
            }}
          >
            <option value="conservative">Prudente</option>
            <option value="balanced">Bilanciato</option>
            <option value="dynamic">Dinamico</option>
          </select>
        </label>
        <label className="portfolioDescription">
          <span>Descrizione</span>
          <input
            value={draft.description || ""}
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
            placeholder="Obiettivo o strategia del portafoglio"
          />
        </label>
      </div>

      <div className="riskLimitGrid">
        {[
          ["min_cash_pct", "Cash minimo %"],
          ["max_position_pct", "Max posizione %"],
          ["max_sector_pct", "Max settore %"],
          ["max_new_position_pct", "Nuovo ingresso max %"],
          ["max_increment_pct", "Incremento max %"],
          ["min_score", "Score minimo"],
          ["min_average_turnover", "Controvalore minimo"],
          ["max_positions", "Max posizioni"],
        ].map(([key, label]) => (
          <label key={key}>
            <span>{label}</span>
            <input
              type="number"
              min="0"
              value={draft.risk_limits?.[key] ?? ""}
              onChange={(event) => setDraft({
                ...draft,
                risk_limits: {
                  ...(draft.risk_limits || {}),
                  [key]: Number(event.target.value),
                },
              })}
            />
          </label>
        ))}
      </div>

      <div className="portfolioPolicyGroups">
        <fieldset className="portfolioChoiceGroup">
          <legend>Mercati abilitati</legend>
          {[
            ["ftse_mib", "FTSE MIB"],
            ["commodities", "Materie prime"],
            ["etf", "ETF"],
            ["watchlist", "Watchlist"],
          ].map(([value, label]) => (
            <label key={value}>
              <input
                type="checkbox"
                checked={(draft.allowed_markets || []).includes(value)}
                onChange={(event) => toggleList("allowed_markets", value, event.target.checked)}
              />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
        <fieldset className="portfolioChoiceGroup">
          <legend>Strumenti abilitati</legend>
          {[
            ["equity", "Azioni"],
            ["etf", "ETF"],
            ["commodity_etc", "ETC / commodity"],
          ].map(([value, label]) => (
            <label key={value}>
              <input
                type="checkbox"
                checked={(draft.allowed_asset_classes || []).includes(value)}
                onChange={(event) => toggleList("allowed_asset_classes", value, event.target.checked)}
              />
              <span>{label}</span>
            </label>
          ))}
          <label>
            <input
              type="checkbox"
              checked={Boolean(draft.allow_leveraged)}
              onChange={(event) => setDraft({ ...draft, allow_leveraged: event.target.checked })}
            />
            <span>Leveraged</span>
          </label>
        </fieldset>
      </div>

      <div className="actions">
        <button className="primaryHeaderAction" onClick={save} disabled={!!busy}>Salva configurazione</button>
        {config.status === "active" ? (
          <button onClick={() => changeStatus("paused")} disabled={!!busy}>Sospendi operativita</button>
        ) : (
          <button onClick={() => changeStatus("active")} disabled={!!busy}>Riattiva operativita</button>
        )}
      </div>
      <div className="portfolioDangerZone">
        <div>
          <strong>Eliminazione completa</strong>
          {selectedId === "main" ? (
            <p>Il portafoglio principale <b>main</b> è protetto e non può essere eliminato.</p>
          ) : (
            <p>Rimuove definitivamente posizioni, trigger, proposte, storico, runtime, cache dashboard e impostazioni di <b>{selectedId}</b>.</p>
          )}
        </div>
        {selectedId !== "main" && (
          <div className="portfolioDeleteControls">
            <label>
              <span>Digita <b>{selectedId}</b> per confermare</span>
              <input
                value={deleteConfirmation}
                onChange={(event) => setDeleteConfirmation(event.target.value)}
                autoComplete="off"
              />
            </label>
            <button
              className="dangerButton"
              onClick={deleteSelectedPortfolio}
              disabled={!!busy || deleteConfirmation !== selectedId}
            >
              {busy === "delete" ? "Eliminazione e verifica..." : "Elimina tutto il portafoglio"}
            </button>
          </div>
        )}
      </div>
      {message && <div className={message.startsWith("Errore") ? "error" : "okBox"}>{message}</div>}
    </section>
  );
}

function App() {
  const [selectedPortfolioId, setSelectedPortfolioId] = useState(
    () => window.localStorage.getItem("selectedPortfolioId") || "main",
  );
  const [data, setData] = useState(() => readDashboardSnapshot(
    window.localStorage.getItem("selectedPortfolioId") || "main",
  ));
  const [error, setError] = useState("");
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [chartItem, setChartItem] = useState(null);
  const [newsTicker, setNewsTicker] = useState("");
  const [runNowBusy, setRunNowBusy] = useState(false);
  const [runNowMessage, setRunNowMessage] = useState("");
  const [schedulerBusy, setSchedulerBusy] = useState(false);
  const [showPortfolioForm, setShowPortfolioForm] = useState(false);
  const [portfolioFormBusy, setPortfolioFormBusy] = useState(false);
  const [portfolioFormError, setPortfolioFormError] = useState("");
  const [portfolioForm, setPortfolioForm] = useState({
    id: "",
    name: "",
    initial_capital: 20000,
    risk_profile: "balanced",
    allowed_markets: ["ftse_mib", "commodities", "etf", "watchlist"],
    allowed_asset_classes: ["equity", "etf", "commodity_etc"],
    allow_leveraged: false,
  });
  const loadingRef = useRef(false);
  const agentStatusLoadingRef = useRef(false);

  async function load(options = {}) {
    const silent = Boolean(options.silent);
    const refresh = Boolean(options.refresh);
    const portfolioId = options.portfolioId || selectedPortfolioId;
    if (loadingRef.current) return;
    loadingRef.current = true;
    if (!silent) setDashboardLoading(true);
    try {
      setError("");
      const result = await api(
        `/api/dashboard?portfolio_id=${encodeURIComponent(portfolioId)}&refresh=${refresh ? "true" : "false"}`,
        { timeoutMs: refresh ? 120000 : 10000 },
      );
      const normalizedResult = normalizeDashboardPayload(result);
      setData(normalizedResult);
      saveDashboardSnapshot(portfolioId, normalizedResult);
    } catch (err) {
      const message = err.name === "AbortError"
        ? "Timeout nel caricamento dei dati. Il backend sta impiegando troppo tempo a rispondere."
        : err.message;
      setError(message);
    } finally {
      loadingRef.current = false;
      if (!silent) setDashboardLoading(false);
    }
  }

  useEffect(() => {
    window.localStorage.setItem("selectedPortfolioId", selectedPortfolioId);
    const snapshot = readDashboardSnapshot(selectedPortfolioId);
    setData(snapshot);
    setError("");
  }, [selectedPortfolioId]);
  useEffect(() => {
    async function loadAgentStatus() {
      if (agentStatusLoadingRef.current) return;
      agentStatusLoadingRef.current = true;
      try {
        const state = await api(
          `/api/agent/status?portfolio_id=${encodeURIComponent(selectedPortfolioId)}`,
          { timeoutMs: 5000 },
        );
        setData((current) => current
          ? {
              ...current,
              agent_run_state: {
                ...(current.agent_run_state || {}),
                ...state,
              },
            }
          : current);
      } catch {
        // Keep the last known state; the full dashboard refresh reports backend errors.
      } finally {
        agentStatusLoadingRef.current = false;
      }
    }
    loadAgentStatus();
    const timer = window.setInterval(loadAgentStatus, 3000);
    return () => window.clearInterval(timer);
  }, [selectedPortfolioId]);
  useEffect(() => {
    function openTickerNews(event) {
      const ticker = String(event.detail?.ticker || "").trim().toUpperCase();
      if (ticker) setNewsTicker(ticker);
    }
    window.addEventListener("open-ticker-news", openTickerNews);
    return () => window.removeEventListener("open-ticker-news", openTickerNews);
  }, []);
  const perf = data?.performance || {};
  const portfolio = data?.portfolio || {};
  const portfolioConfig = data?.portfolio_config || {};
  const portfolioOptions = data?.portfolios?.items || [];

  async function createPortfolio(event) {
    event.preventDefault();
    setPortfolioFormBusy(true);
    setPortfolioFormError("");
    try {
      const result = await api("/api/portfolios", {
        method: "POST",
        body: JSON.stringify(portfolioForm),
        timeoutMs: 15000,
      });
      const portfolioId = result?.config?.id;
      if (!portfolioId) throw new Error("Il backend non ha restituito l'ID del portafoglio.");
      setShowPortfolioForm(false);
      setPortfolioForm({
        id: "",
        name: "",
        initial_capital: 20000,
        risk_profile: "balanced",
        allowed_markets: ["ftse_mib", "commodities", "etf", "watchlist"],
        allowed_asset_classes: ["equity", "etf", "commodity_etc"],
        allow_leveraged: false,
      });
      setSelectedPortfolioId(portfolioId);
    } catch (err) {
      setPortfolioFormError(err.message);
    } finally {
      setPortfolioFormBusy(false);
    }
  }

  async function handlePortfolioDeleted(portfolioId, result) {
    window.localStorage.removeItem(dashboardStorageKey(portfolioId));
    window.localStorage.setItem("selectedPortfolioId", "main");
    setSelectedPortfolioId("main");
    setData(readDashboardSnapshot("main"));
    setRunNowMessage(`Portafoglio ${portfolioId} eliminato completamente: ${result.removed_items_count} elementi rimossi e verifica completata.`);
    await load({ portfolioId: "main", silent: true });
  }

  async function runNow() {
    setRunNowBusy(true);
    setRunNowMessage("Esecuzione manuale avviata. Analizzo tutto lo scope: FTSE MIB, MateriePrime.xlsx, ETF, watchlist e trigger monitorati.");
    try {
      await api("/api/agent/run-once", {
        method: "POST",
        body: JSON.stringify({
          scan_limit: 5,
          max_auto_trade_pct: 25,
          portfolio_id: selectedPortfolioId,
        }),
        timeoutMs: 900000,
      });
      setRunNowMessage("Esecuzione manuale completata. Dashboard aggiornata.");
      await load({ refresh: true });
    } catch (err) {
      setRunNowMessage(`Errore esecuzione manuale: ${err.message}. Dettagli completi nel tab Run log.`);
    } finally {
      setRunNowBusy(false);
    }
  }

  async function toggleScheduler() {
    const currentlyEnabled = data?.agent_run_state?.scheduler_enabled !== false;
    const enabled = !currentlyEnabled;
    setSchedulerBusy(true);
    setRunNowMessage(enabled
      ? "Riattivazione dell'esecuzione automatica..."
      : "Disattivazione delle prossime esecuzioni automatiche...");
    try {
      const result = await api("/api/scheduler/settings", {
        method: "POST",
        body: JSON.stringify({ enabled }),
        timeoutMs: 15000,
      });
      setData((current) => current
        ? {
            ...current,
            agent_run_state: {
              ...(current.agent_run_state || {}),
              ...result,
            },
          }
        : current);
      setRunNowMessage(enabled
        ? "Esecuzione automatica riattivata."
        : "Esecuzione automatica disattivata. Un'eventuale run gia avviata puo terminare normalmente.");
    } catch (err) {
      setRunNowMessage(`Errore scheduler: ${err.message}`);
    } finally {
      setSchedulerBusy(false);
    }
  }

  const tabs = useMemo(() => [
    ["dashboard", "Dashboard"],
    ["summary", "Riepilogo"],
    ["portfolios", "Portafogli"],
    ["ftse-mib", "FTSE MIB"],
    ["commodities", "Materie prime"],
    ["etfs", "ETF"],
    ["news", "News"],
    ["chat", "Chat"],
    ["watchlist", "Watchlist"],
    ["actions", "Azioni"],
  ], []);
  const [tab, setTab] = useState("dashboard");
  const riskProfileLabel = {
    conservative: "Prudente",
    balanced: "Bilanciato",
    dynamic: "Dinamico",
    custom: "Personalizzato",
  }[portfolioConfig.risk_profile] || portfolioConfig.risk_profile || "Profilo";
  const portfolioStatusLabel = {
    active: "Attivo",
    paused: "Sospeso",
    archived: "Archiviato",
  }[portfolioConfig.status] || portfolioConfig.status || "Dati non caricati";

  const openChart = (chartData) => setChartItem({
    ...chartData,
    portfolio_id: chartData?.portfolio_id || selectedPortfolioId,
  });

  return (
    <main>
      <header className="appHeader">
        <div className="appBrand">
          <div className="brandIcon"><Bot size={25} /></div>
          <div>
            <h1>Autonomous Trading Agent</h1>
            <p>Portafogli virtuali, analisi condivise e trading automatico.</p>
          </div>
        </div>
        <div className="headerActions">
          <div className="activePortfolioControl">
            <div className="activePortfolioTop">
              <span className="activePortfolioLabel">Portafoglio attivo</span>
              <span className={`activePortfolioStatus ${portfolioConfig.status || "loading"}`}>
                <i /> {portfolioStatusLabel}
              </span>
            </div>
            <div className="activePortfolioSelector">
              <select aria-label="Portafoglio attivo" value={selectedPortfolioId} onChange={(event) => setSelectedPortfolioId(event.target.value)}>
                {portfolioOptions.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
                {!portfolioOptions.some((item) => item.id === selectedPortfolioId) && <option value={selectedPortfolioId}>{selectedPortfolioId}</option>}
              </select>
              <button className="portfolioAddButton" onClick={() => setShowPortfolioForm((value) => !value)} title="Crea un nuovo portafoglio" aria-label="Crea un nuovo portafoglio">+</button>
            </div>
            <div className="activePortfolioMeta">
              <div>
                <span>{riskProfileLabel}</span>
                {portfolioConfig.initial_capital != null && <span>{eur(portfolioConfig.initial_capital)} iniziali</span>}
              </div>
              <button
                className={`schedulerCompact ${data?.agent_run_state?.scheduler_enabled === false ? "schedulerOff" : ""}`}
                onClick={toggleScheduler}
                disabled={schedulerBusy || !data?.agent_run_state?.scheduler_task_name}
                title="Attiva o disattiva le esecuzioni automatiche ogni 30 minuti"
              >
                {data?.agent_run_state?.scheduler_enabled === false ? <PlayCircle size={13} /> : <PauseCircle size={13} />}
                {schedulerBusy ? "Aggiorno" : data?.agent_run_state?.scheduler_enabled === false ? "Auto OFF" : "Auto ON"}
              </button>
            </div>
          </div>
          <button className="iconButton primaryHeaderAction" onClick={runNow} disabled={runNowBusy}>
            <Activity size={18} /> {runNowBusy ? "Avvio..." : "Esegui ora"}
          </button>
          <button
            className="iconButton refreshHeaderAction refreshIconOnly"
            onClick={() => load({ refresh: true })}
            disabled={dashboardLoading}
            title="Aggiorna dati Yahoo Finance (riusa la cache se ha meno di 10 minuti)"
            aria-label="Aggiorna dati Yahoo Finance"
          >
            <RefreshCw size={18} className={dashboardLoading ? "spinning" : ""} />
          </button>
        </div>
      </header>

      {showPortfolioForm && (
        <section className="panel portfolioCreatePanel">
          <div className="portfolioCreateHeading">
            <div>
              <h2>Nuovo portafoglio</h2>
              <p>Crea un capitale virtuale indipendente scegliendo il profilo di rischio iniziale.</p>
            </div>
            <button onClick={() => setShowPortfolioForm(false)}>Chiudi</button>
          </div>
          <form className="portfolioCreateForm" onSubmit={createPortfolio}>
            <label>
              <span>Nome</span>
              <input
                required
                value={portfolioForm.name}
                onChange={(event) => {
                  const name = event.target.value;
                  const suggestedId = name
                    .toLowerCase()
                    .normalize("NFD")
                    .replace(/[\u0300-\u036f]/g, "")
                    .replace(/[^a-z0-9]+/g, "-")
                    .replace(/^-|-$/g, "")
                    .slice(0, 50);
                  setPortfolioForm((current) => ({
                    ...current,
                    name,
                    id: suggestedId,
                  }));
                }}
                placeholder="Per esempio: Prudente ETF"
              />
            </label>
            <label>
              <span>ID stabile</span>
              <input
                required
                minLength={3}
                value={portfolioForm.id}
                onChange={(event) => setPortfolioForm((current) => ({ ...current, id: event.target.value.toLowerCase() }))}
                placeholder="prudente-etf"
              />
            </label>
            <label>
              <span>Capitale iniziale</span>
              <input
                required
                type="number"
                min="1"
                step="0.01"
                value={portfolioForm.initial_capital}
                onChange={(event) => setPortfolioForm((current) => ({ ...current, initial_capital: Number(event.target.value) }))}
              />
            </label>
            <label>
              <span>Profilo di rischio</span>
              <select
                value={portfolioForm.risk_profile}
                onChange={(event) => setPortfolioForm((current) => ({ ...current, risk_profile: event.target.value }))}
              >
                <option value="conservative">Prudente</option>
                <option value="balanced">Bilanciato</option>
                <option value="dynamic">Dinamico</option>
              </select>
            </label>
            <fieldset className="portfolioChoiceGroup">
              <legend>Mercati</legend>
              {[
                ["ftse_mib", "FTSE MIB"],
                ["commodities", "Materie prime"],
                ["etf", "ETF"],
                ["watchlist", "Watchlist"],
              ].map(([value, label]) => (
                <label key={value}>
                  <input
                    type="checkbox"
                    checked={portfolioForm.allowed_markets.includes(value)}
                    onChange={(event) => setPortfolioForm((current) => ({
                      ...current,
                      allowed_markets: event.target.checked
                        ? [...current.allowed_markets, value]
                        : current.allowed_markets.filter((item) => item !== value),
                    }))}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </fieldset>
            <fieldset className="portfolioChoiceGroup">
              <legend>Strumenti</legend>
              {[
                ["equity", "Azioni"],
                ["etf", "ETF"],
                ["commodity_etc", "ETC / commodity"],
              ].map(([value, label]) => (
                <label key={value}>
                  <input
                    type="checkbox"
                    checked={portfolioForm.allowed_asset_classes.includes(value)}
                    onChange={(event) => setPortfolioForm((current) => ({
                      ...current,
                      allowed_asset_classes: event.target.checked
                        ? [...current.allowed_asset_classes, value]
                        : current.allowed_asset_classes.filter((item) => item !== value),
                    }))}
                  />
                  <span>{label}</span>
                </label>
              ))}
              <label>
                <input
                  type="checkbox"
                  checked={portfolioForm.allow_leveraged}
                  onChange={(event) => setPortfolioForm((current) => ({
                    ...current,
                    allow_leveraged: event.target.checked,
                  }))}
                />
                <span>Leveraged</span>
              </label>
            </fieldset>
            <button className="primaryHeaderAction" disabled={portfolioFormBusy}>
              {portfolioFormBusy ? "Creazione..." : "Crea portafoglio"}
            </button>
          </form>
          {portfolioFormError && <div className="error">{portfolioFormError}</div>}
        </section>
      )}

      {error && <div className="error">{error}</div>}

      <nav className="mainNav">
        {tabs.map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
        <select
          className={`systemNavSelect ${["logs", "controls"].includes(tab) ? "active" : ""}`}
          aria-label="Pagine di sistema"
          value={["logs", "controls"].includes(tab) ? tab : ""}
          onChange={(event) => event.target.value && setTab(event.target.value)}
        >
          <option value="">Sistema</option>
          <option value="logs">Run log</option>
          <option value="controls">Controlli</option>
        </select>
      </nav>

      {!data && tab === "logs" && <RunLogs />}
      {!data && tab === "controls" && <Controls reload={load} portfolioId={selectedPortfolioId} />}
      {!data && tab === "news" && <NewsReports />}
      {!data && !["logs", "controls", "news"].includes(tab) && (
        <section className="panel dashboardLoading">
          <strong>Nessun dato dashboard salvato</strong>
          <p>L'apertura della pagina non interroga automaticamente Yahoo Finance.</p>
          <button className="primaryHeaderAction" onClick={() => load({ refresh: true })} disabled={dashboardLoading}>
            <RefreshCw size={16} className={dashboardLoading ? "spinning" : ""} />
            {dashboardLoading ? "Collegamento a Yahoo Finance..." : "Aggiorna dati ora"}
          </button>
        </section>
      )}

      {data && (
        <>
          <div className="dashboardFreshness">
            <span>
              Dati Yahoo aggiornati: <b>{dateTime(data.dashboard_cache?.refreshed_at)}</b>
              {data.dashboard_cache?.source === "cache" && " · visualizzati dalla cache"}
            </span>
            {data.dashboard_cache?.refresh_skipped_recent && <strong>Nessun nuovo collegamento: dati aggiornati meno di 10 minuti fa.</strong>}
            {dashboardLoading && <strong>Aggiornamento Yahoo Finance in corso...</strong>}
          </div>
          {(data.exit_enforcement?.decisions || []).map((decision) => (
            <div
              className={decision.applied ? "exitExecutionBanner applied" : "exitExecutionBanner pending"}
              key={`${decision.ticker}-${decision.proposal_id || decision.decision}`}
            >
              <strong>{decision.ticker}: {decision.applied ? "VENDITA TOTALE ESEGUITA" : "USCITA NON ANCORA ESEGUITA"}</strong>
              <span>
                Prezzo {price(decision.current_price)} · stop {price(decision.stop_level)} · proposta {decision.proposal_id || "esistente"}
                {!decision.applied && ` · stato ${decision.decision}`}
              </span>
            </div>
          ))}
          {!["summary", "portfolios"].includes(tab) && <div className="metrics">
            <AgentRunStatus
              state={data.agent_run_state || {}}
              playwrightHealth={data.playwright_health || {}}
              tokenUsage={data.token_usage || {}}
              stats={{
                positionsCount: (perf.positions || []).length,
                monitoredCount: (data.monitored || []).length,
                ftseMibCount: (data.ftse_mib || []).length,
                commoditiesCount: (data.commodities || []).length,
                etfCount: (data.etfs || []).length,
              }}
            />
            <Metric label="Capitale iniziale" value={eur(portfolio.initial_capital)} icon={<Wallet size={16} />} />
            <Metric
              label="Patrimonio totale"
              value={eur(perf.total_value)}
              delta={perf.total_pnl_pct}
              icon={<Activity size={16} />}
              subtitle="Cash + valore corrente dei titoli"
              emphasis="total"
            />
            <Metric
              label="Valore titoli"
              value={eur(perf.positions_value)}
              icon={<TrendingUp size={16} />}
              subtitle={`${pct(perf.exposure_pct, false)} del patrimonio`}
              emphasis="positions"
            />
            <Metric
              label="Cash disponibile"
              value={eur(perf.cash)}
              icon={<Wallet size={16} />}
              subtitle={`${pct(perf.cash_pct, false)} del patrimonio`}
              emphasis="cash"
            />
            <Metric label="P/L totale" value={eur(perf.total_pnl)} valueTone={signedClass(perf.total_pnl)} delta={perf.total_pnl_pct} icon={perf.total_pnl >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />} />
          </div>}
          {runNowMessage && <div className={`manualRunBanner ${runNowBusy ? "running" : ""}`}>{runNowMessage}</div>}

          {tab === "dashboard" && (
            <>
              <TokenUsagePanel usage={data.token_usage || {}} />
              <PortfolioPerformanceChart data={data.performance_history || {}} />
              <Positions rows={perf.positions || []} onChart={openChart} performance={perf} />
              <ExitConditions rows={data.exit_conditions || []} onChart={openChart} />
              <Monitoring rows={data.monitored || []} positions={perf.positions || []} onChart={openChart} />
            </>
          )}
          {tab === "summary" && (
            <PortfoliosSummary
              selectedId={selectedPortfolioId}
              onSelect={setSelectedPortfolioId}
              onChart={openChart}
            />
          )}
          {tab === "portfolios" && (
            <PortfolioManager
              config={portfolioConfig}
              registry={data.portfolios || {}}
              selectedId={selectedPortfolioId}
              onSelect={setSelectedPortfolioId}
              onDeleted={handlePortfolioDeleted}
              reload={load}
            />
          )}
          {tab === "ftse-mib" && <FtseMib rows={data.ftse_mib || []} monitoredRows={data.monitored || []} positions={perf.positions || []} onChart={openChart} />}
          {tab === "commodities" && <Commodities rows={data.commodities || []} monitoredRows={data.monitored || []} positions={perf.positions || []} onChart={openChart} />}
          {tab === "etfs" && <Etfs rows={data.etfs || []} monitoredRows={data.monitored || []} positions={perf.positions || []} onChart={openChart} />}
          {tab === "news" && <NewsReports />}
          {tab === "chat" && <Chat portfolioId={selectedPortfolioId} />}
          {tab === "watchlist" && (
            <Watchlist
              rows={portfolio.watchlist || []}
              reload={load}
              onChart={openChart}
              portfolioId={selectedPortfolioId}
            />
          )}
          {tab === "actions" && <Actions rows={data.recent_actions || []} />}
          {tab === "logs" && <RunLogs />}
          {tab === "controls" && <Controls reload={load} portfolioId={selectedPortfolioId} />}
        </>
      )}
      <ChartModal item={chartItem} onClose={() => setChartItem(null)} />
      {newsTicker && <QuickNewsPanel ticker={newsTicker} onClose={() => setNewsTicker("")} />}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
