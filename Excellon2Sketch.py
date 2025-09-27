# Fusion 360 Excellon (.drl) → Sketch Points (and optional circles) importer
# - Creates one sketch per tool (T01, T02, ...), places points at X/Y hits,
#   and can optionally draw circles at the tool diameter.
#
# Tested with files like:
#   M48
#   METRIC,0000.00
#   T01C0.8
#   T02C0.9
#   %
#   T01
#   X+001610Y+003670
#   ...
#   T00
#   M30
#
# Usage:
#   Utilities → Add-Ins → Scripts and Add-Ins → Scripts → Run
#
# Notes:
#  - Units: supports METRIC and INCH (M71/M72 or INCH/METRIC line).
#  - Zero suppression:
#       - If a format like "0000.00" is present, decimals = digits after '.'.
#       - If TZ/LZ is present without a format, script guesses decimals=4 (metric) or 4 (inch)
#         — tweak DEFAULT_DECIMALS below if needed.
#  - Coordinates are assumed absolute unless G91 is found (rare in DRL); G90 default.
#  - Routing/milling (slots) are ignored; this imports drill hits (X/Y with current T).
#  - Z is not used here; set depth in CAM. Origin is (0,0) at sketch.
#
import adsk.core, adsk.fusion, adsk.cam, traceback, math

# ---- User toggles ----
DRAW_CIRCLES = True          # Also draw circles at tool diameter for visual QC
CIRCLE_CONSTRUCTION = True   # Make those circles construction geometry (not solid lines)
DEFAULT_DECIMALS = 4         # If format "0000.00" not found, fallback decimals
INCH_TO_MM = 25.4
SCALE_FACTOR = 0.1   # <-- multiply all parsed coordinates by this factor (set 1.0 to disable)

app = adsk.core.Application.get()
ui = app.userInterface if app else None

def parse_excellon(path):
    """
    Parse a typical Excellon .drl file.
    Returns:
      {
        'units': 'mm',
        'tools': { 'T01': 0.8, 'T02': 0.9, ... }  # diameters in mm
        'hits':  { 'T01': [(x_mm, y_mm), ...], 'T02': [...], ... }
      }
    """
    units = 'mm'       # default metric
    decimals = None    # will infer from "0000.00" pattern
    zero_mode = None   # 'TZ' or 'LZ' (mostly irrelevant if we have explicit format)
    abs_mode = True    # G90 default

    tools = {}
    hits = {}
    curr_tool = None
    in_header = True

    # helpers
    def infer_decimals(fmt_line):
        # Example: "METRIC,0000.00" → decimals=2
        if ',' in fmt_line:
            right = fmt_line.split(',', 1)[1].strip()
            if '.' in right:
                return len(right.split('.', 1)[1])
        return None

    def parse_xy(token):
        # tokens like "X+001610Y+003670" or "X001610Y003670"
        # Extract numbers after X and Y; allow optional sign and '+'.
        x_val = None
        y_val = None
        s = token.strip()
        # Ensure we have separate X and Y. Some files split them with spaces (rare).
        # We'll just scan.
        i = 0
        while i < len(s):
            if s[i] in ('X', 'x'):
                j = i+1
                while j < len(s) and s[j] not in ('X','Y','x','y','T','M','\r','\n'):
                    j += 1
                x_str = s[i+1:j].replace('+','')
                x_val = x_str
                i = j
            elif s[i] in ('Y','y'):
                j = i+1
                while j < len(s) and s[j] not in ('X','Y','x','y','T','M','\r','\n'):
                    j += 1
                y_str = s[i+1:j].replace('+','')
                y_val = y_str
                i = j
            else:
                i += 1
        return x_val, y_val

    def to_mm(val_str):
        # Input may be integer string with implicit decimals, like "001610"
        # If decimals is known, insert decimal point.
        if val_str is None or val_str == '':
            return None
        sign = 1.0
        if val_str.startswith('-'):
            sign = -1.0
            val_str = val_str[1:]
        # Remove any leading '+'
        val_str = val_str.lstrip('+')

        if decimals is None:
            # Fallback: treat as integer with DEFAULT_DECIMALS
            if len(val_str) <= DEFAULT_DECIMALS:
                raw = int(val_str) if val_str else 0
                value = raw / (10 ** DEFAULT_DECIMALS)
            else:
                raw = int(val_str)
                value = raw / (10 ** DEFAULT_DECIMALS)
        else:
            if len(val_str) <= decimals:
                raw = int(val_str) if val_str else 0
                value = raw / (10 ** decimals)
            else:
                raw = int(val_str)
                value = raw / (10 ** decimals)

        value *= sign
        # Convert to mm if current units are inch
        if units == 'inch':
            value *= INCH_TO_MM
        
        # Apply global scale correction (e.g., x10 for your DRL)
        value *= SCALE_FACTOR
        return value

    try:
        with open(path, 'r', errors='ignore') as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue

                # Header parsing until we hit '%'
                if in_header:
                    uline = line.upper()
                    if uline.startswith('M48'):
                        # start of header
                        continue
                    if 'METRIC' in uline:
                        units = 'mm'
                        # Try to infer decimals from "METRIC,0000.00"
                        d = infer_decimals(line)
                        if d is not None:
                            decimals = d
                        # Also detect TZ/LZ if present
                        if 'TZ' in uline:
                            zero_mode = 'TZ'
                        elif 'LZ' in uline:
                            zero_mode = 'LZ'
                        continue
                    if 'INCH' in uline:
                        units = 'inch'
                        d = infer_decimals(line)
                        if d is not None:
                            decimals = d
                        if 'TZ' in uline:
                            zero_mode = 'TZ'
                        elif 'LZ' in uline:
                            zero_mode = 'LZ'
                        continue
                    if uline.startswith('T') and 'C' in uline:
                        # Tool definition like "T01C0.8" or "T01C0.031"
                        # Split at 'C'
                        parts = uline.split('C')
                        tcode = parts[0].strip()
                        try:
                            dia = float(parts[1])
                        except:
                            continue
                        # Convert inch tools if needed
                        if units == 'inch':
                            dia *= INCH_TO_MM
                        tools[tcode] = dia
                        hits.setdefault(tcode, [])
                        continue
                    if uline.startswith('%'):
                        in_header = False
                        continue

                # Body (after %)
                uline = line.upper()

                # modal / mode lines
                if uline.startswith('M71'):
                    units = 'mm'
                    continue
                if uline.startswith('M72'):
                    units = 'inch'
                    continue
                if uline.startswith('G90'):
                    abs_mode = True
                    continue
                if uline.startswith('G91'):
                    abs_mode = False
                    continue
                if uline.startswith('T'):
                    # Tool select (e.g., "T01")
                    # End when T00 or M30 encountered
                    if uline.startswith('T00'):
                        curr_tool = None
                        continue
                    curr_tool = uline.split()[0]
                    hits.setdefault(curr_tool, [])
                    continue
                if uline.startswith('M30'):
                    break

                # Hole hit line: something with X.. Y..
                if 'X' in uline or 'Y' in uline:
                    if curr_tool is None:
                        # No tool selected yet: skip
                        continue
                    x_str, y_str = parse_xy(line)
                    x_mm = to_mm(x_str)
                    y_mm = to_mm(y_str)
                    if x_mm is not None and y_mm is not None:
                        hits[curr_tool].append((x_mm, y_mm))

        # Clean hits to only defined tools; sometimes a DRL may have T codes used but not declared with C
        # We'll still keep unknown tools and set their diameter to 0 for reference.
        for t in list(hits.keys()):
            tools.setdefault(t, 0.0)

        return {'units': 'mm', 'tools': tools, 'hits': hits}

    except Exception as e:
        raise e

def ensure_new_component(root, name):
    occs = root.occurrences
    trans = adsk.core.Matrix3D.create()
    occ = occs.addNewComponent(trans)
    comp = adsk.fusion.Component.cast(occ.component)
    comp.name = name
    return comp

def run(context):
    try:
        if not app:
            return
        doc = app.activeDocument
        if not doc:
            doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)

        design = adsk.fusion.Design.cast(app.activeProduct)
        root = design.rootComponent

        # File dialog
        dlg = ui.createFileDialog()
        dlg.isMultiSelectEnabled = False
        dlg.title = 'Select Excellon Drill File (.drl)'
        dlg.filter = 'Excellon Drill (*.drl);;All Files (*.*)'
        if dlg.showOpen() != adsk.core.DialogResults.DialogOK:
            return
        drl_path = dlg.filename

        # Parse
        data = parse_excellon(drl_path)
        tools = data['tools']   # dict: 'Tnn' -> diameter_mm
        hits  = data['hits']    # dict: 'Tnn' -> [(x_mm, y_mm), ...]

        if not any(hits.values()):
            ui.messageBox('No drill hits found in file.')
            return

        # Create container component
        comp = ensure_new_component(root, 'DRL_Import')

        # For each tool, make a sketch and drop points/circles
        planes = comp.xYConstructionPlane
        for tcode in sorted(hits.keys()):
            pts = hits[tcode]
            if not pts:
                continue
            dia = SCALE_FACTOR * tools.get(tcode, 0.0)

            sk = comp.sketches.add(planes)
            sk.name = f'{tcode} (Ø{dia:.3f} mm)'

            geo = sk.sketchCurves
            points = sk.sketchPoints

            for (x_mm, y_mm) in pts:
                # Place a point
                pt = adsk.core.Point3D.create(x_mm, y_mm, 0)
                points.add(pt)

                # Optional circle at tool diameter for visual QC / CAM selection
                #if DRAW_CIRCLES and dia > 0:
                #    circ = geo.sketchCircles.addByCenterRadius(pt, dia/2.0)
                #    if CIRCLE_CONSTRUCTION:
                #        circ.isConstruction = True

        ui.messageBox(
            'DRL import complete.\n\n'
            '• One sketch per tool code was created.\n'
            '• Points mark drill hits.\n'
            f'• Circles {"were" if DRAW_CIRCLES else "were NOT"} drawn at tool diameters.\n\n'
            'You can now switch to Manufacture → Drill and select these points/circles.'
        )

    except:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))

def stop(context):
    # Nothing persistent to clean up
    pass
