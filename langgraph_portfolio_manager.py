import argparse

from finance_tools.common import load_env_file
from langgraph_agent.graph import run_langgraph_workflow, state_to_json


def main():
    load_env_file()
    parser = argparse.ArgumentParser(
        description="Prototype LangGraph per Autonomous Trading Agent."
    )
    parser.add_argument(
        "request",
        nargs="?",
        default="monitor",
        help="Richiesta operativa da passare al grafo.",
    )
    parser.add_argument("--scan-limit", type=int, default=5)
    parser.add_argument(
        "--universe-limit",
        type=int,
        default=None,
        help="Limita il numero di strumenti per mercato durante i test.",
    )
    parser.add_argument("--json", action="store_true", help="Stampa lo stato finale JSON.")
    args = parser.parse_args()

    final_state = run_langgraph_workflow(
        request=args.request,
        scan_limit=args.scan_limit,
        universe_limit=args.universe_limit,
    )
    if args.json:
        print(state_to_json(final_state))
    else:
        print()
        print(final_state.get("final_summary", "Nessun riepilogo generato."))


if __name__ == "__main__":
    main()

