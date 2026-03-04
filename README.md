# Mesh Easy GUI

GUI NiceGUI per Meshtastic (TCP / USB / BLE) con focus su:

- scan BLE affidabile con tabella cliccabile;
- connessione non bloccante (async + thread);
- NodeDB aggiornata senza perdere filtri/ricerche AG Grid;
- Remote Admin: `Set Favorite` con log del comando equivalente.

## Requisiti

- Python 3.10+
- Dipendenze in `requirements.txt`

## Installazione

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Avvio

```bash
python app.py
```

Apri: `http://localhost:8080`

## Uso rapido

1. Seleziona connessione (TCP / USB / BLE).
2. Per BLE:
   - premi **SCAN BLE**;
   - usa la tabella dispositivi (Name, Address, RSSI);
   - click riga = copia Address nel campo MAC manuale override.
3. Premi **CONNECT**.
4. Guarda stato connessione e dettagli (`localNode`, `myInfo`, `metadata`).
5. Tabella nodi:
   - click su NodeID = copia negli appunti;
   - click riga = riempie il campo "Nodo da favoritare".
6. Premi **SET FAVORITE (REMOTE)** per inviare il comando.

## Note BLE

- In alcuni ambienti (VM/LXC/container) il BLE richiede pass-through dell'adapter.
- Se la connessione è attiva ma NodeDB resta vuota, controlla:
  - pairing/permessi BLE;
  - adapter corretto;
  - che il device target sia Meshtastic.
- Su Windows, effettua pairing BLE prima di usare `(auto/paired)`.

## Funzionamento tecnico (sintesi)

- Le connessioni lente sono eseguite in `asyncio.to_thread(...)`.
- La griglia NodeDB viene creata una sola volta; gli update toccano solo `rowData`.
- Auto-refresh nodi è **OFF** di default.

