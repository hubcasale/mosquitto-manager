# Mosquitto Manager

Una piccola interfaccia web, da installare in casa, per gestire un broker [Eclipse Mosquitto](https://mosquitto.org)
**già esistente**: utenti, password, ruoli e ACL, chi è collegato, e perché un dispositivo non riesce a entrare.

*English: [README.md](README.md)*

![Dashboard](docs/screenshots/dashboard.jpg)

<p>
  <img src="docs/screenshots/clients.jpg" alt="Utenti" width="49%">
  <img src="docs/screenshots/activity.jpg" alt="Login falliti" width="49%">
</p>

## Cosa fa

- **Utenti**: crea, disabilita, elimina, cambia password (con generatore), lega un utente a un client id.
- **Ruoli, gruppi e ACL**: concedi un topic con un clic ("leggere e scrivere su `shellies/#`") senza scrivere a mano
  le quattro regole di Dynamic Security; consenti/nega; accesso predefinito.
- **Chi è collegato**: connessioni attive per utente, con indirizzo, client id, protocollo e keepalive.
- **Login falliti**: quale client id e quale indirizzo vengono rifiutati, e quante volte.
- **Prova il login**: apre una breve connessione con nome utente e password, come un dispositivo, e mostra la
  risposta del broker in parole semplici.
- **Registro attività**: connessioni, disconnessioni, login rifiutati e ogni modifica fatta dal canale di controllo
  del broker (le password non vengono mai mostrate).
- **Dashboard**: versione e uptime del broker, client, sottoscrizioni, messaggi al minuto, grafici dell'ultima ora.
- **Sicuro per costruzione**: rifiuta le azioni che lo escluderebbero dal broker.
- Interfaccia in italiano e inglese, tema chiaro e scuro, usabile da telefono.

**Non** ha bisogno dei file del broker, di Docker né dell'host: è solo un client MQTT (parla col plugin Dynamic
Security e legge `$SYS`). Può girare ovunque raggiunga la porta MQTT del broker.

## Requisiti

- Mosquitto **2.0 o successivo** con il plugin Dynamic Security (incluso nei pacchetti ufficiali e nell'immagine
  `eclipse-mosquitto`). Provato con 2.0.22 e 2.1.2.
- Consigliato **2.1 o successivo**: indica direttamente le connessioni attive per utente e permette di
  [mantenere le password già esistenti](#hai-già-utenti-in-un-password_file) passando da `password_file`.

## Installazione

**1. Abilita il plugin e il registro** in `mosquitto.conf` ([esempio completo](docs/mosquitto.conf.example)) e riavvia
il broker:

```conf
plugin /usr/lib/mosquitto_dynamic_security.so
plugin_opt_config_file /mosquitto/data/dynamic-security.json

log_dest stdout
log_dest topic
log_type error
log_type warning
log_type notice
log_type information
connection_messages true
```

**2. Crea l'account del manager.** Serve un ruolo a privilegi minimi (solo controllo Dynamic Security e `$SYS`).
Lo strumento in `tools/` scrive la configurazione e genera la password:

```bash
python3 tools/passwd_to_dynsec.py --out ./dynamic-security.json --admin mm-admin
```

Metti il file dove punta `plugin_opt_config_file` e riavvia il broker.

**3. Avvia il manager** ([esempio compose](docker-compose.example.yml)):

```bash
docker run -d --name mosquitto-manager --restart unless-stopped -p 8088:8080 \
  -e MQTT_HOST=192.168.1.10 \
  -e MQTT_USERNAME=mm-admin -e MQTT_PASSWORD='la-password-generata' \
  -e UI_PASSWORD='una-password-lunga-per-la-web-ui' \
  -v mosquitto-manager-data:/data \
  ghcr.io/hubcasale/mosquitto-manager:latest
```

Apri `http://<server>:8088`.

L'immagine non è ancora pubblicata? Costruiscila da una copia del repo: `docker build -t mosquitto-manager .` e usa quel nome.

## Hai già utenti in un `password_file`?

Con Mosquitto **2.1+** puoi passare a Dynamic Security **senza toccare nessun dispositivo**: gli hash delle password
vengono importati così come sono. Verificato su 2.1.2.

Da sapere prima:

1. **Con il plugin caricato, un utente deve esistere in Dynamic Security per avere accesso**, anche se il login
   passerebbe dal `password_file` (provato: l'utente si autentica ma le sottoscrizioni vengono rifiutate).
   Quindi è un'*importazione*, non una convivenza.
2. L'importazione non assegna **nessun ruolo** e imposta l'**accesso predefinito su "consenti"**: è la stessa
   situazione di un broker senza `acl_file`, dove tutti possono tutto. Poi stringi con calma dall'interfaccia.
3. Le regole di un eventuale `acl_file` **non** vengono importate: tieni "consenti" finché non le hai ricreate
   come ruoli, altrimenti i dispositivi perdono accessi che hanno oggi.
4. Serve **un riavvio** del broker (pochi secondi); i dispositivi si ricollegano da soli.

Passi:

```bash
# 0. fai una copia della cartella di configurazione del broker

# 1. genera la configurazione dal tuo password_file
python3 tools/passwd_to_dynsec.py --passwd /percorso/passwd \
  --out /percorso/dynamic-security.json --admin mm-admin
```

Lo strumento stampa quanti utenti ha importato e la password generata per `mm-admin` (mostrata una sola volta:
va in `MQTT_PASSWORD`). Le voci che non sono hash `$7$` (testo in chiaro o vecchi `$6$`) vengono elencate come
*non importate*: ricreale dall'interfaccia.

Poi in `mosquitto.conf` aggiungi il plugin e il registro (vedi sopra), togli `password_file`, riavvia, e avvia il manager.
Guida completa in inglese: [docs/MIGRATION.md](docs/MIGRATION.md). Per tornare indietro basta rimettere il vecchio
`mosquitto.conf`: il file delle password non viene mai modificato.

## Configurazione

| Variabile | Predefinito | |
|---|---|---|
| `MQTT_HOST` | *obbligatoria* | Indirizzo del broker |
| `MQTT_PORT` | `1883` | |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | *obbligatorie* | Account Dynamic Security del manager |
| `MQTT_TLS` | `false` | TLS verso il broker |
| `MQTT_CA_FILE` | CA di sistema | Certificato CA da usare |
| `UI_PASSWORD` | *obbligatoria* | Password della web UI, almeno 8 caratteri |
| `AUTH_DISABLED` | `false` | Disattiva il login. Solo dietro qualcosa che già autentica |
| `FRAME_ANCESTORS` | `'self'` | Chi può incorporare la UI in un iframe (CSP `frame-ancestors`) |
| `COOKIE_SECURE` | `false` | Metti `true` se servita in HTTPS |
| `SESSION_HOURS` | `12` | Validità del login |
| `PORT` | `8080` | Porta dentro il container |

## Sicurezza

Questo strumento può cambiare chi si collega al tuo broker: trattalo come un pannello di amministrazione.

- Tienilo **in LAN o dietro VPN / reverse proxy con autenticazione e HTTPS**. Non esporlo direttamente su internet.
  Parla in HTTP semplice: termina il TLS in un proxy e imposta `COOKIE_SECURE=true`.
- La UI ha una password, cookie di sessione firmato `HttpOnly` e `SameSite=Strict`, limite ai tentativi di login
  (5 errori in 5 minuti per indirizzo) e un header anti-CSRF su ogni modifica.
- L'account del manager può modificare ogni utente e ACL: dagli una password lunga e casuale. Il manager rifiuta di
  eliminare, disabilitare, cambiare la password o togliere il ruolo al proprio account.

## Limiti

- **Dettagli delle connessioni**: client id, protocollo, keepalive e "da quando" arrivano dal registro del broker,
  quindi esistono solo per le connessioni aperte *dopo* l'avvio del manager. Con 2.1+ l'indirizzo delle connessioni
  precedenti si vede comunque; con 2.0.x non sono elencate finché il dispositivo non si ricollega.
- **Storico limitato**: gli ultimi ~1000 eventi, in memoria e in un piccolo file in `/data`.
- **Niente import di `acl_file`**: Dynamic Security lo sostituisce; riscrivi le regole come ruoli.
- **Un broker per manager**.

## Licenza

[MIT](LICENSE)
