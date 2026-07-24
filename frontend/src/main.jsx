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

function signedClass(value) {
  const n = Number(value);
  if (n > 0) return "positive";
  if (n < 0) return "negative";
  return "neutral";
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 30000);
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    signal: controller.signal,
    ...options,
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
  return response.json();
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

function PriceChart({ prices = [], triggerLevel, supportLevel }) {
  const width = 1040;
  const height = 430;
  const pad = { top: 28, right: 86, bottom: 44, left: 64 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const closeValues = prices.map((row) => Number(row.close)).filter((value) => !Number.isNaN(value));
  const levels = [triggerLevel, supportLevel].map(Number).filter((value) => !Number.isNaN(value) && value > 0);
  const min = Math.min(...closeValues, ...levels);
  const max = Math.max(...closeValues, ...levels);
  const span = max - min || 1;
  const yMin = min - span * 0.08;
  const yMax = max + span * 0.08;
  const x = (index) => pad.left + (prices.length <= 1 ? 0 : (index / (prices.length - 1)) * plotW);
  const y = (value) => pad.top + ((yMax - value) / (yMax - yMin)) * plotH;
  const path = prices
    .map((row, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(Number(row.close)).toFixed(2)}`)
    .join(" ");
  const area = `${path} L ${pad.left + plotW} ${pad.top + plotH} L ${pad.left} ${pad.top + plotH} Z`;
  const ticks = Array.from({ length: 5 }, (_, index) => yMin + ((yMax - yMin) / 4) * index);
  const last = prices[prices.length - 1];
  const first = prices[0];

  function LevelLine({ value, label, className }) {
    const level = Number(value);
    if (Number.isNaN(level) || level <= 0) return null;
    const ly = y(level);
    return (
      <g className={className}>
        <line x1={pad.left} x2={pad.left + plotW} y1={ly} y2={ly} />
        <text x={pad.left + plotW + 10} y={ly + 4}>{label} {price(level)}</text>
      </g>
    );
  }

  if (!prices.length) return <div className="chartEmpty">Nessun dato prezzo disponibile.</div>;

  return (
    <svg className="priceChart" viewBox={`0 0 ${width} ${height}`} role="img">
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
          <text x={pad.left - 10} y={y(tick) + 4}>{price(tick)}</text>
        </g>
      ))}
      <path className="areaPath" d={area} />
      <path className="pricePath" d={path} />
      <LevelLine value={triggerLevel} label="TRIGGER" className="triggerLine" />
      <LevelLine value={supportLevel} label="SUPPORTO" className="supportLine" />
      {last && (
        <g className="lastPoint">
          <circle cx={x(prices.length - 1)} cy={y(Number(last.close))} r="5" />
          <text x={pad.left + plotW + 10} y={y(Number(last.close)) - 10}>Prezzo {price(last.close)}</text>
        </g>
      )}
      <g className="axisLabels">
        <text x={pad.left} y={height - 14}>{first?.date}</text>
        <text x={pad.left + plotW} y={height - 14} textAnchor="end">{last?.date}</text>
      </g>
    </svg>
  );
}

function ChartModal({ item, onClose }) {
  const [state, setState] = useState({ loading: true, error: "", prices: [] });
  const ticker = item?.ticker;

  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    setState({ loading: true, error: "", prices: [] });
    api(`/api/chart/${encodeURIComponent(ticker)}?period=6mo&interval=1d`)
      .then((result) => {
        if (!cancelled) setState({ loading: false, error: "", prices: result.prices || [] });
      })
      .catch((error) => {
        if (!cancelled) setState({ loading: false, error: error.message, prices: [] });
      });
    return () => { cancelled = true; };
  }, [ticker]);

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
        {state.loading && <div className="chartStatus">Caricamento storico prezzi...</div>}
        {state.error && <div className="error">{state.error}</div>}
        {!state.loading && !state.error && <PriceChart prices={state.prices} triggerLevel={item.trigger_level} supportLevel={item.support_level} />}
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
            <pre>{message.content}</pre>
          </div>
        ))}
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
      const result = await api(path, { method: "POST", body: JSON.stringify(body || {}) });
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
            <Metric label="Capitale" value={eur(portfolio.initial_capital)} icon={<Wallet size={16} />} />
            <Metric label="Valore portafoglio" value={eur(perf.total_value)} delta={perf.total_pnl_pct} icon={<Activity size={16} />} />
            <Metric label="P/L totale" value={eur(perf.total_pnl)} delta={perf.total_pnl_pct} icon={perf.total_pnl >= 0 ? <TrendingUp size={16} /> : <TrendingDown size={16} />} />
            <Metric label="Cash" value={eur(portfolio.cash)} icon={<Wallet size={16} />} />
          </div>

          <nav>{tabs.map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>)}</nav>

          {tab === "dashboard" && (
            <>
              <Positions rows={perf.positions || []} onChart={setChartItem} />
              <Monitoring rows={data.monitored || []} onChart={setChartItem} />
            </>
          )}
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
