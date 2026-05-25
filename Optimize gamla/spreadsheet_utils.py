"""
Spreadsheet helper utilities for FreeCAD.

- Cell addressing
- Safe get/set
- Quantity parsing / formatting
- Parameter bounds handling
"""

from __future__ import annotations
import FreeCAD as App
from .optimize_config import SPREADSHEET_NAME


# =========================
# Core helpers
# =========================


def cell(col, row):
    col = "".join(ch for ch in str(col).strip().upper() if ch.isalpha())
    return f"{col}{int(row)}"


def safe_get(ss, addr):
    try:
        return ss.get(addr)
    except Exception:
        try:
            return ss.getContents(addr)
        except Exception:
            return None


def safe_set(ss, addr, value):
    try:
        ss.set(addr, value)
        return True
    except Exception:
        return False


# =========================
# Quantity helpers
# =========================


def parse_quantity(val):
    """
    Parse FreeCAD quantity or raw value.
    Returns (float_value, unit | None)
    """
    if val is None:
        return None, None

    s = str(val).replace("\u2212", "-").replace(",", ".").strip()

    try:
        q = App.Units.Quantity(s)
        parts = q.UserString.split()
        unit = parts[-1] if len(parts) > 1 else None
        return float(q.Value), unit
    except Exception:
        try:
            return float(s), None
        except Exception:
            return None, None


def format_value(value, unit):
    if value is None:
        return ""
    return f"{value} {unit}" if unit else str(value)


def get_quantity(ss, addr):
    return parse_quantity(safe_get(ss, addr))[0]


def set_quantity(ss, addr, value, unit):
    safe_set(ss, addr, format_value(value, unit))


# =========================
# Parameter handling
# =========================


def set_params_by_name(ss, param_map):
    """
    Sätter värden i kolumn B baserat på variabelnamn.
    param_map: dict { "Comp M Radius": 22.19, "Length": 25.0, ... }
    Respekterar bounds om de finns.
    """
    info = read_param_bounds(ss)
    lookup = {name: (row, unit, lohi) for name, row, lohi, unit, _ in info}

    for name, new_value in param_map.items():
        if name not in lookup:
            App.Console.PrintError(f"[set_params_by_name] Okänt namn: {name}\n")
            continue

        row, unit, (lo, hi) = lookup[name]

        # Clamp värdet inom bounds
        v = new_value
        if lo is not None:
            v = max(v, lo)
        if hi is not None:
            v = min(v, hi)

        # Sätt värdet i kolumn B
        addr = cell("B", row)
        set_quantity(ss, addr, v, unit)
        # App.Console.PrintMessage(f"[set_params_by_name] {name} → {v} {unit or ''}\n")


def set_param_B(ss, row, new_value):
    """
    Set parameter value in column B while respecting bounds in C/D.
    Missing bounds are auto-filled from B.
    """

    b_raw = safe_get(ss, cell("B", row))
    b_val, unit = parse_quantity(b_raw)

    c_val = get_quantity(ss, cell("C", row))
    d_val = get_quantity(ss, cell("D", row))

    # Normalize bounds
    if c_val is None and d_val is None:
        lo = hi = b_val
        set_quantity(ss, cell("C", row), lo, unit)
        set_quantity(ss, cell("D", row), hi, unit)

    elif c_val is None:
        lo, hi = b_val, d_val
        set_quantity(ss, cell("C", row), lo, unit)

    elif d_val is None:
        lo, hi = c_val, b_val
        set_quantity(ss, cell("D", row), hi, unit)

    else:
        lo, hi = sorted((c_val, d_val))

    # Clamp value
    v = new_value
    if lo is not None:
        v = max(v, lo)
    if hi is not None:
        v = min(v, hi)

    set_quantity(ss, cell("B", row), v, unit)


def read_param_bounds(ss):
    """
    Read parameter bounds from spreadsheet.

    Expected layout:
      A: name
      B: current value
      C: min (optional)
      D: max (optional)

    Returns:
      list of (name, row, (lo, hi), unit, current_value)


    Typ exempel på returvärde:
        [
            ("Width", 2, (10.0, 40.0), "mm", 25.0),
            ("Height", 3, (None, 20.0), "mm", 12.0),
            ("Depth", 4, (18.0, None), "mm", 15.0),
            ("Radius", 5, (None, None), "mm", 8.0),
        ]

    """

    out = []
    row = 2

    while True:
        name = safe_get(ss, cell("A", row))
        b_raw = safe_get(ss, cell("B", row))

        if not (name or b_raw):
            break

        pname = str(name).strip() if name else f"Row{row}"
        b_val, unit = parse_quantity(b_raw)

        c_val = get_quantity(ss, cell("C", row))
        d_val = get_quantity(ss, cell("D", row))

        if c_val is None and d_val is None:
            lo = hi = b_val
        else:
            values = [v for v in (c_val, d_val, b_val) if v is not None]
            lo = min(values)
            hi = max(values)

        out.append((pname, row, (lo, hi), unit, b_val))
        row += 1

    return out


# =========================
# Document / Sheet helpers
# =========================


def clear_sheet(doc: App.Document, sheet_name: str):
    """
    Clearing of Spreadsheet in a document using clearAll().
    Prints error if sheet is missing or if clearAll fails.
    """
    if doc is None:
        App.Console.PrintError("[clear_sheet] Dokument är None\n")
        return

    ss = doc.getObject(sheet_name)
    if ss is None:
        App.Console.PrintError(f"[clear_sheet] Hittar inget Sheet med namn '{sheet_name}'\n")
        return

    try:
        ss.clearAll()
    except Exception as e:
        App.Console.PrintError(f"[clear_sheet] clearAll misslyckades: {e}\n")


def remove_objects_by_name(doc: App.Document, *names: str) -> int:
    """
    Remove objects from the document by their label/name.
    Returns number of successfully removed objects.

    OBS: FreeCAD skiljer på .Name (unik intern id) och .Label (visningsnamn).
    doc.getObject(name) söker på intern Name, medan doc.getObjectsByLabel(label)
    hittar alla med visningsnamnet. Vi försöker båda för robusthet.

    Exempel:
        remove_objects_by_name(App.ActiveDocument, "RayHits", "HitScores")

    """
    if doc is None:
        return 0

    removed = 0
    for nm in names:
        if not nm:
            continue

        # 1) Försök med intern Name (unik)
        obj = doc.getObject(nm)
        if obj is not None:
            try:
                doc.removeObject(obj.Name)
                removed += 1
                continue
            except Exception:
                pass

        # 2) Försök med Label (kan ge flera)
        try:
            matches = doc.getObjectsByLabel(nm) or []
        except Exception:
            matches = []

        for obj in matches:
            try:
                doc.removeObject(obj.Name)
                removed += 1
            except Exception:
                # Fortsätt med nästa
                pass

    return removed


def remove_spreadsheets_by_name(doc: App.Document, *labels_or_names: str) -> int:
    """
    Remove Spreadsheet-objekt från dokumentet genom att ange label eller intern Name.
    Returnerar antal borttagna.

    Vi filtrerar på TypeId 'Spreadsheet::Sheet' för att inte råka ta bort andra typer.
    """
    if doc is None:
        return 0

    removed = 0
    for nm in labels_or_names:
        if not nm:
            continue

        # 1) Direkt objekt via intern Name
        obj = doc.getObject(nm)
        if obj is not None and getattr(obj, "TypeId", "") == "Spreadsheet::Sheet":
            try:
                doc.removeObject(obj.Name)
                removed += 1
                continue
            except Exception:
                pass

        # 2) Leta via Label (kan vara flera)
        try:
            matches = doc.getObjectsByLabel(nm) or []
        except Exception:
            matches = []

        for obj in matches:
            if getattr(obj, "TypeId", "") != "Spreadsheet::Sheet":
                continue
            try:
                doc.removeObject(obj.Name)
                removed += 1
            except Exception:
                pass

    return removed


def apply_cad_params(params: dict):
    """
    Applicera CAD-parametrar på dokumentet.
    Används vid elit-restore (stop).
    Körs i main thread.
    """
    doc = App.ActiveDocument
    if not doc:
        return
    ss = doc.getObject(SPREADSHEET_NAME)
    if not ss:
        App.Console.PrintError("[apply_cad_params] Spreadsheet saknas\n")
        return
    set_params_by_name(ss, params)


def append_dict_to_sheet(sheet_name: str, data: dict):
    """
    Appendar en rad till ett Spreadsheet.
    - Skapar sheet om det inte finns
    - Första raden = kolumnnamn
    - data måste vara flat dict {str: number}
    """
    doc = App.ActiveDocument
    if not doc:
        return
    # --- hämta eller skapa sheet ---
    ss = doc.getObject(sheet_name)
    if not ss:
        ss = doc.addObject("Spreadsheet::Sheet", sheet_name)
    # --- läs existerande headers ---
    headers = []
    col = 1
    while True:
        cell = f"{chr(ord('A') + col - 1)}1"
        try:
            val = ss.get(cell)
        except Exception:
            val = None
        if not val:
            break
        headers.append(str(val))
        col += 1
    # --- init headers om tom ---
    if not headers:
        headers = list(data.keys())
        for i, name in enumerate(headers):
            cell = f"{chr(ord('A') + i)}1"
            ss.set(cell, name)
    # --- hitta nästa tomma rad ---
    row = 2
    while True:
        try:
            if ss.get(f"A{row}") in ("", None):
                break
        except Exception:
            App.Console.PrintError("[append_dict_to_sheet] whil true faller\n")
            break
        row += 1
    # --- skriv data ---
    for key, value in data.items():
        if key not in headers:
            continue  # ignorera okända kolumner
        col = headers.index(key)
        cell = f"{chr(ord('A') + col)}{row}"
        try:
            ss.set(cell, str(value))

        except Exception as e:
            App.Console.PrintError(f"[append_dict_to_sheet] Misslyckades skriva: cell={cell} key={key} value={value}  error={e}\n")

            # App.Console.PrintError("[append_dict_to_sheet] kan inte skriva till cell\n")
            pass  # ignorera icke-skrivbara värden
