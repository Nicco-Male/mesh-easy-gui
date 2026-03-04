# Mesh Easy GUI

Interfaccia web **semplice e pratica** per gestire alcune operazioni Meshtastic senza ricordarsi ogni volta i comandi CLI.

Questa app è costruita con **[NiceGUI](https://nicegui.io/)** e permette di:

- collegarti a un nodo Meshtastic via **TCP**, **USB/Seriale** o **BLE**;
- vedere i nodi disponibili nella NodeDB locale;
- selezionare rapidamente un nodo e copiarne il NodeID;
- impostare da GUI il comando **set favorite node** su un nodo remoto amministrabile.

---

## Cosa fa in pratica

L'app è pensata come wrapper visuale per un flusso tipico Meshtastic:

1. ti connetti al controller (radio locale);
2. visualizzi i nodi che il controller conosce;
3. scegli il nodo da segnare come preferito;
4. invii il comando di favorite al nodo remoto (`--dest ... --set-favorite-node ...`).

In log viene mostrata anche la **CLI equivalente**, così puoi sempre verificare cosa sta succedendo.

---

## Requisiti

- Python **3.10+** consigliato
- una radio/nodo Meshtastic raggiungibile via:
  - TCP (es. radio con Wi-Fi), oppure
  - USB/Seriale, oppure
  - BLE

### Dipendenze Python

Dipendenze principali:

- `nicegui`
- `meshtastic`

Opzionali ma utili:

- `pyserial` (enumerazione porte seriali più robusta)
- `bleak` (scan BLE dalla GUI)

---

## Installazione veloce

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install nicegui meshtastic pyserial bleak
```

> Se non ti serve BLE scan puoi anche omettere `bleak`.

---

## Avvio

```bash
python app.py
```

Poi apri il browser su:

- `http://localhost:8080`

---

## Guida rapida all'uso

### 1) Scegli il tipo di connessione

In alto seleziona:

- **TCP** → inserisci Host e porta (default 4403)
- **USB** → scegli la porta seriale (o lascia `(auto)`)
- **BLE** → fai scan, poi scegli il dispositivo (o lascia `(auto/paired)`)

Clicca **CONNECT**.

### 2) Visualizza nodi

Dopo la connessione compare la tabella nodi con:

- NodeID
- Short / Long name
- Last heard
- Hops
- Role
- HW

Tip utili:

- click sul valore NodeID → copia negli appunti
- click sulla riga → precompila automaticamente il campo “Nodo da favoritare”

### 3) Imposta il favorite remoto

Compila (o verifica):

- **Dest remoto (admin)**: nodo su cui inviare il comando
- **Nodo da favoritare**: nodo da impostare come favorite

Clicca **⭐ SET FAVORITE (REMOTE)**.

---

## Note su BLE e ambienti virtualizzati

In VM/LXC/container il BLE spesso richiede pass-through del controller Bluetooth host.
Se lo scan non trova device, controlla prima i permessi/dispositivo a livello sistema.

---

## Troubleshooting

- **“Connessione fallita”**
  - verifica host/porta (TCP),
  - verifica porta seriale e permessi utente (USB),
  - verifica pairing/adapter (BLE).

- **Nessun nodo in tabella**
  - la NodeDB può essere ancora in aggiornamento,
  - attendi qualche secondo dopo la connessione o verifica che il controller veda la mesh.

- **Errore durante favorite remoto**
  - assicurati che `dest` sia corretto,
  - verifica di avere i permessi/ruolo necessari sul nodo di destinazione.

---

## Struttura minima repo

```text
.
├── app.py
└── README.md
```

---

## Licenza

Aggiungi qui la tua licenza preferita (MIT, Apache-2.0, ecc.).
