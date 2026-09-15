"""PyBlox Studio — редактор в стиле Roblox Studio со скриптами."""
import os, sys, json, time, uuid, ssl, threading, copy, math, traceback

sys.excepthook = lambda *a: traceback.print_exception(*a)

# ============================================================
# Panda3D config
# ============================================================
try:
    from panda3d.core import loadPrcFileData, base
    loadPrcFileData('', 'basic-shaders-only true')
    loadPrcFileData('', 'sync-video false')
    loadPrcFileData('', 'textures-power-2 none')
except Exception as e:
    print("[prc]", e)
    base = None

try:
    from ursina import *
    from ursina import Ursina
except ImportError:
    print("pip install ursina"); sys.exit(1)

try:
    import paho.mqtt.client as mqtt
    MQTT_OK = True
except Exception:
    MQTT_OK = False

print("[Studio] imports OK")

SESSION_FILE = 'session.json'
PLACES_DIR = 'places'
BROKER, BROKER_PORT, BROKER_PATH = "broker.emqx.io", 8084, "/mqtt"
PLACES_TOPIC = "pyblox/v11/places"

# ============================================================
# App
# ============================================================
app = Ursina(title="PyBlox Studio")

# --- Скрываем крестик и dev-overlay ---
try:
    if hasattr(window, 'exit_button') and window.exit_button:
        window.exit_button.enabled = False
        window.exit_button.visible = False
        window.exit_button.position = (9999, 9999)
except Exception: pass

for _attr in ('fps_counter', 'collider_counter', 'entity_counter'):
    try:
        _obj = getattr(window, _attr, None)
        if _obj:
            _obj.enabled = False
            try: _obj.visible = False
            except Exception: pass
    except Exception: pass

try: application.development_mode = False
except Exception: pass

# ============================================================
# ФАКТИЧЕСКИЙ РАЗМЕР ОКНА (главный фикс)
# ============================================================
def _read_window_size():
    # 1) через Panda3D — самый надёжный
    try:
        if base is not None and base.win is not None:
            wp = base.win.getProperties()
            w = int(wp.getXSize())
            h = int(wp.getYSize())
            if w > 200 and h > 150:
                return w, h
    except Exception as e:
        print("[size] base.win:", e)
    # 2) через window.size
    try:
        w = int(window.size[0])
        h = int(window.size[1])
        if w > 200 and h > 150:
            return w, h
    except Exception: pass
    # 3) fallback
    return 1024, 576

W_PX, H_PX = _read_window_size()
ASPECT = W_PX / H_PX
print(f"[Studio] window {W_PX}x{H_PX}  aspect={ASPECT:.3f}")

# ============================================================
# КООРДИНАТЫ
# ============================================================
# В Ursina camera.ui: X от -aspect/2 до +aspect/2, Y от -0.5 до +0.5
def NX(x_px): return (x_px / W_PX - 0.5) * ASPECT
def NY(y_px): return 0.5 - (y_px / H_PX)
def SX(w_px): return (w_px / W_PX) * ASPECT
def SY(h_px): return h_px / H_PX

# ============================================================
# Утилиты
# ============================================================
def load_json(p, d):
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f: return json.load(f)
        except Exception: pass
    return d

def save_json(p, d):
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def C(r, g, b, a=255):
    try: return color.rgba32(int(r), int(g), int(b), int(a))
    except Exception:
        try: return color.rgba(r/255.0, g/255.0, b/255.0, a/255.0)
        except Exception: return color.white

# ============================================================
# Session
# ============================================================
session = load_json(SESSION_FILE, {})
username = session.get('user') or 'guest'
os.makedirs(PLACES_DIR, exist_ok=True)

# ============================================================
# MQTT
# ============================================================
mqtt_client = None
mqtt_ok = [False]

def mqtt_start():
    global mqtt_client
    if not MQTT_OK: return
    try:
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, transport="websockets",
                            client_id="studio-" + str(int(time.time()*1000) % 1000000))
        except Exception:
            c = mqtt.Client(transport="websockets",
                            client_id="studio-" + str(int(time.time()*1000) % 1000000))
        c.ws_set_options(path=BROKER_PATH)
        c.tls_set(cert_reqs=ssl.CERT_NONE); c.tls_insecure_set(True)
        def on_conn(cl, u, f, rc, p=None):
            if rc == 0: mqtt_ok[0] = True
        c.on_connect = on_conn
        c.connect(BROKER, BROKER_PORT, keepalive=30); c.loop_start()
        mqtt_client = c
    except Exception as e:
        print("[MQTT]", e)

threading.Thread(target=mqtt_start, daemon=True).start()

# ============================================================
# Цвета
# ============================================================
C_MENU      = C(240, 240, 240)
C_TABROW    = C(252, 252, 252)
C_TAB_ACT   = C(232, 232, 232)
C_RIBBON    = C(238, 238, 238)
C_BORDER    = C(200, 200, 200)
C_BTN       = C(248, 248, 248)
C_PANEL     = C(245, 245, 245)
C_PANEL_HDR = C(228, 228, 228)
C_PLACETAB  = C(232, 232, 232)
C_TEXT      = C(55, 55, 55)
C_TEXT_DIM  = C(150, 150, 150)
C_BLUE      = C(0, 120, 215)
C_SEL       = C(190, 220, 250)
C_WHITE     = C(255, 255, 255)
C_GROUND    = C(110, 145, 175)
C_GREEN     = C(60, 160, 60)
C_RED       = C(190, 60, 60)
C_ORANGE    = C(200, 130, 40)
C_PURPLE    = C(140, 90, 200)

# ============================================================
# 3D Scene
# ============================================================
try:
    editor_cam = EditorCamera()
    editor_cam.position = (18, 16, -20)
    editor_cam.look_at(Vec3(0, 2, 0))
    Entity(model='plane', scale=300, color=C_GROUND, collider='box', unlit=True)
    try:
        Entity(model=Grid(80, 80), rotation_x=90, scale=300,
               color=C(255, 255, 255, 45), y=0.02, unlit=True)
    except Exception: pass
    print("[Studio] 3D OK")
except Exception as e:
    print("[Studio] scene:", e)

# ============================================================
# UI helpers
# ============================================================
ui = camera.ui

def panel(x, y, w, h, col, z=0.05):
    try:
        return Entity(parent=ui, model='quad', color=col,
                      position=(NX(x + w/2), NY(y + h/2)),
                      scale=(SX(w), SY(h)), z=z, unlit=True)
    except Exception as e:
        print("[panel]", e); return None

def text_at(label, x, y, col=None, scale=1.0, z=0.2):
    if col is None: col = C_TEXT
    try:
        return Text(parent=ui, text=label,
                    position=(NX(x), NY(y)),
                    scale=scale, color=col, origin=(0, 0), z=z)
    except Exception as e:
        print("[text]", e); return None

def rect_btn(x, y, w, h, col, cb=None, z=0.1):
    try:
        b = Button(parent=ui, text='')
        b.color = col
        b.position = (NX(x + w/2), NY(y + h/2))
        b.scale = (SX(w), SY(h))
        b.z = z
        try: b.highlight_color = C(220, 232, 245)
        except Exception: pass
        if cb:
            try: b.on_click = cb
            except Exception: pass
        return b
    except Exception as e:
        print("[btn]", e); return None

def button(label, x, y, w, h, col, cb=None,
           tscale=1.0, tcol=None, z=0.1):
    if tcol is None: tcol = C_TEXT
    rect_btn(x, y, w, h, col, cb, z=z)
    text_at(label, x + w/2, y + h/2, tcol, tscale, z=z + 0.02)

def field_at(x, y, w, h, default="", z=0.15):
    try:
        f = InputField(parent=ui, default_value=default)
        f.color = C_WHITE
        f.position = (NX(x + w/2), NY(y + h/2))
        f.scale = (SX(w), SY(h))
        f.z = z
        return f
    except Exception as e:
        print("[field]", e); return None

def hline(x, y, w, col=C_BORDER, z=0.07):
    panel(x, y, w, 1, col, z)

def vline(x, y, h, col=C_BORDER, z=0.07):
    panel(x, y, 1, h, col, z)

# ============================================================
# State
# ============================================================
class State:
    def __init__(self):
        self.place_id = None
        self.place_name = "Place1"
        self.max_players = 15
        self.spawn = [0, 2, 0]
        self.parts = []
        self.ents = {}
        self.sel_id = None
        self.history = []
        self.redo_stack = []
        self.grid_size = 2.0
        self.grid_on = True
        self.next_part_num = 1
        self.dirty = False
        self.script_state = {}

st = State()
clipboard = [None]
log_label = [None]

def log(msg):
    print("[Studio]", msg)
    try:
        if log_label[0]: log_label[0].text = "Output: " + msg
    except Exception: pass

# ============================================================
# СКРИПТЫ
# ============================================================
SCRIPT_DEFS = {
    'rotate': {'label': 'Rotate', 'color': C_ORANGE, 'fields': ['axis', 'speed']},
    'float':  {'label': 'Float',  'color': C_BLUE,   'fields': ['amp', 'speed']},
    'pulse':  {'label': 'Pulse',  'color': C_PURPLE, 'fields': ['amp', 'speed']},
    'bounce': {'label': 'Bounce', 'color': C_GREEN,  'fields': ['amp', 'speed']},
}

def make_script(kind):
    if kind == 'rotate': return {'type': 'rotate', 'axis': 'y', 'speed': 60}
    if kind == 'float':  return {'type': 'float',  'amp': 0.5, 'speed': 2}
    if kind == 'pulse':  return {'type': 'pulse',  'amp': 0.3, 'speed': 2}
    if kind == 'bounce': return {'type': 'bounce', 'amp': 0.8, 'speed': 3}
    return {'type': 'rotate', 'axis': 'y', 'speed': 60}

def scripts_for(p):
    if 'scripts' not in p: p['scripts'] = []
    return p['scripts']

def add_script_to(p, kind):
    scripts_for(p).append(make_script(kind))
    st.dirty = True
    log(f"Added script {kind} to {p['name']}")

def remove_script(p, idx):
    try:
        scripts_for(p).pop(idx)
        st.dirty = True
    except Exception: pass

def apply_scripts():
    now = time.time()
    for p in st.parts:
        scripts = p.get('scripts', [])
        if not scripts: continue
        e = st.ents.get(p['id'])
        if not e: continue
        s_state = st.script_state.setdefault(p['id'], {
            't0': now,
            'base_pos': (p['x'], p['y'], p['z']),
            'base_rot': (p['rx'], p['ry'], p['rz']),
            'base_color': tuple(p['color']),
        })
        dt = now - s_state['t0']
        pos = list(s_state['base_pos'])
        rot = list(s_state['base_rot'])
        col = list(s_state['base_color'])
        for s in scripts:
            t = s.get('type')
            if t == 'rotate':
                axis = s.get('axis', 'y'); speed = s.get('speed', 60)
                deg = dt * speed
                if axis == 'x': rot[0] = s_state['base_rot'][0] + deg
                elif axis == 'y': rot[1] = s_state['base_rot'][1] + deg
                elif axis == 'z': rot[2] = s_state['base_rot'][2] + deg
            elif t == 'float':
                amp = s.get('amp', 0.5); speed = s.get('speed', 2)
                pos[1] = s_state['base_pos'][1] + math.sin(dt * speed) * amp
            elif t == 'pulse':
                amp = s.get('amp', 0.3); speed = s.get('speed', 2)
                k = 1 + math.sin(dt * speed) * amp
                col[0] = max(0, min(255, int(s_state['base_color'][0] * k)))
                col[1] = max(0, min(255, int(s_state['base_color'][1] * k)))
                col[2] = max(0, min(255, int(s_state['base_color'][2] * k)))
            elif t == 'bounce':
                amp = s.get('amp', 0.8); speed = s.get('speed', 3)
                pos[1] = s_state['base_pos'][1] + abs(math.sin(dt * speed)) * amp
        try:
            e.position = tuple(pos)
            e.rotation = tuple(rot)
            e.color = C(col[0], col[1], col[2])
        except Exception: pass

# ============================================================
# Части
# ============================================================
def make_color(rgbv):
    try: return C(rgbv[0], rgbv[1], rgbv[2])
    except Exception: return C(163, 162, 165)

def snap(v):
    if not st.grid_on: return v
    return round(v / st.grid_size) * st.grid_size

def shape_model(shape):
    return {'cube': 'cube', 'sphere': 'sphere', 'plane': 'quad'}.get(shape, 'cube')

def create_part_entity(p):
    try:
        e = Entity(model=shape_model(p.get('shape', 'cube')),
                   position=(p['x'], p['y'], p['z']),
                   scale=(p['sx'], p['sy'], p['sz']),
                   rotation=(p['rx'], p['ry'], p['rz']),
                   color=make_color(p['color']),
                   collider='box', unlit=True)
        e.part_id = p['id']
        return e
    except Exception as ex:
        print("[part]", ex); return None

def sync_part(p):
    e = st.ents.get(p['id'])
    if not e: return
    try:
        e.position = (p['x'], p['y'], p['z'])
        e.scale = (p['sx'], p['sy'], p['sz'])
        e.rotation = (p['rx'], p['ry'], p['rz'])
        e.color = make_color(p['color'])
    except Exception: pass
    st.script_state.pop(p['id'], None)
    if p['id'] == st.sel_id: update_sel_box()
    st.dirty = True

try:
    sel_box = Entity(model='wireframe_cube', color=C(70, 140, 240, 230),
                     scale=(1,1,1), enabled=False, unlit=True)
except Exception:
    sel_box = Entity(model='cube', color=C(70, 140, 240, 60),
                     scale=(1,1,1), enabled=False, unlit=True)

def update_sel_box():
    p = get_selected()
    if not p:
        sel_box.enabled = False; return
    sel_box.enabled = True
    sel_box.position = (p['x'], p['y'], p['z'])
    sel_box.scale = (p['sx']*1.02, p['sy']*1.02, p['sz']*1.02)
    try: sel_box.rotation = (p['rx'], p['ry'], p['rz'])
    except Exception: pass

def get_selected():
    if not st.sel_id: return None
    for p in st.parts:
        if p['id'] == st.sel_id: return p
    return None

def select_part(pid):
    st.sel_id = pid
    update_sel_box()
    refresh_explorer()
    refresh_properties()

# ============================================================
# History
# ============================================================
def push_history():
    try:
        s = json.dumps(st.parts, ensure_ascii=False)
        if not st.history or st.history[-1] != s:
            st.history.append(s)
            if len(st.history) > 50: st.history.pop(0)
            st.redo_stack.clear()
            st.dirty = True
    except Exception: pass

def apply_history(parts_json):
    for pid in list(st.ents.keys()):
        try: destroy(st.ents[pid])
        except Exception: pass
    st.ents = {}
    st.script_state.clear()
    st.parts = json.loads(parts_json)
    for p in st.parts:
        e = create_part_entity(p)
        if e: st.ents[p['id']] = e
    st.sel_id = None
    update_sel_box(); refresh_explorer(); refresh_properties()

def undo():
    if len(st.history) < 2: return
    st.redo_stack.append(st.history.pop())
    apply_history(st.history[-1])
    log("Undo")

def redo():
    if not st.redo_stack: return
    nxt = st.redo_stack.pop()
    st.history.append(nxt)
    apply_history(nxt)
    log("Redo")

# ============================================================
# Действия с частями
# ============================================================
def viewport_center():
    try:
        p = editor_cam.position + editor_cam.forward * 15
        return (snap(p.x), max(1, snap(p.y)), snap(p.z))
    except Exception: return (0, 1, 0)

def add_part(shape='cube', pos=None):
    if pos is None: pos = viewport_center()
    push_history()
    num = st.next_part_num; st.next_part_num += 1
    p = {'id': str(uuid.uuid4())[:8], 'name': f"{shape.capitalize()}_{num}",
         'shape': shape,
         'x': snap(pos[0]), 'y': snap(pos[1]), 'z': snap(pos[2]),
         'sx': 2.0, 'sy': 2.0, 'sz': 2.0,
         'rx': 0.0, 'ry': 0.0, 'rz': 0.0,
         'color': [163, 162, 165], 'transparency': 0,
         'scripts': []}
    st.parts.append(p)
    e = create_part_entity(p)
    if e: st.ents[p['id']] = e
    select_part(p['id'])
    log(f"Created: {p['name']}")

def delete_selected():
    if not st.sel_id: return
    push_history()
    e = st.ents.pop(st.sel_id, None)
    if e:
        try: destroy(e)
        except Exception: pass
    st.script_state.pop(st.sel_id, None)
    st.parts = [p for p in st.parts if p['id'] != st.sel_id]
    st.sel_id = None
    update_sel_box(); refresh_explorer(); refresh_properties()
    log("Deleted")

def duplicate_selected():
    p = get_selected()
    if not p: return
    push_history()
    np = copy.deepcopy(p)
    np['id'] = str(uuid.uuid4())[:8]
    st.next_part_num += 1
    np['name'] = f"{p['name']}_copy"
    np['x'] = p['x'] + snap(4); np['z'] = p['z'] + snap(4)
    st.parts.append(np)
    e = create_part_entity(np)
    if e: st.ents[np['id']] = e
    select_part(np['id'])
    log("Duplicated")

def copy_to_clip(p):
    clipboard[0] = copy.deepcopy(p); log("Copied")

def paste_from_clip():
    if not clipboard[0]: return
    push_history()
    np = copy.deepcopy(clipboard[0])
    np['id'] = str(uuid.uuid4())[:8]
    st.next_part_num += 1
    np['name'] = f"{clipboard[0]['name']}_{st.next_part_num}"
    np['x'] = clipboard[0]['x'] + snap(4); np['z'] = clipboard[0]['z'] + snap(4)
    st.parts.append(np)
    e = create_part_entity(np)
    if e: st.ents[np['id']] = e
    select_part(np['id'])
    log("Pasted")

# ============================================================
# Camera
# ============================================================
def focus_selected():
    p = get_selected()
    if not p: return
    try:
        d = max(p['sx'], p['sy'], p['sz']) * 3
        editor_cam.position = (p['x'] + d, p['y'] + d*0.7, p['z'] - d)
        editor_cam.look_at(Vec3(p['x'], p['y'], p['z']))
    except Exception: pass

def camera_view(which):
    try:
        if which == 'top':
            editor_cam.position = (0, 30, 0); editor_cam.look_at(Vec3(0, 0, 0))
        elif which == 'front':
            editor_cam.position = (0, 5, -25); editor_cam.look_at(Vec3(0, 2, 0))
        elif which == 'side':
            editor_cam.position = (-25, 5, 0); editor_cam.look_at(Vec3(0, 2, 0))
        elif which == 'persp':
            editor_cam.position = (18, 16, -20); editor_cam.look_at(Vec3(0, 2, 0))
    except Exception: pass

# ============================================================
# File actions
# ============================================================
def save_place():
    if not st.place_id: st.place_id = str(uuid.uuid4())[:8]
    data = {'id': st.place_id, 'name': st.place_name, 'author': username,
            'max_players': st.max_players, 'spawn': st.spawn,
            'blocks': st.parts, 'updated': time.time()}
    save_json(os.path.join(PLACES_DIR, st.place_id + '.json'), data)
    st.dirty = False
    log(f"Saved: {st.place_id}.json")

def publish_place():
    if not mqtt_ok[0] or not mqtt_client:
        log("No network"); return
    if not st.place_id: st.place_id = str(uuid.uuid4())[:8]
    save_place()
    data = {'id': st.place_id, 'name': st.place_name, 'author': username,
            'max_players': st.max_players, 'spawn': st.spawn,
            'blocks': st.parts, 'updated': time.time()}
    try:
        mqtt_client.publish(f"{PLACES_TOPIC}/{st.place_id}",
                            json.dumps(data), qos=1, retain=True)
        log(f"Published: {st.place_name}")
    except Exception as e:
        log("Publish error: " + str(e))

def new_place():
    push_history()
    for pid in list(st.ents.keys()):
        try: destroy(st.ents[pid])
        except Exception: pass
    st.parts = []; st.ents = {}; st.sel_id = None; st.script_state.clear()
    st.place_id = None; st.place_name = "Place1"
    st.spawn = [0, 2, 0]; st.max_players = 15; st.next_part_num = 1
    update_sel_box(); refresh_explorer(); refresh_properties()
    log("New place")

def load_last_saved():
    if not os.path.isdir(PLACES_DIR): log("No places/"); return
    files = [f for f in os.listdir(PLACES_DIR) if f.endswith('.json')]
    if not files: log("No saves"); return
    files.sort(key=lambda f: os.path.getmtime(os.path.join(PLACES_DIR, f)),
               reverse=True)
    data = load_json(os.path.join(PLACES_DIR, files[0]), None)
    if not data: log("Bad file"); return
    push_history()
    for pid in list(st.ents.keys()):
        try: destroy(st.ents[pid])
        except Exception: pass
    st.parts = []; st.ents = {}; st.sel_id = None; st.script_state.clear()
    st.place_id = data.get('id')
    st.place_name = data.get('name', 'Place1')
    st.max_players = int(data.get('max_players', 15))
    st.spawn = data.get('spawn', [0, 2, 0])
    st.next_part_num = len(data.get('blocks', [])) + 1
    for p in data.get('blocks', []):
        if 'name' not in p:
            p['name'] = f"Cube_{st.next_part_num}"; st.next_part_num += 1
        if 'shape' not in p: p['shape'] = 'cube'
        if 'transparency' not in p: p['transparency'] = 0
        if 'scripts' not in p: p['scripts'] = []
        st.parts.append(p)
        e = create_part_entity(p)
        if e: st.ents[p['id']] = e
    update_sel_box(); refresh_explorer(); refresh_properties()
    log(f"Loaded: {st.place_name}")

# ============================================================
# LAYOUT
# ============================================================
MENU_H     = 26
TABROW_H   = 34
RIBBON_H   = 86
PLACETAB_H = 24
TOP_TOTAL  = MENU_H + TABROW_H + RIBBON_H
VIEW_TOP   = TOP_TOTAL + PLACETAB_H

RIGHT_W    = 340
OUTPUT_H   = 26
OUTPUT_Y   = H_PX - OUTPUT_H

panel(0, 0, W_PX, MENU_H, C_MENU, z=0.04)
hline(0, MENU_H - 1, W_PX, C_BORDER, z=0.05)

panel(0, MENU_H, W_PX, TABROW_H, C_TABROW, z=0.04)
hline(0, MENU_H + TABROW_H - 1, W_PX, C_BORDER, z=0.05)

panel(0, MENU_H + TABROW_H, W_PX, RIBBON_H, C_RIBBON, z=0.04)
hline(0, TOP_TOTAL - 1, W_PX, C_BORDER, z=0.05)

panel(0, TOP_TOTAL, W_PX, PLACETAB_H, C_PLACETAB, z=0.04)
hline(0, VIEW_TOP - 1, W_PX, C_BORDER, z=0.05)

panel(W_PX - RIGHT_W, VIEW_TOP, RIGHT_W, H_PX - VIEW_TOP - OUTPUT_H, C_PANEL, z=0.04)
vline(W_PX - RIGHT_W, VIEW_TOP, H_PX - VIEW_TOP - OUTPUT_H, C_BORDER, z=0.05)

panel(0, OUTPUT_Y, W_PX, OUTPUT_H, C_PANEL_HDR, z=0.04)
hline(0, OUTPUT_Y, W_PX, C_BORDER, z=0.05)

# ============================================================
# MENU BAR
# ============================================================
mx = 12
for name in ["File", "Edit", "View", "Plugins", "Test", "Window", "Help"]:
    text_at(name, mx, MENU_H/2, C_TEXT, 0.9)
    mx += 54

# ============================================================
# TAB ROW
# ============================================================
y_mid = MENU_H + TABROW_H/2
text_at("Test", 12, y_mid, C_TEXT, 0.9)
text_at("v",  50, y_mid, C_TEXT_DIM, 0.85)
vline(70, MENU_H + 5, TABROW_H - 10, C_BORDER, z=0.06)
text_at(">",  86, y_mid, C_TEXT, 1.1)
text_at("||", 110, y_mid, C_TEXT, 0.95)
text_at("[]", 132, y_mid, C_RED, 1.0)

tab_x = 160
tabs = [("Home", True), ("Avatar", False), ("UI", False),
        ("Script", False), ("Model", False), ("Plugins", False)]
for label, active in tabs:
    tw = 70
    if active:
        panel(tab_x, MENU_H + 3, tw, TABROW_H - 3, C_TAB_ACT, z=0.06)
        panel(tab_x, MENU_H + TABROW_H - 3, tw, 2, C_BLUE, z=0.08)
        text_at(label, tab_x + tw/2, y_mid, C_TEXT, 0.95, z=0.2)
    else:
        text_at(label, tab_x + tw/2, y_mid, C_TEXT_DIM, 0.9, z=0.15)
    tab_x += tw + 3

text_at("Untitled", W_PX - 230, y_mid, C_TEXT_DIM, 0.9)
text_at("+",        W_PX - 160, y_mid, C_TEXT_DIM, 1.1)

# ============================================================
# RIBBON
# ============================================================
RIB_Y = MENU_H + TABROW_H
BTN_Y = RIB_Y + 8
BTN_H = RIBBON_H - 16
BTN_W = 62
GAP = 3

def ribbon_btn(icon, label, x, cb=None, color=None):
    if color is None: color = C_BTN
    rect_btn(x, BTN_Y, BTN_W, BTN_H, color, cb, z=0.1)
    text_at(icon, x + BTN_W/2, BTN_Y + 22, C_TEXT, 1.5, z=0.2)
    text_at(label, x + BTN_W/2, BTN_Y + BTN_H - 10, C_TEXT, 0.78, z=0.2)

x = 8
ribbon_btn("N", "New",     x, new_place, C_GREEN); x += BTN_W + GAP
ribbon_btn("S", "Save",    x, save_place);         x += BTN_W + GAP
ribbon_btn("L", "Load",    x, load_last_saved);    x += BTN_W + GAP
ribbon_btn("P", "Publish", x, publish_place, C_ORANGE); x += BTN_W + 8
vline(x, RIB_Y + 12, RIBBON_H - 24, C_BORDER, z=0.06); x += 10

ribbon_btn("#", "Part",    x, lambda: add_part('cube', viewport_center())); x += BTN_W + GAP
ribbon_btn("O", "Sphere",  x, lambda: add_part('sphere', viewport_center())); x += BTN_W + GAP
ribbon_btn("_", "Plane",   x, lambda: add_part('plane', viewport_center())); x += BTN_W + 8
vline(x, RIB_Y + 12, RIBBON_H - 24, C_BORDER, z=0.06); x += 10

ribbon_btn("C", "Copy", x, lambda: copy_to_clip(get_selected()) if get_selected() else log("No sel")); x += BTN_W + GAP
ribbon_btn("V", "Paste", x, paste_from_clip);  x += BTN_W + GAP
ribbon_btn("D", "Dup",   x, duplicate_selected); x += BTN_W + GAP
ribbon_btn("<", "Undo",  x, undo); x += BTN_W + GAP
ribbon_btn(">", "Redo",  x, redo)

# ============================================================
# PLACE TAB
# ============================================================
panel(0, TOP_TOTAL, 130, PLACETAB_H, C_WHITE, z=0.06)
panel(0, TOP_TOTAL + PLACETAB_H - 1, 130, 1, C_BORDER, z=0.07)
text_at("[P]", 14, TOP_TOTAL + PLACETAB_H/2, C_BLUE, 1.0, z=0.2)
text_at("Place1", 38, TOP_TOTAL + PLACETAB_H/2, C_TEXT, 0.9, z=0.2)
text_at("x", 116, TOP_TOTAL + PLACETAB_H/2, C_TEXT_DIM, 1.0, z=0.2)

# ============================================================
# EXPLORER
# ============================================================
EXP_X = W_PX - RIGHT_W
EXP_W = RIGHT_W

panel(EXP_X, VIEW_TOP, EXP_W, 24, C_PANEL_HDR, z=0.07)
hline(EXP_X, VIEW_TOP + 24, EXP_W, C_BORDER, z=0.08)
text_at("Explorer", EXP_X + 12, VIEW_TOP + 12, C_TEXT, 0.95, z=0.2)
text_at("R M X", EXP_X + EXP_W - 46, VIEW_TOP + 12, C_TEXT_DIM, 0.85, z=0.2)

search_y = VIEW_TOP + 30
panel(EXP_X + 6, search_y, EXP_W - 12, 20, C_WHITE, z=0.08)
panel(EXP_X + 6, search_y + 19, EXP_W - 12, 1, C_BORDER, z=0.09)
text_at("Search", EXP_X + 14, search_y + 10, C_TEXT_DIM, 0.88, z=0.2)

TREE_Y0 = search_y + 26

static_tree = [
    ("-", "Workspace"),
    (".", "Players"),
    (".", "Lighting"),
    (".", "ReplicatedStorage"),
    (".", "ServerScriptService"),
    (".", "ServerStorage"),
    (".", "StarterGui"),
    (".", "StarterPack"),
    ("-", "StarterPlayer"),
    (".", "Teams"),
    (".", "SoundService"),
]
for i, (icon, name) in enumerate(static_tree):
    y_row = TREE_Y0 + i * 16 + 8
    text_at(icon, EXP_X + 10, y_row, C_TEXT_DIM, 0.9, z=0.2)
    text_at(name, EXP_X + 26, y_row, C_TEXT, 0.85, z=0.2)

# ============================================================
# EXPLORER — части
# ============================================================
explorer_widgets = []

def refresh_explorer():
    global explorer_widgets
    for w in explorer_widgets:
        try: destroy(w)
        except Exception: pass
    explorer_widgets = []

    y0 = TREE_Y0 + len(static_tree) * 16 + 8
    for i, part in enumerate(st.parts[:14]):
        yy = y0 + i * 16
        if yy > H_PX - OUTPUT_H - 220: break
        is_sel = part['id'] == st.sel_id
        bg = C_SEL if is_sel else C_WHITE
        b = rect_btn(EXP_X + 20, yy, EXP_W - 28, 14, bg,
                     (lambda pid=part['id']: select_part(pid)), z=0.15)
        if b: explorer_widgets.append(b)
        marker = "."
        try:
            if part.get('scripts'): marker = "-"
        except Exception: pass
        t_ = text_at(f"{marker} {part['name']}", EXP_X + 26, yy + 7,
                     C_TEXT, 0.82, z=0.2)
        if t_: explorer_widgets.append(t_)

# ============================================================
# PROPERTIES + SCRIPTS
# ============================================================
prop_widgets = []
prop_fields = {}

def clear_props():
    global prop_widgets, prop_fields
    for w in prop_widgets:
        try: destroy(w)
        except Exception: pass
    prop_widgets = []
    prop_fields = {}

def refresh_properties():
    clear_props()
    p = get_selected()

    # Properties — под Explorer
    y0 = TREE_Y0 + len(static_tree) * 16 + 8 + min(len(st.parts), 14) * 16 + 12
    max_y = H_PX - OUTPUT_H - 260
    if y0 > max_y:
        y0 = max_y
    if y0 < TREE_Y0 + 20:
        y0 = TREE_Y0 + 20

    ttl = text_at("- Properties", EXP_X + 12, y0, C_BLUE, 0.95, z=0.2)
    if ttl: prop_widgets.append(ttl)
    y0 += 22

    def row(lbl, key, val, place_kind=None, w=90):
        nonlocal y0
        if y0 > H_PX - OUTPUT_H - 18: return
        t_ = text_at(lbl, EXP_X + 14, y0, C_TEXT, 0.8, z=0.2)
        if t_: prop_widgets.append(t_)
        f = field_at(EXP_X + 145, y0 - 9, w, 18, str(val), z=0.15)
        if f:
            def submit(fo=f, k=key, pk=place_kind):
                try:
                    if pk == 'place_name':
                        st.place_name = (fo.text or "Place1")[:40]; st.dirty = True
                    elif pk == 'max_pl':
                        v = max(2, min(100, int(float(fo.text))))
                        st.max_players = v; fo.text = str(v); st.dirty = True
                    elif pk == 'spawn_x': st.spawn[0] = float(fo.text); st.dirty = True
                    elif pk == 'spawn_y': st.spawn[1] = float(fo.text); st.dirty = True
                    elif pk == 'spawn_z': st.spawn[2] = float(fo.text); st.dirty = True
                    else:
                        if not p: return
                        v = float(fo.text)
                        push_history(); p[k] = v; sync_part(p)
                except Exception: pass
            try: f.on_submit = submit
            except Exception: pass
            prop_fields[key] = f
            prop_widgets.append(f)
        y0 += 20

    if p:
        row("Name", 'name', p.get('name', ''))
        row("Position X", 'x', f"{p['x']:.2f}")
        row("Position Y", 'y', f"{p['y']:.2f}")
        row("Position Z", 'z', f"{p['z']:.2f}")
        row("Size X", 'sx', f"{p['sx']:.2f}")
        row("Size Y", 'sy', f"{p['sy']:.2f}")
        row("Size Z", 'sz', f"{p['sz']:.2f}")
        row("Rotation X", 'rx', f"{p['rx']:.2f}")
        row("Rotation Y", 'ry', f"{p['ry']:.2f}")
        row("Rotation Z", 'rz', f"{p['rz']:.2f}")

        y0 += 6
        t2 = text_at("- Scripts", EXP_X + 12, y0, C_PURPLE, 0.95, z=0.2)
        if t2: prop_widgets.append(t2)
        y0 += 22

        sx = EXP_X + 14
        for kind, info in SCRIPT_DEFS.items():
            bw = 72
            def add_cb(k=kind, pp=p):
                add_script_to(pp, k); refresh_properties()
            rect_btn(sx, y0 - 10, bw, 18, info['color'], add_cb, z=0.15)
            t_ = text_at("+ " + info['label'], sx + bw/2, y0, C_WHITE, 0.75, z=0.2)
            if t_: prop_widgets.append(t_)
            sx += bw + 4
        y0 += 24

        scr_list = scripts_for(p)
        for idx, s in enumerate(scr_list):
            if y0 > H_PX - OUTPUT_H - 22: break
            kind = s.get('type', '?')
            info = SCRIPT_DEFS.get(kind, {'label': kind, 'color': C_TEXT_DIM})

            rect_btn(EXP_X + 14, y0 - 10, 90, 18, info['color'], None, z=0.14)
            t_ = text_at(info['label'], EXP_X + 14 + 45, y0, C_WHITE, 0.75, z=0.2)
            if t_: prop_widgets.append(t_)

            params = ""
            if kind == 'rotate': params = f"axis={s.get('axis','y')} {s.get('speed',60)}/s"
            elif kind == 'float': params = f"amp={s.get('amp',0.5)} spd={s.get('speed',2)}"
            elif kind == 'pulse': params = f"amp={s.get('amp',0.3)} spd={s.get('speed',2)}"
            elif kind == 'bounce': params = f"amp={s.get('amp',0.8)} spd={s.get('speed',3)}"
            t2_ = text_at(params, EXP_X + 112, y0, C_TEXT, 0.72, z=0.2)
            if t2_: prop_widgets.append(t2_)

            def del_cb(i=idx, pp=p):
                remove_script(pp, i); refresh_properties()
            rect_btn(EXP_X + EXP_W - 32, y0 - 9, 20, 16, C_RED, del_cb, z=0.15)
            t3_ = text_at("x", EXP_X + EXP_W - 22, y0, C_WHITE, 0.9, z=0.2)
            if t3_: prop_widgets.append(t3_)

            y0 += 22
    else:
        row("Place name", 'place_name', st.place_name, 'place_name', w=110)
        row("Max players", 'max_players', st.max_players, 'max_pl', w=60)
        row("Spawn X", 'spawn_x', st.spawn[0], 'spawn_x', w=60)
        row("Spawn Y", 'spawn_y', st.spawn[1], 'spawn_y', w=60)
        row("Spawn Z", 'spawn_z', st.spawn[2], 'spawn_z', w=60)

        y0 += 8
        t_ = text_at("Select a part in Explorer", EXP_X + 14, y0,
                     C_TEXT_DIM, 0.78, z=0.2)
        if t_: prop_widgets.append(t_)
        y0 += 18
        t_ = text_at("to add scripts", EXP_X + 14, y0,
                     C_TEXT_DIM, 0.78, z=0.2)
        if t_: prop_widgets.append(t_)

# ============================================================
# OUTPUT
# ============================================================
log_label[0] = text_at("Output: Ready", 12, OUTPUT_Y + OUTPUT_H/2,
                       C_TEXT, 0.9, z=0.2)

# ============================================================
# INPUT
# ============================================================
def is_ui_entity(ent):
    e = ent
    while e:
        try:
            if e.parent is ui: return True
        except Exception: pass
        e = getattr(e, 'parent', None)
    return False

def field_active():
    try:
        for f in prop_fields.values():
            if f and getattr(f, 'active', False): return True
    except Exception: pass
    return False

def on_scene_click():
    try:
        ent = mouse.hovered_entity
        if ent and is_ui_entity(ent): return
        e = ent; found = None
        while e:
            if hasattr(e, 'part_id'): found = e; break
            e = getattr(e, 'parent', None)
        if found: select_part(found.part_id)
        else:
            st.sel_id = None
            update_sel_box(); refresh_explorer(); refresh_properties()
    except Exception as ex:
        print("[click]", ex)

def input(key):
    try:
        if key == 'left mouse down':
            on_scene_click(); return
        if field_active(): return

        ctrl = False
        try:
            ctrl = bool(held_keys['left control'] or held_keys['left ctrl'] or
                        held_keys['right control'] or held_keys['right ctrl'])
        except Exception: pass

        if ctrl and key == 'z': undo(); return
        if ctrl and key == 'y': redo(); return
        if ctrl and key == 'c':
            p = get_selected()
            if p: copy_to_clip(p)
            return
        if ctrl and key == 'v': paste_from_clip(); return
        if ctrl and key == 'd': duplicate_selected(); return

        if key == 'delete': delete_selected(); return
        if key == 'f': focus_selected(); return
        if key == '1': camera_view('top'); return
        if key == '2': camera_view('front'); return
        if key == '3': camera_view('side'); return
        if key == '4': camera_view('persp'); return

        p = get_selected()
        if not p: return
        step = st.grid_size if st.grid_on else 0.5
        rot = 15
        changed = False
        if key == 'left arrow':   p['x'] -= step; changed = True
        if key == 'right arrow':  p['x'] += step; changed = True
        if key == 'up arrow':     p['z'] += step; changed = True
        if key == 'down arrow':   p['z'] -= step; changed = True
        if key == 'page up':      p['y'] += step; changed = True
        if key == 'page down':    p['y'] -= step; changed = True

        try:
            shift = bool(held_keys['left shift'] or held_keys['right shift'])
        except Exception: shift = False
        if shift:
            if key == 'left arrow':  p['ry'] -= rot; changed = True
            if key == 'right arrow': p['ry'] += rot; changed = True
            if key == 'up arrow':    p['rx'] -= rot; changed = True
            if key == 'down arrow':  p['rx'] += rot; changed = True
        if ctrl:
            if key == 'up arrow':    p['sy'] += step; changed = True
            if key == 'down arrow':  p['sy'] -= step; changed = True
            if key == 'right arrow': p['sx'] += step; changed = True
            if key == 'left arrow':  p['sx'] -= step; changed = True
            if key == 'page up':     p['sz'] += step; changed = True
            if key == 'page down':   p['sz'] -= step; changed = True

        if changed:
            push_history(); sync_part(p); refresh_properties()
    except Exception as ex:
        print("[input]", ex)

# ============================================================
# UPDATE
# ============================================================
def update():
    try:
        apply_scripts()
    except Exception: pass

# ============================================================
# START
# ============================================================
if len(sys.argv) >= 3 and sys.argv[1] == '--load':
    load_path = sys.argv[2]
    if os.path.exists(load_path):
        try: load_last_saved()
        except Exception as e: print("[auto-load]", e)

push_history()
refresh_explorer()
refresh_properties()
log("PyBlox Studio ready.")
print("[Studio] === READY ===")
app.run()