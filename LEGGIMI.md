# MoonDownloader v14.8 — cosa è cambiato e come si configura

> Documento storico della linea 14.x (motore ed estrazione, validi anche adesso).
> Per la v16 — GUI su WebView2, lancio pigro di Chrome, verifica — leggi
> **[LEGGIMI_WEB_v16.md](LEGGIMI_WEB_v16.md)**.

## v14.8 — impostazioni GUI divise per metodo

Il pannello SETTINGS descriveva un'architettura che non esiste più: un solo
slider "Browsers" per due metodi che ormai non condividono niente. fuckingfast
non apre nessun browser (è HTTP puro via curl_cffi), datanodes è Chrome +
Turnstile. Ora il pannello è diviso in tre:

**SETTINGS · COMMON** — valgono per entrambi
- `Extractors` (2-32, rec. 16) — quante estrazioni in parallelo
- `DL streams` (2-48, **rec. 8**, prima era 48)
- `Retries` (0-5)

**FUCKINGFAST · HTTP, NIENTE BROWSER** — nessuna impostazione, solo lo stato
- mostra se `curl_cffi` è attivo (verde) o mancante (rosso) — se manca, ogni
  link prende 403 e adesso lo vedi subito invece di scoprirlo dai log

**DATANODES · CHROME + TURNSTILE**
- `Pages` (1-8, rec. 3) — tab in contemporanea sulla stessa finestra/identità
- `Captcha s` (30-600) — quanto attende la spunta manuale
- `Chrome` — percorso a `chrome.exe` con selettore file
- `API key` — mascherata

**Non serve più `setx` per niente di tutto questo.** Prima ogni valore veniva
letto una sola volta all'avvio del processo, quindi l'unico modo di cambiarlo
era variabile d'ambiente + riavvio. Ora la GUI chiama `moon_extract.configure()`
subito prima di partire: quello che vedi sullo schermo è quello che gira. Le
variabili d'ambiente restano valide come default se preferisci usarle.

Il banner di avvio ora dice anche cosa sta usando per ciascun host:

```
▶  85 links  ·  16 extractors  ·  8 streams  ·  3 retries  ·  v14.8
   fuckingfast: HTTP diretto   ·   datanodes: 3 pages, captcha 240s
   chrome: C:\Program Files\Google\Chrome\Application\chrome.exe
```

### Sul numero di stream: correzione

Nel tuo screenshot a 62.2 MB/s aggregati i singoli file andavano a 8-13 MB/s con
**5 download attivi**. Nel log precedente a 48 stream: 31.9 MB/s aggregati e 1.9
MB/s per file con ~17 attivi. Quindi il tetto NON è un limite per-connessione
del tier free come avevo detto — **è la tua banda totale**, divisa per il numero
di stream. Meno stream = più banda per file e, in quel confronto, anche
aggregato più alto. Per questo il consiglio è scesa da 48 a 8.

---

## v14.7 — le finestre separate hanno peggiorato Cloudflare: tornato a una sola

La v14.6 apriva 4 finestre separate (contesti isolati) per far girare più
estrazioni in parallelo. Sulla carta doveva aiutare; dal vivo ha fatto
l'opposto: **Cloudflare ha iniziato a bloccare la verifica** ("Verification
failed" nel widget, la stessa schermata rossa del problema originale con il
Chromium di Playwright) e la sessione risultava più lenta, non più veloce —
esattamente quello che hai segnalato tu.

La causa: 4 contesti separati = 4 identità/cookie diverse che colpiscono
Cloudflare dallo stesso IP quasi in contemporanea. Per un sistema anti-bot,
"più sessioni diverse dalla stessa rete in pochi secondi" è ESATTAMENTE il
pattern di un bot-farm — molto più sospetto di una sola finestra condivisa
che naviga pagina dopo pagina con cookie coerenti (quello che facevano v14.4
e v14.5, e che per te funzionava).

**Tornato a UNA sola finestra/contesto condiviso**, esattamente come in
v14.4/14.5 — stessi cookie, stessa identità per ogni file. `MOON_DN_LANES`
adesso significa "quante pagine puoi tenere aperte in contemporanea SU quella
finestra" (default 3), non più "quante finestre separate aprire". Verificato
dal vivo: 5 estrazioni lanciate in parallelo, tutte sullo stesso identico
oggetto di contesto — un solo browsing context aperto in totale, mai 5.

**Aggiunta anche una via d'uscita rapida per quando Cloudflare fallisce
comunque.** Prima, se il widget Turnstile andava in "Verification failed" (un
guasto del widget stesso, non un problema di click), il tool continuava a
provare a cliccarlo per il budget intero — fino a 45s di tentativi automatici
+ 240s di attesa manuale = quasi 5 minuti PER FILE bloccato così. Ora il tool
riconosce subito quel testo sullo schermo, ricarica la pagina UNA volta (a
volte basta per far ripartire un widget Turnstile pulito), e se fallisce
ancora passa oltre subito invece di restare fermo. Verificato dal vivo: da
~45 secondi di attesa inutile a 0.01 secondi di rilevamento.

Restano dal v14.6, invariati: il rilancio automatico se il Chrome condiviso
crasha (`is_connected()` controllato ad ogni chiamata), e la chiusura più
rapida dei popup pubblicitari (1s invece di 3s).

### Variabile

| Variabile | Default | Cosa fa |
|---|---|---|
| `MOON_DN_LANES` | `3` | Pagine in contemporanea SULLA STESSA finestra/identità (1-8) |

Non impostate `MOON_DN_LANES` a un numero enorme pensando che apra più
finestre: non lo fa più, e non dovrebbe — è quello che ha rotto Cloudflare in
v14.6. Serve solo a limitare quante pagine pesanti (Turnstile + pubblicità)
restano aperte insieme sulla finestra condivisa, per lo stesso motivo per cui
prima il browser crashava dopo troppi file di fila.

---

## v14.6 — il crash e il rallentamento generale (letto dal tuo log)

Dal tuo `moontech_...json` da 85 file: aggregato **31.9 MB/s** (42.5GB in 22m14s),
ma per-connessione una media di **1.9 MB/s** — e con 16 browser, quasi tutti
tab nella STESSA finestra Chrome condivisa. Due bug reali, entrambi ora corretti:

**1. Il browser condiviso moriva dopo ~80 estrazioni sequenziali.**
Nel tuo log, righe 256 e 259 (su 268 totali — quasi alla fine):
`Browser.new_context: Target page, context or browser has been closed`.
La v14.4/14.5 apriva UNA finestra Chrome condivisa e ogni worker ci apriva
sopra una tab; con 16 worker che aprono/chiudono tab in sequenza, il processo
Chrome è morto per pressione di memoria — e siccome il codice non verificava
MAI se il browser condiviso fosse ancora vivo, ogni estrazione successiva
sarebbe rimasta rotta per il resto della sessione. Nel tuo caso è successo
troppo tardi per fare danni gravi (1 file su 85), ma su un batch più lungo
avrebbe fermato tutto.

**Ora `open_browser()` controlla `is_connected()` a ogni chiamata.** Se il
Chrome condiviso è morto, lo *rilancia* da solo — stesso profilo, nuova
istanza — e lo fa in modo trasparente anche per i worker che stanno ancora
usando il riferimento "vecchio" al browser (è il punto delicato: un worker
prende il suo `browser` una volta all'avvio e lo tiene per tutta la sessione;
la correzione doveva funzionare SOTTO quel riferimento stantio, non chiedendo
al chiamante di andarne a prendere uno nuovo). Testato dal vivo: killato il
processo Chrome a metà sessione, la chiamata successiva lo rileva
(`is_connected() == False`), lo rilancia con un PID nuovo, ricostruisce le
finestre, e l'estrazione riparte pulita.

**2. Troppe tab pesanti nella stessa finestra = tutto più lento.**
Ogni tab caricava Turnstile + pubblicità intere (obbligatorio per non far
scattare `detect-adblock`), e con 16 tab aperte contemporaneamente nella
STESSA finestra, Chrome mette in *background-throttling* tutte le tab tranne
quella in primo piano — i timer interni della pagina (lo scan Vue di ~6s, il
countdown di 15s) diventano lentissimi quando la tab non è quella attiva.
Risultato: pipeline di estrazione più lenta, codegli download restavano ad
aspettare un link da estrarre invece di scaricare.

**Ora c'è un pool fisso di finestre persistenti ("lane"), indipendente dal
numero di "Browsers" che imposti nella GUI.** Default 4, configurabile con
`MOON_DN_LANES`. La lane 0 è il profilo persistente su disco (i cookie
sopravvivono ai riavvii); le lane 1-3 sono finestre proprie, ognuna un
top-level window separato quando Chrome è reale — non tab nella stessa
finestra, quindi niente throttling incrociato. Ogni lane resta apertA per
tutta la sessione e viene RIUSATA file dopo file (niente più apri/chiudi
finestra per ogni singolo file) — verificato dal vivo: stessi oggetti di
contesto Python, stesso ID di memoria, su due file consecutivi.

Ho anche accorciato l'intervallo con cui il tool chiude i popup pubblicitari
(da 3s a 1s) — ogni secondo che un popup resta aperto è CPU/rete sprecata su
una finestra condivisa.

## Sulla velocità per-file: cos'è nostro e cos'è del server

**31.9 MB/s aggregati non sono male** per un tier gratuito — significa che in
media girava un ~16-17 di stream attivi in parallelo (aggregato ÷ media per
connessione). Il parallelismo funziona. Il tetto è altrove:

La UI di datanodes lo dice chiaro, guarda lo screenshot che hai mandato tu
stesso: **"Download speed: Standard" per Free, "Maximum" per Premium.** Non è
un bug del tool — è un limite per-connessione lato server sul tier gratuito.
La v14.6 con le lane più veloci ti farà girare la pipeline di ESTRAZIONE più
liscia (meno tempo perso ad aprire/chiudere finestre, niente crash a metà
sessione), il che alza l'aggregato riducendo i tempi morti — ma il tetto per
singola connessione (~1-3 MB/s che vedi nel tuo log) resta quello che
Datanodes decide di dare a un account free. L'unica leva che abbiamo è più
stream paralleli (il parametro "Streams" che hai già a 48), non il bypass del
tetto stesso.

## Variabili nuove in v14.6

| Variabile | Default | Cosa fa |
|---|---|---|
| `MOON_DN_LANES` | `4` | Finestre persistenti per l'estrazione datanodes (1-8) |

Con "Browsers" alto (es. 16) e `MOON_DN_LANES=4`, i worker in eccesso
semplicemente aspettano in coda una lane libera invece di aprire una nuova
finestra — niente più esplosione di tab.

---

# v14.4 — cosa è cambiato e come si configura (storico)

## fuckingfast.co — risolto, zero configurazione

Serve solo la dipendenza nuova:

```
pip install curl_cffi
```

Senza `curl_cffi` fuckingfast prende **403 su ogni link**. Cloudflare su quell'host
non guarda gli header: fa fingerprinting TLS, e il ClientHello di `aiohttp` viene
marcato come bot. `curl_cffi` replica quello di Chrome e passa.

Misurato su link FitGirl reali: **0.23–0.33s per link**, verificato con `HTTP 206`,
`Content-Range` corretto e magic bytes `Rar!`.

## datanodes.to — usa Chrome vero, non il Chromium di Playwright

Il tuo "Verification failed / Error Code 600010" **non** è colpa del click: il click
arriva. È Cloudflare che scarta il browser prima ancora di valutare la spunta.

Il Chromium bundled di Playwright viene beccato per tre motivi insieme:

1. Playwright lo avvia con gli switch di automazione → `navigator.webdriver` è `true`
2. non è una build Google-branded
3. il profilo è vuoto, nessuna cronologia, nessun `cf_clearance`

**v14.4 avvia il tuo Chrome vero e ci si attacca via CDP.** Nessuno switch di
automazione, build firmata, profilo persistente. Verificato: `navigator.webdriver`
passa da `true` a `false`.

### Cosa fa da solo

Trova Chrome da solo su Windows (`Program Files`, `Program Files (x86)`,
`LOCALAPPDATA`, e come ripiego Edge, che è Chromium branded e va bene uguale). Se sta
altrove:

```cmd
setx MOON_CHROME_PATH "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

Lo lancia con **solo** questi argomenti — niente di più, ogni flag in più è un segnale:

```
--remote-debugging-port=9222
--user-data-dir=%LOCALAPPDATA%\MoonDownloader\chrome-profile
--no-first-run --no-default-browser-check
```

Il profilo è **dedicato**, non il tuo. *Chrome rifiuta `--remote-debugging-port` su un
`--user-data-dir` che un altro Chrome ha già aperto, quindi puntarlo sul profilo di
tutti i giorni produce silenziosamente un browser a cui non ti puoi attaccare.*

### Il profilo persistente è il punto

Tutti i worker condividono **una** istanza Chrome e **un** contesto. Quindi un solo
`cf_clearance`: risolvi il captcha una volta e Cloudflare smette di ri-sfidarti sui
link successivi, invece di trattare ogni worker come un visitatore nuovo.

Il profilo sopravvive tra un avvio e l'altro. Più lo usi, meno ti sfida.

### Se il click automatico non passa

Il tool prova da solo per 45s (prima dentro l'iframe via Playwright, poi col mouse
reale sulle coordinate del widget, con movimento del puntatore prima — Turnstile pesa
l'entropia del mouse). Poi te lo passa:

```
>>> Spunta il captcha 'Verify you are human' nella finestra del browser (attendo 240s) <<<
```

Spunti tu, e grazie al profilo condiviso quella spunta vale anche per i link dopo.

## L'API di datanodes — solo premium

Ho testato la tua key: **valida** (`account/info` → `status:200`), ma:

```json
{"msg":"This function not allowed in API","status":403}
```

`file/direct_link` è **premium-only**. Il tuo account risulta `premium_expire: null`,
cioè free. Ho provato anche `file/download`, `file/dl`, `file/link`, `file/url`,
`file/get`, `file/direct` — tutti `Invalid operation`. Non esiste un endpoint free
che dia il link diretto.

Quindi: la key la lasci pure impostata (il tool la prova per prima e se un giorno
passi a premium diventa istantaneo, zero browser e zero captcha), ma **oggi la strada
è il browser**.

**Rigenera la key** — l'hai incollata in chiaro in chat.

## Variabili d'ambiente

| Variabile | Default | Cosa fa |
|---|---|---|
| `MOON_CHROME_PATH` | *(auto)* | Percorso di `chrome.exe` se non lo trova |
| `MOON_CHROME_PROFILE` | `%LOCALAPPDATA%\MoonDownloader\chrome-profile` | Profilo dedicato |
| `MOON_REAL_CHROME` | `1` | `0` = torna al Chromium di Playwright |
| `MOON_CDP_PORT` | `9222` | Porta di debug |
| `MOON_DN_API_KEY` | *(vuota)* | Key datanodes (serve premium per `direct_link`) |
| `MOON_DN_HEADLESS` | `0` | `1` = headless (il captcha **non** si risolve) |
| `MOON_DN_CAPTCHA_WAIT` | `240` | Secondi di attesa per la spunta manuale |
| `MOON_DEBUG` | *(off)* | `1` = traccia ogni gate dell'estrazione |

`setx` scrive la variabile solo per i processi **nuovi**: dopo averla impostata devi
chiudere e riaprire il prompt (o rilanciare `avvia.bat` da un prompt nuovo), altrimenti
non la vedi cambiare — è probabilmente perché non hai notato differenze.

## Consiglio operativo

Con la strada browser metti **"Browsers" a 1 o 2**. Adesso condividono comunque una
sola finestra Chrome, ma tenere basso il parallelismo riduce le sfide di Cloudflare.

## Bug riparati nel flusso datanodes

Tutti verificati sul sito live:

1. L'URL di condivisione fa **302 su `/download`** e piazza un cookie `file_code`.
2. Il form dello step 1 è nell'HTML dal primo byte ma dentro `#downloadReveal`
   collassato, con submit `disabled`; lo scan Vue lo arma a ~6s (failsafe del sito a
   8s). Il vecchio codice faceva `form.submit()` a t≈0.
3. Il POST **deve** contenere `method_free=Free Download >>`, altrimenti il server
   ri-serve lo step 1. Un click sintetico non risulta submitter affidabile, quindi la
   coppia viene materializzata come input hidden.
4. È ammesso **un solo** `POST /download`. Il secondo ri-esegue SecSave e invalida il
   token dello step 2 — poi download2 fallisce SecCheck e il server risponde HTML. Sta
   scritto nel commento del loro sorgente. Il vecchio `poll("free download")` +
   `FIND_BTN_JS` ri-cliccava il bottone dello step 1 e bruciava il token.
5. `BLOCKED_DOMS` conteneva `"challenges.cloudflare"` → Turnstile non si caricava mai.
6. `BLOCKED_RES` conteneva `"stylesheet"` → senza CSS ogni `getBoundingClientRect()`
   collassa a 0x0 e il finder dei bottoni, che filtra su `s>0`, non trovava niente.
7. Bloccare i domini pubblicitari faceva scattare `:detect-adblock="true"`.
8. La cattura dell'URL finale non è più agganciata alla stringa `dlproxy`.
9. Ogni sonda sul DOM passa da `_dn_eval()`, che sopravvive alla navigazione dello
   step 1 invece di crashare con "Execution context was destroyed".
10. I popup pubblicitari sono ora tracciati per-pagina: su un contesto condiviso
    `context.pages` conteneva le schede degli altri worker e il vecchio sweep gliele
    avrebbe chiuse in faccia.

## File

| File | Note |
|---|---|
| `moon_extract.py` | **nuovo** — estrazione + gestione Chrome via CDP |
| `gen_1.py` | patchato |
| `gen_cli.py` | patchato |
| `requirements.txt` | aggiunto `curl_cffi>=0.7` |
| `avvia.bat` | check dipendenze aggiornato |
| `apply_patch.py` | idempotente, per applicare la patch a una tua copia |
