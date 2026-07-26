# Autonomous Trading Agent - Requisiti Operativi

Questo file va riletto prima di ogni modifica importante, run manuale, revisione agentica o refactoring. Serve a evitare di perdere requisiti gia discussi e a mantenere prevedibile il comportamento del sistema.

## Obiettivo

Autonomous Trading Agent gestisce un portafoglio virtuale con trading automatico, monitoraggio trigger, analisi tecnica, news tramite ChatGPT/Playwright e notifiche Telegram.

Il sistema deve aiutare l'utente a:

- monitorare posizioni aperte;
- trovare nuovi candidati operativi su piu mercati;
- valutare ingressi, uscite, riduzioni, incrementi e ribilanciamenti;
- agire autonomamente solo quando la modalita configurata lo consente;
- spiegare sempre cosa ha fatto, perche lo ha fatto e cosa sta aspettando.

## Mercati In Scope

Il processo deve considerare tutti i mercati configurati:

- FTSE MIB: titoli italiani principali, ex MIB30 nel codice storico;
- Materie prime / ETC: strumenti caricati da `MateriePrime.xlsx`;
- ETF: lista dedicata, inizialmente con `ROBO.MI` come Robotics & Automation;
- Watchlist manuale: titoli aggiunti dall'utente, anche se non selezionati dagli scanner.

Ogni mercato deve avere una vista chiara, separata e coerente. Non mischiare FTSE MIB, Materie prime/ETC ed ETF nella stessa sezione se questo rende poco leggibile lo stato operativo.

### Liste Mercato Configurabili

Le liste mercato devono essere gestibili in modo uniforme per tutti i mercati configurabili:

- aggiunta manuale da GUI;
- import da Excel;
- selezione attivo/non attivo;
- rimozione;
- scan sul solo universo attivo;
- visualizzazione chiara di universo, attivi, candidati, liquidita e score.

Il file configurato dall'utente e la lista manuale sono la fonte autorevole per:

- ticker;
- nome;
- descrizione;
- mercato;
- stato attivo.

La cache scanner puo arricchire i record con:

- score;
- prezzo;
- variazione giornaliera;
- indicatori;
- liquidita;
- supporti/resistenze;
- ragioni/rischi.

La cache scanner non deve sovrascrivere nome o descrizione configurati dall'utente. Se lo scan contiene un vecchio nome, la dashboard deve continuare a mostrare il nome della lista mercato.

Endpoint minimi attesi:

- `GET /api/markets/{market}/universe`;
- `POST /api/markets/{market}/instrument`;
- `PATCH /api/markets/{market}/instrument/{ticker}`;
- `DELETE /api/markets/{market}/instrument/{ticker}`;
- `POST /api/markets/{market}/import-excel`.

La GUI non deve mostrare `Not Found` come stato normale. Se un endpoint manca o il backend e vecchio, deve essere evidente che serve riavviare il backend o correggere il contratto API.

### ETF

Il mercato ETF deve essere trattato come mercato autonomo, non come watchlist generica.

Requisiti iniziali:

- ticker iniziale: `ROBO.MI`;
- nome/descrizione: `Robotics and Automation`;
- asset class: `etf`;
- il titolo deve comparire nella tab ETF anche prima dello scan;
- dopo lo scan deve mostrare score, prezzo, liquidita e ragioni/rischi;
- se la liquidita non e ok, deve restare visibile ma non diventare candidato operativo automatico.

## Processo Di Analisi

Il flusso standard deve essere:

1. Caricare portafoglio, watchlist, condizioni monitorate e configurazioni.
2. Scansionare gli universi di mercato con indicatori locali.
3. Filtrare per liquidita, score tecnico, trigger vicini e stato del portafoglio.
4. Approfondire solo i titoli rilevanti.
5. Usare Playwright/ChatGPT solo quando serve davvero.
6. Applicare o proporre azioni in base alla modalita di autonomia.
7. Salvare stato, decisioni, log e notifiche.

### Modalita Di Run

I pulsanti e i comandi devono avere nomi comprensibili.

Nomi da evitare o chiarire:

- `Run Playwright no API` e ambiguo.

Nome consigliato:

- `Monitor via ChatGPT Web`;
- oppure `Run con ChatGPT Web`.

Descrizione richiesta:

- usa ChatGPT nel browser tramite Playwright per gli approfondimenti;
- riduce l'uso della OpenAI API key;
- richiede Chrome aperto con debug remoto e sessione ChatGPT valida;
- puo essere piu lento della modalita SDK.

Modalita principali:

- `Run monitor SDK`: usa OpenAI SDK/API per orchestrazione completa, con Playwright solo quando serve.
- `Run con ChatGPT Web`: usa Playwright/ChatGPT web per approfondimenti e riduce uso API.
- `Analisi profonda portafoglio`: lavora soprattutto sulle posizioni aperte e produce report operativo dettagliato.
- `Esegui ora`: run manuale completo su tutto lo scope operativo configurato, rispettando filtri e policy.

## Uso Di Playwright

Playwright deve essere usato per ridurre consumo di token API e per sfruttare ChatGPT nel browser gia loggato.

Non usare Playwright su tutti i titoli degli Excel o degli universi completi.

Usare Playwright solo per:

- titoli in portafoglio;
- buy candidate o candidati operativi reali;
- trigger scattati;
- trigger molto vicini o condizioni critiche;
- news live richieste dall'utente;
- analisi approfondita on demand.

Per ogni uso di Playwright i log devono indicare:

- perche il titolo e stato selezionato;
- quale ticker viene analizzato;
- se si stanno leggendo grafici, news o entrambi;
- inizio, avanzamento e fine subprocess;
- durata e output prodotto.

Playwright non deve essere chiamato due volte per lo stesso ticker e la stessa finalita nello stesso run, salvo errore esplicito e retry controllato.

Esempio:

- corretto: `CPR.MI grafico+news via Playwright per posizione in portafoglio`;
- non corretto: due subprocess paralleli o consecutivi per `CPR.MI` senza motivo tracciato.

Se Playwright resta appeso, il log deve dire:

- ticker;
- fase;
- durata;
- ultimo output;
- azione di recovery;
- se il run continua o si interrompe.

## API OpenAI

L'API OpenAI serve principalmente per orchestrare l'agente e prendere decisioni strutturate.

Il grosso dell'analisi visuale/news deve passare da Playwright/ChatGPT quando possibile.

Usare modelli piu leggeri quando i run sono lunghi o coinvolgono molti titoli. Evitare prompt troppo grandi e tool call non necessarie.

## Score E Candidati

Lo score tecnico deve essere calcolato per i titoli effettivamente scansionati.

Le categorie devono essere distinte:

- Universo: titolo disponibile ma non ancora interessante o non ancora scansionato.
- Monitorato: titolo con condizione salvata da rivalutare.
- Nuovo candidato operativo: titolo liquido, score sufficiente, non gia in portafoglio.
- Gia in portafoglio: titolo posseduto, da gestire con logica di uscita, incremento, riduzione o mantenimento.
- Escluso per liquidita: titolo tecnicamente interessante ma non adatto per operativita virtuale per liquidita insufficiente.
- Score sotto soglia: titolo scansionato ma non abbastanza forte per essere operativo.

I titoli con liquidita bassa non devono essere proposti come candidati operativi automatici.

I candidati operativi dopo scanner devono escludere:

- titoli gia presenti in portafoglio, che vanno mostrati in una sezione separata come "posizioni gia aperte rilevate dallo scanner";
- titoli con liquidita bassa;
- titoli con score sotto soglia;
- titoli senza dati sufficienti.

La GUI deve distinguere chiaramente:

- `Nuovo candidato operativo`: titolo non in portafoglio, liquido e con score adeguato;
- `Gia in portafoglio`: titolo posseduto, da valutare per mantenere/ridurre/vendere/incrementare;
- `Monitorato`: titolo con trigger o scenario da rivalutare;
- `Universo`: titolo disponibile ma non operativo.

Se una tabella mostra un titolo con score basso ma badge candidato, deve essere chiaro se "candidato" significa solo "ha superato un filtro tecnico minimo" o "nuovo candidato operativo". La seconda definizione e quella da preferire per la UI.

## Liquidita

La liquidita va verificata prima di includere un titolo tra i candidati operativi.

Parametri da considerare:

- volume medio;
- turnover stimato;
- regolarita degli scambi;
- presenza di buchi o candele piatte;
- spread/illiquidita quando inferibile.

Se un titolo ha liquidita non adeguata:

- puo rimanere nell'universo;
- puo essere mostrato come escluso;
- non deve essere comprato automaticamente;
- deve riportare chiaramente il motivo.

## Trigger Di Ingresso

I trigger di ingresso devono essere precisi e distinguere gli scenari:

- Breakout: ingresso su chiusura sopra resistenza con volumi in recupero o sopra media.
- Pullback su supporto: ingresso possibile solo su tenuta/rimbalzo del supporto, stop sotto supporto e news non negative.

Quando un trigger scatta, il sistema deve indicare la condizione esatta scattata.

Esempio non sufficiente:

- "trigger scattato: chiusura sopra resistenza oppure tenuta supporto"

Esempio corretto:

- "trigger scattato per scenario PULLBACK_SUPPORT: prezzo sopra supporto 3,782, supporto tenuto, volume 1,49x MA10, news non negative"

Per i trigger a doppio scenario, il sistema deve salvare e mostrare separatamente:

- scenario breakout;
- scenario pullback/supporto.

Non basta salvare una frase unica con `oppure`, perche quando il trigger scatta bisogna sapere quale ramo si e verificato.

Ogni scenario deve avere:

- livello trigger;
- livello supporto/stop;
- condizione volume;
- condizione news;
- invalidazione;
- stato: waiting, near_trigger, met, invalidated, executed.

L'agente puo decidere liberamente se comprare quando un supporto regge, ma deve verificare almeno:

- tenuta/rimbalzo del supporto;
- stop definito sotto supporto;
- volume non debole o in recupero;
- assenza di news negative;
- liquidita ok;
- coerenza con esposizione e cash del portafoglio.

## Trigger Di Uscita

Per ogni titolo in portafoglio devono esistere condizioni di uscita/riduzione/mantenimento:

- stop operativo;
- supporto chiave;
- take profit o resistenza;
- trailing stop o spostamento stop a break-even quando opportuno;
- riduzione parziale se il prezzo si avvicina a resistenza con momentum debole;
- uscita se news negative o breakdown tecnico.

L'analisi dei titoli in portafoglio deve sempre considerare:

- prezzo di ingresso;
- importo investito;
- quantita virtuale;
- valore attuale;
- P/L assoluto;
- P/L percentuale;
- variazione giornaliera;
- rischio rispetto a stop e target.

## Autonomia Operativa

La modalita di autonomia deve essere configurabile da GUI.

Modalita previste:

- Conferma sempre: ogni acquisto, incremento, riduzione, vendita o ribilanciamento resta pending finche l'utente non conferma.
- Protezione automatica: l'agente puo ridurre o vendere automaticamente su rischio confermato; nuovi ingressi e incrementi richiedono conferma.
- Autonomia completa: l'agente puo comprare, incrementare, ridurre, vendere e ribilanciare automaticamente il portafoglio virtuale.

In modalita autonomia completa, se un trigger valido scatta e le condizioni di rischio/news/liquidita sono coerenti, l'agente puo agire sul portafoglio virtuale senza conferma utente.

Ogni azione autonoma deve:

- essere salvata;
- essere loggata;
- essere notificata su Telegram se le impostazioni lo prevedono;
- spiegare motivo, dati usati e condizione scattata.

## Portafoglio

La dashboard portafoglio deve mostrare:

- capitale iniziale;
- cash disponibile;
- valore portafoglio;
- P/L totale;
- posizioni aperte;
- P/L per posizione;
- variazione giornaliera per posizione;
- quantita;
- prezzo ingresso;
- prezzo corrente;
- grafico.

Evitare duplicazioni inutili tra tabella portafoglio e box operativi. Se un titolo in portafoglio appare anche nello scanner, deve essere chiarito che non e un nuovo candidato di ingresso, ma una posizione aperta da gestire.

I box sotto "Condizioni di uscita" non sono duplicati della tabella portafoglio: devono servire solo a decidere cosa fare sulle posizioni aperte.

Devono quindi enfatizzare:

- stop;
- target/take profit;
- distanza da stop;
- distanza da target;
- rischio operativo;
- suggerimento operativo: mantieni, riduci, vendi, incrementa solo se motivato.

La tabella portafoglio invece deve restare sintetica e contabile:

- investito;
- valore attuale;
- P/L;
- prezzo di ingresso;
- prezzo corrente;
- variazione giornaliera.

## Performance

Il rendimento del portafoglio deve essere tracciato nel tempo.

Mostrare:

- valore ultimo giorno disponibile;
- P/L ultimo giorno disponibile;
- rendimento giornaliero calcolato solo sui giorni disponibili;
- range storico solo se ci sono abbastanza giorni.

Non mostrare grafici con piu punti identici nello stesso giorno spacciandoli per serie giornaliera.

Sabato e domenica vanno esclusi dalle valutazioni giornaliere e dalla schedulazione.

Se c'e un solo giorno disponibile, mostrare solo il dato giornaliero e non una linea piatta con date duplicate.

I valori monetari in GUI devono usare il simbolo `€` a destra del numero, non la scritta `EUR` davanti.

P/L negativo deve essere rosso sia nel valore grande sia nel badge percentuale; P/L positivo verde.

## Scheduling

Il monitor automatico gira ogni 30 minuti solo nei giorni e orari utili.

Regole:

- giorni: lunedi-venerdi;
- fascia operativa: 10:00-20:00;
- dopo le 21:00 non schedulare altri run;
- sabato e domenica nessun run automatico;
- prossimo run deve essere calcolato saltando weekend e fuori orario.

La GUI deve indicare in modo comprensibile:

- ultimo ciclo agente completato;
- prossimo run previsto;
- se il run e in corso, terminato, fallito o stale;
- cosa significa eventuale stato stale.

`running stale` significa che un run risulta ancora marcato come in corso ma ha superato il tempo massimo atteso. La GUI deve spiegarlo in linguaggio utente e offrire una recovery esplicita, per esempio:

- "Run precedente probabilmente rimasto appeso";
- "Puoi pulire lo stato e rilanciare";
- "Ultimo log disponibile: ...".

Non mostrare `running stale` senza spiegazione.

## Logging

I log sono requisito fondamentale.

Ogni log deve avere timestamp.

Durante un run manuale o schedulato deve essere chiarissimo:

- tipo run: manuale, schedulato, analisi profonda, Telegram, Playwright;
- mercato in analisi;
- ticker in analisi;
- fase corrente;
- tool chiamato;
- motivo della selezione del ticker;
- output o decisione sintetica;
- errore e recovery eventuale.

Esempio richiesto:

```text
2026-07-25 10:31:12 [run] START manuale scope=FTSE_MIB,MateriePrime,ETF,watchlist
2026-07-25 10:31:13 [scanner] FTSE_MIB 1/40 A2A.MI score=8 liquidita=ok motivo=MACD sopra signal; resistenza vicina
2026-07-25 10:31:14 [decision] A2A.MI approfondimento Playwright=SI motivo=titolo in portafoglio + trigger vicino
2026-07-25 10:31:20 [playwright] A2A.MI grafici inviati a ChatGPT
2026-07-25 10:32:10 [decision] A2A.MI azione=MANTIENI motivo=supporto regge, nessun segnale uscita
```

I log vuoti o senza contesto non sono accettabili.

La GUI deve avere:

- vista log aggiornata;
- pulsante aggiorna log;
- pulsante pulisci log;
- stato processo con progressione leggibile durante run lunghi.

Il log deve essere scritto anche per run manuali lanciati da GUI, non solo per schedulati.

Quando parte un run manuale deve comparire subito:

- timestamp;
- scope completo: FTSE MIB, Materie prime, ETF, watchlist, trigger monitorati;
- numero titoli per mercato;
- modalita: SDK, ChatGPT Web, analisi profonda;
- modello se usa API;
- policy autonomia;
- policy Telegram.

Se dopo 30 secondi non c'e alcun nuovo log, e un problema da correggere: l'utente deve sempre capire che cosa sta facendo il processo.

I log devono indicare per ogni titolo se:

- e solo scansionato localmente;
- e escluso per liquidita;
- e escluso per score;
- e candidato operativo;
- e in portafoglio;
- viene approfondito con Playwright;
- viene ignorato e perche.

## Telegram

Telegram deve essere sia canale di notifica sia interfaccia conversazionale.

Requisiti:

- un solo processo bridge attivo per evitare conflitti `getUpdates`;
- risposte rapide ai messaggi utente;
- se l'agente impiega tempo, inviare conferma immediata;
- non inviare prompt/debug interni all'utente;
- messaggi leggibili, compatti, senza muri di testo;
- Markdown semplice, no tabelle complesse;
- invio grafici quando l'utente chiede grafico.

Modalita notifiche configurabili:

- invia sempre;
- solo variazioni;
- solo alert;
- disattivato.

I messaggi monitoraggio/performance devono essere sintetici e leggibili, con sezioni:

- portafoglio;
- posizioni principali;
- trigger scattati;
- trigger in attesa piu vicini;
- azioni applicate o proposte;
- nota finale.

Il bridge Telegram deve filtrare output tecnico/debug:

- non inviare prompt interni;
- non inviare stack trace completi;
- non inviare log raw;
- non inviare messaggi duplicati.

In caso di errore API/Playwright/backend, Telegram deve inviare una sintesi breve:

- cosa e fallito;
- se il portafoglio e stato modificato o no;
- cosa puo fare l'utente.

Il messaggio deve usare righe brevi. Se il contenuto e lungo, inviare piu messaggi o rimandare alla GUI/log.

## GUI React

La GUI deve essere la vista operativa principale.

Tab principali:

- Dashboard;
- FTSE MIB;
- Materie prime;
- ETF;
- Chat;
- Watchlist;
- Azioni;
- Run log;
- Controlli.

La UI deve evitare informazioni ambigue o inutili. Se un dato non aiuta a decidere, va rimosso o trasformato in informazione operativa.

Esempi:

- "9 titoli" da solo non basta: spiegare cosa sono, dove si trovano e perche contano.
- "ultimo ticker analizzato" ha poco valore se non dice che analisi e stata fatta e dove vedere output.
- "candidati" deve distinguere tra nuovi candidati e titoli gia in portafoglio.

La dashboard deve privilegiare informazioni operative, non diagnostica tecnica fine a se stessa.

Da evitare in alto se non spiegato:

- ultimo ticker analizzato;
- numero generico di titoli analizzati;
- badge tecnici senza spiegazione;
- errori vecchi persistenti come se fossero stato corrente.

Se mostrati, devono diventare informativi:

- `Ultimo file analisi AI`: indicare che e un file/grafico analizzato via Playwright e dove vederlo;
- `Copertura analisi`: indicare che sono file tecnici pronti per grafici/trigger/approfondimenti;
- `Portafoglio e trigger`: indicare quanti titoli sono in posizione e quanti trigger operativi sono da rivalutare.

La tab ETF deve mostrare `ROBO.MI` appena presente nella lista configurata, anche prima di uno scan.

Il tab `Materie prime` deve stare tra `FTSE MIB` e `Chat`.

Il tab `Watchlist` deve stare dopo `Chat`.

La pagina `Run log` deve essere utile per capire il flusso, non solo per vedere testo tecnico.

## Grafici

I grafici devono mostrare:

- prezzo;
- variazione giornaliera;
- volumi con barre verdi/rosse coerenti con le candele;
- trigger ingresso;
- supporto/stop;
- distanza dal trigger;
- RSI/Stocastico/Williams;
- MACD con istogramma;
- ADX e DI;
- vista "Tutti" con tutti i grafici disponibili.

Tooltip essenziale:

- data;
- close.

Evitare grafici piatti causati da dati mancanti o buchi di mercato. Se i dati sono insufficienti, indicarlo chiaramente invece di mostrare un grafico fuorviante.

## Watchlist

La watchlist manuale consente all'utente di aggiungere titoli anche se non filtrati dallo scanner.

Per ogni titolo in watchlist si deve poter definire:

- ticker;
- priorita;
- motivo;
- categoria/tag;
- condizione di ingresso.

L'agente deve poter proporre condizioni di ingresso via analisi tecnica e Playwright solo quando utile.

La watchlist deve essere inclusa nel monitor periodico.

Se l'utente scrive un ticker o una frase ambigua in chat/Telegram, l'agente deve cercare di risolvere il ticker:

- controllando portafoglio;
- condizioni monitorate;
- watchlist;
- FTSE MIB;
- Materie prime;
- ETF.

Esempio: se l'utente scrive `Amplifon`, l'agente deve risolvere `AMP.MI`; se scrive `ROBO`, deve risolvere `ROBO.MI` se presente nella lista ETF.

## Analisi Approfondita On Demand

L'utente deve poter avviare analisi approfondita:

- solo titoli in portafoglio;
- uno specifico ticker;
- watchlist;
- mercato specifico;
- intero scope.

Durante l'analisi la GUI deve mostrare un box stato processo con:

- fase corrente;
- ticker corrente;
- cosa sta facendo;
- log sintetico live;
- durata.

Alla fine deve restare disponibile un report con data e ora, piu dettagliato del messaggio Telegram.

Il report finale deve essere persistente e sempre consultabile in GUI.

Deve includere:

- data/ora inizio e fine;
- posizioni analizzate;
- per ogni posizione: prezzo ingresso, quantita, investito, prezzo corrente, P/L, stop, target, news, lettura grafico, decisione;
- eventuali azioni applicate, proposte o scartate;
- motivi per cui non e stata applicata alcuna azione.

Il messaggio Telegram puo essere una sintesi; la GUI deve contenere il report esteso.

## Branch LangGraph

Esiste un branch dedicato alla revisione architetturale LangGraph.

Obiettivo del branch:

- rendere il flusso predictable;
- modellare nodi e stati;
- separare scanner, decisioni, Playwright, autonomia, Telegram e persistence;
- migliorare log e tracciabilita.

Il README e la documentazione devono mostrare:

- grafo logico;
- sequenza dei nodi;
- condizioni di transizione;
- punti in cui si usa OpenAI SDK;
- punti in cui si usa Playwright.

## Requisiti Ricorrenti Da Non Perdere

Questi punti sono emersi piu volte durante lo sviluppo e devono essere considerati regressioni se ricompaiono.

### Verifica Prima Del Rilascio

- Prima di dichiarare una funzionalita pronta, testare sia il codice importato sia il processo live usato dalla GUI.
- Test minimo backend live: chiamare gli endpoint reali su `http://127.0.0.1:8000`, non solo `TestClient`.
- Test minimo frontend: verificare che tab, pulsanti e messaggi leggano davvero i dati aggiornati dal backend live.
- Se un endpoint funziona con `TestClient` ma non dal browser, il backend live e probabilmente vecchio e va riavviato prima di chiudere il task.
- Ogni modifica a contratti API usati da React deve essere verificata con risposta reale JSON e build frontend.

### Stato E Run

- Un run manuale deve considerare tutto lo scope attivo: FTSE MIB, Materie prime, ETF, watchlist e trigger monitorati.
- Il pulsante `Esegui ora` deve produrre subito log visibili, anche se il lavoro richiede minuti.
- Lo stato `running` deve diventare `ok`, `error` o `stale` in modo coerente a fine run.
- Se il sistema mostra `stale`, deve spiegare che il run precedente sembra rimasto appeso e offrire una pulizia/ripartenza.
- Il prossimo scheduled run deve rispettare giorni feriali e fascia 10:00-20:00; sabato, domenica e sera tardi sono esclusi.

### Candidati, Monitorati E Portafoglio

- `Monitorati` significa titoli con condizioni/trigger salvati da rivalutare.
- `Candidati operativi` significa nuovi titoli liquidi e non gia in portafoglio, selezionati dallo scanner.
- Un titolo gia in portafoglio non deve comparire come nuovo candidato di acquisto senza una spiegazione esplicita: va trattato come posizione da mantenere, incrementare, ridurre o vendere.
- I box duplicati per lo stesso ticker devono essere evitati o separati per ruolo: ingresso, uscita, posizione, watchlist.
- Se un titolo ha liquidita bassa, puo essere mostrato come universo o escluso, ma non deve entrare nei candidati operativi automatici.
- Lo score deve essere presente per i titoli scansionati; se manca, la UI deve spiegare se il titolo non e stato scansionato, non ha dati o e fuori scope.

### Playwright E News

- Playwright deve essere selettivo: portafoglio, trigger scattati, trigger molto vicini, nuovi buy candidate reali, richieste esplicite utente.
- Non usare Playwright su tutti i titoli di `MateriePrime.xlsx` o su tutto FTSE MIB.
- News live devono passare da Playwright/ChatGPT quando possibile, non da API OpenAI, per ridurre token API.
- Ogni chiamata Playwright deve essere giustificata nei log con motivo operativo.
- Non fare doppia analisi grafico/news per lo stesso ticker e scopo nello stesso run.

### Telegram

- Deve esistere un solo bridge Telegram attivo; errori 409 `getUpdates` indicano piu istanze contemporanee.
- Telegram deve rispondere subito almeno con presa in carico.
- Telegram non deve inviare prompt interni, stack trace, log raw o testo di debug.
- Se l'utente chiede un grafico, il bot deve inviare il grafico, non solo descriverlo.
- I messaggi devono indicare con precisione quale trigger e scattato, non riportare condizioni generiche con `oppure`.
- I riepiloghi automatici devono essere compatti e rimandare alla GUI/log per dettagli lunghi.

### GUI

- La dashboard deve mostrare informazioni operative, non dati tecnici privi di contesto.
- Evitare campi come `ultimo ticker analizzato` o `9 titoli` se non spiegano cosa e stato analizzato e dove vedere l'output.
- La tab ETF deve mostrare `ROBO.MI` appena configurato, anche prima dello scan.
- Le tab devono restare nell'ordine: Dashboard, FTSE MIB, Materie prime, ETF, Chat, Watchlist, Azioni, Run log, Controlli.
- Gli endpoint di mercato devono avere un contratto coerente con la GUI: ogni lista operativa deve esporre `items`, `count` e `active_count` oltre a eventuali alias legacy (`etfs`, `commodities`, `tickers`). Un titolo configurato deve essere visibile anche prima dello scan.
- I valori monetari devono usare il simbolo euro a destra del numero.
- P/L negativo sempre rosso; P/L positivo sempre verde.
- Nei grafici il tooltip deve essere compatto: data e close.
- Prezzo e volumi possono stare insieme nel grafico prezzo; i colori dei volumi devono essere coerenti con le candele.
- Nel grafico devono essere visibili trigger, supporto/stop e variazione giornaliera.

### Documentazione E Manutenibilita

- `REQUIREMENTS.md` deve essere aggiornato quando emerge un requisito nuovo o una correzione ricorrente.
- `README.md` deve spiegare mercati, architettura, flusso, uso di Playwright, OpenAI SDK, Telegram, React backend/frontend e scheduler.
- Prima di lavorare su modifiche significative, rileggere questo file.

## Regole Di Qualita

Prima di considerare completata una modifica:

- verificare che non ci siano duplicazioni UI fuorvianti;
- verificare che i log spieghino cosa succede;
- verificare che Telegram non invii messaggi debug;
- verificare che i titoli illiquidi non siano candidati operativi;
- verificare che Playwright non venga chiamato su interi universi;
- verificare che weekend e fuori orario siano gestiti;
- verificare che il portafoglio virtuale sia coerente dopo ogni azione.

## Domande Aperte Da Rivalutare Periodicamente

- Quale soglia minima di liquidita usare per ogni mercato?
- Quale score minimo rende un titolo "nuovo candidato operativo"?
- Quanto cash minimo mantenere?
- Quanto capitale massimo allocare per singola posizione?
- Quando un supporto diventa opportunita di ingresso invece che rischio?
- Quando ridurre parzialmente una posizione in gain vicino alla resistenza?
- Quali notifiche Telegram sono davvero utili e quali diventano rumore?
