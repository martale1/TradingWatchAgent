import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from finance_tools.common import PROJECT_ROOT, load_env_file
from finance_tools.performance_tool import calculate_portfolio_performance
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


def dataframe_or_empty(rows):
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


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

tab_overview, tab_monitoring, tab_actions, tab_controls = st.tabs(
    ["Performance", "Monitoraggio", "Azioni agente", "Controlli"]
)

with tab_overview:
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
        st.dataframe(positions_df[[c for c in columns if c in positions_df.columns]], use_container_width=True)

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
    st.subheader("Condizioni monitorate")
    conditions = status.get("monitored_conditions", [])
    conditions_df = dataframe_or_empty(conditions)
    if conditions_df.empty:
        st.info("Nessuna condizione monitorata.")
    else:
        columns = ["id", "ticker", "status", "condition", "action_if_met", "updated_at"]
        st.dataframe(conditions_df[[c for c in columns if c in conditions_df.columns]], use_container_width=True)

    st.subheader("Proposte pending")
    pending = status.get("pending_buy_proposals", []) + status.get("pending_other_proposals", [])
    pending_df = dataframe_or_empty(pending)
    if pending_df.empty:
        st.success("Nessuna proposta pending.")
    else:
        st.dataframe(pending_df, use_container_width=True)

with tab_actions:
    st.subheader("Azioni agente recenti")
    closed = list(reversed(portfolio.get("closed_proposals", [])))[:20]
    closed_df = dataframe_or_empty(closed)
    if closed_df.empty:
        st.info("Nessuna azione recente.")
    else:
        st.dataframe(closed_df, use_container_width=True)

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
