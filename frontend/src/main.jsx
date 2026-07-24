import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, Bot, LineChart, MessageSquare, RefreshCw, Send, TrendingDown, TrendingUp, Wallet, X } from "lucide-react";
import "./styles.css";

const API = "http://127.0.0.1:8000";

function eur(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/d";
  return `EUR ${Number(value).toLocaleString("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
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
  const unit = "\\s*(?:eur|euro|gbp|p|€)?";
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
    .replaceAll("â‚¬", "€")
    .replaceAll("Ã¨", "è")
    .replaceAll("Ã©", "é")
    .replaceAll("Ã ", "à")
    .replaceAll("Ã²", "ò")
    .replaceAll("Ã¹", "ù")
    .replaceAll("Ã¬", "ì")
    .replaceAll("Â°", "°");
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
    throw new Error(text || `Errore HTTP ${response.status}`);
  }
  const data = await response.json();
  return normalizeData(data);
}

function normalizeData(value) {
  if (typeof value === "string") return cleanText(value);
  if (Array.isArray(value)) return value.map(normalizeData);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, normalizeData(item)]));
  }
  return value;
}

function Metric({ label, value, delta, icon }) {
  return (
    <div className="metric">
      <div className="metricLabel">{icon}{label}</div>
      <div className="metricValue">{value}</div>
      {delta !== undefined && <div className={`metricDelta ${signedClass(delta)}`}>{pct(delta)}</div>}
    </div>
  );
}

function AgentRunStatus({ state = {} }) {
  const status = state.status || "never_run";
  const statusClass = status === "ok" ? "positive" : status === "running" ? "warning" : status === "error" ? "negative" : "neutral";
  const schedulerDisabled = state.scheduler_state === "Disabled" || state.scheduler_enabled === false;
  const scheduleClass = schedulerDisabled || state.running_state_is_stale ? "negative" : state.next_scheduled_is_overdue ? "warning" : "neutral";
  const primaryNextRun = state.scheduler_enabled && state.scheduler_next_run_at
    ? state.scheduler_next_run_at
    : state.next_scheduled_expected_at;
  const scheduleText = schedulerDisabled
    ? "Scheduler disabilitato"
    : primaryNextRun
      ? dateTime(primaryNextRun)
      : "Non schedulato";
  const scheduleBadge = schedulerDisabled
    ? "task disabled"
    : state.running_state_is_stale
      ? "running stale"
      : state.next_scheduled_is_overdue
        ? "in ritardo"
        : "";
  return (
    <section className="agentStatus">
      <div>
        <span className="agentStatusLabel">Stato agente</span>
        <strong className={`pill ${statusClass}`}>{status === "never_run" ? "mai eseguito" : status}</strong>
      </div>
      <div><span>Ultimo grafico/analisi file</span><b>{dateTime(state.last_stock_analysis_at)}</b></div>
      <div><span>Ultimo ticker con file analisi</span><b>{state.last_stock_analysis_ticker || "n/d"}</b></div>
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
      <div><span>Analisi disponibili</span><b>{state.analyzed_tickers_count || 0} titoli</b></div>
      <div><span>Ultimo ciclo agente completato</span><b>{dateTime(state.last_completed_at)}</b></div>
      <div><span>Modalita</span><b>{state.last_mode || "n/d"}</b></div>
      {state.last_error && <div className="agentStatusError"><span>Errore ultima run</span><b>{state.last_error}</b></div>}
    </section>
  );
}

function Positions({ rows = [], onChart }) {
  return (
    <section className="panel">
      <h2>Portafoglio</h2>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Investito</th>
              <th>Valore attuale</th>
              <th>P/L</th>
              <th>P/L %</th>
              <th>Entry</th>
              <th>Prezzo</th>
              <th>Oggi</th>
              <th>Quantita</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.ticker}>
                <td className="ticker">{row.ticker}</td>
                <td>{eur(row.invested_amount)}</td>
                <td>{eur(row.market_value)}</td>
                <td className={signedClass(row.pnl)}>{eur(row.pnl)}</td>
                <td><span className={`pill ${signedClass(row.pnl_pct)}`}>{pct(row.pnl_pct)}</span></td>
                <td>{price(row.entry_price)}</td>
                <td>{price(row.current_price)}</td>
                <td><span className={`pill ${signedClass(row.daily_change_pct)}`}>{pct(row.daily_change_pct)}</span></td>
                <td>{price(row.virtual_quantity)}</td>
                <td><button className="miniButton" onClick={() => onChart({ ticker: row.ticker, current_price: row.current_price, trigger_level: row.entry_price, support_level: null, condition: "Prezzo di ingresso posizione" })}><LineChart size={15} /> Grafico</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ExitConditions({ rows = [], onChart }) {
  if (!rows.length) {
    return (
      <section className="panel">
        <h2>Condizioni di uscita</h2>
        <div className="emptyState">Nessuna posizione aperta da gestire.</div>
      </section>
    );
  }
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Condizioni di uscita</h2>
        <span>Basate su supporti/resistenze e analisi Playwright quando disponibile</span>
      </div>
      <div className="exitGrid">
        {rows.map((row) => (
          <div className="exitCard" key={row.ticker}>
            <div className="triggerHeader">
              <strong>{row.ticker}</strong>
              <span className={`status ${row.status_kind}`}>{row.status}</span>
            </div>
            <div className="triggerGrid">
              <div><span>Prezzo</span><b>{price(row.current_price)}</b></div>
              <div><span>Oggi</span><b className={signedClass(row.daily_change_pct)}>{pct(row.daily_change_pct)}</b></div>
              <div><span>P/L posizione</span><b className={signedClass(row.pnl_pct)}>{pct(row.pnl_pct)}</b></div>
              <div><span>Stop uscita</span><b>{price(row.stop_level)}</b></div>
              <div><span>Take profit</span><b>{price(row.take_profit_level)}</b></div>
              <div><span>Distanza stop</span><b className={signedClass(row.distance_to_stop_pct)}>{pct(row.distance_to_stop_pct)}</b></div>
              <div><span>Distanza target</span><b className={signedClass(row.distance_to_take_profit_pct)}>{pct(row.distance_to_take_profit_pct)}</b></div>
            </div>
            <p className="exitAction">{row.primary_action}</p>
            <p className="condition">{row.explanation}</p>
            <div className="sourceLine">Fonte: {row.source}</div>
            <button
              className="chartButton"
              onClick={() => onChart({
                ticker: row.ticker,
                current_price: row.current_price,
                trigger_level: row.take_profit_level,
                support_level: row.stop_level,
                trigger_distance_pct: row.distance_to_take_profit_pct,
                condition: `Uscita: stop ${price(row.stop_level)} / take profit ${price(row.take_profit_level)}. ${row.primary_action}`,
              })}
            >
              <LineChart size={16} /> Grafico uscita
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

function TriggerCard({ item, onChart }) {
  const progress = item.trigger_progress ?? 0;
  const missing = item.trigger_distance_pct === null || item.trigger_distance_pct === undefined ? null : -item.trigger_distance_pct;
  return (
    <div className="triggerCard">
      <div className="triggerHeader">
        <strong>{item.ticker}</strong>
        <span className={`status ${item.trigger_status_kind}`}>{item.trigger_status}</span>
      </div>
      <div className="triggerGrid">
        <div><span>Prezzo attuale</span><b>{price(item.current_price)}</b></div>
        <div><span>Oggi</span><b className={signedClass(item.daily_change_pct)}>{pct(item.daily_change_pct)}</b></div>
        <div><span>Trigger ingresso</span><b>{price(item.trigger_level)}</b></div>
        <div><span>Supporto/stop</span><b>{price(item.support_level)}</b></div>
        <div><span>Distanza trigger</span><b className={signedClass(item.trigger_distance_pct)}>{pct(item.trigger_distance_pct)}</b></div>
      </div>
      <div className="rangeLabels"><span>Supporto</span><span>Trigger</span></div>
      <div className="progress"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
      <p className="small">
        {item.trigger_distance_pct >= 0
          ? `Prezzo sopra il trigger di ${pct(item.trigger_distance_pct, false)}.`
          : missing !== null
            ? `Mancano ${pct(missing, false)} al trigger di ingresso.`
            : "Distanza dal trigger non disponibile."}
      </p>
      <p className="condition">{item.condition}</p>
      <button className="chartButton" onClick={() => onChart(item)}><LineChart size={16} /> Apri grafico trigger</button>
    </div>
  );
}

function Monitoring({ rows = [], onChart }) {
  const near = rows.filter((row) => row.trigger_distance_pct !== null && Math.abs(row.trigger_distance_pct) <= 3);
  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Monitoraggio trigger</h2>
        <span>{near.length} vicini entro +/-3%</span>
      </div>
      <div className="cardsGrid">
        {rows.map((item) => <TriggerCard key={item.id || item.ticker} item={item} onChart={onChart} />)}
      </div>
    </section>
  );
}

function Watchlist({ rows = [], reload, onChart }) {
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
      await api("/api/watchlist", {
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
      await api("/api/watchlist", {
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
      await api(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" });
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
      const result = await api("/api/agent/analyze-watchlist-entry-conditions", {
        method: "POST",
        body: JSON.stringify({}),
        timeoutMs: 1800000,
      });
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

function PriceChart({ prices = [], triggerLevel, supportLevel, mode = "candles" }) {
  const [hoverIndex, setHoverIndex] = useState(null);
  const width = 1040;
  const height = 470;
  const pad = { top: 34, right: 142, bottom: 70, left: 88 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const priceValues = prices
    .flatMap((row) => [row.open, row.high, row.low, row.close].map(Number))
    .filter((value) => !Number.isNaN(value));
  const closeValues = prices.map((row) => Number(row.close)).filter((value) => !Number.isNaN(value));
  const levels = [triggerLevel, supportLevel].map(Number).filter((value) => !Number.isNaN(value) && value > 0);
  const min = Math.min(...priceValues, ...levels);
  const max = Math.max(...priceValues, ...levels);
  const span = max - min || 1;
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.08;
  const x = (index) => pad.left + (prices.length <= 1 ? 0 : (index / (prices.length - 1)) * plotW);
  const y = (value) => pad.top + ((yMax - value) / (yMax - yMin)) * plotH;
  const candleW = Math.max(3, Math.min(12, plotW / Math.max(prices.length, 1) * 0.58));
  const path = prices
    .map((row, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(Number(row.close)).toFixed(2)}`)
    .join(" ");
  const area = `${path} L ${pad.left + plotW} ${pad.top + plotH} L ${pad.left} ${pad.top + plotH} Z`;
  const ticks = Array.from({ length: 5 }, (_, index) => yMin + ((yMax - yMin) / 4) * index);
  const last = prices[prices.length - 1];
  const first = prices[0];
  const hover = hoverIndex === null ? last : prices[hoverIndex];
  const hoverX = hover ? x(hoverIndex === null ? prices.length - 1 : hoverIndex) : null;
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

  function LevelLine({ value, label, className }) {
    const level = Number(value);
    if (Number.isNaN(level) || level <= 0) return null;
    const ly = y(level);
    return (
      <g className={className}>
        <line x1={pad.left} x2={pad.left + plotW} y1={ly} y2={ly} />
        <text x={pad.left + plotW + 12} y={ly + 4}>{label} {price(level)}</text>
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
          <line x1={x(tick.index)} x2={x(tick.index)} y1={pad.top + plotH} y2={pad.top + plotH + 7} />
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
      <LevelLine value={triggerLevel} label="TRIGGER" className="triggerLine" />
      <LevelLine value={supportLevel} label="SUPPORTO" className="supportLine" />
      {last && (
        <g className="lastPoint">
          <circle cx={x(prices.length - 1)} cy={y(Number(last.close))} r="5" />
          <text x={pad.left + plotW + 12} y={y(Number(last.close)) - 10}>Prezzo {price(last.close)}</text>
        </g>
      )}
      {hover && hoverX !== null && (
        <g className="hoverLayer">
          <line x1={hoverX} x2={hoverX} y1={pad.top} y2={pad.top + plotH} />
          <circle cx={hoverX} cy={y(Number(hover.close))} r="4" />
          <g transform={`translate(${Math.min(hoverX + 12, width - 230)} ${pad.top + 12})`}>
            <rect width="210" height="86" rx="8" />
            <text x="10" y="22">{hover.date}</text>
            <text x="10" y="44">Close {price(hover.close)}</text>
            <text x="10" y="66">O/H/L {price(hover.open)} / {price(hover.high)} / {price(hover.low)}</text>
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

  if (!item) return null;
  const parsedLevels = levelsFromCondition(item.condition || "");
  const triggerLevel = numeric(item.trigger_level) || parsedLevels.trigger;
  const supportLevel = numeric(item.support_level) || parsedLevels.support;
  const lastPrice = state.prices.length ? numeric(state.prices[state.prices.length - 1]?.close) : null;
  const currentPrice = numeric(item.current_price) || lastPrice;
  const distance = numeric(item.trigger_distance_pct)
    ?? (currentPrice && triggerLevel ? ((triggerLevel - currentPrice) / currentPrice) * 100 : null);
  const parsedNote = (!numeric(item.trigger_level) && parsedLevels.trigger) || (!numeric(item.support_level) && parsedLevels.support);
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
          <span>Trigger <b>{price(triggerLevel)}</b></span>
          <span>Supporto/stop <b>{price(supportLevel)}</b></span>
          <span>Distanza trigger <b className={signedClass(distance)}>{pct(distance)}</b></span>
        </div>
        {parsedNote && (
          <div className="chartLevelNote">
            Livelli letti dalla condizione ingresso e disegnati sul grafico prezzo.
          </div>
        )}
        <div className="chartToolbar">
          <div className="segmented">
            {["1mo", "3mo", "6mo", "1y"].map((value) => (
              <button key={value} className={period === value ? "active" : ""} onClick={() => setPeriod(value)}>{value}</button>
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
                <PriceChart prices={state.prices} triggerLevel={triggerLevel} supportLevel={supportLevel} mode={mode} />
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
            ? <PriceChart prices={state.prices} triggerLevel={triggerLevel} supportLevel={supportLevel} mode={mode} />
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
                <td className="ticker">{row.ticker}</td>
                <td className="reason">{row.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Chat() {
  const [messages, setMessages] = useState([
    { role: "assistant", content: "Ciao, sono TradingWatchAgent. Chiedimi stato, performance, condizioni o nuove analisi." },
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
        body: JSON.stringify({ message, history: messages }),
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

function Controls({ reload }) {
  const [scanLimit, setScanLimit] = useState(5);
  const [maxTradePct, setMaxTradePct] = useState(25);
  const [telegramSettings, setTelegramSettings] = useState({
    monitoring_mode: "always",
    send_performance_alerts: true,
    max_monitoring_items: 5,
  });
  const [busy, setBusy] = useState("");
  const [log, setLog] = useState("");
  const [status, setStatus] = useState({
    state: "idle",
    label: "Pronto",
    detail: "Nessuna operazione in corso.",
    startedAt: null,
    finishedAt: null,
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
        const result = await api("/api/telegram/settings");
        setTelegramSettings(result.settings || telegramSettings);
      } catch (error) {
        setLog(`Errore caricamento impostazioni Telegram: ${error.message}`);
      }
    }
    loadTelegramSettings();
  }, []);

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
    setNow(startedAt);
    setStatus({
      state: "running",
      label,
      detail: `Esecuzione ${label} in corso. Attendo risposta dal backend/agente...`,
      startedAt,
      finishedAt: null,
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
      });
      reload();
    } catch (error) {
      setLog(error.message);
      setStatus({
        state: "error",
        label,
        detail: `Errore durante ${label}: ${error.message}`,
        startedAt,
        finishedAt: Date.now(),
      });
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
      const result = await api("/api/telegram/settings", {
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

  return (
    <section className="panel">
      <h2>Controlli</h2>
      <div className="controlRow">
        <label>Scan limit<input type="number" value={scanLimit} min="1" max="40" onChange={(e) => setScanLimit(e.target.value)} /></label>
        <label>Max auto trade %<input type="number" value={maxTradePct} min="1" max="100" onChange={(e) => setMaxTradePct(e.target.value)} /></label>
      </div>
      <div className="actions">
        <button onClick={() => run("/api/agent/run-once", { scan_limit: scanLimit, max_auto_trade_pct: maxTradePct }, "monitor")} disabled={!!busy}>Run monitor once</button>
        <button onClick={() => run("/api/telegram/monitoring", {}, "telegram")} disabled={!!busy}>Telegram monitoraggio</button>
        <button onClick={() => run("/api/telegram/performance", {}, "performance")} disabled={!!busy}>Telegram performance</button>
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
        <div className="runProgress" aria-hidden="true"><span /></div>
        <p>{status.detail}</p>
      </div>
      {log && <pre className="log">{log}</pre>}
    </section>
  );
}

function RunLogs() {
  const [state, setState] = useState({ loading: true, error: "", data: null });
  const [lines, setLines] = useState(300);

  async function loadLogs() {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const data = await api(`/api/run-logs?lines=${lines}`);
      setState({ loading: false, error: "", data });
    } catch (error) {
      setState({ loading: false, error: error.message, data: null });
    }
  }

  useEffect(() => { loadLogs(); }, []);

  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Run log</h2>
        <div className="sectionActions">
          <label className="logLinesControl">Righe
            <input type="number" min="50" max="2000" value={lines} onChange={(event) => setLines(event.target.value)} />
          </label>
          <button className="iconButton" onClick={loadLogs} disabled={state.loading}><RefreshCw size={16} /> Aggiorna log</button>
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
            <h3>scheduled-monitor.log</h3>
            <pre className="log runLog">{state.data.scheduled_log || "Nessun output disponibile."}</pre>
          </div>
          <div>
            <h3>scheduled-monitor.err.log</h3>
            <pre className="log runLog errorLog">{state.data.scheduled_err || "Nessun errore disponibile."}</pre>
          </div>
        </div>
      )}
    </section>
  );
}

function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [chartItem, setChartItem] = useState(null);
  const [runNowBusy, setRunNowBusy] = useState(false);
  const [runNowMessage, setRunNowMessage] = useState("");

  async function load() {
    setDashboardLoading(true);
    try {
      setError("");
      setData(await api("/api/dashboard", { timeoutMs: 120000 }));
    } catch (err) {
      const message = err.name === "AbortError"
        ? "Timeout nel caricamento dei dati. Il backend sta impiegando troppo tempo a rispondere."
        : err.message;
      setError(message);
    } finally {
      setDashboardLoading(false);
    }
  }

  useEffect(() => { load(); }, []);
  const perf = data?.performance || {};
  const portfolio = data?.portfolio || {};

  async function runNow() {
    setRunNowBusy(true);
    setRunNowMessage("Esecuzione manuale avviata. L'agente puo impiegare qualche minuto.");
    try {
      await api("/api/agent/run-once", {
        method: "POST",
        body: JSON.stringify({ scan_limit: 5, max_auto_trade_pct: 25 }),
        timeoutMs: 900000,
      });
      setRunNowMessage("Esecuzione manuale completata. Dashboard aggiornata.");
      await load();
    } catch (err) {
      setRunNowMessage(`Errore esecuzione manuale: ${err.message}`);
    } finally {
      setRunNowBusy(false);
    }
  }

  const tabs = useMemo(() => [
    ["dashboard", "Dashboard"],
    ["watchlist", "Watchlist"],
    ["chat", "Chat"],
    ["actions", "Azioni"],
    ["logs", "Run log"],
    ["controls", "Controlli"],
  ], []);
  const [tab, setTab] = useState("dashboard");

  return (
    <main>
      <header>
        <div>
          <h1><Bot size={34} /> TradingWatchAgent</h1>
          <p>Portafoglio virtuale, agent autonomia e monitoraggio trigger.</p>
        </div>
        <div className="headerActions">
          <button className="iconButton primaryHeaderAction" onClick={runNow} disabled={runNowBusy}>
            <Activity size={18} /> {runNowBusy ? "Avvio..." : "Esegui ora"}
          </button>
          <button className="iconButton" onClick={load} disabled={dashboardLoading}>
            <RefreshCw size={18} /> {dashboardLoading ? "Aggiorno..." : "Aggiorna"}
          </button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <nav>{tabs.map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>)}</nav>

      {!data && tab === "logs" && <RunLogs />}
      {!data && tab === "controls" && <Controls reload={load} />}
      {!data && !["logs", "controls"].includes(tab) && (
        <section className="panel dashboardLoading">
          <strong>Caricamento dashboard in corso...</strong>
          <p>Sto aggiornando prezzi, performance e condizioni monitorate. Se il backend sta interrogando Yahoo Finance puo impiegare anche 20-60 secondi.</p>
          <p>Puoi aprire subito <b>Run log</b> o <b>Controlli</b> dal menu sopra mentre la dashboard termina il caricamento.</p>
        </section>
      )}

      {data && (
        <>
          <div className="metrics">
            <AgentRunStatus state={data.agent_run_state || {}} />
            <Metric label="Capitale" value={eur(portfolio.initial_capital)} icon={<Wallet size={16} />} />
            <Metric label="Valore portafoglio" value={eur(perf.total_value)} delta={perf.total_pnl_pct} icon={<Activity size={16} />} />
            <Metric label="P/L totale" value={eur(perf.total_pnl)} delta={perf.total_pnl_pct} icon={perf.total_pnl >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />} />
            <Metric label="Cash" value={eur(portfolio.cash)} icon={<Wallet size={16} />} />
          </div>
          {runNowMessage && <div className={`manualRunBanner ${runNowBusy ? "running" : ""}`}>{runNowMessage}</div>}

          {tab === "dashboard" && (
            <>
              <Positions rows={perf.positions || []} onChart={setChartItem} />
              <ExitConditions rows={data.exit_conditions || []} onChart={setChartItem} />
              <Monitoring rows={data.monitored || []} onChart={setChartItem} />
            </>
          )}
          {tab === "watchlist" && <Watchlist rows={portfolio.watchlist || []} reload={load} onChart={setChartItem} />}
          {tab === "chat" && <Chat />}
          {tab === "actions" && <Actions rows={data.recent_actions || []} />}
          {tab === "logs" && <RunLogs />}
          {tab === "controls" && <Controls reload={load} />}
        </>
      )}
      <ChartModal item={chartItem} onClose={() => setChartItem(null)} />
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
