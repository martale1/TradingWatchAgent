import argparse
import json
import os
import sys
from pathlib import Path

from agents import Agent, ModelSettings, Runner, function_tool

from finance_tools.chart_tool import generate_chart_context_json
from finance_tools.common import PROJECT_ROOT, load_env_file
from finance_tools.deep_chart_tool import confirm_candidate_with_chart_ai_json
from finance_tools.mib30_scanner import propose_virtual_allocation_json, scan_mib30_candidates_json
from finance_tools.news_tool import get_news_report_json
from finance_tools.portfolio_store import (
    add_monitored_condition,
    confirm_proposal as confirm_portfolio_proposal,
    init_portfolio,
    list_monitored_conditions,
    list_pending_proposals,
    load_portfolio as load_portfolio_file,
    reject_proposal as reject_portfolio_proposal,
)


DEFAULT_MODEL = os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6-luna")


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
def confirm_portfolio_proposal_tool(proposal_id: str) -> str:
    """Confirm and apply a pending portfolio proposal.

    Args:
        proposal_id: The proposal id to confirm.
    """
    log_step(f"Tool confirm_portfolio_proposal_tool chiamato | proposal_id={proposal_id}")
    return json.dumps(confirm_portfolio_proposal(proposal_id), ensure_ascii=False, indent=2)


@function_tool
def reject_portfolio_proposal_tool(proposal_id: str) -> str:
    """Reject and archive a pending portfolio proposal.

    Args:
        proposal_id: The proposal id to reject.
    """
    log_step(f"Tool reject_portfolio_proposal_tool chiamato | proposal_id={proposal_id}")
    return json.dumps(reject_portfolio_proposal(proposal_id), ensure_ascii=False, indent=2)


def build_agent(model=DEFAULT_MODEL):
    log_step(f"Creo agente Portfolio Monitor Agent | model={model} | parallel_tool_calls=False")
    return Agent(
        name="Portfolio Monitor Agent",
        model=model,
        instructions=(
            "Sei un agente finanziario operativo per monitorare un portafoglio virtuale e una watchlist. "
            "Usa i tool disponibili per raccogliere dati tecnici e news. "
            "Rispondi sempre in italiano. Non dare consulenza finanziaria personalizzata. "
            "Non modificare mai il portafoglio autonomamente: puoi solo creare proposte pending, "
            "e applicarle esclusivamente quando l'utente conferma esplicitamente un proposal_id. "
            "Se l'utente chiede una proposta o chiede se ci sono titoli da comprare, devi rispondere in modo operativo: "
            "BUY CANDIDATE, WAIT/MONITOR oppure SCARTATO. "
            "Prima di rifare analisi live, consulta load_virtual_portfolio, list_portfolio_proposals e list_conditions_to_monitor "
            "per usare lo stato gia salvato. "
            "Puoi dire BUY CANDIDATE solo dopo avere usato analisi dettagliata del grafico e news disponibili; "
            "in quel caso crea una proposta pending se ci sono capitale e condizioni sufficienti, altrimenti chiedi il dato mancante. "
            "Quando una condizione non e verificata ma il titolo resta interessante, salva la condizione con record_monitored_condition "
            "e spiega quando andra rivalutata. "
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
            "Formatta l'output in modo compatto, adatto anche a Telegram."
        ),
        model_settings=ModelSettings(parallel_tool_calls=False),
        tools=[
            analyze_stock_chart,
            analyze_stock_news,
            confirm_candidate_chart_with_playwright,
            load_watchlist,
            load_virtual_portfolio,
            scan_mib30_for_candidates,
            propose_virtual_portfolio_from_mib30,
            list_portfolio_proposals,
            record_monitored_condition,
            list_conditions_to_monitor,
            confirm_portfolio_proposal_tool,
            reject_portfolio_proposal_tool,
        ],
    )


def run_agent_once(agent, request, display_request=None):
    log_step("Prompt operativo inviato all'agente:")
    log_step(display_request or request)
    log_step("Invio richiesta all'agente OpenAI SDK e attendo risposta/tool calls...")
    result = Runner.run_sync(agent, request, max_turns=20)
    log_step("Risposta finale agente ricevuta")
    print("\n" + str(result.final_output).strip() + "\n", flush=True)
    return result


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


def print_interactive_help():
    print()
    print("Cosa posso fare:")
    print("- creare un portafoglio virtuale partendo da capitale iniziale")
    print("- scannerizzare i titoli MIB30 e trovare candidati interessanti")
    print("- decidere se confermare i candidati migliori con analisi visuale grafici via Playwright/ChatGPT")
    print("- proporre acquisti/vendite/ribilanciamenti sempre come proposte pending")
    print("- salvare condizioni non ancora verificate e rivalutarle nei controlli successivi")
    print("- mostrare, confermare o rifiutare proposte pending")
    print("- analizzare uno o piu titoli con grafici tecnici")
    print("- cercare news live tramite Playwright/ChatGPT se Chrome e aperto con debug remoto")
    print()
    print("Comandi esempio:")
    print("- scannerizza 3 titoli del MIB30 e dimmi i migliori")
    print("- il portafoglio e vuoto, voglio investire 10000 euro")
    print("- crea una proposta di portafoglio con 5 titoli e 15% cash")
    print("- mostra proposte pending")
    print("- mostra condizioni da monitorare")
    print("- conferma proposta 20260723-203433")
    print("- analizza VOD.L con news live")
    print()
    print("Regola di sicurezza: non modifico mai il portafoglio senza tua conferma esplicita.")
    print("Scrivi 'aiuto' per rivedere questa guida, oppure 'esci' per terminare.")


def run_interactive_loop(model):
    log_step("Modalita interattiva attiva")
    print("Ciao, sono TradingWatchAgent.")
    print("Ti aiuto a costruire e monitorare un portafoglio virtuale con analisi tecnica, news e proposte controllate.")
    portfolio = load_portfolio_file()
    if portfolio is None or not portfolio.get("positions"):
        print()
        print("Stato iniziale: il portafoglio non ha posizioni aperte.")
        print("Per partire puoi scrivere, ad esempio: il portafoglio e vuoto, voglio investire 10000 euro")
    print_interactive_help()
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
            print_interactive_help()
            continue
        contextual_request = build_contextual_request(history, user_text)
        result = run_agent_once(agent, contextual_request, display_request=user_text)
        history.append(
            {
                "user": user_text,
                "assistant": str(result.final_output).strip(),
            }
        )


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
