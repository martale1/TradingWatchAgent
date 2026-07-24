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
  return (
    <section className="agentStatus">
      <div>
        <span className="agentStatusLabel">Stato agente</span>
        <strong className={`pill ${statusClass}`}>{status === "never_run" ? "mai eseguito" : status}</strong>
      </div>
      <div><span>Ultima analisi titoli</span><b>{dateTime(state.last_stock_analysis_at)}</b></div>
      <div><span>Ultimo ticker analizzato</span><b>{state.last_stock_analysis_ticker || "n/d"}</b></div>
      <div><span>Prossimo scheduled expected</span><b>{state.next_scheduled_expected_at ? dateTime(state.next_scheduled_expected_at) : "Non schedulato"}</b></div>
      <div><span>Intervallo</span><b>{state.interval_minutes || 30} min</b></div>
      <div><span>Analisi disponibili</span><b>{state.analyzed_tickers_count || 0} titoli</b></div>
      <div><span>Ultima run agente</span><b>{dateTime(state.last_completed_at)}</b></div>
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
              <div><span>P/L</span><b className={signedClass(row.pnl_pct)}>{pct(row.pnl_pct)}</b></div>
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
  const [priority, setPriority] = useState("normal");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");

  async function addItem(event) {
    event.preventDefault();
    if (!ticker.trim()) return;
    setBusy("add");
    setMessage("");
    try {
      await api("/api/watchlist", {
        method: "POST",
        body: JSON.stringify({ ticker, reason, priority }),
      });
      setTicker("");
      setReason("");
      setPriority("normal");
      setMessage("Titolo aggiunto alla watchlist.");
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

  return (
    <section className="panel">
      <div className="sectionHeader">
        <h2>Watchlist manuale</h2>
        <span>Titoli da analizzare anche se non selezionati dallo scanner</span>
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
        <button disabled={!!busy || !ticker.trim()}>Aggiungi</button>
      </form>
      {message && <p className="small">{message}</p>}
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
                  <td>{dateTime(row.added_at)}</td>
                  <td className="rowActions">
                    <button className="miniButton" onClick={() => onChart({ ticker: row.ticker, condition: row.reason || "Watchlist manuale" })}><LineChart size={15} /> Grafico</button>
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

function ChartModal({ item, onClose }) {
  const [state, setState] = useState({ loading: true, error: "", prices: [] });
  const [period, setPeriod] = useState("6mo");
  const [mode, setMode] = useState("candles");
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
  const distance = item.trigger_distance_pct;
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
          <span>Prezzo attuale <b>{price(item.current_price)}</b></span>
          <span>Trigger <b>{price(item.trigger_level)}</b></span>
          <span>Supporto/stop <b>{price(item.support_level)}</b></span>
          <span>Distanza trigger <b className={signedClass(distance)}>{pct(distance)}</b></span>
        </div>
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
        </div>
        {state.loading && <div className="chartStatus">Caricamento storico prezzi...</div>}
        {state.error && <div className="error">{state.error}</div>}
        {!state.loading && !state.error && <PriceChart prices={state.prices} triggerLevel={item.trigger_level} supportLevel={item.support_level} mode={mode} />}
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
  const [busy, setBusy] = useState("");
  const [log, setLog] = useState("");

  async function run(path, body, label) {
    setBusy(label);
    setLog("");
    try {
      const result = await api(path, { method: "POST", body: JSON.stringify(body || {}), timeoutMs: 900000 });
      setLog(result.output || result.message || JSON.stringify(result, null, 2));
      reload();
    } catch (error) {
      setLog(error.message);
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
      {busy && <p className="small">Esecuzione {busy} in corso...</p>}
      {log && <pre className="log">{log}</pre>}
    </section>
  );
}

function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [chartItem, setChartItem] = useState(null);

  async function load() {
    try {
      setError("");
      setData(await api("/api/dashboard"));
    } catch (err) {
      const message = err.name === "AbortError"
        ? "Timeout nel caricamento dei dati. Il backend sta impiegando troppo tempo a rispondere."
        : err.message;
      setError(message);
    }
  }

  useEffect(() => { load(); }, []);
  const perf = data?.performance || {};
  const portfolio = data?.portfolio || {};

  const tabs = useMemo(() => [
    ["dashboard", "Dashboard"],
    ["watchlist", "Watchlist"],
    ["chat", "Chat"],
    ["actions", "Azioni"],
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
        <button className="iconButton" onClick={load}><RefreshCw size={18} /> Aggiorna</button>
      </header>

      {error && <div className="error">{error}</div>}
      {!data ? <div className="panel">Caricamento...</div> : (
        <>
          <div className="metrics">
            <AgentRunStatus state={data.agent_run_state || {}} />
            <Metric label="Capitale" value={eur(portfolio.initial_capital)} icon={<Wallet size={16} />} />
            <Metric label="Valore portafoglio" value={eur(perf.total_value)} delta={perf.total_pnl_pct} icon={<Activity size={16} />} />
            <Metric label="P/L totale" value={eur(perf.total_pnl)} delta={perf.total_pnl_pct} icon={perf.total_pnl >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />} />
            <Metric label="Cash" value={eur(portfolio.cash)} icon={<Wallet size={16} />} />
          </div>

          <nav>{tabs.map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>)}</nav>

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
          {tab === "controls" && <Controls reload={load} />}
        </>
      )}
      <ChartModal item={chartItem} onClose={() => setChartItem(null)} />
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
