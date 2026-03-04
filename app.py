# app.py
from __future__ import annotations

import asyncio
import glob
import json
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple

from nicegui import ui

from meshtastic.tcp_interface import TCPInterface  # type: ignore
from meshtastic.serial_interface import SerialInterface  # type: ignore
from meshtastic.ble_interface import BLEInterface  # type: ignore

AUTO = "__AUTO__"  # sentinel per select (non usare stringa vuota)

iface: Any = None

state: Dict[str, Any] = {
    "conn_mode": "TCP",          # TCP | USB | BLE
    "host": "192.168.10.8",
    "tcp_port": 4403,

    "serial_port": AUTO,         # AUTO oppure /dev/ttyUSB0 ...
    "ble_address": AUTO,         # AUTO oppure AA:BB:...

    "dest": "!a5592387",
    "favorite": "!0c3a3de4",

    "log": [],
}

log_area: Optional[ui.textarea] = None
fav_in: Optional[ui.input] = None

row_tcp: Optional[ui.row] = None
row_usb: Optional[ui.row] = None
row_ble: Optional[ui.row] = None

serial_sel: Optional[ui.select] = None
ble_sel: Optional[ui.select] = None


def normalize_ble_address(value: str) -> str:
    s = value.strip().upper()
    if len(s) == 17 and s.count(":") == 5:
        return s
    return value.strip()


ui.add_head_html(
    """
    <style>
      .page-wrap { max-width: 1200px; margin: 0 auto; }
      .ag-theme-alpine { border-radius: 10px; overflow: hidden; }
      .nicegui-content { padding-top: 12px; }
      .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
      .muted { color: #6b7280; }
    </style>
    """
)


def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    state["log"].append(f"[{ts}] {msg}")
    if len(state["log"]) > 400:
        state["log"] = state["log"][-400:]
    if log_area:
        log_area.value = "\n".join(state["log"])


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
    ports += sorted(glob.glob("COM[0-9]*"))
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


async def scan_ble_devices() -> List[Tuple[str, str]]:
    try:
        from bleak import BleakScanner  # type: ignore
    except Exception as e:
        log(f"❌ Bleak non disponibile: {e} (pip install bleak)")
        return []
    try:
        devices = await BleakScanner.discover(timeout=5.0)
        results: List[Tuple[str, str]] = []
        for d in devices:
            name = (d.name or "").strip()
            addr = (d.address or "").strip()
            if not addr:
                continue
            label = f"{name} ({addr})" if name else addr
            results.append((addr, label))
        return results
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
    global iface
    try:
        if iface:
            iface.close()
        iface = None
        if not silent:
            log("🔌 Disconnesso")
        refresh_nodes.refresh()
    except Exception as e:
        iface = None
        log(f"⚠️ Errore disconnect: {e}")
        refresh_nodes.refresh()


def connect() -> None:
    global iface
    disconnect(silent=True)

    mode = state["conn_mode"]
    try:
        if mode == "TCP":
            iface = TCPInterface(hostname=state["host"], portNumber=int(state["tcp_port"]))
            log(f"✅ Connesso via TCP a {state['host']}:{state['tcp_port']}")

        elif mode == "USB":
            sel = state["serial_port"]
            dev = None if sel == AUTO else str(sel).strip()
            if dev == "":
                dev = None
            iface = SerialInterface(devPath=dev)
            log(f"✅ Connesso via USB/Seriale a {dev or '(auto)'}")

        elif mode == "BLE":
            sel = state["ble_address"]
            addr = None if sel == AUTO else normalize_ble_address(str(sel))
            if addr == "":
                addr = None
            iface = BLEInterface(address=addr)
            log(f"✅ Connesso via BLE a {addr or '(auto/paired)'}")

        else:
            log(f"❌ Modalità sconosciuta: {mode}")
            iface = None

        refresh_nodes.refresh()

    except Exception as e:
        iface = None
        log(f"❌ Connessione fallita ({mode}): {e}")
        refresh_nodes.refresh()


def set_favorite_remote() -> None:
    if not iface:
        log("❌ Non connesso.")
        return
    dest = format_node_id(state["dest"].strip())
    fav = format_node_id(state["favorite"].strip())

    log(f"🧠 CLI equivalente:\nmeshtastic ({state['conn_mode']}) --dest '{dest}' --set-favorite-node '{fav}'")
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


@ui.refreshable
def refresh_nodes() -> None:
    ui.label("Nodi visibili (NodeDB locale del controllore):").classes("text-subtitle2")

    if not iface:
        ui.label("— non connesso —").classes("muted")
        return

    rows = build_rows()

    grid = ui.aggrid(
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
            "rowData": rows,
            "rowSelection": "single",
            "animateRows": True,
        }
    ).classes("ag-theme-alpine w-full").style("height: 520px;")

    def on_row_clicked(e: Any) -> None:
        data = e.args.get("data") if isinstance(e.args, dict) else None
        if not isinstance(data, dict):
            return
        nid = data.get("id", "")
        if nid:
            state["favorite"] = nid
            if fav_in:
                fav_in.value = nid
            log(f"➡️ Selezionato per favorite: {nid}")

    def on_cell_clicked(e: Any) -> None:
        if not isinstance(e.args, dict):
            return
        col = e.args.get("colId") or (e.args.get("colDef") or {}).get("field")
        if col != "id":
            return
        value = e.args.get("value") or (e.args.get("data") or {}).get("id")
        if value:
            js_copy_to_clipboard(str(value))

    grid.on("rowClicked", on_row_clicked)
    grid.on("cellClicked", on_cell_clicked)


def refresh_serial_ports() -> None:
    ports = list_serial_ports()
    # sempre includere AUTO
    opts = {AUTO: "(auto)"} | {p: p for p in ports}
    if serial_sel:
        serial_sel.options = opts
        # se value non è nelle options, reset ad AUTO
        if state["serial_port"] not in opts:
            custom = str(state["serial_port"]).strip()
            if custom:
                opts[custom] = f"{custom} (manuale)"
                serial_sel.options = opts
                serial_sel.value = custom
            else:
                state["serial_port"] = AUTO
                serial_sel.value = AUTO
    log(f"🔄 Porte seriali trovate: {len(ports)}")


async def do_ble_scan_and_update() -> None:
    results = await scan_ble_devices()
    opts = {AUTO: "(auto/paired)"} | {normalize_ble_address(addr): label for addr, label in results}
    if ble_sel:
        ble_sel.options = opts
        if state["ble_address"] not in opts:
            custom = normalize_ble_address(str(state["ble_address"]))
            if custom:
                state["ble_address"] = custom
                opts[custom] = f"{custom} (manuale)"
                ble_sel.options = opts
                ble_sel.value = custom
            else:
                state["ble_address"] = AUTO
                ble_sel.value = AUTO
    log(f"🔎 BLE scan: {len(results)} device(s)")


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

        ui.button("CONNECT", on_click=connect)
        ui.button("DISCONNECT", on_click=lambda: disconnect(silent=False))

    # TCP
    row_tcp = ui.row().classes("w-full items-end")
    with row_tcp:
        ui.input("Host (TCP)", value=state["host"], on_change=lambda e: state.update(host=e.value)).classes("w-72")
        ui.number("TCP port", value=state["tcp_port"], format="%.0f",
                  on_change=lambda e: state.update(tcp_port=int(e.value))).classes("w-40")
        ui.label("Tip: TCP = radio con WiFi attivo").classes("muted")

    # USB
    row_usb = ui.row().classes("w-full items-end")
    with row_usb:
        serial_sel = ui.select(
            label="Porta USB/Seriale",
            options={AUTO: "(auto)"},
            value=state["serial_port"],
            on_change=lambda e: state.update(serial_port=e.value),
        ).classes("w-96")
        ui.input(
            "Porta manuale (override)",
            placeholder="es. COM7 o /dev/ttyUSB0",
            on_change=lambda e: state.update(serial_port=e.value or AUTO),
        ).classes("w-72")
        ui.button("↻ Refresh porte", on_click=refresh_serial_ports)
        ui.label("Se scegli (auto), prova a trovare una radio da solo").classes("muted")

    # BLE
    row_ble = ui.row().classes("w-full items-end")
    with row_ble:
        ble_sel = ui.select(
            label="BLE device",
            options={AUTO: "(auto/paired)"},
            value=state["ble_address"],
            on_change=lambda e: state.update(ble_address=e.value),
        ).classes("w-96")
        ui.input(
            "MAC BLE manuale (override)",
            placeholder="AA:BB:CC:DD:EE:FF",
            on_change=lambda e: state.update(ble_address=normalize_ble_address(e.value) or AUTO),
        ).classes("w-72")
        ui.button("🔎 Scan BLE", on_click=lambda: asyncio.create_task(do_ble_scan_and_update()))
        ui.label("BLE in VM/LXC può richiedere pass-through del controller").classes("muted")

    set_conn_rows_visibility()
    refresh_serial_ports()

    ui.separator()

    with ui.row().classes("w-full items-end"):
        ui.input("Dest remoto (admin)", value=state["dest"], on_change=lambda e: state.update(dest=e.value)).classes("w-72")
        fav_in = ui.input("Nodo da favoritare", value=state["favorite"], on_change=lambda e: state.update(favorite=e.value)).classes("w-72")
        ui.button("⭐ SET FAVORITE (REMOTE)", on_click=set_favorite_remote)

    ui.separator()
    refresh_nodes()

    ui.separator()
    ui.label("Log:").classes("text-subtitle2")
    log_area = ui.textarea(value="", placeholder="log...").props("readonly").classes("w-full").style("height: 220px;")


ui.run(port=8080)
