import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from agents import Agent, ModelSettings, Runner, function_tool

from finance_tools.chart_tool import generate_chart_context_json
from finance_tools.common import PROJECT_ROOT, load_env_file
from finance_tools.deep_chart_tool import confirm_candidate_with_chart_ai_json
from finance_tools.mib30_scanner import propose_virtual_allocation_json, scan_mib30_candidates_json
from finance_tools.news_tool import get_news_report_json
from finance_tools.performance_tool import calculate_portfolio_performance_json
from finance_tools.portfolio_store import (
    add_buy_proposal,
    add_monitored_condition,
    confirm_proposal as confirm_portfolio_proposal,
    init_portfolio,
    list_monitored_conditions,
    list_pending_proposals,
    load_portfolio as load_portfolio_file,
    portfolio_status_summary,
    reject_proposal as reject_portfolio_proposal,
    update_portfolio_capital,
    update_monitored_condition,
)
from finance_tools.telegram_tool import send_monitoring_summary, send_performance_summary


DEFAULT_MODEL = os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6-luna")
DEFAULT_MAX_TURNS = int(os.getenv("OPENAI_AGENT_MAX_TURNS", "60"))
DEFAULT_MONITOR_INTERVAL_MINUTES = int(os.getenv("MONITOR_INTERVAL_MINUTES", "30"))
DEFAULT_MAX_AUTO_TRADE_PCT = float(os.getenv("MAX_AUTO_TRADE_PCT", "25"))


def configure_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def log_step(message):
    print(f"[agent] {message}", flush=True)


@function_tool
def analyze_stock_chart(ticker: str, days: int = 70, period: str = "1y") -> str:
    """Generate technical charts and numeric technical context for one stock.

    Args:
        ticker: Stock ticker symbol, for example VOD.L or A2A.MI.
        days: Number of recent trading bars to include in charts.
        period: Yahoo Finance download period, for example 6mo, 1y, or 2y.
    """
    log_step(f"Tool analyze_stock_chart chiamato per {ticker} | days={days} period={period}")
    return generate_chart_context_json(ticker=ticker, days=days, period=period)


@function_tool
def analyze_stock_news(ticker: str, live: bool = False) -> str:
    """Return a news report for one stock.

    Args:
        ticker: Stock ticker symbol, for example VOD.L or A2A.MI.
        live: If true, run the Playwright ChatGPT news workflow; if false, read cached news if available.
    """
    mode = "Playwright live" if live else "cache locale"
    log_step(f"Tool analyze_stock_news chiamato per {ticker} | modalita={mode}")
    return get_news_report_json(ticker=ticker, live=live)


@function_tool
def confirm_candidate_chart_with_playwright(ticker: str, no_telegram: bool = True) -> str:
    """Run a deep visual chart confirmation with Playwright/ChatGPT for one candidate.

    Args:
        ticker: Stock ticker symbol to confirm visually, for example AMP.MI.
        no_telegram: If true, do not send Telegram during confirmation.
    """
    log_step(
        "Tool confirm_candidate_chart_with_playwright chiamato | "
        f"ticker={ticker} no_telegram={no_telegram}"
    )
    return confirm_candidate_with_chart_ai_json(ticker=ticker, no_telegram=no_telegram)


@function_tool
def load_watchlist(path: str = "portfolio.example.json") -> str:
    """Load a watchlist JSON file.

    Args:
        path: Relative or absolute path to a JSON file containing a watchlist array.
    """
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path
    log_step(f"Tool load_watchlist chiamato | file={file_path}")
    if not file_path.exists():
        return json.dumps({"status": "missing", "file": str(file_path)}, ensure_ascii=False)
    return file_path.read_text(encoding="utf-8")


@function_tool
def load_virtual_portfolio() -> str:
    """Load the current virtual portfolio, if it exists."""
    log_step("Tool load_virtual_portfolio chiamato")
    portfolio = load_portfolio_file()
    if portfolio is None:
        return json.dumps({"status": "missing", "message": "portfolio.json non esiste."}, ensure_ascii=False)
    return json.dumps({"status": "ok", "portfolio": portfolio}, ensure_ascii=False, indent=2)


@function_tool
def scan_mib30_for_candidates(limit: int = 5, create_proposals: bool = False, universe_limit: int = 0) -> str:
    """Scan Italian MIB30 tickers and find interesting technical candidates.

    Args:
        limit: Maximum number of candidates to return.
        create_proposals: If true, create pending proposals in portfolio.json. Proposals still require user confirmation.
        universe_limit: Optional number of tickers to analyze for quick tests. Use 0 for full universe.
    """
    log_step(
        "Tool scan_mib30_for_candidates chiamato | "
        f"limit={limit} create_proposals={create_proposals} universe_limit={universe_limit}"
    )
    return scan_mib30_candidates_json(
        limit=limit,
        create_proposals=create_proposals,
        universe_limit=universe_limit or None,
    )


@function_tool
def propose_virtual_portfolio_from_mib30(
    capital: float,
    max_positions: int = 5,
    cash_pct: float = 15,
    universe_limit: int = 0,
) -> str:
    """Create a pending virtual portfolio allocation proposal from MIB30 candidates.

    Args:
        capital: Total virtual capital the user wants to invest.
        max_positions: Maximum number of stocks in the proposal.
        cash_pct: Percentage of capital to keep as cash.
        universe_limit: Optional number of tickers to analyze for quick tests. Use 0 for full universe.
    """
    log_step(
        "Tool propose_virtual_portfolio_from_mib30 chiamato | "
        f"capital={capital} max_positions={max_positions} cash_pct={cash_pct} universe_limit={universe_limit}"
    )
    return propose_virtual_allocation_json(
        capital=capital,
        max_positions=max_positions,
        cash_pct=cash_pct,
        universe_limit=universe_limit or None,
    )


@function_tool
def list_portfolio_proposals() -> str:
    """List pending portfolio proposals that require explicit user confirmation."""
    log_step("Tool list_portfolio_proposals chiamato")
    return json.dumps({"status": "ok", "pending": list_pending_proposals()}, ensure_ascii=False, indent=2)


@function_tool
def get_portfolio_operating_status() -> str:
    """Return one operational view: open positions, pending buys, monitored conditions and watchlist."""
    log_step("Tool get_portfolio_operating_status chiamato")
    return json.dumps(portfolio_status_summary(), ensure_ascii=False, indent=2)


@function_tool
def set_virtual_portfolio_capital(new_capital: float, reason: str = "") -> str:
    """Update the virtual portfolio capital after explicit user instruction.

    Args:
        new_capital: New total virtual capital.
        reason: Optional reason/audit note.
    """
    log_step(f"Tool set_virtual_portfolio_capital chiamato | new_capital={new_capital}")
    return json.dumps(
        update_portfolio_capital(new_capital=new_capital, reason=reason),
        ensure_ascii=False,
        indent=2,
    )


@function_tool
def record_monitored_condition(
    ticker: str,
    condition: str,
    reason: str,
    action_if_met: str = "rivaluta per possibile proposta",
    status: str = "waiting",
) -> str:
    """Persist a condition that must be monitored and re-evaluated later.

    Args:
        ticker: Stock ticker symbol.
        condition: Concrete condition to monitor, for example close sopra 3.966 con volumi.
        reason: Why the condition matters.
        action_if_met: What the agent should do when the condition is met.
        status: Condition status, usually waiting.
    """
    log_step(f"Tool record_monitored_condition chiamato | ticker={ticker} condition={condition}")
    item = add_monitored_condition(
        ticker=ticker,
        condition=condition,
        reason=reason,
        action_if_met=action_if_met,
        status=status,
    )
    return json.dumps({"status": "ok", "condition": item}, ensure_ascii=False, indent=2)


@function_tool
def list_conditions_to_monitor(status: str = "waiting") -> str:
    """List conditions that the agent has saved for later monitoring.

    Args:
        status: Optional status filter, for example waiting. Empty string returns all conditions.
    """
    clean_status = status or None
    log_step(f"Tool list_conditions_to_monitor chiamato | status={clean_status}")
    return json.dumps(
        {"status": "ok", "conditions": list_monitored_conditions(status=clean_status)},
        ensure_ascii=False,
        indent=2,
    )


@function_tool
def update_condition_status(condition_id: str, status: str, note: str = "") -> str:
    """Update a monitored condition after re-evaluation.

    Args:
        condition_id: Monitored condition id.
        status: New status: waiting, met, invalidated, archived.
        note: Short reason for the update.
    """
    log_step(f"Tool update_condition_status chiamato | condition_id={condition_id} status={status}")
    return json.dumps(
        update_monitored_condition(condition_id=condition_id, status=status, note=note),
        ensure_ascii=False,
        indent=2,
    )


@function_tool
def create_buy_proposal(
    ticker: str,
    reason: str,
    amount: float | None = None,
    entry_price: float | None = None,
) -> str:
    """Create a pending virtual buy proposal. User confirmation is still required.

    Args:
        ticker: Stock ticker symbol.
        reason: Why the buy proposal is being created.
        amount: Optional virtual amount to invest.
        entry_price: Optional current or reference entry price.
    """
    log_step(f"Tool create_buy_proposal chiamato | ticker={ticker} amount={amount} entry_price={entry_price}")
    proposal = add_buy_proposal(ticker=ticker, reason=reason, amount=amount, entry_price=entry_price)
    return json.dumps({"status": "ok", "proposal": proposal}, ensure_ascii=False, indent=2)


@function_tool
def send_monitoring_telegram_summary(extra_note: str = "") -> str:
    """Send a Telegram summary of monitored conditions, pending proposals and portfolio state.

    Args:
        extra_note: Optional short note to include at the end of the Telegram message.
    """
    log_step("Tool send_monitoring_telegram_summary chiamato")
    return json.dumps(send_monitoring_summary(extra_note=extra_note), ensure_ascii=False, indent=2)


@function_tool
def get_portfolio_performance() -> str:
    """Calculate current virtual portfolio performance with P/L per position and portfolio totals."""
    log_step("Tool get_portfolio_performance chiamato")
    return calculate_portfolio_performance_json()


@function_tool
def send_portfolio_performance_telegram(extra_note: str = "") -> str:
    """Send a Telegram message with current virtual portfolio performance."""
    log_step("Tool send_portfolio_performance_telegram chiamato")
    return json.dumps(send_performance_summary(extra_note=extra_note), ensure_ascii=False, indent=2)


@function_tool
def confirm_portfolio_proposal_tool(proposal_id: str) -> str:
    """Confirm and apply a pending portfolio proposal.

    Args:
        proposal_id: The proposal id to confirm.
    """
    log_step(f"Tool confirm_portfolio_proposal_tool chiamato | proposal_id={proposal_id}")
    return json.dumps(confirm_portfolio_proposal(proposal_id), ensure_ascii=False, indent=2)


@function_tool
def auto_apply_virtual_proposal_tool(proposal_id: str, max_trade_pct: float = DEFAULT_MAX_AUTO_TRADE_PCT) -> str:
    """Confirm and apply one pending proposal in autonomous virtual mode with a cash percentage limit.

    Args:
        proposal_id: Pending proposal id to apply.
        max_trade_pct: Maximum percentage of current cash allowed for this autonomous virtual action.
    """
    log_step(
        "Tool auto_apply_virtual_proposal_tool chiamato | "
        f"proposal_id={proposal_id} max_trade_pct={max_trade_pct}"
    )
    portfolio = load_portfolio_file()
    if portfolio is None:
        return json.dumps({"status": "missing", "message": "portfolio.json non esiste."}, ensure_ascii=False)

    pending = portfolio.get("pending_proposals", [])
    proposal = next((item for item in pending if item.get("id") == proposal_id), None)
    if not proposal:
        return json.dumps({"status": "missing", "proposal_id": proposal_id}, ensure_ascii=False)

    if proposal.get("action") != "buy_virtual_position":
        return json.dumps(
            {
                "status": "blocked",
                "proposal_id": proposal_id,
                "message": "La modalita autonoma puo applicare solo buy_virtual_position.",
            },
            ensure_ascii=False,
            indent=2,
        )

    amount = proposal.get("metadata", {}).get("amount")
    if amount is None:
        return json.dumps(
            {
                "status": "blocked",
                "proposal_id": proposal_id,
                "message": "Importo mancante: proposta non applicabile autonomamente.",
            },
            ensure_ascii=False,
            indent=2,
        )

    cash = float(portfolio.get("cash", 0) or 0)
    max_amount = round(cash * float(max_trade_pct) / 100.0, 2)
    if float(amount) > max_amount:
        return json.dumps(
            {
                "status": "blocked",
                "proposal_id": proposal_id,
                "amount": amount,
                "cash": cash,
                "max_allowed": max_amount,
                "message": "Importo oltre il limite autonomo configurato.",
            },
            ensure_ascii=False,
            indent=2,
        )

    result = confirm_portfolio_proposal(proposal_id)
    return json.dumps(result, ensure_ascii=False, indent=2)


@function_tool
def reject_portfolio_proposal_tool(proposal_id: str) -> str:
    """Reject and archive a pending portfolio proposal.

    Args:
        proposal_id: The proposal id to reject.
    """
    log_step(f"Tool reject_portfolio_proposal_tool chiamato | proposal_id={proposal_id}")
    return json.dumps(reject_portfolio_proposal(proposal_id), ensure_ascii=False, indent=2)


def build_agent(model=DEFAULT_MODEL, auto_apply_virtual=False, max_auto_trade_pct=DEFAULT_MAX_AUTO_TRADE_PCT):
    mode = "AUTO-VIRTUAL" if auto_apply_virtual else "CONFIRMATION"
    log_step(
        "Creo agente Portfolio Monitor Agent | "
        f"model={model} | parallel_tool_calls=False | mode={mode}"
    )
    if auto_apply_virtual:
        operation_policy = (
            "Modalita AUTONOMA VIRTUALE attiva: puoi applicare da solo operazioni simulate sul solo portafoglio virtuale "
            "con auto_apply_virtual_proposal_tool dopo avere creato una proposta pending motivata. "
            "Non puoi operare su broker reali o sistemi esterni. "
            f"Ogni nuova operazione autonoma deve rispettare il limite massimo del {max_auto_trade_pct:.1f}% del cash disponibile "
            "al momento della decisione. "
            "Prima di applicare un acquisto autonomo devi avere analisi tecnica aggiornata, news disponibili, e motivazione sintetica. "
            "Se il segnale e debole o contraddittorio, salva/aggiorna una condizione monitorata invece di applicare. "
            "Non chiedere conferma all'utente in questa modalita: applica se le regole sono rispettate e notifica l'utente via Telegram. "
            "Dopo ogni operazione autonoma devi chiamare send_monitoring_telegram_summary e dichiarare proposal_id, ticker, importo e motivo. "
        )
    else:
        operation_policy = (
            "Non modificare mai il portafoglio autonomamente: puoi solo creare proposte pending, "
            "e applicarle esclusivamente quando l'utente conferma esplicitamente un proposal_id. "
        )
    tools = [
        analyze_stock_chart,
        analyze_stock_news,
        confirm_candidate_chart_with_playwright,
        load_watchlist,
        load_virtual_portfolio,
        get_portfolio_operating_status,
        set_virtual_portfolio_capital,
        scan_mib30_for_candidates,
        propose_virtual_portfolio_from_mib30,
        list_portfolio_proposals,
        record_monitored_condition,
        list_conditions_to_monitor,
        update_condition_status,
        create_buy_proposal,
        send_monitoring_telegram_summary,
        get_portfolio_performance,
        send_portfolio_performance_telegram,
        reject_portfolio_proposal_tool,
    ]
    if auto_apply_virtual:
        tools.append(auto_apply_virtual_proposal_tool)
    else:
        tools.append(confirm_portfolio_proposal_tool)
    return Agent(
        name="Portfolio Monitor Agent",
        model=model,
        instructions=(
            "Sei un agente finanziario operativo per monitorare un portafoglio virtuale e una watchlist. "
            "Usa i tool disponibili per raccogliere dati tecnici e news. "
            "Rispondi sempre in italiano. Non dare consulenza finanziaria personalizzata. "
            + operation_policy +
            "Il capitale virtuale puo invece essere aggiornato quando l'utente lo chiede esplicitamente "
            "con frasi come 'aggiorna il capitale a 20000 euro' o 'il capitale e 20000': usa set_virtual_portfolio_capital "
            "e poi mostra il nuovo stato operativo. "
            "Quando inizi un monitoraggio, una proposta o una domanda sullo stato operativo, usa get_portfolio_operating_status "
            "per costruire una vista unica: posizioni in portafoglio, proposte pending, condizioni monitorate e watchlist. "
            "Quando l'utente chiede rendimento, performance o guadagno/perdita, usa get_portfolio_performance. "
            "Durante il monitor periodico valuta la performance del portafoglio e segnala alert di rendimento rilevanti. "
            "Valuta sempre anche le posizioni gia in portafoglio: se emergono segnali di uscita, riduzione o protezione, "
            "devi creare una proposta pending e motivarla; applicala solo se la policy operativa corrente lo consente. "
            "Se l'utente chiede una proposta o chiede se ci sono titoli da comprare, devi rispondere in modo operativo: "
            "BUY CANDIDATE, WAIT/MONITOR oppure SCARTATO. "
            "Prima di rifare analisi live, consulta load_virtual_portfolio, list_portfolio_proposals e list_conditions_to_monitor "
            "per usare lo stato gia salvato. "
            "Puoi dire BUY CANDIDATE solo dopo avere usato analisi dettagliata del grafico e news disponibili; "
            "in quel caso crea una proposta pending se ci sono capitale e condizioni sufficienti, altrimenti chiedi il dato mancante. "
            "Se invece l'utente chiede esplicitamente di procedere con un acquisto anche se il segnale non e confermato, "
            "asseconda la richiesta creando una proposta pending con create_buy_proposal, includendo nel reason i rischi e "
            "specificando che e una forzatura consapevole rispetto al filtro prudenziale. "
            "Applicala solo se la policy operativa corrente lo consente, altrimenti attendi conferma proposal_id. "
            "Quando una condizione non e verificata ma il titolo resta interessante, salva la condizione con record_monitored_condition "
            "e spiega quando andra rivalutata. "
            "Il runner invia automaticamente un riepilogo Telegram quando condizioni monitorate o proposte cambiano "
            "a valle di screening, rivalutazione o proposta; non inviare duplicati se non richiesto esplicitamente. "
            "Quando rivaluti condizioni monitorate, per ogni condizione devi scegliere: mantenerla waiting, marcarla met, "
            "marcarla invalidated oppure archiviarla. Se la condizione e met e il titolo resta valido dopo grafico/news, "
            "crea una proposta pending con create_buy_proposal. Se il contesto tecnico/news e peggiorato, usa update_condition_status "
            "con status invalidated o archived e spiega il motivo. "
            "Quando analizzi un titolo, combina news, momentum, trend, supporti, resistenze, volumi e rischio. "
            "Quando cerchi candidati MIB30, spiega i criteri usati e distingui ragioni tecniche e rischi. "
            "Quando devi proporre titoli da mettere in portafoglio, usa prima lo scanner numerico. "
            "Poi decidi autonomamente se approfondire i migliori candidati con confirm_candidate_chart_with_playwright: "
            "fallo sempre se stai per creare una proposta di acquisto o allocazione, se ci sono segnali tecnici contrastanti, "
            "se i candidati hanno score simili, o se il rischio non e chiaro. "
            "Quando approfondisci piu candidati, procedi in sequenza: chiama un solo tool alla volta, attendi il risultato, "
            "riassumi cosa hai imparato e solo dopo decidi se chiamare il tool per il candidato successivo. "
            "Analizza un titolo selezionato alla volta: completa grafico, eventuali news, sintesi e giudizio provvisorio "
            "per quel ticker prima di iniziare qualsiasi tool sul ticker successivo. "
            "Non chiamare mai piu tool Playwright nello stesso passaggio di ragionamento. "
            "Se non approfondisci con Playwright, devi spiegare perche non era necessario. "
            "Se un tool restituisce dati mancanti, dichiaralo chiaramente e continua con i dati disponibili. "
            "Formatta l'output in modo compatto, adatto anche a Telegram. "
            "Alla fine di ogni risposta operativa proponi sempre una sezione 'Opzioni successive' con 3-6 opzioni numerate, "
            "ognuna con un comando concreto che l'utente puo scrivere, per esempio rivalutare condizioni, creare proposta, "
            "mostrare stato operativo, analizzare un ticker, cercare news live, confermare o rifiutare proposte. "
            "Le opzioni devono essere coerenti con lo stato attuale: se non ci sono proposte pending non proporre conferma proposta; "
            "se ci sono condizioni waiting proponi rivalutazione; se il capitale e assente proponi aggiornamento capitale."
        ),
        model_settings=ModelSettings(parallel_tool_calls=False),
        tools=tools,
    )


def run_agent_once(agent, request, display_request=None):
    log_step("Prompt operativo inviato all'agente:")
    log_step(display_request or request)
    log_step(f"Invio richiesta all'agente OpenAI SDK e attendo risposta/tool calls... max_turns={DEFAULT_MAX_TURNS}")
    before_state = monitoring_state_signature()
    final_output = ""
    try:
        result = Runner.run_sync(agent, request, max_turns=DEFAULT_MAX_TURNS)
        final_output = str(result.final_output).strip()
        log_step("Risposta finale agente ricevuta")
        print("\n" + final_output + "\n", flush=True)
    except Exception as exc:
        final_output = (
            f"Run interrotta prima della risposta finale: {exc.__class__.__name__}: {exc}. "
            "Le azioni gia eseguite dai tool restano salvate; controllo lo stato operativo e invio eventuale riepilogo."
        )
        log_step(final_output)
        print("\n" + final_output + "\n", flush=True)
        result = SimpleNamespace(final_output=final_output)
    after_state = monitoring_state_signature()
    maybe_send_automatic_monitoring_summary(request, final_output, before_state, after_state)
    return result


def build_periodic_monitor_request(
    scan_limit=5,
    universe_limit=0,
    live_news=False,
    deep_confirm_limit=3,
    auto_apply_virtual=False,
    max_auto_trade_pct=DEFAULT_MAX_AUTO_TRADE_PCT,
):
    live_news_hint = "usa live=True solo per titoli con trigger o rischio rilevante" if live_news else "usa live=False per le news"
    universe_hint = f"universe_limit={universe_limit}" if universe_limit else "universo completo"
    if auto_apply_virtual:
        operation_hint = (
            "Modalita AUTONOMA VIRTUALE abilitata: non devi chiedere conferma all'utente. "
            "Puoi applicare operazioni simulate usando auto_apply_virtual_proposal_tool dopo avere creato una proposta pending motivata, "
            "solo se il segnale e chiaro e dopo analisi tecnica/news. "
            f"Limite per nuova operazione autonoma: massimo {max_auto_trade_pct:.1f}% del cash disponibile. "
            "Se il segnale non e netto, non applicare: mantieni o crea una condizione monitorata. "
            "Dopo ogni operazione autonoma invia riepilogo Telegram. "
        )
    else:
        operation_hint = "Non applicare mai operazioni al portafoglio senza conferma esplicita dell'utente. "
    return (
        "Esegui un ciclo periodico di monitoraggio operativo. "
        "Obiettivo: controllare posizioni aperte, proposte pending, condizioni monitorate e nuove opportunita dal MIB30. "
        + operation_hint +
        "Prima chiama get_portfolio_operating_status e get_portfolio_performance. "
        "Se get_portfolio_performance mostra alert rilevanti su P/L posizione o portafoglio, chiama send_portfolio_performance_telegram. "
        "Se ci sono posizioni aperte, analizzale una alla volta con analyze_stock_chart e analyze_stock_news; "
        f"{live_news_hint}. Se emergono segnali di uscita, riduzione, protezione o presa profitto, crea solo una proposta pending. "
        "Poi rivaluta tutte le condizioni waiting una alla volta: per ogni ticker usa analyze_stock_chart e news disponibili, "
        "poi aggiorna la condizione come waiting, met, invalidated o archived. "
        "Se una condizione e met e il quadro resta valido, crea una proposta pending motivata. "
        f"Infine scannerizza il MIB30 con scan_mib30_for_candidates limit={scan_limit}, create_proposals=False, {universe_hint}. "
        f"Approfondisci al massimo {deep_confirm_limit} nuovi candidati solo se servono davvero per una proposta o per un monitoraggio serio; "
        "in tal caso usa confirm_candidate_chart_with_playwright un ticker alla volta. "
        "Se trovi candidati interessanti ma non ancora comprabili, salva condizioni concrete con record_monitored_condition. "
        "Concludi con una vista compatta: posizioni, proposte pending, condizioni monitorate, nuovi candidati, azioni consigliate. "
        "Se condizioni/proposte/stato sono cambiati, il runner inviera il riepilogo Telegram automatico."
    )


def run_periodic_monitor_loop(
    model,
    interval_minutes=DEFAULT_MONITOR_INTERVAL_MINUTES,
    scan_limit=5,
    universe_limit=0,
    live_news=False,
    deep_confirm_limit=3,
    auto_apply_virtual=False,
    max_auto_trade_pct=DEFAULT_MAX_AUTO_TRADE_PCT,
    once=False,
):
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")
    agent = build_agent(
        model=model,
        auto_apply_virtual=auto_apply_virtual,
        max_auto_trade_pct=max_auto_trade_pct,
    )
    interval_seconds = max(1, int(interval_minutes * 60))
    cycle = 1
    while True:
        log_step(
            "Ciclo monitor periodico "
            f"#{cycle} | interval_minutes={interval_minutes} scan_limit={scan_limit} "
            f"universe_limit={universe_limit} live_news={live_news} auto_apply_virtual={auto_apply_virtual}"
        )
        request = build_periodic_monitor_request(
            scan_limit=scan_limit,
            universe_limit=universe_limit,
            live_news=live_news,
            deep_confirm_limit=deep_confirm_limit,
            auto_apply_virtual=auto_apply_virtual,
            max_auto_trade_pct=max_auto_trade_pct,
        )
        run_agent_once(agent, request, display_request=f"monitor periodico ciclo #{cycle}")
        if once:
            log_step("Monitor periodico completato in modalita --once")
            return
        log_step(f"Prossimo ciclo tra {interval_minutes} minuti. Interrompi con CTRL+C.")
        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\nMonitor periodico interrotto dall'utente.")
            return
        cycle += 1


def monitoring_state_signature():
    status = portfolio_status_summary()
    conditions = [
        {
            "id": item.get("id"),
            "ticker": item.get("ticker"),
            "status": item.get("status"),
            "condition": item.get("condition"),
            "action_if_met": item.get("action_if_met"),
        }
        for item in status.get("monitored_conditions", [])
    ]
    pending_buy = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "action": item.get("action"),
            "ticker": item.get("ticker"),
            "metadata": item.get("metadata", {}),
        }
        for item in status.get("pending_buy_proposals", [])
    ]
    pending_other = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "action": item.get("action"),
            "ticker": item.get("ticker"),
            "metadata": item.get("metadata", {}),
        }
        for item in status.get("pending_other_proposals", [])
    ]
    positions = [
        {
            "ticker": item.get("ticker"),
            "status": item.get("status"),
            "allocated_amount": item.get("allocated_amount"),
            "entry_price": item.get("entry_price"),
            "virtual_quantity": item.get("virtual_quantity"),
        }
        for item in status.get("positions", [])
    ]
    relevant_state = {
        "pending_buy_proposals": pending_buy,
        "pending_other_proposals": pending_other,
        "monitored_conditions": conditions,
        "positions": positions,
        "cash": status.get("cash"),
    }
    return json.dumps(relevant_state, ensure_ascii=False, sort_keys=True)


def maybe_send_automatic_monitoring_summary(request, final_output, before_state, after_state):
    if before_state == after_state:
        return

    combined = f"{request}\n{final_output}".lower()
    trigger_words = [
        "mib30",
        "scanner",
        "screening",
        "rivaluta",
        "monitor",
        "condizioni",
        "proposta",
        "compra",
        "acquista",
    ]
    if not any(word in combined for word in trigger_words):
        return

    log_step("Cambio monitoraggio/proposte rilevato: invio riepilogo Telegram automatico")
    result = send_monitoring_summary(extra_note="Riepilogo automatico dopo aggiornamento monitoraggio/proposte.")
    if result.get("status") == "ok":
        log_step("Riepilogo Telegram automatico inviato")
    else:
        log_step(f"Riepilogo Telegram non inviato: {result.get('message')}")


def build_contextual_request(history, user_text, max_turns=6):
    recent_history = history[-max_turns:]
    if not recent_history:
        return user_text

    lines = [
        "Questa e una sessione interattiva. Usa il contesto recente per risolvere riferimenti come "
        "'questi titoli', 'i candidati', 'il precedente elenco', 'la proposta'.",
        "",
        "Contesto recente:",
    ]
    for item in recent_history:
        lines.append(f"Utente: {item['user']}")
        lines.append(f"Agente: {item['assistant']}")
        lines.append("")
    lines.append("Nuova richiesta utente:")
    lines.append(user_text)
    return "\n".join(lines)


def extract_next_options(text):
    lines = str(text or "").splitlines()
    options = []
    in_section = False
    for line in lines:
        clean = line.strip()
        if not clean:
            if in_section and options:
                break
            continue
        header = clean.lstrip("#").strip().lower()
        if header.startswith("opzioni successive"):
            in_section = True
            continue
        if not in_section:
            continue
        match = re.match(r"^\d+[\.\)]\s+`?(.+?)`?\s*$", clean)
        if match:
            option = match.group(1).strip().strip("`").strip()
            if option:
                options.append(option)
            continue
        if options:
            break
    return options


def print_monitored_conditions_quick():
    conditions = list_monitored_conditions(status=None)
    if not conditions:
        print("Nessun titolo sotto monitoring.")
        return
    print()
    print("Titoli sotto monitoring:")
    for item in conditions:
        print(
            f"- {item.get('ticker')} | stato={item.get('status')} | "
            f"condizione={item.get('condition')} | azione={item.get('action_if_met')}"
        )


def parse_italian_amount(value):
    clean = value.strip().lower().replace("euro", "").replace("eur", "").replace("€", "")
    clean = clean.replace(" ", "")
    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "," in clean:
        clean = clean.replace(",", ".")
    elif "." in clean:
        parts = clean.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            clean = "".join(parts)
    return float(clean)


def handle_local_interactive_command(user_text):
    text = user_text.strip()
    lower = text.lower()

    capital_match = re.search(
        r"\b(?:capitale(?:\s+disponibile)?|aggiorna\s+il\s+capitale|il\s+capitale\s+(?:e|è))\D+([0-9][0-9\., ]*)",
        lower,
    )
    if capital_match:
        amount = parse_italian_amount(capital_match.group(1))
        result = update_portfolio_capital(amount, reason=f"richiesta esplicita utente: {text}")
        print()
        print(f"Capitale virtuale aggiornato: EUR {result['old_capital']:.2f} -> EUR {result['new_capital']:.2f}")
        print(f"Liquidita aggiornata: EUR {result['old_cash']:.2f} -> EUR {result['new_cash']:.2f}")
        return True

    buy_intent = re.search(r"\b(compra|compriamo|acquista|acquistiamo|procedi|procediamo)\b", text, flags=re.IGNORECASE)
    ticker_match = re.search(r"\b([A-Z0-9]{1,8}\.[A-Z]{1,4})\b", text, flags=re.IGNORECASE)
    if buy_intent and ticker_match:
        ticker = ticker_match.group(1).upper()
        amount_candidates = re.findall(r"[0-9][0-9\., ]*", text[: ticker_match.start()])
        if not amount_candidates:
            print("Importo non trovato. Esempio: compriamo 10000 euro di HER.MI")
            return True
        amount = parse_italian_amount(amount_candidates[-1])
        portfolio = load_portfolio_file()
        if portfolio is None:
            print("portfolio.json non esiste. Prima inizializza o imposta il capitale virtuale.")
            return True
        cash = float(portfolio.get("cash", 0) or 0)
        if amount > cash:
            print(f"Liquidita insufficiente: richiesta EUR {amount:.2f}, cash disponibile EUR {cash:.2f}.")
            return True
        reason = (
            f"Richiesta esplicita utente: proposta acquisto EUR {amount:.2f} di {ticker}. "
            "Forzatura consapevole: la proposta puo essere creata anche se il filtro prudenziale non e confermato. "
            "Richiede conferma esplicita del proposal_id."
        )
        proposal = add_buy_proposal(ticker=ticker, reason=reason, amount=amount)
        print()
        print("Proposta pending creata su richiesta esplicita.")
        print(f"- proposal_id: {proposal['id']}")
        print(f"- ticker: {ticker}")
        print(f"- importo: EUR {amount:.2f}")
        print("Nessun acquisto applicato: per eseguire devi confermare il proposal_id.")
        result = send_monitoring_summary(extra_note="Riepilogo automatico dopo proposta pending creata da comando esplicito.")
        if result.get("status") == "ok":
            print("Riepilogo monitoraggio inviato su Telegram.")
        else:
            print(f"Telegram non inviato: {result.get('message')}")
        return True

    if lower in {
        "invia riepilogo telegram",
        "manda riepilogo telegram",
        "telegram monitoring",
        "invia monitoraggio telegram",
    }:
        result = send_monitoring_summary(extra_note="Invio manuale richiesto dall'utente.")
        print()
        if result.get("status") == "ok":
            print("Riepilogo monitoraggio inviato su Telegram.")
        else:
            print(f"Telegram non inviato: {result.get('message')}")
        return True

    return False


def build_startup_options(portfolio):
    options = []
    if portfolio is None:
        options.append("inizializza portafoglio con capitale 20000 euro")
    else:
        options.append("mostra stato operativo del portafoglio")
        conditions = [item for item in portfolio.get("monitored_conditions", []) if item.get("status") == "waiting"]
        pending = [item for item in portfolio.get("pending_proposals", []) if item.get("status") == "pending"]
        positions = [item for item in portfolio.get("positions", []) if item.get("status") == "open"]
        if conditions:
            options.append("rivaluta le condizioni monitorate")
        if pending:
            first_id = pending[0].get("id", "<proposal_id>")
            options.append(f"mostra proposte pending e dettagli proposta {first_id}")
        if positions:
            options.append("rivaluta i titoli in portafoglio e proponi eventuali azioni")
        if not positions:
            options.append("scannerizza il MIB30 e cerca candidati per il portafoglio")

    options.extend(
        [
            "analizza un titolo specifico con grafico e news live",
            "cerca news live per un ticker",
        ]
    )
    return options[:6]


def print_next_options(portfolio=None):
    print()
    print("Opzioni successive:")
    options = build_startup_options(portfolio)
    for index, option in enumerate(options, start=1):
        print(f"{index}. {option}")
    return options


def print_interactive_help(portfolio=None):
    print()
    print("Cosa posso fare:")
    print("- creare un portafoglio virtuale partendo da capitale iniziale")
    print("- scannerizzare i titoli MIB30 e trovare candidati interessanti")
    print("- decidere se confermare i candidati migliori con analisi visuale grafici via Playwright/ChatGPT")
    print("- proporre acquisti/vendite/ribilanciamenti sempre come proposte pending")
    print("- salvare condizioni non ancora verificate e rivalutarle nei controlli successivi")
    print("- mostrare una vista unica con portafoglio, proposte, condizioni monitorate e watchlist")
    print("- aggiornare il capitale virtuale quando lo dichiari esplicitamente")
    print("- mostrare, confermare o rifiutare proposte pending")
    print("- analizzare uno o piu titoli con grafici tecnici")
    print("- cercare news live tramite Playwright/ChatGPT se Chrome e aperto con debug remoto")
    print("- inviare riepilogo Telegram dei titoli monitorati e proposte pending")
    print("- avviare un monitor periodico che controlla portafoglio, condizioni e MIB30")
    print("- avviare un monitor periodico autonomo virtuale che applica decisioni e notifica via Telegram")
    print()
    print("Comandi esempio:")
    print("- cosa posso fare adesso?")
    print("- scannerizza 3 titoli del MIB30 e dimmi i migliori")
    print("- il portafoglio e vuoto, voglio investire 10000 euro")
    print("- crea una proposta di portafoglio con 5 titoli e 15% cash")
    print("- mostra proposte pending")
    print("- mostra condizioni da monitorare")
    print("- titoli monitorati")
    print("- mostra stato operativo del portafoglio")
    print("- aggiorna il capitale a 20000 euro")
    print("- conferma proposta 20260723-203433")
    print("- analizza VOD.L con news live")
    print("- invia riepilogo telegram")
    print("- monitor periodico ogni 30 minuti: usa da CLI --daemon-monitor --monitor-interval-minutes 30")
    print("- monitor autonomo virtuale: usa da CLI --autonomous-monitor")
    print()
    print("Regola di sicurezza: non modifico mai il portafoglio senza tua conferma esplicita.")
    print("Scrivi 'aiuto' per rivedere questa guida, oppure 'esci' per terminare.")
    return print_next_options(portfolio)


def run_interactive_loop(model):
    log_step("Modalita interattiva attiva")
    print("Ciao, sono TradingWatchAgent.")
    print("Ti aiuto a costruire e monitorare un portafoglio virtuale con analisi tecnica, news e proposte controllate.")
    portfolio = load_portfolio_file()
    if portfolio is None or not portfolio.get("positions"):
        print()
        print("Stato iniziale: il portafoglio non ha posizioni aperte.")
        print("Per partire puoi scrivere, ad esempio: il portafoglio e vuoto, voglio investire 10000 euro")
    current_options = print_interactive_help(portfolio)
    agent = build_agent(model=model)
    history = []
    while True:
        try:
            user_text = input("\nTu> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nUscita dalla modalita interattiva.")
            return
        user_text = user_text.lstrip("\ufeffï»¿")
        if not user_text:
            continue
        if user_text.lower() in {"esci", "exit", "quit", "q"}:
            print("Uscita dalla modalita interattiva.")
            return
        if user_text.lower() in {"aiuto", "help", "?"}:
            current_options = print_interactive_help(load_portfolio_file())
            continue
        if user_text.lower() in {
            "monitoring veloce",
            "titoli monitorati",
            "titoli sotto monitoring",
            "mostra titoli monitorati",
            "mostra condizioni veloci",
        }:
            print_monitored_conditions_quick()
            current_options = print_next_options(load_portfolio_file())
            continue
        if user_text.isdigit():
            option_index = int(user_text)
            if 1 <= option_index <= len(current_options):
                selected_option = current_options[option_index - 1]
                print(f"Opzione selezionata: {selected_option}")
                user_text = selected_option
            else:
                print(f"Opzione {option_index} non disponibile. Scrivi 'aiuto' per vedere le opzioni.")
                continue
        if handle_local_interactive_command(user_text):
            current_options = print_next_options(load_portfolio_file())
            continue
        contextual_request = build_contextual_request(history, user_text)
        result = run_agent_once(agent, contextual_request, display_request=user_text)
        history.append(
            {
                "user": user_text,
                "assistant": str(result.final_output).strip(),
            }
        )
        response_options = extract_next_options(str(result.final_output))
        current_options = response_options or build_startup_options(load_portfolio_file())


def main():
    configure_stdout()
    load_env_file()
    parser = argparse.ArgumentParser(description="Agente OpenAI SDK per watchlist e analisi titoli.")
    parser.add_argument(
        "request",
        nargs="?",
        default="Analizza VOD.L usando analisi tecnica e news disponibili.",
        help="Richiesta da inviare all'agente.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Modello OpenAI da usare.")
    parser.add_argument("--interactive", action="store_true", help="Avvia una sessione interattiva con l'agente.")
    parser.add_argument("--stocks", default="", help='Ticker separati da virgola, es. "VOD.L,A2A.MI,AVIO.MI".')
    parser.add_argument("--live-news", action="store_true", help="Permetti al news tool di usare Playwright live.")
    parser.add_argument("--init-portfolio", action="store_true", help="Crea portfolio.json con capitale iniziale.")
    parser.add_argument("--capital", type=float, default=None, help="Capitale iniziale del portafoglio virtuale.")
    parser.add_argument("--overwrite-portfolio", action="store_true", help="Ricrea portfolio.json se esiste gia.")
    parser.add_argument("--scan-mib30", action="store_true", help="Scannerizza il MIB30 e chiedi all'agente una sintesi.")
    parser.add_argument("--scan-limit", type=int, default=5, help="Numero massimo candidati MIB30.")
    parser.add_argument(
        "--daemon-monitor",
        action="store_true",
        help="Avvia monitoraggio periodico di portafoglio, condizioni e MIB30.",
    )
    parser.add_argument(
        "--autonomous-monitor",
        action="store_true",
        help="Avvia monitoraggio autonomo virtuale periodico: applica decisioni simulate e notifica via Telegram.",
    )
    parser.add_argument(
        "--monitor-interval-minutes",
        type=int,
        default=DEFAULT_MONITOR_INTERVAL_MINUTES,
        help="Intervallo in minuti tra un ciclo periodico e il successivo.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Esegue un solo ciclo nelle modalita periodiche/test e poi termina.",
    )
    parser.add_argument(
        "--periodic-live-news",
        action="store_true",
        help="Nel monitor periodico consente news live via Playwright per casi rilevanti.",
    )
    parser.add_argument(
        "--auto-apply-virtual",
        action="store_true",
        help="Permette al monitor periodico di applicare autonomamente operazioni simulate sul portafoglio virtuale.",
    )
    parser.add_argument(
        "--max-auto-trade-pct",
        type=float,
        default=DEFAULT_MAX_AUTO_TRADE_PCT,
        help="Percentuale massima del cash usabile per una nuova operazione autonoma virtuale.",
    )
    parser.add_argument(
        "--deep-chart-confirmation",
        action="store_true",
        help="Forza conferma dei migliori candidati con analisi grafica Playwright/ChatGPT.",
    )
    parser.add_argument(
        "--no-auto-deep-confirmation",
        action="store_true",
        help="Disattiva la scelta autonoma dell'agente di approfondire candidati con Playwright.",
    )
    parser.add_argument(
        "--deep-confirm-limit",
        type=int,
        default=3,
        help="Numero massimo di candidati da confermare con Playwright/ChatGPT.",
    )
    parser.add_argument(
        "--universe-limit",
        type=int,
        default=0,
        help="Solo per test: analizza al massimo N ticker dell'universo MIB30.",
    )
    parser.add_argument(
        "--build-empty-portfolio",
        action="store_true",
        help="Se il portafoglio e vuoto, chiedi capitale e crea proposta allocazione MIB30 pending.",
    )
    parser.add_argument("--cash-pct", type=float, default=15, help="Percentuale da lasciare cash nella proposta.")
    parser.add_argument(
        "--create-proposals",
        action="store_true",
        help="Durante lo scan crea proposte pending, da confermare esplicitamente.",
    )
    args = parser.parse_args()
    log_step("Avvio TradingWatchAgent")
    log_step(f"Working directory: {PROJECT_ROOT}")

    if args.autonomous_monitor:
        args.daemon_monitor = True
        args.auto_apply_virtual = True

    if args.daemon_monitor:
        mode = "autonomo virtuale" if args.auto_apply_virtual else "solo proposte"
        log_step(f"Modalita monitor periodico attiva | mode={mode}")
        run_periodic_monitor_loop(
            model=args.model,
            interval_minutes=args.monitor_interval_minutes,
            scan_limit=args.scan_limit,
            universe_limit=args.universe_limit,
            live_news=args.periodic_live_news,
            deep_confirm_limit=args.deep_confirm_limit,
            auto_apply_virtual=args.auto_apply_virtual,
            max_auto_trade_pct=args.max_auto_trade_pct,
            once=args.once,
        )
        return

    if args.interactive:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")
        run_interactive_loop(args.model)
        return

    if args.init_portfolio:
        capital = args.capital
        if capital is None:
            capital_text = input("Capitale iniziale portafoglio virtuale: ").strip().replace(",", ".")
            capital = float(capital_text)
        log_step(f"Inizializzo portafoglio virtuale | capital={capital} overwrite={args.overwrite_portfolio}")
        result = init_portfolio(capital, overwrite=args.overwrite_portfolio)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.build_empty_portfolio:
        capital = args.capital
        portfolio = load_portfolio_file()
        is_empty = portfolio is None or not portfolio.get("positions")
        if not is_empty:
            print("Il portafoglio contiene gia posizioni. Uso --scan-mib30 per analisi o conferme.")
            return
        if capital is None:
            capital_text = input("Il portafoglio e vuoto. Quanto vuoi investire nel portafoglio virtuale? ").strip()
            capital = float(capital_text.replace(",", "."))
        log_step(f"Portafoglio vuoto: preparo proposta iniziale | capital={capital}")
        init_portfolio(capital, overwrite=portfolio is None)
        request = (
            f"Il portafoglio e vuoto e l'utente vuole investire {capital:.2f} EUR. "
            f"Usa propose_virtual_portfolio_from_mib30 con max_positions={args.scan_limit} "
            f"cash_pct={args.cash_pct} e universe_limit={args.universe_limit}. "
        )
        if args.deep_chart_confirmation:
            request += (
                f"Prima di presentare la proposta finale, conferma i primi {args.deep_confirm_limit} "
                "candidati migliori con confirm_candidate_chart_with_playwright(no_telegram=True). "
                "Lavora un ticker alla volta: completa approfondimento e giudizio del primo candidato prima di passare al secondo. "
                "Se la conferma visuale smentisce un candidato, dichiaralo e riduci la convinzione. "
            )
        elif not args.no_auto_deep_confirmation:
            request += (
                f"Prima di presentare la proposta finale, valuta autonomamente i migliori candidati e, "
                f"se serve conferma o se stai allocando capitale, approfondisci fino a {args.deep_confirm_limit} "
                "candidati con confirm_candidate_chart_with_playwright(no_telegram=True). "
                "Lavora un ticker alla volta: completa approfondimento e giudizio del primo candidato prima di passare al secondo. "
                "Riporta quali candidati hai approfondito e quali no, con motivazione. "
            )
        request += (
            "Presenta la proposta pending generata, con importi, percentuali, motivazioni e rischi. "
            "Per ogni candidato analizzato assegna uno stato: BUY CANDIDATE, WAIT/MONITOR o SCARTATO. "
            "Se lo stato e WAIT/MONITOR, salva almeno una condizione concreta con record_monitored_condition. "
            "Ricorda che serve conferma esplicita del proposal_id prima di applicarla."
        )
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")
        agent = build_agent(model=args.model)
        run_agent_once(agent, request)
        return

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")

    request = args.request
    if args.scan_mib30:
        log_step(
            f"Modalita scan MIB30 | scan_limit={args.scan_limit} "
            f"universe_limit={args.universe_limit} create_proposals={args.create_proposals}"
        )
        if args.deep_chart_confirmation:
            log_step(f"Conferma grafica Playwright attiva | top={args.deep_confirm_limit}")
        elif not args.no_auto_deep_confirmation:
            log_step(f"Conferma grafica Playwright autonoma consentita | max={args.deep_confirm_limit}")
        proposal_hint = (
            "crea proposte pending per i migliori candidati"
            if args.create_proposals
            else "non creare proposte, mostra solo candidati"
        )
        request = (
            f"Carica il portafoglio virtuale e scannerizza il MIB30 con limite {args.scan_limit}; "
            f"usa universe_limit={args.universe_limit}; "
            f"{proposal_hint}. "
        )
        if args.deep_chart_confirmation:
            request += (
                f"Dopo lo scan devi confermare i primi {args.deep_confirm_limit} candidati migliori "
                "chiamando confirm_candidate_chart_with_playwright con no_telegram=True per ciascuno. "
                "Lavora un ticker alla volta: completa approfondimento e giudizio del primo candidato prima di passare al secondo. "
                "Solo dopo questa conferma visuale puoi indicare quali metteresti in proposta. "
            )
        elif not args.no_auto_deep_confirmation:
            request += (
                f"Dopo lo scan valuta autonomamente se approfondire fino a {args.deep_confirm_limit} candidati "
                "con confirm_candidate_chart_with_playwright(no_telegram=True). "
                "Se il risultato deve diventare una proposta o una raccomandazione operativa, approfondisci i migliori candidati. "
                "Lavora un ticker alla volta: completa approfondimento e giudizio del primo candidato prima di passare al secondo. "
                "Se non lo fai, spiega chiaramente perche lo score numerico e sufficiente. "
            )
        request += (
            "Spiega i criteri tecnici, elenca i candidati migliori, riporta per ogni candidato se la conferma "
            "Playwright e stata fatta o no, e indica quali metteresti in proposta. "
            "Per ogni candidato assegna uno stato: BUY CANDIDATE, WAIT/MONITOR o SCARTATO. "
            "Se una condizione d'acquisto non e verificata ma il titolo resta interessante, "
            "salvala con record_monitored_condition."
        )
    if args.stocks:
        log_step(f"Modalita analisi titoli | stocks={args.stocks} live_news={args.live_news}")
        live_hint = "usa live=True per le news" if args.live_news else "usa live=False per le news"
        request = (
            f"Analizza questi titoli: {args.stocks}. "
            f"Per ciascun titolo chiama analyze_stock_chart e analyze_stock_news; {live_hint}. "
            "Poi produci una sintesi comparativa con rischio, momentum, news disponibili e priorita di monitoraggio."
        )

    agent = build_agent(model=args.model)
    run_agent_once(agent, request)


if __name__ == "__main__":
    main()
