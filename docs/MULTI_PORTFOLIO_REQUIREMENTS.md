# Autonomous Trading Agent - Requisiti Multi-Portafoglio

Stato: approvato per implementazione iniziale
Branch: `codex/multi-portfolio`
Ultimo aggiornamento: 28/07/2026

## Stato implementazione

- [x] Specifica e criteri di accettazione.
- [x] Registry, preset rischio e migrazione idempotente del portafoglio legacy.
- [x] Scritture atomiche dei file portafoglio.
- [x] API elenco, creazione, dettaglio, modifica, pausa e attivazione.
- [x] Dashboard e watchlist riferite al `portfolio_id` selezionato.
- [x] Selettore persistente e creazione portafoglio nella GUI.
- [x] Risk manager alimentato dai limiti del portafoglio.
- [x] Snapshot condiviso delle cache scanner e valutazione per profilo.
- [x] Test automatici di migrazione, isolamento e valutazione differenziata.
- [x] Applicazione dei candidati condivisi ai trigger dei portafogli compatibili.
- [x] Cicli portfolio-specifici senza ripetizione degli scanner di mercato.
- [x] Configurazione completa profilo/mercati/asset class dalla GUI.
- [x] Telegram e analisi approfondita portfolio-aware.
- [x] Attribuzione del consumo token al portafoglio del subprocess.
- [ ] Vista comparativa aggregata dei portafogli e dei token condivisi.

## 1. Obiettivo

Il sistema deve gestire piu portafogli virtuali indipendenti evitando di ripetere
l'analisi tecnica, grafica e news dello stesso strumento per ogni portafoglio.

La soluzione deve separare:

1. analisi condivisa dei mercati e dei ticker;
2. regole, rischio e preferenze di ogni portafoglio;
3. decisioni, trigger, proposte, operazioni e performance del singolo portafoglio.

Uno stesso risultato di mercato puo produrre decisioni diverse: acquisto in un
portafoglio dinamico, monitoraggio in uno bilanciato ed esclusione in uno
prudente.

## 2. Principi vincolanti

- Ogni portafoglio rappresenta capitale virtuale indipendente.
- Cash, posizioni e performance non possono essere condivisi implicitamente.
- Lo scan di un ticker deve essere eseguito una sola volta per ciclo e riusato.
- News e analisi grafica devono essere riusate entro la loro validita temporale.
- Le decisioni operative devono sempre essere attribuite a un `portfolio_id`.
- Le impostazioni globali sono valori predefiniti; il portafoglio puo sovrascriverle.
- Il portafoglio esistente deve essere migrato senza perdita di dati.
- L'operativita rimane virtuale e non invia ordini a broker.

## 3. Terminologia

- **Registry**: elenco e metadati dei portafogli conosciuti.
- **Portafoglio attivo in GUI**: portafoglio selezionato dall'utente.
- **Portafoglio operativo**: portafoglio abilitato ai cicli schedulati.
- **Analisi condivisa**: dati tecnici, liquidita, news e scenario del ticker.
- **Valutazione portfolio-specifica**: applicazione di rischio, preferenze e
  disponibilita del singolo portafoglio.
- **Opportunita**: risultato condiviso potenzialmente applicabile a uno o piu
  portafogli.

## 4. Creazione e ciclo di vita

Ogni portafoglio deve avere:

- `id`: slug univoco, stabile e non modificabile;
- `name`: nome leggibile;
- `description`: descrizione facoltativa;
- `status`: `active`, `paused` o `archived`;
- `initial_capital`;
- `base_currency`, inizialmente solo `EUR`;
- `risk_profile`;
- `allowed_markets`;
- `allowed_asset_classes`;
- modalita di autonomia;
- impostazioni Telegram;
- date di creazione e aggiornamento.

Operazioni richieste:

- creazione da profilo;
- elenco;
- selezione;
- modifica configurazione;
- sospensione e riattivazione;
- archiviazione solo se non distruttiva;
- duplicazione della configurazione, senza copiare le posizioni salvo richiesta
  esplicita futura.

Non e richiesta nella prima versione la cancellazione definitiva dalla GUI.

## 5. Profili di rischio

Il sistema deve fornire tre preset modificabili.

| Parametro | Prudente | Bilanciato | Dinamico |
|---|---:|---:|---:|
| Cash minimo | 25% | 15% | 8% |
| Peso massimo singola posizione | 7% | 12% | 18% |
| Peso massimo settore | 18% | 25% | 35% |
| Nuova posizione massima | 5% | 8% | 12% |
| Incremento massimo | 2% | 3% | 5% |
| Trade minimo | 1% | 1% | 1% |
| Score minimo indicativo | alto | medio-alto | medio |
| Liquidita minima | alta | medio-alta | media |
| Numero massimo posizioni | 25 | 18 | 12 |

Identificativi:

- `conservative`;
- `balanced`;
- `dynamic`;
- `custom` quando un parametro differisce dal preset selezionato.

I parametri devono essere salvati nella configurazione del portafoglio e passati
esplicitamente al risk manager. Le variabili `.env` restano fallback legacy.

## 6. Preferenze strumenti e mercati

Configurazioni minime:

- asset class: `equity`, `etf`, `commodity_etc`;
- mercati: `ftse_mib`, `commodities`, `etf`, `watchlist`;
- strumenti leveraged ammessi si/no;
- settori esclusi e preferiti;
- ticker esclusi;
- limite percentuale per asset class;
- controvalore medio minimo;
- numero massimo di posizioni.

Un titolo escluso dalla policy deve restare visibile nell'analisi condivisa, con
motivo portfolio-specifico, ma non puo generare un acquisto per quel portafoglio.

## 7. Analisi condivisa

### 7.1 Pipeline

Per ogni ciclo il coordinatore deve:

1. caricare tutti i portafogli `active`;
2. calcolare l'unione dei mercati e ticker richiesti;
3. scaricare e calcolare una sola volta prezzi, indicatori, volumi e liquidita;
4. produrre una shortlist condivisa;
5. eseguire news/grafico solo sui ticker che richiedono approfondimento;
6. salvare opportunita e analisi;
7. applicare le opportunita a ogni portafoglio;
8. salvare decisioni e notifiche separatamente.

### 7.2 Identita e validita cache

Ogni analisi condivisa deve riportare:

- ticker normalizzato;
- mercato e asset class;
- `analysis_date`;
- `as_of`;
- versione dell'algoritmo;
- origine dei dati;
- sessione di mercato;
- scadenza o criterio di freschezza.

Chiave logica minima:

`ticker + analysis_date + analysis_type + algorithm_version`

Il sistema non deve eseguire due chiamate Playwright per lo stesso ticker e
finalita nello stesso ciclo, salvo retry controllato dopo errore.

### 7.3 Distinzione tra analisi e decisione

L'analisi condivisa puo dichiarare un ticker tecnicamente interessante. Non puo
decidere importo o acquisto definitivo senza il contesto del portafoglio.

La valutazione portfolio-specifica deve verificare:

- mercato e asset class ammessi;
- score minimo;
- liquidita minima;
- ticker/settore esclusi;
- posizione esistente;
- spazio residuo per posizione, settore e asset class;
- cash minimo;
- numero massimo posizioni;
- idempotenza dell'operazione.

## 8. Isolamento dei dati

Struttura iniziale richiesta:

```text
data/
  portfolios/
    registry.json
    <portfolio_id>/
      config.json
      portfolio.json
      runtime.json
  shared/
    market-analysis/
    opportunities/
    scheduler-state.json
```

News e grafici gia salvati in `output/stock_ai` possono rimanere nella posizione
attuale durante la prima migrazione, pur essendo considerati dati condivisi.

Ogni file portfolio-specifico deve includere `portfolio_id`.

Le scritture JSON devono essere atomiche. Due run non devono poter modificare
contemporaneamente lo stesso portafoglio.

## 9. Migrazione

Al primo avvio multi-portafoglio:

- creare il registry se assente;
- creare `main` con nome `Portafoglio principale`;
- copiare lo stato del `portfolio.json` esistente nel nuovo percorso;
- non alterare importi, quantita, trigger, proposte o cronologia;
- conservare il file legacy come compatibilita transitoria;
- registrare versione e data della migrazione;
- rendere la migrazione ripetibile senza duplicare dati.

Durante la transizione, l'accesso senza `portfolio_id` deve risolvere il
portafoglio predefinito `main`.

## 10. API backend

Endpoint minimi:

- `GET /api/portfolios`;
- `POST /api/portfolios`;
- `GET /api/portfolios/{portfolio_id}`;
- `PATCH /api/portfolios/{portfolio_id}`;
- `POST /api/portfolios/{portfolio_id}/pause`;
- `POST /api/portfolios/{portfolio_id}/activate`;
- `GET /api/portfolios/{portfolio_id}/status`;
- `GET /api/portfolios/{portfolio_id}/performance`;

Gli endpoint portfolio-specifici esistenti devono accettare gradualmente
`portfolio_id`, preferibilmente nel path o, nella transizione, come query
parameter. L'assenza deve usare il portafoglio predefinito.

Errori richiesti:

- `404` per portafoglio inesistente;
- `409` per ID duplicato o conflitto di scrittura;
- `422` per configurazione o profilo non valido.

## 11. GUI

Requisiti:

- selettore portafoglio persistente nell'intestazione;
- pagina o pannello `Portafogli`;
- wizard di creazione;
- riepilogo del profilo e delle principali soglie;
- stato `attivo`, `sospeso`, `archiviato`;
- dashboard, azioni, trigger e log filtrati sul portafoglio selezionato;
- nome del portafoglio sempre visibile prima di un'azione manuale;
- vista riepilogativa comparativa, successiva all'MVP.

Il cambio del portafoglio selezionato non deve avviare operazioni.

## 12. Scheduler

Deve esistere un coordinatore unico. Non deve essere avviato un processo scanner
completo per ogni portafoglio.

Un ciclo deve avere:

- un `run_id` condiviso;
- una fase di analisi mercati;
- una fase di applicazione per ogni `portfolio_id`;
- stato e log per portafoglio;
- riepilogo finale con portafogli elaborati, ignorati o falliti.

Un errore su un portafoglio non deve annullare le decisioni gia salvate sugli
altri, ma deve essere evidenziato nel riepilogo.

## 13. Telegram

Configurazione globale con override per portafoglio:

- destinazione/chat;
- modalita notifiche;
- alert performance;
- massimo numero di trigger;
- news rilevanti.

Ogni messaggio portfolio-specifico deve indicare chiaramente il nome del
portafoglio.

Una news condivisa puo essere notificata a piu portafogli, ma una sola volta per
`portfolio_id + ticker + news_id + tipo_evento`.

## 14. Token e costi

Il consumo deve distinguere:

- token del ciclo condiviso;
- token direttamente attribuibili a un portafoglio;
- token non attribuibili.

L'aggiunta di un portafoglio non deve moltiplicare automaticamente il costo
dello scan o delle news. La valutazione portfolio-specifica deve usare prima
regole deterministiche; il modello va chiamato solo quando una decisione non e
risolvibile con dati strutturati.

## 15. Idempotenza e concorrenza

Una chiave di esecuzione operativa deve includere almeno:

`portfolio_id + ticker + condition_id + action + trading_date`

Il sistema deve impedire:

- doppio acquisto nello stesso portafoglio per la stessa condizione;
- propagazione accidentale di un'operazione ad altri portafogli;
- due scritture concorrenti sullo stesso file;
- riuso di una decisione oltre la validita dell'analisi sottostante.

## 16. Sicurezza e audit

Ogni decisione deve riportare:

- `portfolio_id`;
- `run_id`;
- ticker;
- analisi condivisa utilizzata;
- profilo e limiti applicati;
- decisione;
- importo proposto o applicato;
- motivo di accettazione o rifiuto;
- timestamp.

Le modifiche alla configurazione devono essere tracciabili almeno tramite
`updated_at`; la cronologia completa delle configurazioni e rinviata.

## 17. Criteri di accettazione MVP

La prima versione e accettata quando:

1. il portafoglio attuale viene migrato in `main` senza variazioni contabili;
2. e possibile creare un secondo portafoglio da uno dei tre profili;
3. i due portafogli mantengono cash, posizioni e trigger indipendenti;
4. la GUI permette di cambiare portafoglio;
5. lo stesso scan viene riusato per entrambi;
6. ciascun portafoglio puo accettare o scartare diversamente la stessa opportunita;
7. il risk manager usa i limiti del portafoglio;
8. log, azioni e notifiche riportano il `portfolio_id`;
9. un portafoglio sospeso non riceve nuove operazioni automatiche;
10. i test dimostrano che non avvengono doppie esecuzioni;
11. backend live e build frontend vengono verificati;
12. il portafoglio legacy resta recuperabile.

## 18. Fasi di implementazione

### Fase 1 - Fondazione

- registry e repository dati;
- schemi e validazione;
- preset rischio;
- migrazione idempotente del portafoglio attuale;
- risoluzione del portafoglio predefinito.

### Fase 2 - Backend portfolio-aware

- API CRUD;
- passaggio di `portfolio_id` ai servizi;
- risk manager configurabile;
- performance, azioni, trigger e Telegram isolati.

### Fase 3 - GUI

- selettore;
- wizard;
- configurazione;
- viste filtrate.

### Fase 4 - Analisi condivisa

- coordinatore unico;
- cache condivisa versionata;
- opportunita indipendenti;
- applicazione ai portafogli attivi.

### Fase 5 - Verifica e rifinitura

- test di migrazione;
- test isolamento e idempotenza;
- test multi-portafoglio end-to-end;
- log, token e notifiche;
- rimozione della compatibilita legacy solo dopo verifica esplicita.

## 19. Decisioni rinviate

Non bloccano l'MVP:

- passaggio da JSON a SQLite;
- vista patrimoniale aggregata;
- condivisione volontaria dello stesso capitale tra strategie;
- integrazione broker reale;
- multiutente e autorizzazioni;
- backtest comparativo automatico dei profili;
- copia opzionale delle posizioni durante la duplicazione.
