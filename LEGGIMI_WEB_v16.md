# MoonDownloader v16 — GUI su WebView2

La v15 era Tkinter, e Tkinter è il muro: **niente antialiasing, niente canale
alfa**. Ogni cerchio, arco e angolo arrotondato usciva a gradini, e i bagliori
erano anelli opachi mescolati contro uno sfondo noto. Sul tuo 2560×1440 il testo
misurava **8 px di inchiostro** e il 38% della finestra restava vuoto.

La v16 sposta la GUI dentro **Edge WebView2** — lo stesso motore di Chromium, già
installato su Windows 10/11. Compositing GPU: gradienti, blur, ombre, transizioni,
antialiasing subpixel. E la tipografia scala con la finestra: `clamp()` porta la
base da 16 px a 1280 di larghezza fino a 19 px sul tuo monitor, invece di restare
inchiodata.

Il motore async **non è stato riscritto**: `_run`, `_browser_worker`, `_do_dl`,
`download_file`, `Telemetry`, `ProxyPool` sono quelli della v14.8, byte per byte.

---

## Avvio

```
avvia.bat
```

Non installa più pywebview: apre un server su `127.0.0.1` (porta scelta dal
kernel) e lancia **Edge** — o Chrome, quello che trova — con `--app=`, cioè una
finestra senza schede e senza barra indirizzi. Stesso Chromium, zero dipendenze
native, nessun backend da indovinare.

### Perché non pywebview

Perché sul tuo PC è ripiegato su **MSHTML**, il motore di IE11: slider nativi
blu con le tacche, wordmark in serif, tutto srotolato in una colonna. pywebview
su Windows sceglie il backend a runtime e, se il ponte .NET verso WebView2 non si
carica (manca `pythonnet`, manca il runtime Evergreen), **passa a Trident in
silenzio** — nessun errore, solo una pagina del 2013. Dentro Trident `grid`,
`clamp()`, `color-mix()`, `system-ui` e `backdrop-filter` non esistono.

Ora la GUI se ne accorge da sola: se il motore non supporta `grid` e `color-mix`
mostra un cartello invece di disegnarsi male.

Restano due modi alternativi, se ti servono:

```
python moon_bridge.py --pywebview    # finestra pywebview, backend forzato a edgechromium
python moon_bridge.py --browser      # browser predefinito
python moon_bridge.py --serve        # solo server, stampa l'URL
```

Vuoi ancora la vecchia GUI Tk? `avvia_tk.bat` → lancia `gen_1.py`, intatto.

Solo la GUI, senza Python, per guardarla: apri `web/index.html` in Chrome/Edge —
parte in modalità **demo** con un motore finto (chip `DEMO` in basso a destra).

### Il server locale, in breve

Ascolta **solo** su `127.0.0.1`, e ogni chiamata `/api/` deve portare il token
generato a ogni avvio: senza token, 403. L'API avvia download e legge percorsi,
quindi non è una formalità. Il processo si spegne da solo dopo 12 secondi senza
richieste: la pagina fa polling ogni 80 ms, quindi "nessuna richiesta" significa
"finestra chiusa", e l'app esce invece di restare un processo orfano.

---

## Come è fatto

```
┌──────────────────────────── moon_bridge.py ────────────────────────────┐
│  server HTTP su 127.0.0.1 + token per avvio                            │
│  lancia Edge/Chrome con --app=  (finestra senza schede)                │
│  Api: hello · snapshot · start · stop · clear_files                    │
│       browse_folder · browse_chrome · load_txt · settings_save         │
└───────────────┬─────────────────────────────────┬──────────────────────┘
                │ POST /api/<name>                │ chiamate dirette
        ┌───────▼────────┐               ┌────────▼─────────┐
        │  web/app.js    │               │ moon_engine.py   │
        │  render a 12Hz │◄──snapshot()──│ Engine (headless)│
        │  index + css   │               │ = motore v14.8   │
        └────────────────┘               └──────────────────┘
```

I dialoghi nativi (cartella, `chrome.exe`, `.txt`) girano in un **processo
figlio** con `tkinter.filedialog`: un dialogo vuole il mainloop del thread che lo
ha creato, e l'handler HTTP sta su un thread del pool — 200 ms di sottoprocesso
sono la risposta noiosa e affidabile.

**Modello pull, non push.** La pagina chiede `snapshot(cursor)` ~12 volte al
secondo. Spingere da Python significherebbe serializzare una stringa JS per tick
e toccare la WebView da un thread che non è il suo; tirando, ogni scrittura nel
DOM resta sulla timeline della pagina e uno snapshot in ritardo è un frame perso,
non uno stallo.

**Il log ha un cursore.** `Engine` tiene un ring di 6000 righe più un contatore
monotono; la pagina chiede "tutto dopo N". Se resta indietro oltre il ring riceve
la riga più vecchia ancora disponibile, non un buco che non potrebbe rilevare.

**Le righe file leggono i `FileRecord` vivi.** `download_file` scrive
`rec.done_bytes` e `rec.live_mbs` ~4 volte al secondo su una finestra **sua**
(`pub_win`), separata da quella dello stall detector: condividerla avrebbe
mangiato la storia a 60s da cui dipende il kill.

**Tutto quello che arriva dalla pagina è input non fidato.** `Engine.apply_cfg()`
converte e blocca ogni numero nei suoi limiti (`workers` 2–32, `dl_streams` 2–48,
`retries` 0–5, `dn_pages` 1–8, `dn_captcha` 30–600) prima che tocchi un semaforo.

---

## File

| file | ruolo |
|---|---|
| `moon_bridge.py` | host della finestra, dialoghi OS, `settings.json` |
| `moon_engine.py` | **generato** — motore v14.8 senza GUI + API JSON |
| `apply_web_v16.py` | il generatore: legge `gen_1.py` pristine, scrive `moon_engine.py` |
| `web/index.html` | struttura |
| `web/styles.css` | tutto il lato estetico |
| `web/app.js` | render, bridge, e un motore finto per la preview |
| `web/assets/` | `mark.png`, `backdrop.png`, `window.png` (Higgsfield) |
| `gen_1.py` | la GUI Tk, sorgente del motore \u2014 unica modifica v16: il lancio pigro di Chrome |
| `gen_cli.py` | la CLI headless, stesso motore e stesso lancio pigro |
| `test_no_chrome.py` | verifica che fuckingfast non apra nessun browser |
| `prep_assets.py` | rigenera gli asset dai render grezzi |
| `shots.py` | render di verifica in Chromium headless |
| `integration_web.py` | test end-to-end GUI ↔ bridge ↔ Engine |

`apply_web_v16.py` **legge** `gen_1.py`, non lo scrive: la GUI Tk continua a
funzionare. `moon_engine.py` è generato — non modificarlo a mano, rigeneralo.

---

## Chrome si apre solo se serve

Fino alla v15 ogni front-end chiamava `open_browser()` **una volta per worker**
all'inizio del run, prima di guardare un solo URL. Risultato: incollavi solo link
fuckingfast — che sono HTTP puro, ~0,25 s a link, zero browser — e ti si apriva
comunque una finestra di Chrome, più il driver Playwright (~1,5 s di avvio). La
finestra era per forza visibile: Turnstile non rilascia il token a un Chrome
headless, quindi datanodes gira con `headless=False` e ogni lancio si vede.

Ora la decisione sta in un punto solo, `moon_extract.BrowserGate`:

- `get()` è l'unica cosa che lancia, e la chiama **solo** il ramo datanodes
- niente link datanodes → niente browser, niente driver, niente processo node
- più worker che chiedono insieme collassano su **una sola** istanza condivisa
  (che è quello che serve al profilo con il `cf_clearance`)
- `aclose()` chiude nell'ordine giusto: prima Chrome, poi il driver

Vale per tutti e tre i front-end: GUI WebView, GUI Tk (`avvia_tk.bat`) e CLI.

```
python test_no_chrome.py
```

Verifica motore e CLI, e controlla i sorgenti di tutti e tre: nessuna chiamata
diretta a `open_browser(`. Non serve né browser né display né Playwright
installato — gira anche in CI a ogni push.

---

## Le funzioni, una per una

**LINK** — textarea con i link **colorati per host mentre scrivi** (overlay
`<pre>` sotto una textarea trasparente, scroll sincronizzato: colori veri senza
perdere selezione, undo e IME). Contatore istantaneo, barra di mix
`datanodes / fuckingfast / altri`.

**DESTINAZIONE** — cartella + dialogo nativo, e `Download` / `Solo link`
(`mode="links"` scrive `output_links.txt` senza scaricare).

**COMUNI** — `Extractors` 2–32, `DL streams` 2–48, `Retries` 0–5. Il valore
consigliato ha un **tick sulla traccia**, non solo una didascalia.

**DATANODES.TO** — `Pages` 1–8, `Captcha` 30–600s, path di Chrome, API key.
Passano da `moon_extract.configure()` a ogni Avvia: niente più `setx` e riavvio.
Il chip in alto a destra dice cosa sta usando: `auto` / `chrome` / `api key`.

**FUCKINGFAST.CO** — nessuna manopola, ed è scritto: HTTP puro, non apre Chrome,
non ha captcha. Mostra solo se `curl_cffi` c'è.

**Le quattro card** — `VELOCITA` (finestra mobile 3s + sparkline SVG con glow),
`COMPLETATI`, `SCARICATO` (`ok / ko / kill`), `ETA` (stima sui byte, non sui
file). `PIPELINE` tiene estrazione e download separati, perché girano insieme.

**FILE ATTIVI** — una riga per file: anello di progresso SVG, stato
(`in coda / estrazione / download / salvato / errore / riavvio`), percentuale,
velocità istantanea, barra sul piede. `content-visibility: auto` così una lista
da 400 righe non costa nulla quando è fuori vista.

**LOG** — le stesse righe di sempre, stessi tag e colori, tetto 2000 righe.

**Footer** — chip `PROXY n` quando `proxies.txt` viene caricato, chip
`.TMP DA RIPRENDERE` quando restano tronconi.

Le impostazioni (e i link incollati) si salvano in `settings.json` accanto allo
script, con scrittura atomica: un crash a metà salvataggio non lascia un file
troncato.

---

## Ultima passata — cosa è cambiato

**Il badge diceva 40 con 124 file scaricati.** Era il cap delle righe tenute in
memoria (`_ROWS_KEEP`), non un conteggio: sopra quella soglia il motore ritirava
le righe già finite e il badge fotografava la lista, non la realtà. Ora il badge
conta **solo i trasferimenti in volo** (download, estrazione, riavvio, coda) e il
cap è salito a 120. Il totale vero sta dove deve stare: nella card COMPLETATI.

**Le righe attive stanno in cima.** Con 124 file la coda dei "salvato" sepelliva i
quattro download veri. Ora l'ordine è: download → estrazione → riavvio → coda →
finiti (i più recenti per primi), e la coda dei finiti è leggermente attenuata.
L'ordinamento usa la proprietà CSS `order`, quindi nessun nodo viene spostato nel
DOM: zero reflow per riordinare 120 righe.

**La tab LOG mostrava la stessa cosa di FILE ATTIVI.** Stessa trappola di
`.empty`: `.files { display: grid }` batte la regola UA `[hidden]`, quindi la
lista restava dipinta sopra il log. Ora `.files[hidden]` e `.log[hidden]` sono
espliciti, e il test end-to-end lo verifica con `getComputedStyle`.

**Default nuovi:** `Captcha 30s`, `Pages 8`. Sono nel motore (`Engine._cfg`) e nel
markup, quindi valgono anche al primo avvio senza `settings.json`.

**Bottone lingua, EN di default.** EN|IT in alto a destra, scelta salvata in
`settings.json`. Il motore non parla più italiano nelle frasi di stato: manda
numeri e un nome di fase (`idle` / `extracting` / `downloading` / `done`) e la
pagina costruisce la frase nella lingua scelta. Cambiare lingua rietichetta anche
quello che è già a schermo, righe comprese.

**Elementi reattivi aggiunti:**

- contatori animati (interpolazione in `requestAnimationFrame`) su velocità,
  completati e GB: si vede *come* si muove il numero, non solo dove è arrivato
- riflettore che segue il cursore sulle card — due custom property per
  `pointermove`, nessun layout
- entrata a scalare delle card all'avvio (`--d` per ritardo)
- barra di progresso globale sotto l'header, con luccichio solo mentre qualcosa
  si muove davvero (una barra ferma che brilla mentre?)
- riga che entra da sinistra, e **lampo verde** quando un file finisce
- striscia di stato che pulsa sui trasferimenti attivi
- sparkline con tratto sfumato blu→teal e testa luminosa
- pressione tattile sui bottoni, anelli di focus visibili, uscita animata dei toast
- `prefers-reduced-motion` rispettato: tutto si spegne

---

## Verifica

```
python integration_http.py     # browser → HTTP loopback → Engine (il percorso di avvia.bat)
python integration_web.py      # bridge pywebview → Engine (il percorso --pywebview)
python shots.py out/           # render a 2554x1400 e 1440x900 + audit di overflow
python moon_engine.py          # motore headless: stampa uno snapshot e esce
```

`integration_http.py` è quello che conta: fa partire il server vero, apre la
pagina vera in Chromium, verifica che **il token gate risponda 403** a una
chiamata senza credenziale, poi avvia un run e controlla che velocità, righe,
byte, fase, anelli di progresso e log arrivino dal motore; infine premette STOP e
verifica che il motore si fermi.

Ultima esecuzione: `token 403 ok · 8 righe · 25.4 MB/s · 2 completati · anello 32% ·
log tab isolato · lingua en→it rietichetta · badge 6 = 6 righe attive · stop → done`.
