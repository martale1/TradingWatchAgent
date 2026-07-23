import argparse
import json
import os
from pathlib import Path

from agents import Agent, Runner, function_tool

from finance_tools.chart_tool import generate_chart_context_json
from finance_tools.common import PROJECT_ROOT, load_env_file
from finance_tools.mib30_scanner import propose_virtual_allocation_json, scan_mib30_candidates_json
from finance_tools.news_tool import get_news_report_json
from finance_tools.portfolio_store import (
    confirm_proposal as confirm_portfolio_proposal,
    init_portfolio,
    list_pending_proposals,
    load_portfolio as load_portfolio_file,
    reject_proposal as reject_portfolio_proposal,
)


DEFAULT_MODEL = os.getenv("OPENAI_AGENT_MODEL", "gpt-4.1-mini")


@function_tool
def analyze_stock_chart(ticker: str, days: int = 70, period: str = "1y") -> str:
    """Generate technical charts and numeric technical context for one stock.

    Args:
        ticker: Stock ticker symbol, for example VOD.L or A2A.MI.
        days: Number of recent trading bars to include in charts.
        period: Yahoo Finance download period, for example 6mo, 1y, or 2y.
    """
    return generate_chart_context_json(ticker=ticker, days=days, period=period)


@function_tool
def analyze_stock_news(ticker: str, live: bool = False) -> str:
    """Return a news report for one stock.

    Args:
        ticker: Stock ticker symbol, for example VOD.L or A2A.MI.
        live: If true, run the Playwright ChatGPT news workflow; if false, read cached news if available.
    """
    return get_news_report_json(ticker=ticker, live=live)


@function_tool
def load_watchlist(path: str = "portfolio.example.json") -> str:
    """Load a watchlist JSON file.

    Args:
        path: Relative or absolute path to a JSON file containing a watchlist array.
    """
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path
    if not file_path.exists():
        return json.dumps({"status": "missing", "file": str(file_path)}, ensure_ascii=False)
    return file_path.read_text(encoding="utf-8")


@function_tool
def load_virtual_portfolio() -> str:
    """Load the current virtual portfolio, if it exists."""
    portfolio = load_portfolio_file()
    if portfolio is None:
        return json.dumps({"status": "missing", "message": "portfolio.json non esiste."}, ensure_ascii=False)
    return json.dumps({"status": "ok", "portfolio": portfolio}, ensure_ascii=False, indent=2)


@function_tool
def scan_mib30_for_candidates(limit: int = 5, create_proposals: bool = False) -> str:
    """Scan Italian MIB30 tickers and find interesting technical candidates.

    Args:
        limit: Maximum number of candidates to return.
        create_proposals: If true, create pending proposals in portfolio.json. Proposals still require user confirmation.
    """
    return scan_mib30_candidates_json(limit=limit, create_proposals=create_proposals)


@function_tool
def propose_virtual_portfolio_from_mib30(capital: float, max_positions: int = 5, cash_pct: float = 15) -> str:
    """Create a pending virtual portfolio allocation proposal from MIB30 candidates.

    Args:
        capital: Total virtual capital the user wants to invest.
        max_positions: Maximum number of stocks in the proposal.
        cash_pct: Percentage of capital to keep as cash.
    """
    return propose_virtual_allocation_json(capital=capital, max_positions=max_positions, cash_pct=cash_pct)


@function_tool
def list_portfolio_proposals() -> str:
    """List pending portfolio proposals that require explicit user confirmation."""
    return json.dumps({"status": "ok", "pending": list_pending_proposals()}, ensure_ascii=False, indent=2)


@function_tool
def confirm_portfolio_proposal_tool(proposal_id: str) -> str:
    """Confirm and apply a pending portfolio proposal.

    Args:
        proposal_id: The proposal id to confirm.
    """
    return json.dumps(confirm_portfolio_proposal(proposal_id), ensure_ascii=False, indent=2)


@function_tool
def reject_portfolio_proposal_tool(proposal_id: str) -> str:
    """Reject and archive a pending portfolio proposal.

    Args:
        proposal_id: The proposal id to reject.
    """
    return json.dumps(reject_portfolio_proposal(proposal_id), ensure_ascii=False, indent=2)


def build_agent(model=DEFAULT_MODEL):
    return Agent(
        name="Portfolio Monitor Agent",
        model=model,
        instructions=(
            "Sei un agente finanziario operativo per monitorare un portafoglio virtuale e una watchlist. "
            "Usa i tool disponibili per raccogliere dati tecnici e news. "
            "Rispondi sempre in italiano. Non dare consulenza finanziaria personalizzata. "
            "Non modificare mai il portafoglio autonomamente: puoi solo creare proposte pending, "
            "e applicarle esclusivamente quando l'utente conferma esplicitamente un proposal_id. "
            "Quando analizzi un titolo, combina news, momentum, trend, supporti, resistenze, volumi e rischio. "
            "Quando cerchi candidati MIB30, spiega i criteri usati e distingui ragioni tecniche e rischi. "
            "Se un tool restituisce dati mancanti, dichiaralo chiaramente e continua con i dati disponibili. "
            "Formatta l'output in modo compatto, adatto anche a Telegram."
        ),
        tools=[
            analyze_stock_chart,
            analyze_stock_news,
            load_watchlist,
            load_virtual_portfolio,
            scan_mib30_for_candidates,
            propose_virtual_portfolio_from_mib30,
            list_portfolio_proposals,
            confirm_portfolio_proposal_tool,
            reject_portfolio_proposal_tool,
        ],
    )


def main():
    load_env_file()
    parser = argparse.ArgumentParser(description="Agente OpenAI SDK per watchlist e analisi titoli.")
    parser.add_argument(
        "request",
        nargs="?",
        default="Analizza VOD.L usando analisi tecnica e news disponibili.",
        help="Richiesta da inviare all'agente.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Modello OpenAI da usare.")
    parser.add_argument("--stocks", default="", help='Ticker separati da virgola, es. "VOD.L,A2A.MI,AVIO.MI".')
    parser.add_argument("--live-news", action="store_true", help="Permetti al news tool di usare Playwright live.")
    parser.add_argument("--init-portfolio", action="store_true", help="Crea portfolio.json con capitale iniziale.")
    parser.add_argument("--capital", type=float, default=None, help="Capitale iniziale del portafoglio virtuale.")
    parser.add_argument("--overwrite-portfolio", action="store_true", help="Ricrea portfolio.json se esiste gia.")
    parser.add_argument("--scan-mib30", action="store_true", help="Scannerizza il MIB30 e chiedi all'agente una sintesi.")
    parser.add_argument("--scan-limit", type=int, default=5, help="Numero massimo candidati MIB30.")
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

    if args.init_portfolio:
        capital = args.capital
        if capital is None:
            capital_text = input("Capitale iniziale portafoglio virtuale: ").strip().replace(",", ".")
            capital = float(capital_text)
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
        init_portfolio(capital, overwrite=portfolio is None)
        request = (
            f"Il portafoglio e vuoto e l'utente vuole investire {capital:.2f} EUR. "
            f"Usa propose_virtual_portfolio_from_mib30 con max_positions={args.scan_limit} "
            f"e cash_pct={args.cash_pct}. "
            "Presenta la proposta pending generata, con importi, percentuali, motivazioni e rischi. "
            "Ricorda che serve conferma esplicita del proposal_id prima di applicarla."
        )
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")
        agent = build_agent(model=args.model)
        result = Runner.run_sync(agent, request, max_turns=20)
        print(result.final_output)
        return

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")

    request = args.request
    if args.scan_mib30:
        proposal_hint = (
            "crea proposte pending per i migliori candidati"
            if args.create_proposals
            else "non creare proposte, mostra solo candidati"
        )
        request = (
            f"Carica il portafoglio virtuale e scannerizza il MIB30 con limite {args.scan_limit}; "
            f"{proposal_hint}. "
            "Spiega i criteri tecnici, elenca i candidati migliori e indica quali metteresti in proposta."
        )
    if args.stocks:
        live_hint = "usa live=True per le news" if args.live_news else "usa live=False per le news"
        request = (
            f"Analizza questi titoli: {args.stocks}. "
            f"Per ciascun titolo chiama analyze_stock_chart e analyze_stock_news; {live_hint}. "
            "Poi produci una sintesi comparativa con rischio, momentum, news disponibili e priorita di monitoraggio."
        )

    agent = build_agent(model=args.model)
    result = Runner.run_sync(agent, request, max_turns=20)
    print(result.final_output)


if __name__ == "__main__":
    main()
