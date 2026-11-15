// Translations: key -> [English, Italiano]
const S = {
  // ---- common
  'common.close': ['Close', 'Chiudi'],
  'common.cancel': ['Cancel', 'Annulla'],
  'common.confirm': ['Confirm', 'Conferma'],
  'common.create': ['Create', 'Crea'],
  'common.save': ['Save', 'Salva'],
  'common.saved': ['Saved', 'Salvato'],
  'common.add': ['Add', 'Aggiungi'],
  'common.added': ['Added', 'Aggiunto'],
  'common.remove': ['Remove', 'Rimuovi'],
  'common.removed': ['Removed', 'Rimosso'],
  'common.delete': ['Delete', 'Elimina'],
  'common.deleted': ['Deleted', 'Eliminato'],
  'common.manage': ['Manage', 'Gestisci'],
  'common.none': ['None', 'Nessuno'],
  'common.nothing.to.add': ['Nothing left to add.', 'Non resta nulla da aggiungere.'],
  'common.generate': ['Generate', 'Genera'],
  'common.show': ['Show', 'Mostra'],
  'common.language': ['Language', 'Lingua'],
  'err.network': ['Cannot reach the manager service.', 'Impossibile raggiungere il servizio.'],
  'err.auth': ['Session expired, please sign in again.', 'Sessione scaduta, accedi di nuovo.'],

  // ---- navigation / shell
  'nav.dashboard': ['Dashboard', 'Dashboard'],
  'nav.clients': ['Clients', 'Utenti'],
  'nav.roles': ['Roles', 'Ruoli'],
  'nav.groups': ['Groups', 'Gruppi'],
  'nav.map': ['Map', 'Mappa'],
  'nav.activity': ['Activity', 'Attività'],
  'nav.test': ['Test connection', 'Test connessione'],
  'pill.online': ['Broker online', 'Broker online'],
  'pill.offline': ['Broker offline', 'Broker offline'],
  'login.password': ['Password', 'Password'],
  'login.submit': ['Sign in', 'Accedi'],
  'login.logout': ['Sign out', 'Esci'],

  // ---- formatting
  'fmt.uptime.dh': ['{d} d {h} h', '{d} g {h} h'],
  'fmt.uptime.hm': ['{h} h {m} min', '{h} h {m} min'],
  'fmt.uptime.m': ['{m} min', '{m} min'],

  // ---- dashboard
  'dash.offline': ['Cannot connect to the broker.', 'Impossibile collegarsi al broker.'],
  'dash.dynsec.title': ['Dynamic Security does not answer.', 'Dynamic Security non risponde.'],
  'dash.dynsec.body': [
    'Load the plugin in mosquitto.conf and give the manager\'s account the admin role (see the README).',
    'Carica il plugin in mosquitto.conf e assegna il ruolo admin all\'account del manager (vedi README).'],
  'dash.nosys': [
    'No $SYS statistics received. Check that the manager\'s role may subscribe to $SYS/#.',
    'Nessuna statistica $SYS ricevuta. Verifica che il ruolo del manager possa sottoscrivere $SYS/#.'],
  'dash.nolog.title': ['Connection history is off.', 'Lo storico connessioni è disattivo.'],
  'dash.nolog.body': [
    'Add the following to mosquitto.conf to see who connects and who fails to log in:',
    'Aggiungi questo a mosquitto.conf per vedere chi si collega e chi sbaglia il login:'],
  'dash.failed': ['{n} failed login attempt(s) in the last 24 h.', '{n} tentativo/i di login fallito/i nelle ultime 24 h.'],
  'dash.failed.link': ['Show details', 'Mostra dettagli'],
  'dash.broker': ['Mosquitto version', 'Versione Mosquitto'],
  'dash.uptime': ['Uptime {v}', 'Attivo da {v}'],
  'dash.connected': ['Connected clients', 'Client connessi'],
  'dash.total': ['{n} known to the broker', '{n} noti al broker'],
  'dash.subs': ['Subscriptions', 'Sottoscrizioni'],
  'dash.retained': ['{n} retained messages', '{n} messaggi retained'],
  'dash.rate': ['Messages / min (in / out)', 'Messaggi / min (in / out)'],
  'dash.rate.sub': ['1-minute average', 'Media a 1 minuto'],
  'dash.traffic': ['Traffic received', 'Traffico ricevuto'],
  'dash.failedlogins': ['Failed logins', 'Login falliti'],
  'dash.24h': ['last 24 hours', 'ultime 24 ore'],
  'dash.chart.clients': ['Connected clients (last hour)', 'Client connessi (ultima ora)'],
  'dash.chart.msgs': ['Messages per minute (last hour)', 'Messaggi al minuto (ultima ora)'],
  'dash.collecting': ['Collecting data…', 'Raccolta dati in corso…'],
  'dash.in': ['in', 'in'],
  'dash.out': ['out', 'out'],
  'dash.recent': ['Recent activity', 'Attività recente'],
  'dash.all': ['See all', 'Vedi tutto'],
  'dash.noevents': ['Nothing yet.', 'Ancora niente.'],
  'dash.updated': ['Updated {v}', 'Aggiornato {v}'],

  // ---- activity
  'kind.connect': ['Connected', 'Connesso'],
  'kind.disconnect': ['Disconnected', 'Disconnesso'],
  'kind.auth_failed': ['Login failed', 'Login fallito'],
  'kind.admin': ['Change', 'Modifica'],
  'kind.log': ['Broker log', 'Log broker'],
  'ev.connect': ['{who} connected from {addr} {proto}', '{who} si è collegato da {addr} {proto}'],
  'ev.disconnect': ['{who} disconnected ({addr})', '{who} si è disconnesso ({addr})'],
  'ev.authfailed': ['Client "{who}" from {addr} was refused (bad credentials or disabled user)',
    'Client "{who}" da {addr} rifiutato (credenziali errate o utente disabilitato)'],
  'ev.viamanager': ['via Mosquitto Manager', 'tramite Mosquitto Manager'],
  'act.filter.all': ['All', 'Tutto'],
  'act.filter.connections': ['Connections', 'Connessioni'],
  'act.filter.auth_failed': ['Failed logins', 'Login falliti'],
  'act.filter.admin': ['Changes', 'Modifiche'],
  'act.internal': ['Show this app\'s own test connections', 'Mostra le connessioni di test di questa app'],
  'act.empty': ['No events yet. They appear as devices connect and disconnect.',
    'Ancora nessun evento. Compaiono quando i dispositivi si collegano e scollegano.'],
  'act.time': ['Time', 'Ora'],
  'act.type': ['Type', 'Tipo'],
  'act.details': ['Details', 'Dettagli'],
  'act.sources': ['Where failed logins come from', 'Da dove arrivano i login falliti'],
  'act.sources.hint': ['Many attempts from one address usually mean a misconfigured device (or a scan).',
    'Molti tentativi dallo stesso indirizzo di solito indicano un dispositivo configurato male (o una scansione).'],
  'act.address': ['Address', 'Indirizzo'],
  'act.attempts': ['Attempts', 'Tentativi'],
  'act.clientids': ['Client ids', 'Client id'],
  'act.last': ['Last', 'Ultimo'],

  // ---- clients
  'clients.search': ['Search…', 'Cerca…'],
  'clients.new': ['New client', 'Nuovo utente'],
  'clients.empty': ['No clients yet. Create the first one.', 'Ancora nessun utente. Crea il primo.'],
  'clients.nomatch': ['No client matches.', 'Nessun utente corrisponde.'],
  'clients.col.status': ['Status', 'Stato'],
  'clients.col.user': ['User', 'Utente'],
  'clients.col.access': ['Roles & groups', 'Ruoli e gruppi'],
  'clients.col.conn': ['Connection', 'Connessione'],
  'clients.online': ['Online ({n})', 'Online ({n})'],
  'clients.offline': ['Offline', 'Offline'],
  'clients.disabled': ['Disabled', 'Disabilitato'],
  'clients.lastseen': ['seen {v}', 'visto {v}'],
  'clients.manager': ['manager', 'manager'],
  'clients.manager.hint': ['The account this app uses to talk to the broker',
    'L\'account che questa app usa per parlare col broker'],
  'clients.manager.note': [
    'This is the account Mosquitto Manager uses. Deleting, disabling or re-passwording it from here is blocked, because it would lock the manager out.',
    'Questo è l\'account usato da Mosquitto Manager. Eliminarlo, disabilitarlo o cambiargli la password da qui è bloccato: il manager non potrebbe più collegarsi.'],
  'clients.created': ['Client "{u}" created', 'Utente "{u}" creato'],
  'clients.f.username': ['Username', 'Nome utente'],
  'clients.f.username.hint': ['What the device puts in its MQTT "username" field.',
    'Ciò che il dispositivo scrive nel campo "username" MQTT.'],
  'clients.f.password': ['Password', 'Password'],
  'clients.f.newpassword': ['New password', 'Nuova password'],
  'clients.f.name': ['Display name', 'Nome visualizzato'],
  'clients.f.desc': ['Description', 'Descrizione'],
  'clients.f.clientid': ['Client id', 'Client id'],
  'clients.f.clientid.hint': [
    'Optional. If set, only a connection using exactly this client id can log in with this user.',
    'Facoltativo. Se impostato, solo una connessione con esattamente questo client id può entrare con questo utente.'],
  'clients.pw.hint': ['Use a long random password; devices never type it.',
    'Usa una password lunga e casuale: i dispositivi non la digitano mai.'],
  'clients.pw.set': ['Set password', 'Imposta password'],
  'clients.pw.changed': ['Password changed. Update the device too.', 'Password cambiata. Aggiorna anche il dispositivo.'],
  'clients.sec.details': ['Details', 'Dettagli'],
  'clients.sec.connections': ['Live connections', 'Connessioni attive'],
  'clients.sec.password': ['Password', 'Password'],
  'clients.sec.test': ['Test the login', 'Prova il login'],
  'clients.sec.danger': ['Danger zone', 'Zona pericolosa'],
  'clients.test.hint': ['Opens a short connection with this user and the password you type, like a device would.',
    'Apre una breve connessione con questo utente e la password digitata, come farebbe un dispositivo.'],
  'clients.noconn': ['Not connected right now.', 'Non collegato in questo momento.'],
  'clients.proto': ['Protocol · keepalive', 'Protocollo · keepalive'],
  'clients.since': ['Since', 'Da'],
  'clients.enable': ['Enable client', 'Abilita utente'],
  'clients.disable': ['Disable client', 'Disabilita utente'],
  'clients.enabled': ['Client enabled', 'Utente abilitato'],
  'clients.disabled.done': ['Client disabled', 'Utente disabilitato'],
  'clients.delete': ['Delete client', 'Elimina utente'],
  'clients.delete.confirm': ['Delete "{u}"? Devices using it will no longer be able to connect. This cannot be undone.',
    'Eliminare "{u}"? I dispositivi che lo usano non potranno più collegarsi. L\'operazione non è annullabile.'],

  // ---- roles
  'roles.new': ['New role', 'Nuovo ruolo'],
  'roles.intro': [
    'A role is a set of topic rules. Give roles to clients (or to groups) to decide what they may publish and subscribe to.',
    'Un ruolo è un insieme di regole sui topic. Assegna i ruoli agli utenti (o ai gruppi) per decidere cosa possono pubblicare e sottoscrivere.'],
  'roles.empty': ['No roles yet.', 'Ancora nessun ruolo.'],
  'roles.topics': ['{n} topics', '{n} topic'],
  'roles.raw': ['Show technical rules', 'Mostra le regole tecniche'],
  'roles.col.what': ['Allows', 'Permette'],
  'roles.sum.readwrite': ['Read and write', 'Lettura e scrittura'],
  'roles.sum.read': ['Read only', 'Sola lettura'],
  'roles.sum.write': ['Write only', 'Sola scrittura'],
  'roles.usedby': ['Used by', 'Usato da'],
  'roles.unused': ['nobody yet', 'ancora nessuno'],
  'roles.delete': ['Delete role', 'Elimina ruolo'],
  'roles.delete.confirm': ['Delete role "{r}"? Clients and groups using it lose its permissions.',
    'Eliminare il ruolo "{r}"? Utenti e gruppi che lo usano perdono i suoi permessi.'],
  'roles.col.type': ['Rule', 'Regola'],
  'roles.col.topic': ['Topic', 'Topic'],
  'roles.col.access': ['Access', 'Accesso'],
  'roles.col.priority': ['Priority', 'Priorità'],
  'roles.allow': ['Allow', 'Consenti'],
  'roles.deny': ['Deny', 'Nega'],
  'roles.norules': ['This role has no rules, so it grants nothing.', 'Questo ruolo non ha regole: non concede nulla.'],
  'roles.addrule': ['Add rule', 'Aggiungi regola'],
  'roles.preset': ['What for', 'Cosa permette'],
  'roles.preset.readwrite': ['Read and write (publish + subscribe)', 'Leggere e scrivere (pubblica + sottoscrivi)'],
  'roles.preset.read': ['Read only (subscribe)', 'Solo lettura (sottoscrivi)'],
  'roles.preset.write': ['Write only (publish)', 'Solo scrittura (pubblica)'],
  'roles.preset.single': ['Single advanced rule…', 'Singola regola avanzata…'],
  'roles.preset.readwrite.help': [
    'Adds the four rules a client needs to both publish and subscribe on this topic.',
    'Aggiunge le quattro regole che servono a un client per pubblicare e sottoscrivere su questo topic.'],
  'roles.preset.read.help': ['Adds the rules to subscribe to this topic and receive its messages.',
    'Aggiunge le regole per sottoscrivere questo topic e ricevere i suoi messaggi.'],
  'roles.preset.write.help': ['Adds the rule to publish on this topic.', 'Aggiunge la regola per pubblicare su questo topic.'],
  'roles.preset.single.help': ['Adds exactly one rule of the type you choose.', 'Aggiunge esattamente una regola del tipo scelto.'],
  'roles.single.hint': ['See the explanation when hovering a rule in the table.', 'Vedi la spiegazione passando sopra una regola nella tabella.'],
  'roles.topic.hint': ['Wildcards: + one level, # everything below.', 'Jolly: + un livello, # tutto ciò che sta sotto.'],
  'roles.f.name': ['Role name', 'Nome del ruolo'],
  'roles.f.text': ['Description', 'Descrizione'],
  'acl.publishClientSend': ['Publish', 'Pubblicare'],
  'acl.publishClientReceive': ['Receive messages', 'Ricevere messaggi'],
  'acl.subscribePattern': ['Subscribe (pattern)', 'Sottoscrivere (pattern)'],
  'acl.subscribeLiteral': ['Subscribe (exact)', 'Sottoscrivere (esatto)'],
  'acl.unsubscribePattern': ['Unsubscribe (pattern)', 'Annullare sottoscrizione (pattern)'],
  'acl.unsubscribeLiteral': ['Unsubscribe (exact)', 'Annullare sottoscrizione (esatto)'],
  'acl.publishClientSend.help': ['The client may publish messages to this topic.', 'Il client può pubblicare messaggi su questo topic.'],
  'acl.publishClientReceive.help': ['The broker may deliver messages on this topic to the client.', 'Il broker può consegnare al client i messaggi di questo topic.'],
  'acl.subscribePattern.help': ['The client may subscribe to any filter matching this pattern.', 'Il client può sottoscrivere qualunque filtro che corrisponde a questo pattern.'],
  'acl.subscribeLiteral.help': ['The client may subscribe to exactly this filter, wildcards included.', 'Il client può sottoscrivere esattamente questo filtro, jolly compresi.'],
  'acl.unsubscribePattern.help': ['The client may unsubscribe from filters matching this pattern.', 'Il client può annullare le sottoscrizioni che corrispondono a questo pattern.'],
  'acl.unsubscribeLiteral.help': ['The client may unsubscribe from exactly this filter.', 'Il client può annullare esattamente questa sottoscrizione.'],
  'defacl.title': ['Default access', 'Accesso predefinito'],
  'defacl.help': ['Applies when no role rule matches. Keeping everything unchecked (deny) is the safe choice.',
    'Vale quando nessuna regola dei ruoli corrisponde. Lasciare tutto disattivato (nega) è la scelta sicura.'],
  'defacl.publishClientSend': ['Allow publishing', 'Consenti di pubblicare'],
  'defacl.publishClientReceive': ['Allow receiving messages', 'Consenti di ricevere messaggi'],
  'defacl.subscribe': ['Allow subscribing', 'Consenti di sottoscrivere'],
  'defacl.unsubscribe': ['Allow unsubscribing', 'Consenti di annullare sottoscrizioni'],

  // ---- groups
  'groups.new': ['New group', 'Nuovo gruppo'],
  'groups.intro': ['A group bundles clients and roles: give a role to the group and every member gets it.',
    'Un gruppo raccoglie utenti e ruoli: dai un ruolo al gruppo e tutti i membri lo ottengono.'],
  'groups.empty': ['No groups yet.', 'Ancora nessun gruppo.'],
  'groups.members': ['{n} members', '{n} membri'],
  'groups.col.members': ['Members', 'Membri'],
  'groups.delete': ['Delete group', 'Elimina gruppo'],
  'groups.delete.confirm': ['Delete group "{g}"? Its members keep their own roles but lose the group\'s.',
    'Eliminare il gruppo "{g}"? I membri mantengono i propri ruoli ma perdono quelli del gruppo.'],
  'groups.f.name': ['Group name', 'Nome del gruppo'],

  // ---- map
  'map.intro': [
    'Who is connected to the broker and from where. Click a client to manage it, or an address to give it a name.',
    'Chi è collegato al broker e da dove. Clicca un client per gestirlo, o un indirizzo per dargli un nome.'],
  'map.empty': ['No connections right now.', 'Nessuna connessione in questo momento.'],
  'map.clients': ['{n} clients', '{n} client'],
  'map.attempts': ['refused ×{n}', 'rifiutato ×{n}'],
  'map.legend.client': ['Connected client', 'Client collegato'],
  'map.legend.manager': ['This manager', 'Questo manager'],
  'map.legend.refused': ['Refused login (24 h)', 'Login rifiutato (24 h)'],
  'map.legend.click': ['Click on a node for details', 'Clicca un nodo per i dettagli'],
  'map.offline': ['Users not connected', 'Utenti non collegati'],
  'map.docker.hint': [
    'Clients running on the same machine, or inside Docker, show the same address (the host or the Docker gateway).',
    'I client che girano sulla stessa macchina, o dentro Docker, mostrano lo stesso indirizzo (l\'host o il gateway di Docker).'],
  'map.host.hint': ['Give {addr} a friendly name, for example the machine or device it belongs to.',
    'Dai a {addr} un nome comprensibile, per esempio la macchina o il dispositivo a cui appartiene.'],
  'map.host.name': ['Name', 'Nome'],
  'map.host.ph': ['e.g. Home server', 'es. Server di casa'],
  'map.host.clear': ['Remove name', 'Rimuovi il nome'],

  // ---- Home Assistant
  'ha.title': ['Home Assistant sensors', 'Sensori per Home Assistant'],
  'ha.off': ['Not publishing. The manager can create sensors in Home Assistant: broker status, clients, failed logins and one connectivity sensor per user.',
    'Non pubblica. Il manager può creare sensori in Home Assistant: stato del broker, client, login falliti e un sensore di connessione per ogni utente.'],
  'ha.off.hint': ['Turn it on with the environment variable', 'Attivalo con la variabile d\'ambiente'],
  'ha.ok': ['Publishing', 'Pubblica'],
  'ha.ok.detail': ['{n} entities through MQTT discovery (prefix "{p}").', '{n} entità tramite MQTT discovery (prefisso "{p}").'],
  'ha.starting': ['starting…', 'avvio in corso…'],
  'ha.error': ['not working: {e}', 'non funziona: {e}'],

  // ---- test connection
  'test.intro': [
    'Check that a username and password work, exactly as a device would log in. Nothing is changed on the broker.',
    'Verifica che nome utente e password funzionino, esattamente come farebbe un dispositivo. Sul broker non cambia nulla.'],
  'test.run': ['Test login', 'Prova il login'],
  'test.ok': ['Login accepted', 'Login accettato'],
  'test.fail': ['Login refused', 'Login rifiutato'],
  'test.clientid': ['Client id (optional)', 'Client id (facoltativo)'],
  'test.clientid.ph': ['random', 'casuale'],
  'test.clientid.hint': ['Only needed if the user is bound to a specific client id.',
    'Serve solo se l\'utente è legato a uno specifico client id.'],
  'test.hint.auth': [
    'Wrong password, unknown or disabled user, or the client id does not match the one the user is bound to.',
    'Password errata, utente inesistente o disabilitato, oppure il client id non coincide con quello a cui l\'utente è legato.'],
  'test.hint.net': ['The manager cannot reach the broker.', 'Il manager non riesce a raggiungere il broker.'],
  'test.tips.title': ['If a device cannot connect', 'Se un dispositivo non si collega'],
  'test.tip.1': ['Test the same username and password here first.', 'Prova prima qui lo stesso nome utente e la stessa password.'],
  'test.tip.2': ['Look in Activity → Failed logins for its address and client id.', 'Guarda in Attività → Login falliti il suo indirizzo e il client id.'],
  'test.tip.3': ['Check that the user is enabled and has a role granting the topics it needs.', 'Controlla che l\'utente sia abilitato e abbia un ruolo con i topic che gli servono.'],
  'test.tip.4': ['A refused login is different from missing permissions: with permissions missing the device connects but its publish or subscribe is silently ignored.', 'Un login rifiutato è diverso da permessi mancanti: senza permessi il dispositivo si collega ma publish e subscribe vengono ignorati in silenzio.'],
};

const KEY = 'mm-lang';
let current = 'en';
try {
  const saved = localStorage.getItem(KEY);
  current = saved === 'it' || saved === 'en' ? saved
    : (navigator.language || 'en').toLowerCase().startsWith('it') ? 'it' : 'en';
} catch {
  current = (navigator.language || 'en').toLowerCase().startsWith('it') ? 'it' : 'en';
}

export const LANGS = { en: 'English', it: 'Italiano' };
export const lang = () => current;

export function setLang(code) {
  current = code === 'it' ? 'it' : 'en';
  try { localStorage.setItem(KEY, current); } catch { /* storage may be blocked */ }
}

export function t(key, vars) {
  const entry = S[key];
  let text = entry ? entry[current === 'it' ? 1 : 0] : key;
  if (vars) text = text.replace(/\{(\w+)\}/g, (_, k) => (vars[k] === undefined ? '' : vars[k]));
  return text;
}

export const _keys = () => Object.keys(S);
