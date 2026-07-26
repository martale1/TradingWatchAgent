# LangGraph Review Branch

Questo branch introduce una prima struttura alternativa basata su LangGraph, affiancata all'agente esistente.

## Obiettivo

Rendere il ciclo operativo piu tracciabile e meno opaco:

- ogni fase del processo diventa un nodo esplicito;
- i log indicano mercato, ticker, score e motivo della decisione;
- Playwright viene pianificato solo quando serve davvero;
- FTSE MIB e Materie prime/ETC seguono lo stesso flusso operativo.

## Flusso iniziale

1. `load_operating_state`
   Legge portafoglio, performance, posizioni aperte, condizioni monitorate e watchlist.

2. `scan_ftse_mib`
   Usa indicatori locali e dati Yahoo Finance per calcolare score e liquidita sui titoli FTSE MIB.

3. `scan_commodities`
   Usa lo stesso processo sugli strumenti caricati da `validTickers/MateriePrime.xlsx`.

4. `build_shortlist`
   Unisce i candidati liquidi dei due mercati, ordinandoli per score.

5. `plan_deep_analysis`
   Prepara gli approfondimenti Playwright solo per:
   - titoli gia in portafoglio;
   - trigger monitorati scattati;
   - buy candidate con score tecnico forte.

6. `draft_decisions`
   Produce decisioni preliminari senza applicare operazioni.

7. `finalize`
   Crea un riepilogo leggibile del ciclo.

## Primo test

```powershell
C:\Users\theoi\anaconda3\envs\openaiAgent\python.exe langgraph_portfolio_manager.py --scan-limit 3 --universe-limit 10
```

Per vedere lo stato completo:

```powershell
C:\Users\theoi\anaconda3\envs\openaiAgent\python.exe langgraph_portfolio_manager.py --scan-limit 3 --universe-limit 10 --json
```

## Nota

Questa prima versione non sostituisce ancora `agent_portfolio_manager.py` e non applica trade. Serve come base per rivedere l'architettura con nodi, logging e policy di approfondimento piu controllabili.
