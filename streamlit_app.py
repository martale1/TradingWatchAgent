import subprocess
import sys
from pathlib import Path
import re

import pandas as pd
import streamlit as st

from finance_tools.common import PROJECT_ROOT, load_env_file
from finance_tools.performance_tool import calculate_portfolio_performance, latest_price
from finance_tools.portfolio_store import load_portfolio, portfolio_status_summary
from finance_tools.telegram_tool import send_monitoring_summary, send_performance_summary


load_env_file()


def run_command(args):
    cmd = [sys.executable, str(PROJECT_ROOT / "agent_portfolio_manager.py"), *args]
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        timeout=600,
    )
    return result


def build_chat_request(messages, user_prompt, max_messages=8):
    recent = messages[-max_messages:]
    if not recent:
        return user_prompt
    lines = [
        "Questa richiesta arriva dalla dashboard Streamlit di TradingWatchAgent.",
        "Usa il contesto recente per capire riferimenti come 'questi titoli', 'la proposta', 'il portafoglio'.",
        "",
        "Contesto recente:",
    ]
    for message in recent:
        role = "Utente" if message["role"] == "user" else "Agente"
        lines.append(f"{role}: {message['content']}")
    lines.extend(["", "Nuova richiesta utente:", user_prompt])
    return "\n".join(lines)


def extract_agent_answer(result):
    output = result.stdout.strip() if result.stdout else result.stderr.strip()
    marker = "[agent] Risposta finale agente ricevuta"
    if marker in output:
        return output.split(marker, 1)[1].strip()
    interrupted = "Run interrotta prima della risposta finale"
    if interrupted in output:
        return output[output.find(interrupted):].strip()
    return output.strip()


def run_agent_chat(messages, user_prompt):
    request = build_chat_request(messages, user_prompt)
    result = run_command([request])
    answer = extract_agent_answer(result)
    if result.returncode != 0:
        answer = f"Errore agente, exit code {result.returncode}.\n\n{answer}"
    return answer


def dataframe_or_empty(rows):
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def parse_condition_levels(condition):
    levels = []
    for match in re.finditer(r"€?\s*([0-9]+(?:[,.][0-9]+)?)", str(condition or "")):
        try:
            levels.append(float(match.group(1).replace(",", ".")))
        except ValueError:
            continue
    return levels


def enrich_monitored_conditions(conditions):
    rows = []
    for item in conditions:
        ticker = str(item.get("ticker", "")).strip().upper()
        condition = item.get("condition", "")
        levels = parse_condition_levels(condition)
        current_price = None
        nearest_level = None
        distance = None
        distance_pct = None
        price_status = "ok"
        try:
            current_price = latest_price(ticker)
            if levels:
                nearest_level = min(levels, key=lambda level: abs(current_price - level))
                distance = current_price - nearest_level
                distance_pct = (distance / nearest_level * 100.0) if nearest_level else None
        except Exception as exc:
            price_status = str(exc)
        rows.append(
            {
                "ticker": ticker,
                "status": item.get("status"),
                "prezzo_attuale": round(current_price, 4) if current_price is not None else None,
                "soglie": ", ".join(str(level).replace(".", ",") for level in levels),
                "soglia_piu_vicina": round(nearest_level, 4) if nearest_level is not None else None,
                "distanza": round(distance, 4) if distance is not None else None,
                "distanza_pct": round(distance_pct, 2) if distance_pct is not None else None,
                "condizione": condition,
                "azione": item.get("action_if_met"),
                "aggiornato": item.get("updated_at"),
                "price_status": price_status,
            }
        )
    return rows


st.set_page_config(page_title="TradingWatchAgent", layout="wide")
st.title("TradingWatchAgent")
st.caption("Portafoglio virtuale, performance, condizioni monitorate e controllo agentico.")

portfolio = load_portfolio()
status = portfolio_status_summary()
performance = calculate_portfolio_performance()

if portfolio is None:
    st.warning("portfolio.json non esiste. Inizializza il portafoglio dalla CLI o dalla chat interattiva.")
    st.stop()

cash = float(status.get("cash") or 0)
initial_capital = float(status.get("initial_capital") or 0)
total_value = float(performance.get("total_value") or 0)
total_pnl = float(performance.get("total_pnl") or 0)
total_pnl_pct = float(performance.get("total_pnl_pct") or 0)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Capitale iniziale", f"EUR {initial_capital:,.2f}")
col2.metric("Valore portafoglio", f"EUR {total_value:,.2f}", f"{total_pnl_pct:.2f}%")
col3.metric("P/L totale", f"EUR {total_pnl:,.2f}")
col4.metric("Cash", f"EUR {cash:,.2f}", f"{performance.get('cash_pct', 0):.1f}%")

tab_chat, tab_overview, tab_monitoring, tab_actions, tab_controls = st.tabs(
    ["Chat agente", "Performance", "Monitoraggio", "Azioni agente", "Controlli"]
)

with tab_chat:
    st.subheader("Chat con TradingWatchAgent")
    st.caption("Parla con l'agente usando linguaggio naturale. Le operazioni reali restano simulate nel portfolio.json.")

    if "agent_chat_messages" not in st.session_state:
        st.session_state.agent_chat_messages = [
            {
                "role": "assistant",
                "content": (
                    "Ciao, sono TradingWatchAgent. Puoi chiedermi stato portafoglio, rendimento, "
                    "condizioni monitorate, scan MIB, news, oppure decisioni operative virtuali."
                ),
            }
        ]

    queued_prompt = st.session_state.pop("queued_agent_prompt", None)
    if queued_prompt:
        history = list(st.session_state.agent_chat_messages)
        st.session_state.agent_chat_messages.append({"role": "user", "content": queued_prompt})
        with st.spinner("L'agente sta analizzando..."):
            answer = run_agent_chat(history, queued_prompt)
        st.session_state.agent_chat_messages.append({"role": "assistant", "content": answer})

    for message in st.session_state.agent_chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Scrivi all'agente...")
    if prompt:
        st.session_state.agent_chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("L'agente sta analizzando..."):
                answer = run_agent_chat(st.session_state.agent_chat_messages[:-1], prompt)
            st.markdown(answer)
        st.session_state.agent_chat_messages.append({"role": "assistant", "content": answer})

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Stato portafoglio", key="chat_status"):
        st.session_state.queued_agent_prompt = "mostra stato operativo del portafoglio"
        st.rerun()
    if c2.button("Performance", key="chat_perf"):
        st.session_state.queued_agent_prompt = "mostra rendimento e performance del portafoglio"
        st.rerun()
    if c3.button("Condizioni", key="chat_conditions"):
        st.session_state.queued_agent_prompt = "mostra condizioni monitorate"
        st.rerun()
    if c4.button("Pulisci chat", key="chat_clear"):
        st.session_state.agent_chat_messages = []
        st.rerun()

with tab_overview:
    st.subheader("Portafoglio")
    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Investito", f"EUR {float(performance.get('invested_amount') or 0):,.2f}")
    p2.metric("Valore posizioni", f"EUR {float(performance.get('positions_value') or 0):,.2f}")
    p3.metric("Esposizione", f"{float(performance.get('exposure_pct') or 0):.1f}%")
    p4.metric("Numero posizioni", str(performance.get("positions_count", 0)))

    st.subheader("Posizioni aperte")
    positions_df = dataframe_or_empty(performance.get("positions", []))
    if positions_df.empty:
        st.info("Nessuna posizione aperta.")
    else:
        columns = [
            "ticker",
            "invested_amount",
            "market_value",
            "pnl",
            "pnl_pct",
            "entry_price",
            "current_price",
            "virtual_quantity",
        ]
        st.dataframe(positions_df[[c for c in columns if c in positions_df.columns]], width="stretch")

    alerts = performance.get("alerts", [])
    st.subheader("Alert performance")
    if alerts:
        for alert in alerts:
            if alert.get("level") == "warning":
                st.warning(alert.get("message"))
            else:
                st.info(alert.get("message"))
    else:
        st.success("Nessun alert performance.")

with tab_monitoring:
    st.subheader("Titoli monitorati con soglie")
    conditions = status.get("monitored_conditions", [])
    enriched_conditions = enrich_monitored_conditions(conditions)
    enriched_df = dataframe_or_empty(enriched_conditions)
    if enriched_df.empty:
        st.info("Nessuna condizione monitorata.")
    else:
        columns = [
            "ticker",
            "status",
            "prezzo_attuale",
            "soglie",
            "soglia_piu_vicina",
            "distanza",
            "distanza_pct",
            "condizione",
            "azione",
        ]
        st.dataframe(enriched_df[[c for c in columns if c in enriched_df.columns]], width="stretch")

        near = enriched_df[
            enriched_df["distanza_pct"].notna() & (enriched_df["distanza_pct"].abs() <= 2.0)
        ]
        if not near.empty:
            st.info("Titoli vicini a una soglia entro +/-2%:")
            st.dataframe(
                near[["ticker", "prezzo_attuale", "soglia_piu_vicina", "distanza_pct", "condizione"]],
                width="stretch",
            )

    st.subheader("Proposte pending")
    pending = status.get("pending_buy_proposals", []) + status.get("pending_other_proposals", [])
    pending_df = dataframe_or_empty(pending)
    if pending_df.empty:
        st.success("Nessuna proposta pending.")
    else:
        st.dataframe(pending_df, width="stretch")

with tab_actions:
    st.subheader("Azioni agente recenti")
    closed = list(reversed(portfolio.get("closed_proposals", [])))[:20]
    closed_df = dataframe_or_empty(closed)
    if closed_df.empty:
        st.info("Nessuna azione recente.")
    else:
        st.dataframe(closed_df, width="stretch")

with tab_controls:
    st.subheader("Comandi")
    scan_limit = st.number_input("Scan limit", min_value=1, max_value=40, value=5, step=1)
    max_trade_pct = st.number_input("Max auto trade %", min_value=1.0, max_value=100.0, value=25.0, step=1.0)

    c1, c2, c3 = st.columns(3)
    if c1.button("Invia Telegram monitoraggio"):
        result = send_monitoring_summary(extra_note="Invio richiesto da dashboard Streamlit.")
        if result.get("status") == "ok":
            st.success("Telegram monitoraggio inviato.")
        else:
            st.error(result.get("message"))

    if c2.button("Invia Telegram performance"):
        result = send_performance_summary(extra_note="Invio richiesto da dashboard Streamlit.")
        if result.get("status") == "ok":
            st.success("Telegram performance inviato.")
        else:
            st.error(result.get("message"))

    if c3.button("Run monitor autonomo una volta"):
        with st.spinner("Eseguo monitor autonomo --once..."):
            result = run_command(
                [
                    "--autonomous-monitor",
                    "--once",
                    "--scan-limit",
                    str(int(scan_limit)),
                    "--max-auto-trade-pct",
                    str(float(max_trade_pct)),
                ]
            )
        st.code(result.stdout or result.stderr)
        if result.returncode == 0:
            st.success("Monitor completato.")
        else:
            st.error(f"Errore monitor: exit code {result.returncode}")

st.caption(f"Project root: {Path(PROJECT_ROOT)}")
