# app.py (versione base) — BLE scan con lista dispositivi + NodeDB senza refresh distruttivo
from __future__ import annotations

import asyncio
import glob
import json
import re
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple

from nicegui import ui

from meshtastic.tcp_interface import TCPInterface  # type: ignore
from meshtastic.serial_interface import SerialInterface  # type: ignore
from meshtastic.ble_interface import BLEInterface  # type: ignore

AUTO = "__AUTO__"  # sentinel per select (non usare stringa vuota)

iface: Any = None

# UI handles
log_area: Optional[ui.textarea] = None
fav_in: Optional[ui.input] = None
ble_manual_in: Optional[ui.input] = None
conn_status: Optional[ui.label] = None
nodes_count_label: Optional[ui.label] = None

row_tcp: Optional[ui.row] = None
row_usb: Optional[ui.row] = None
row_ble: Optional[ui.row] = None

serial_sel: Optional[ui.select] = None
ble_sel: Optional[ui.select] = None

ble_grid: Optional[ui.aggrid] = None
nodes_grid: Optional[ui.aggrid] = None

_last_nodes_sig: Optional[int] = None
_auto_refresh_enabled: bool = False

state: Dict[str, Any] = {
    "conn_mode": "BLE",          # TCP | USB | BLE
    "host": "192.168.10.8",
    "tcp_port": 4403,

    "serial_port": AUTO,         # AUTO oppure /dev/ttyUSB0 ...
    "ble_choice": AUTO,          # AUTO oppure address da scan
    "ble_manual": "",            # MAC manuale (override)

    "dest": "!a5592387",
    "favorite": "!0c3a3de4",

    "log": [],
}

ui.add_head_html(
    """
    <style>
      .page-wrap { max-width: 1200px; margin: 0 auto; }
      .ag-theme-alpine { border-radius: 10px; overflow: hidden; }
      .nicegui-content { padding-top: 12px; }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
      .muted { color: #6b7280; }
      .card { border: 1px solid rgba(0,0,0,.08); border-radius: 12px; padding: 12px; }
    </style>
    """
)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    state["log"].append(f"[{ts}] {msg}")
    if len(state["log"]) > 600:
        state["log"] = state["log"][-600:]
    if log_area:
        log_area.value = "\n".join(state["log"])


def set_status(text: str, muted: bool = False) -> None:
    if conn_status:
        conn_status.text = text
        conn_status.classes(remove="muted")
        if muted:
            conn_status.classes(add="muted")


def _is_hex8(s: str) -> bool:
    if len(s) != 8:
        return False
    try:
        int(s, 16)
        return True
    except Exception:
        return False


def format_node_id(node_id: Any) -> str:
    if isinstance(node_id, int):
        return f"!{node_id & 0xFFFFFFFF:08x}"
    s = str(node_id).strip()
    if s.startswith("!"):
        return s
    if _is_hex8(s):
        return f"!{s.lower()}"
    return s


def pick_field(obj: Any, *names: str, default: str = "") -> str:
    if obj is None:
        return default

    if isinstance(obj, dict):
        for n in names:
            if n in obj and obj[n] not in (None, ""):
                return str(obj[n])
        lower_map = {str(k).lower(): k for k in obj.keys()}
        for n in names:
            k = lower_map.get(n.lower())
            if k is not None and obj[k] not in (None, ""):
                return str(obj[k])
        return default

    for n in names:
        if hasattr(obj, n):
            v = getattr(obj, n)
            if v not in (None, ""):
                return str(v)

    d = getattr(obj, "__dict__", None)
    if isinstance(d, dict):
        for n in names:
            if n in d and d[n] not in (None, ""):
                return str(d[n])

    return default


def get_user_obj(node: Any) -> Any:
    if node is None:
        return None
    if isinstance(node, dict):
        return node.get("user") or node.get("User")
    return getattr(node, "user", None)


def get_node_field(node: Any, *names: str, default: Any = None) -> Any:
    if node is None:
        return default
    if isinstance(node, dict):
        for n in names:
            if n in node:
                return node.get(n, default)
        lower_map = {str(k).lower(): k for k in node.keys()}
        for n in names:
            k = lower_map.get(n.lower())
            if k is not None:
                return node.get(k, default)
        return default
    for n in names:
        if hasattr(node, n):
            return getattr(node, n)
    return default


def human_last_heard(v: Any) -> str:
    if v in (None, "", 0):
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(v)
    return str(v)


def list_serial_ports() -> List[str]:
    ports: List[str] = []
    ports += sorted(glob.glob("/dev/ttyACM*"))
    ports += sorted(glob.glob("/dev/ttyUSB*"))
    ports += sorted(glob.glob("/dev/serial/by-id/*"))
    ports += sorted(glob.glob("/dev/cu.usb*"))
    ports += sorted(glob.glob("/dev/tty.usb*"))

    try:
        import serial.tools.list_ports  # type: ignore
        for p in serial.tools.list_ports.comports():
            if p.device and p.device not in ports:
                ports.append(p.device)
    except Exception:
        pass

    seen = set()
    out = []
    for p in ports:
        if p not in seen:
            out.append(p)
            seen.add(p)
    return out


def normalize_mac(s: str) -> str:
    return (s or "").strip().replace("-", ":").upper()


def looks_like_mac(s: str) -> bool:
    s = normalize_mac(s)
    return bool(re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", s))


async def scan_ble_devices() -> List[Tuple[str, str, Optional[int]]]:
    """Ritorna lista (address, label, rssi)."""
    try:
        from bleak import BleakScanner  # type: ignore
    except Exception as e:
        log(f"❌ Bleak non disponibile: {e} (pip install bleak)")
        return []

    try:
        devices = await BleakScanner.discover(timeout=6.0)
        results: List[Tuple[str, str, Optional[int]]] = []
        for d in devices:
            name = (getattr(d, "name", "") or "").strip()
            addr = (getattr(d, "address", "") or "").strip()
            rssi = getattr(d, "rssi", None)
            if not addr:
                continue
            label = f"{name} ({addr})" if name else addr
            results.append((addr, label, rssi))

        # dedup per address
        seen = set()
        uniq: List[Tuple[str, str, Optional[int]]] = []
        for addr, label, rssi in results:
            if addr not in seen:
                uniq.append((addr, label, rssi))
                seen.add(addr)

        # ordina: nome prima, poi rssi più alto
        def sort_key(x: Tuple[str, str, Optional[int]]):
            addr, label, rssi = x
            has_name = "(" in label and not label.startswith(addr)
            return (0 if has_name else 1, -(rssi or -999))

        uniq.sort(key=sort_key)
        return uniq
    except Exception as e:
        log(f"❌ Scan BLE fallita: {e}")
        return []


def set_conn_rows_visibility() -> None:
    if row_tcp:
        row_tcp.set_visibility(state["conn_mode"] == "TCP")
    if row_usb:
        row_usb.set_visibility(state["conn_mode"] == "USB")
    if row_ble:
        row_ble.set_visibility(state["conn_mode"] == "BLE")


def disconnect(silent: bool = False) -> None:
    global iface, _last_nodes_sig
    try:
        if iface:
            iface.close()
        iface = None
        _last_nodes_sig = None
        if not silent:
            log("🔌 Disconnesso")
        set_status("— non connesso —", muted=True)
        update_nodes_grid(force=True)
    except Exception as e:
        iface = None
        _last_nodes_sig = None
        log(f"⚠️ Errore disconnect: {e}")
        set_status("— non connesso —", muted=True)
        update_nodes_grid(force=True)


async def connect_async() -> None:
    """Connessione in thread: BLE può essere lento."""
    global iface
    disconnect(silent=True)
    mode = state["conn_mode"]

    try:
        set_status("Connessione in corso…", muted=True)

        if mode == "TCP":
            host = str(state["host"]).strip()
            port = int(state["tcp_port"])
            iface = await asyncio.to_thread(lambda: TCPInterface(hostname=host, portNumber=port))
            log(f"✅ Connesso via TCP a {host}:{port}")
            set_status(f"✅ Connesso TCP {host}:{port}")

        elif mode == "USB":
            sel = state["serial_port"]
            dev = None if sel == AUTO else str(sel).strip()
            iface = await asyncio.to_thread(lambda: SerialInterface(devPath=dev))
            log(f"✅ Connesso via USB/Seriale a {dev or '(auto)'}")
            set_status(f"✅ Connesso USB {dev or '(auto)'}")

        elif mode == "BLE":
            manual = normalize_mac(state.get("ble_manual", ""))
            if manual:
                if not looks_like_mac(manual):
                    log(f"❌ MAC manuale non valido: {manual}")
                    set_status("❌ MAC manuale non valido", muted=False)
                    iface = None
                    return
                addr = manual
            else:
                sel = state["ble_choice"]
                addr = None if sel == AUTO else str(sel).strip()

            iface = await asyncio.to_thread(lambda: BLEInterface(address=addr))
            log(f"✅ Connesso via BLE a {addr or '(auto/paired)'}")
            set_status(f"✅ Connesso BLE {addr or '(auto/paired)'}")

        else:
            log(f"❌ Modalità sconosciuta: {mode}")
            set_status("❌ Modalità sconosciuta", muted=False)
            iface = None
            return

        # Su BLE i primi pacchetti arrivano dopo 1–3s
        await asyncio.sleep(1.2)
        update_nodes_grid(force=True)

    except Exception as e:
        iface = None
        log(f"❌ Connessione fallita ({mode}): {e}")
        set_status("❌ Connessione fallita", muted=False)
        update_nodes_grid(force=True)


def set_favorite_remote() -> None:
    if not iface:
        log("❌ Non connesso.")
        return
    dest = format_node_id(state["dest"].strip())
    fav = format_node_id(state["favorite"].strip())
    log(f"🧠 CLI equivalente:\nmeshtastic (...) --dest '{dest}' --set-favorite-node '{fav}'")
    try:
        iface.getNode(dest, False).setFavorite(fav)
        log(f"⭐ Impostato favorite {fav} su {dest}")
    except Exception as e:
        log(f"❌ Set favorite fallito: {e}")


def build_rows() -> list[dict]:
    if not iface:
        return []

    nodes = getattr(iface, "nodes", {}) or {}
    rows: list[dict] = []

    for raw_id, node in nodes.items():
        nid = format_node_id(raw_id)
        user = get_user_obj(node)

        short = pick_field(user, "shortName", "short_name", "short", "shortname", default="")
        long_ = pick_field(user, "longName", "long_name", "long", "longname", default="")

        last_heard = get_node_field(node, "lastHeard", "last_heard", default=None)
        hops = get_node_field(node, "hopsAway", "hops_away", default="")
        role = get_node_field(node, "role", default="")
        hw = get_node_field(node, "hwModel", "hw_model", "hardwareModel", "hardware_model", default="")

        rows.append(
            {
                "id": nid,
                "short": short,
                "long": long_,
                "last": human_last_heard(last_heard),
                "hops": hops if hops is not None else "",
                "role": str(role) if role is not None else "",
                "hw": str(hw) if hw is not None else "",
            }
        )

    rows.sort(key=lambda r: (r["short"] == "" and r["long"] == "", r["id"]))
    return rows


def js_copy_to_clipboard(text: str) -> None:
    payload = json.dumps(text)
    ui.run_javascript(f"navigator.clipboard.writeText({payload});")
    ui.notify(f"Copiato: {text}", type="positive", timeout=1200)


def update_nodes_grid(force: bool = False) -> None:
    """Aggiorna SOLO i dati (rowData), senza ricreare la tabella => non perdi filtri/ricerche."""
    global _last_nodes_sig

    if not nodes_grid:
        return

    if not iface:
        nodes_grid.options["rowData"] = []
        nodes_grid.update()
        if nodes_count_label:
            nodes_count_label.text = "Nodi in memoria: 0"
        return

    rows = build_rows()

    # firma leggera per evitare update inutili (che fanno flicker)
    sig = hash(tuple((r["id"], r.get("last", ""), r.get("hops", ""), r.get("short", ""), r.get("long", "")) for r in rows))
    if (not force) and (_last_nodes_sig == sig):
        return
    _last_nodes_sig = sig

    nodes_grid.options["rowData"] = rows
    nodes_grid.update()

    if nodes_count_label:
        nodes_count_label.text = f"Nodi in memoria: {len(rows)}"


async def scan_ble_and_update() -> None:
    """Popola sia la dropdown sia la LISTA dispositivi (AG Grid)"""
    results = await scan_ble_devices()
    log(f"🔎 BLE scan: {len(results)} device(s)")

    # dropdown
    opts = {AUTO: "(auto/paired)"} | {addr: label for addr, label, _ in results}
    if ble_sel:
        ble_sel.options = opts
        if state["ble_choice"] not in opts:
            state["ble_choice"] = AUTO
            ble_sel.value = AUTO

    # lista device
    if ble_grid:
        ble_grid.options["rowData"] = [
            {"name": label, "addr": addr, "rssi": (rssi if rssi is not None else "")}
            for addr, label, rssi in results
        ]
        ble_grid.update()
        # su alcuni browser aiuta a “svegliarla”
        try:
            await ble_grid.run_grid_method("sizeColumnsToFit")
        except Exception:
            pass

    if results:
        head = "\n".join([f"  - {label}" for _, label, _ in results[:10]])
        log(f"📋 Trovati (top):\n{head}")


def refresh_serial_ports() -> None:
    ports = list_serial_ports()
    opts = {AUTO: "(auto)"} | {p: p for p in ports}
    if serial_sel:
        serial_sel.options = opts
        if state["serial_port"] not in opts:
            state["serial_port"] = AUTO
            serial_sel.value = AUTO
    log(f"🔄 Porte seriali trovate: {len(ports)}")


def set_auto_refresh(v: bool) -> None:
    global _auto_refresh_enabled
    _auto_refresh_enabled = bool(v)
    log(f"⏱️ Auto-refresh nodi: {'ON' if _auto_refresh_enabled else 'OFF'}")


# --- UI
with ui.column().classes("page-wrap w-full"):
    ui.label("Meshtastic CLI Wrapper — Preferiti Remoti").classes("text-h5")

    with ui.row().classes("w-full items-end"):
        ui.select(
            label="Connessione",
            options=["TCP", "USB", "BLE"],
            value=state["conn_mode"],
            on_change=lambda e: (state.update(conn_mode=e.value), set_conn_rows_visibility()),
        ).classes("w-40")

        ui.button("CONNECT", on_click=connect_async)
        ui.button("DISCONNECT", on_click=lambda: disconnect(silent=False))

        conn_status = ui.label("— non connesso —").classes("muted")

    # TCP
    row_tcp = ui.row().classes("w-full items-end")
    with row_tcp:
        ui.input("Host (TCP)", value=state["host"], on_change=lambda e: state.update(host=e.value)).classes("w-72")
        ui.number("TCP port", value=state["tcp_port"], format="%.0f",
                  on_change=lambda e: state.update(tcp_port=int(e.value))).classes("w-40")

    # USB
    row_usb = ui.row().classes("w-full items-end")
    with row_usb:
        serial_sel = ui.select(
            label="Porta USB/Seriale",
            options={AUTO: "(auto)"},
            value=state["serial_port"],
            on_change=lambda e: state.update(serial_port=e.value),
        ).classes("w-96")
        ui.button("↻ Refresh porte", on_click=refresh_serial_ports)

    # BLE
    row_ble = ui.row().classes("w-full items-end")
    with row_ble:
        ble_sel = ui.select(
            label="BLE device (scan)",
            options={AUTO: "(auto/paired)"},
            value=state["ble_choice"],
            on_change=lambda e: state.update(ble_choice=e.value),
        ).classes("w-96")

        ui.button("🔎 SCAN BLE", on_click=scan_ble_and_update)

        ble_manual_in = ui.input(
            "MAC BLE manuale (override)",
            value=state["ble_manual"],
            on_change=lambda e: state.update(ble_manual=e.value),
        ).classes("w-72")

        ui.button(
            "🧹 Clear MAC",
            on_click=lambda: (state.update(ble_manual=""), setattr(ble_manual_in, "value", "")),
        )

    set_conn_rows_visibility()
    refresh_serial_ports()

    ui.separator()

    # Lista dispositivi BLE (sempre visibile, così non “sparisce”)
    ui.label("Lista dispositivi BLE (scan) — click riga = copia MAC nel campo manuale").classes("text-subtitle2")
    ble_grid = ui.aggrid(
        {
            "defaultColDef": {"resizable": True, "sortable": True, "filter": True},
            "columnDefs": [
                {"headerName": "Name", "field": "name", "flex": 1, "minWidth": 280},
                {"headerName": "Address", "field": "addr", "minWidth": 190, "maxWidth": 230, "cellClass": "mono"},
                {"headerName": "RSSI", "field": "rssi", "minWidth": 90, "maxWidth": 110, "cellClass": "mono"},
            ],
            "rowData": [],
            "rowSelection": "single",
            "animateRows": True,
        }
    ).classes("ag-theme-alpine w-full").style("height: 260px;")

    def on_ble_row_clicked(e: Any) -> None:
        data = e.args.get("data") if isinstance(e.args, dict) else None
        if not isinstance(data, dict):
            return
        addr = (data.get("addr") or "").strip()
        if addr:
            state["ble_manual"] = addr
            if ble_manual_in:
                ble_manual_in.value = addr
            log(f"📌 MAC selezionato: {addr} (incollato nel campo manuale)")

    ble_grid.on("rowClicked", on_ble_row_clicked)

    ui.separator()

    with ui.row().classes("w-full items-end"):
        ui.input("Dest remoto (admin)", value=state["dest"], on_change=lambda e: state.update(dest=e.value)).classes("w-72")
        fav_in = ui.input("Nodo da favoritare", value=state["favorite"], on_change=lambda e: state.update(favorite=e.value)).classes("w-72")
        ui.button("⭐ SET FAVORITE (REMOTE)", on_click=set_favorite_remote)

    ui.separator()

    # Nodi: griglia creata UNA VOLTA, poi aggiorniamo solo rowData
    with ui.row().classes("w-full items-end"):
        ui.label("Nodi visibili (NodeDB locale del controllore):").classes("text-subtitle2")
        nodes_count_label = ui.label("Nodi in memoria: 0").classes("muted")
        ui.button("↻ Aggiorna", on_click=lambda: update_nodes_grid(force=True))
        ui.checkbox("Auto-refresh", value=False, on_change=lambda e: set_auto_refresh(e.value))

    nodes_grid = ui.aggrid(
        {
            "defaultColDef": {"resizable": True, "sortable": True, "filter": True, "floatingFilter": True},
            "enableCellTextSelection": True,
            "ensureDomOrder": True,
            "columnDefs": [
                {"headerName": "NodeID (click = copia)", "field": "id", "minWidth": 190, "maxWidth": 240, "cellClass": "mono"},
                {"headerName": "Short", "field": "short", "minWidth": 140, "maxWidth": 190},
                {"headerName": "Long name", "field": "long", "flex": 1, "minWidth": 300},
                {"headerName": "Last heard", "field": "last", "minWidth": 190, "maxWidth": 220, "cellClass": "mono"},
                {"headerName": "Hops", "field": "hops", "minWidth": 90, "maxWidth": 110, "cellClass": "mono"},
                {"headerName": "Role", "field": "role", "minWidth": 120, "maxWidth": 150},
                {"headerName": "HW", "field": "hw", "minWidth": 140, "maxWidth": 190},
            ],
            "rowData": [],
            "rowSelection": "single",
            "animateRows": True,
        }
    ).classes("ag-theme-alpine w-full").style("height: 520px;")

    def on_nodes_cell_clicked(e: Any) -> None:
        if not isinstance(e.args, dict):
            return
        col = e.args.get("colId") or (e.args.get("colDef") or {}).get("field")
        if col != "id":
            return
        value = e.args.get("value") or (e.args.get("data") or {}).get("id")
        if value:
            js_copy_to_clipboard(str(value))

    nodes_grid.on("cellClicked", on_nodes_cell_clicked)

    ui.separator()
    ui.label("Log:").classes("text-subtitle2")
    log_area = ui.textarea(value="", placeholder="log...").props("readonly").classes("w-full").style("height: 220px;")


# Timer: aggiorna solo se auto-refresh ON (e senza distruggere filtri)
def _timer_tick():
    if _auto_refresh_enabled and iface:
        update_nodes_grid(force=False)

ui.timer(2.0, _timer_tick)

ui.run(port=8080)
