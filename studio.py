"""PyBlox Studio — редактор в стиле Roblox Studio (тёмная тема, дерево, Lua, скролл)."""
import os, sys, json, time, uuid, ssl, threading, copy, math, traceback, random, re

sys.excepthook = lambda *a: traceback.print_exception(*a)

try:
    from panda3d.core import loadPrcFileData
    loadPrcFileData('', 'win-size 1280 720')
    loadPrcFileData('', 'window-title PyBlox Studio')
except Exception as e:
    print("[prc]", e)

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

try:
    from i18n import t, set_lang, load_lang, LANG
    I18N_OK = True
    load_lang()
except Exception as _e:
    I18N_OK = False
    def t(k, **kw): return k
    def set_lang(l): pass
    LANG = 'ru'

print("[Studio] imports OK")

SESSION_FILE = 'session.json'
PLACES_DIR = 'places'
BROKER, BROKER_PORT, BROKER_PATH = "broker.emqx.io", 8084, "/mqtt"
PLACES_TOPIC = "pyblox/v11/places"

# ============================================================
# App
# ============================================================
app = Ursina(title="PyBlox Studio")

try:
    if hasattr(window, 'exit_button') and window.exit_button:
        window.exit_button.enabled = False
        window.exit_button.visible = False
except Exception: pass

for _attr in ('fps_counter', 'collider_counter', 'entity_counter'):
    try:
        obj = getattr(window, _attr, None)
        if obj:
            obj.enabled = False
            try: obj.visible = False
            except Exception: pass
    except Exception: pass

try: application.development_mode = False
except Exception: pass

# ============================================================
# ВИРТУАЛЬНАЯ СИСТЕМА КООРДИНАТ
# ============================================================
REF_W = 1100.0

def current_aspect():
    try:
        a = float(window.aspect_ratio)
        if 0.5 < a < 4.0: return a
    except Exception: pass
    return 16.0 / 9.0

def REF_H(): return REF_W / current_aspect()
def NX(x_px):
    a = current_aspect()
    return (x_px / REF_W) * a - a * 0.5
def NY(y_px): return 0.5 - y_px / REF_H()
def SX(w_px): return (w_px / REF_W) * current_aspect()
def SY(h_px): return h_px / REF_H()

print(f"[Studio] virtual canvas {REF_W:.0f} wide  aspect={current_aspect():.3f}")

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
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[save_json]", e)

def C(r, g, b, a=255):
    try: return color.rgba32(int(r), int(g), int(b), int(a))
    except Exception:
        try: return color.rgba(r/255.0, g/255.0, b/255.0, a/255.0)
        except Exception: return color.white

session = load_json(SESSION_FILE, {})
if not isinstance(session, dict): session = {}
username = session.get('user') or 'guest'
os.makedirs(PLACES_DIR, exist_ok=True)

# ============================================================
# ТЕМЫ
# ============================================================
THEMES = {
    'light': {
        'MENU':(240,240,240),'TABROW':(252,252,252),'TAB_ACT':(232,232,232),
        'RIBBON':(238,238,238),'BORDER':(200,200,200),'BTN':(248,248,248),
        'BTN_HOV':(220,232,245),'BTN_SEL':(180,210,245),'PANEL':(245,245,245),
        'PANEL_HDR':(228,228,228),'PLACETAB':(232,232,232),'TEXT':(55,55,55),
        'TEXT_DIM':(150,150,150),'BLUE':(0,120,215),'SEL':(190,220,250),
        'WHITE':(255,255,255),'GROUND':(110,145,175),'MENU_BG':(250,250,250),
        'STATUS':(210,210,210),'TOOLBAR':(235,235,235),
        'EDITOR_BG':(40,44,52),'EDITOR_FG':(220,220,220),
    },
    'dark': {
        'MENU':(30,30,30),'TABROW':(37,37,38),'TAB_ACT':(45,45,48),
        'RIBBON':(37,37,38),'BORDER':(60,60,65),'BTN':(45,45,48),
        'BTN_HOV':(60,60,65),'BTN_SEL':(0,100,180),'PANEL':(37,37,38),
        'PANEL_HDR':(30,30,30),'PLACETAB':(37,37,38),'TEXT':(215,215,215),
        'TEXT_DIM':(130,130,130),'BLUE':(0,120,215),'SEL':(9,71,113),
        'WHITE':(45,45,48),'GROUND':(55,65,80),'MENU_BG':(45,45,48),
        'STATUS':(30,30,30),'TOOLBAR':(45,45,48),
        'EDITOR_BG':(20,20,22),'EDITOR_FG':(220,220,220),
    },
}

current_theme = [session.get('theme', 'light')]

# Цвета по умолчанию (перезапишутся через apply_theme)
C_MENU=C_TABROW=C_TAB_ACT=C_RIBBON=C_BORDER=C_BTN=C_BTN_HOV=C_BTN_SEL=None
C_PANEL=C_PANEL_HDR=C_PLACETAB=C_TEXT=C_TEXT_DIM=C_BLUE=C_SEL=C_WHITE=None
C_GROUND=C_MENU_BG=C_STATUSBAR=C_TOOLBAR=C_EDITOR_BG=C_EDITOR_FG=None
C_GREEN = C(60, 160, 60)
C_RED   = C(190, 60, 60)
C_ORANGE= C(200, 130, 40)
C_PURPLE= C(140, 90, 200)

def apply_theme(name):
    global C_MENU,C_TABROW,C_TAB_ACT,C_RIBBON,C_BORDER,C_BTN,C_BTN_HOV,C_BTN_SEL
    global C_PANEL,C_PANEL_HDR,C_PLACETAB,C_TEXT,C_TEXT_DIM,C_BLUE,C_SEL,C_WHITE
    global C_GROUND,C_MENU_BG,C_STATUSBAR,C_TOOLBAR,C_EDITOR_BG,C_EDITOR_FG
    if name not in THEMES: name = 'light'
    T = THEMES[name]
    C_MENU      = C(*T['MENU'])
    C_TABROW    = C(*T['TABROW'])
    C_TAB_ACT   = C(*T['TAB_ACT'])
    C_RIBBON    = C(*T['RIBBON'])
    C_BORDER    = C(*T['BORDER'])
    C_BTN       = C(*T['BTN'])
    C_BTN_HOV   = C(*T['BTN_HOV'])
    C_BTN_SEL   = C(*T['BTN_SEL'])
    C_PANEL     = C(*T['PANEL'])
    C_PANEL_HDR = C(*T['PANEL_HDR'])
    C_PLACETAB  = C(*T['PLACETAB'])
    C_TEXT      = C(*T['TEXT'])
    C_TEXT_DIM  = C(*T['TEXT_DIM'])
    C_BLUE      = C(*T['BLUE'])
    C_SEL       = C(*T['SEL'])
    C_WHITE     = C(*T['WHITE'])
    C_GROUND    = C(*T['GROUND'])
    C_MENU_BG   = C(*T['MENU_BG'])
    C_STATUSBAR = C(*T['STATUS'])
    C_TOOLBAR   = C(*T['TOOLBAR'])
    C_EDITOR_BG = C(*T['EDITOR_BG'])
    C_EDITOR_FG = C(*T['EDITOR_FG'])

apply_theme(current_theme[0])

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
# 3D Scene
# ============================================================
ground_ent = None
grid_ent = None
editor_cam = None
try:
    editor_cam = EditorCamera()
    editor_cam.position = (18, 16, -20)
    editor_cam.look_at(Vec3(0, 2, 0))
    ground_ent = Entity(model='plane', scale=300, color=C_GROUND,
                        collider='box', unlit=True)
    try:
        grid_ent = Entity(model=Grid(80, 80), rotation_x=90, scale=300,
                          color=C(255, 255, 255, 45), y=0.02, unlit=True)
    except Exception: pass
    print("[Studio] 3D OK")
except Exception as e:
    print("[Studio] scene:", e)

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
        self.script_dirty = set()
        self.tool = 'select'
        self.workspace_open = True

st = State()
clipboard = [None]
log_label = [None]
status_label = [None]

# Скроллы (в пикселях)
scroll_props = [0]
scroll_explorer = [0]
PROPS_CONTENT_H = [0]   # заполняется в refresh_properties
EXPLORER_CONTENT_H = [0]

# Все UI-элементы для полной пересборки
ui_all = []

def log(msg):
    print("[Studio]", msg)
    try:
        if log_label[0]: log_label[0].text = "Output: " + str(msg)
    except Exception: pass

def set_status(tool=None, msg=None):
    try:
        if not status_label[0]: return
        tool_txt = (tool if tool is not None else st.tool).upper()
        msg_txt = msg if msg is not None else "Ready"
        status_label[0].text = f"Tool: {tool_txt}  |  {msg_txt}"
    except Exception: pass

# ============================================================
# UI helpers — ignore=True для декоративных элементов
# ============================================================
def panel(x, y, w, h, col, z=0.05, track=True, ignore=True):
    try:
        p = Entity(parent=camera.ui, model='quad', color=col,
                   position=(NX(x + w/2), NY(y + h/2)),
                   scale=(SX(w), SY(h)), z=z, unlit=True)
        try: p.ignore = ignore
        except Exception: pass
        if track: ui_all.append(p)
        return p
    except Exception as e:
        print("[panel]", e); return None

def text_at(label, x, y, col=None, scale=1.0, z=0.2, track=True):
    if col is None: col = C_TEXT
    if label is None: label = " "
    label = str(label)
    label = label.replace("<", " ").replace(">", " ").replace("&", " ")
    if len(label.strip()) == 0: label = " "
    safe_z = min(z, 0.02)
    try:
        t_ = Text(parent=camera.ui, text=label,
                  position=(NX(x), NY(y)),
                  scale=scale, color=col, origin=(-0.5, 0.5), z=safe_z)
        try: t_.ignore = True
        except Exception: pass
        if track: ui_all.append(t_)
        return t_
    except Exception as e:
        print(f"[text '{label[:16]}']:", e); return None

def rect_btn(x, y, w, h, col, cb=None, z=0.1, track=True):
    if w < 2: w = 2
    if h < 2: h = 2
    try:
        b = Button(parent=camera.ui, text=' ')
        b.color = col
        b.position = (NX(x + w/2), NY(y + h/2))
        b.scale = (SX(w), SY(h))
        b.z = z
        try: b.highlight_color = C_BTN_HOV
        except Exception: pass
        try: b.ignore = False
        except Exception: pass
        if cb:
            try: b.on_click = cb
            except Exception: pass
        if track: ui_all.append(b)
        return b
    except Exception as e:
        print("[btn]", e); return None

def field_at(x, y, w, h, default=" ", z=0.15, track=True):
    if default is None: default = " "
    default = str(default)
    if len(default) == 0: default = " "
    try:
        f = InputField(parent=camera.ui, default_value=default)
        f.color = C_WHITE
        f.position = (NX(x + w/2), NY(y + h/2))
        f.scale = (SX(w), SY(h))
        f.z = z
        try: f.text_color = C_TEXT
        except Exception: pass
        if track: ui_all.append(f)
        return f
    except Exception as e:
        print("[field]", e); return None

def hline(x, y, w, col=None, z=0.07):
    if col is None: col = C_BORDER
    panel(x, y, w, 1, col, z)

def vline(x, y, h, col=None, z=0.07):
    if col is None: col = C_BORDER
    panel(x, y, 1, h, col, z)

def destroy_all_ui():
    global ui_all
    for w in ui_all:
        try: destroy(w)
        except Exception: pass
    ui_all = []

# ============================================================
# Lua → Python
# ============================================================
def _lua_expr(s):
    s = re.sub(r'\bnil\b', 'None', s)
    s = re.sub(r'\btrue\b', 'True', s)
    s = re.sub(r'\bfalse\b', 'False', s)
    s = s.replace('~=', '!=')
    s = re.sub(r'(?<=[\w\)\"\'])\.\.(?=[\w\(\"\'])', '+', s)
    s = re.sub(r'math\.random\s*\(([^,)]+),\s*([^)]+)\)',
               r'random.randint(int(\1), int(\2))', s)
    s = re.sub(r'math\.random\s*\(\s*\)', 'random.random()', s)
    s = re.sub(r'\bVector3\.new\s*\(', 'Vector3(', s)
    s = re.sub(r'\bColor3\.new\s*\(', 'Color3(', s)
    s = re.sub(r'\btostring\s*\(', 'str(', s)
    s = re.sub(r'\btonumber\s*\(', 'float(', s)
    return s

def lua_to_python(src):
    lines = src.split('\n')
    out = []; indent = 0
    for raw in lines:
        line = raw
        idx = line.find('--')
        if idx >= 0:
            before = line[:idx]
            if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
                line = before
        stripped = line.strip()
        if not stripped:
            out.append(''); continue
        if stripped == 'end' or stripped.startswith('end ') or stripped == 'end;':
            indent = max(0, indent - 1); continue
        m = re.match(r'^elseif\s+(.+?)\s+then$', stripped)
        if m:
            out.append('    ' * max(0, indent-1) + f'elif {_lua_expr(m.group(1))}:'); continue
        if stripped == 'else':
            out.append('    ' * max(0, indent-1) + 'else:'); continue
        is_block = False
        transformed = stripped
        m = re.match(r'^if\s+(.+?)\s+then$', stripped)
        if m:
            transformed = f'if {_lua_expr(m.group(1))}:'; is_block = True
        elif re.match(r'^while\s+.+?\s+do$', stripped):
            m2 = re.match(r'^while\s+(.+?)\s+do$', stripped)
            transformed = f'while {_lua_expr(m2.group(1))}:'; is_block = True
        elif re.match(r'^for\s+.+?\s+do$', stripped):
            m2 = re.match(r'^for\s+(.+?)\s+do$', stripped)
            body = m2.group(1)
            mf = re.match(r'^(\w+)\s*=\s*(.+?),\s*(.+?)(?:,\s*(.+?))?$', body)
            if mf:
                var = mf.group(1)
                a = _lua_expr(mf.group(2).strip())
                b = _lua_expr(mf.group(3).strip())
                c = mf.group(4)
                if c:
                    c = _lua_expr(c.strip())
                    transformed = f'for {var} in range(int({a}), int({b})+1, int({c})):'
                else:
                    transformed = f'for {var} in range(int({a}), int({b})+1):'
                is_block = True
        elif stripped.startswith('function '):
            mf = re.match(r'^function\s+([\w\.\:]+)\s*\((.*?)\)$', stripped)
            if mf:
                name = mf.group(1).replace('.', '_').replace(':', '_')
                transformed = f'def {name}({mf.group(2)}):'; is_block = True
        elif stripped.startswith('local '):
            transformed = _lua_expr(stripped[6:])
        else:
            transformed = _lua_expr(stripped)
        out.append('    ' * indent + transformed)
        if is_block: indent += 1
    return '\n'.join(out)

class Vector3:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.X = float(x); self.Y = float(y); self.Z = float(z)
    def __add__(self, o): return Vector3(self.X+o.X, self.Y+o.Y, self.Z+o.Z)
    def __sub__(self, o): return Vector3(self.X-o.X, self.Y-o.Y, self.Z-o.Z)
    def __mul__(self, s):
        if isinstance(s, Vector3): return Vector3(self.X*s.X, self.Y*s.Y, self.Z*s.Z)
        return Vector3(self.X*s, self.Y*s, self.Z*s)

class Color3:
    def __init__(self, r=0.0, g=0.0, b=0.0):
        self.R = float(r); self.G = float(g); self.B = float(b)

class _Vec3:
    def __init__(self, owner, prefix):
        object.__setattr__(self, '_owner', owner)
        object.__setattr__(self, '_prefix', prefix)
    def _get(self, ax):
        try: return float(self._owner._p.get(self._prefix + ax, 0.0))
        except Exception: return 0.0
    def _set(self, ax, v):
        try:
            self._owner._p[self._prefix + ax] = float(v)
            self._owner._sync()
        except Exception: pass
    @property
    def X(self): return self._get('x')
    @X.setter
    def X(self, v): self._set('x', v)
    @property
    def Y(self): return self._get('y')
    @Y.setter
    def Y(self, v): self._set('y', v)
    @property
    def Z(self): return self._get('z')
    @Z.setter
    def Z(self, v): self._set('z', v)

class LuaPartProxy:
    def __init__(self, p): object.__setattr__(self, '_p', p)
    def _sync(self):
        try: st.script_dirty.add(self._p['id'])
        except Exception: pass
    @property
    def Name(self): return self._p.get('name', 'Part')
    @Name.setter
    def Name(self, v): self._p['name'] = str(v)[:32]; self._sync()
    @property
    def Position(self): return _Vec3(self, '')
    @Position.setter
    def Position(self, v):
        self._p['x']=float(v.X); self._p['y']=float(v.Y); self._p['z']=float(v.Z); self._sync()
    @property
    def Rotation(self): return _Vec3(self, 'r')
    @Rotation.setter
    def Rotation(self, v):
        self._p['rx']=float(v.X); self._p['ry']=float(v.Y); self._p['rz']=float(v.Z); self._sync()
    @property
    def Size(self): return _Vec3(self, 's')
    @Size.setter
    def Size(self, v):
        self._p['sx']=float(v.X); self._p['sy']=float(v.Y); self._p['sz']=float(v.Z); self._sync()
    @property
    def Color(self):
        c = self._p.get('color', [163,162,165])
        return Color3(c[0]/255.0, c[1]/255.0, c[2]/255.0)
    @Color.setter
    def Color(self, v):
        try:
            self._p['color'][0]=max(0,min(255,int(v.R*255)))
            self._p['color'][1]=max(0,min(255,int(v.G*255)))
            self._p['color'][2]=max(0,min(255,int(v.B*255)))
        except Exception: pass
        self._sync()

class _StopScript(Exception): pass
play_state = {'running': False, 'paused': False}
script_threads = []

def _wait(t=0.0):
    t = float(t); end = time.time() + t
    while time.time() < end:
        if not play_state['running']: raise _StopScript()
        while play_state['paused']:
            if not play_state['running']: raise _StopScript()
            time.sleep(0.05)
        time.sleep(0.01)
    if not play_state['running']: raise _StopScript()

def _script_print(*args): log(' '.join(str(a) for a in args))

def run_one_script(p):
    src = p.get('script', '')
    if not src.strip(): return
    try:
        py = lua_to_python(src)
        proxy = LuaPartProxy(p)
        ns = {
            '__builtins__': {'int':int,'float':float,'str':str,'bool':bool,
                'len':len,'range':range,'abs':abs,'min':min,'max':max,
                'round':round,'print':_script_print},
            'part': proxy, 'script': proxy,
            'Vector3': Vector3, 'Color3': Color3,
            'math': math, 'random': random,
            'wait': _wait, 'tostring': str, 'tonumber': float,
            'print': _script_print,
        }
        exec(py, ns)
    except _StopScript: pass
    except Exception as e:
        log(f"Script error ({p.get('name','?')}): {e}")

def start_all_scripts():
    stop_all_scripts()
    play_state['running'] = True; play_state['paused'] = False
    count = 0
    for p in st.parts:
        if p.get('script', '').strip():
            th = threading.Thread(target=run_one_script, args=(p,), daemon=True)
            th.start(); script_threads.append(th); count += 1
    log(f"Play: {count} scripts running"); set_status(msg=f"Play: {count}")

def stop_all_scripts():
    play_state['running'] = False; play_state['paused'] = False
    script_threads.clear()

def do_play(): start_all_scripts()
def do_pause():
    if not play_state['running']: return
    play_state['paused'] = not play_state['paused']
    log("Paused" if play_state['paused'] else "Resumed")
def do_stop(): stop_all_scripts(); log("Stopped"); set_status(msg="Stopped")

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
    return {'cube':'cube','sphere':'sphere','plane':'quad',
            'cylinder':'cylinder','cone':'cone'}.get(shape, 'cube')

def create_part_entity(p):
    try:
        e = Entity(model=shape_model(p.get('shape','cube')),
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
    if p['id'] == st.sel_id: update_sel_box()
    st.dirty = True

def apply_script_updates():
    for pid in list(st.script_dirty):
        p = None
        for pp in st.parts:
            if pp['id'] == pid: p = pp; break
        if not p: continue
        e = st.ents.get(pid)
        if not e: continue
        try:
            e.position = (p['x'], p['y'], p['z'])
            e.scale = (p['sx'], p['sy'], p['sz'])
            e.rotation = (p['rx'], p['ry'], p['rz'])
            e.color = make_color(p['color'])
        except Exception: pass
        if pid == st.sel_id: update_sel_box()
    st.script_dirty.clear()

try:
    sel_box = Entity(model='wireframe_cube', color=C(70,140,240,230),
                     scale=(1,1,1), enabled=False, unlit=True)
except Exception:
    sel_box = Entity(model='cube', color=C(70,140,240,60),
                     scale=(1,1,1), enabled=False, unlit=True)

def update_sel_box():
    p = get_selected()
    if not p: sel_box.enabled = False; return
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
    scroll_props[0] = 0
    update_sel_box(); refresh_explorer(); refresh_properties()

# ============================================================
# History / действия
# ============================================================
def push_history():
    try:
        s = json.dumps(st.parts, ensure_ascii=False)
        if not st.history or st.history[-1] != s:
            st.history.append(s)
            if len(st.history) > 50: st.history.pop(0)
            st.redo_stack.clear(); st.dirty = True
    except Exception: pass

def apply_history(parts_json):
    for pid in list(st.ents.keys()):
        try: destroy(st.ents[pid])
        except Exception: pass
    st.ents = {}; st.script_dirty.clear()
    st.parts = json.loads(parts_json)
    for p in st.parts:
        e = create_part_entity(p)
        if e: st.ents[p['id']] = e
    st.sel_id = None
    update_sel_box(); refresh_explorer(); refresh_properties()

def undo():
    if len(st.history) < 2: return
    st.redo_stack.append(st.history.pop())
    apply_history(st.history[-1]); log("Undo"); set_status(msg="Undo")

def redo():
    if not st.redo_stack: return
    nxt = st.redo_stack.pop(); st.history.append(nxt)
    apply_history(nxt); log("Redo"); set_status(msg="Redo")

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
         'color': [163,162,165], 'transparency': 0,
         'anchored': False, 'cancollide': True, 'script': ''}
    st.parts.append(p)
    e = create_part_entity(p)
    if e: st.ents[p['id']] = e
    select_part(p['id'])
    log(f"Created: {p['name']}"); set_status(msg=f"Created {p['name']}")

def delete_selected():
    if not st.sel_id: return
    push_history()
    e = st.ents.pop(st.sel_id, None)
    if e:
        try: destroy(e)
        except Exception: pass
    st.parts = [p for p in st.parts if p['id'] != st.sel_id]
    st.sel_id = None
    update_sel_box(); refresh_explorer(); refresh_properties()
    log("Deleted"); set_status(msg="Deleted")

def duplicate_selected():
    p = get_selected()
    if not p: return
    push_history()
    np = copy.deepcopy(p); np['id'] = str(uuid.uuid4())[:8]
    st.next_part_num += 1
    np['name'] = f"{p['name']}_copy"
    np['x'] = p['x'] + snap(4); np['z'] = p['z'] + snap(4)
    st.parts.append(np)
    e = create_part_entity(np)
    if e: st.ents[np['id']] = e
    select_part(np['id']); log("Duplicated"); set_status(msg="Duplicated")

def copy_to_clip(p):
    if p: clipboard[0] = copy.deepcopy(p); log("Copied"); set_status(msg="Copied")

def paste_from_clip():
    if not clipboard[0]: return
    push_history()
    np = copy.deepcopy(clipboard[0]); np['id'] = str(uuid.uuid4())[:8]
    st.next_part_num += 1
    np['name'] = f"{clipboard[0]['name']}_{st.next_part_num}"
    np['x'] = clipboard[0]['x'] + snap(4); np['z'] = clipboard[0]['z'] + snap(4)
    st.parts.append(np)
    e = create_part_entity(np)
    if e: st.ents[np['id']] = e
    select_part(np['id']); log("Pasted"); set_status(msg="Pasted")

def select_all_parts(): log("Select All (не поддерживается)")

def focus_selected():
    p = get_selected()
    if not p: return
    try:
        d = max(p['sx'], p['sy'], p['sz']) * 3
        editor_cam.position = (p['x'] + d, p['y'] + d*0.7, p['z'] - d)
        editor_cam.look_at(Vec3(p['x'], p['y'], p['z']))
        set_status(msg="Focused")
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
        set_status(msg=f"Camera: {which}")
    except Exception: pass

def save_place():
    if not st.place_id: st.place_id = str(uuid.uuid4())[:8]
    data = {'id': st.place_id, 'name': st.place_name, 'author': username,
            'max_players': st.max_players, 'spawn': st.spawn,
            'blocks': st.parts, 'updated': time.time()}
    save_json(os.path.join(PLACES_DIR, st.place_id + '.json'), data)
    st.dirty = False
    log(f"Saved: {st.place_id}.json"); set_status(msg=f"Saved {st.place_id}.json")

def publish_place():
    if not mqtt_ok[0] or not mqtt_client:
        log("No network"); set_status(msg="No network"); return
    if not st.place_id: st.place_id = str(uuid.uuid4())[:8]
    save_place()
    data = {'id': st.place_id, 'name': st.place_name, 'author': username,
            'max_players': st.max_players, 'spawn': st.spawn,
            'blocks': st.parts, 'updated': time.time()}
    try:
        mqtt_client.publish(f"{PLACES_TOPIC}/{st.place_id}",
                            json.dumps(data), qos=1, retain=True)
        log(f"Published: {st.place_name}"); set_status(msg="Published")
    except Exception as e:
        log("Publish error: " + str(e)); set_status(msg="Publish failed")

def new_place():
    push_history()
    for pid in list(st.ents.keys()):
        try: destroy(st.ents[pid])
        except Exception: pass
    st.parts = []; st.ents = {}; st.sel_id = None; st.script_dirty.clear()
    st.place_id = None; st.place_name = "Place1"
    st.spawn = [0, 2, 0]; st.max_players = 15; st.next_part_num = 1
    scroll_props[0] = 0; scroll_explorer[0] = 0
    update_sel_box(); refresh_explorer(); refresh_properties()
    log("New place"); set_status(msg="New place")

def _apply_place_data(data):
    for pid in list(st.ents.keys()):
        try: destroy(st.ents[pid])
        except Exception: pass
    st.parts = []; st.ents = {}; st.sel_id = None; st.script_dirty.clear()
    st.place_id = data.get('id')
    st.place_name = data.get('name', 'Place1')
    st.max_players = int(data.get('max_players', 15))
    st.spawn = data.get('spawn', [0, 2, 0])
    st.next_part_num = len(data.get('blocks', [])) + 1
    for p in data.get('blocks', []):
        p.setdefault('name', f"Cube_{st.next_part_num}")
        p.setdefault('shape', 'cube')
        p.setdefault('transparency', 0)
        p.setdefault('anchored', False)
        p.setdefault('cancollide', True)
        p.setdefault('script', '')
        st.parts.append(p)
        e = create_part_entity(p)
        if e: st.ents[p['id']] = e
    scroll_props[0] = 0; scroll_explorer[0] = 0
    update_sel_box(); refresh_explorer(); refresh_properties()

def load_place_file(path):
    data = load_json(path, None)
    if not data:
        log(f"Bad file: {path}"); set_status(msg="Load failed"); return
    push_history()
    _apply_place_data(data)
    log(f"Loaded: {st.place_name} ({os.path.basename(path)})")
    set_status(msg=f"Loaded {os.path.basename(path)}")

def load_last_saved():
    if not os.path.isdir(PLACES_DIR): log("No places/"); return
    files = [f for f in os.listdir(PLACES_DIR) if f.endswith('.json')]
    if not files: log("No saves"); set_status(msg="No saves"); return
    files.sort(key=lambda f: os.path.getmtime(os.path.join(PLACES_DIR, f)),
               reverse=True)
    load_place_file(os.path.join(PLACES_DIR, files[0]))

def toggle_grid():
    st.grid_on = not st.grid_on
    log(f"Grid: {'ON' if st.grid_on else 'OFF'}")
    set_status(msg=f"Grid {'ON' if st.grid_on else 'OFF'}")

def toggle_helpers(): log("Toggle Helpers (заглушка)")
def open_welcome(): log("PyBlox Studio v1.3 — тёмная тема, дерево, Lua, скролл")

def toggle_theme():
    new = 'dark' if current_theme[0] == 'light' else 'light'
    current_theme[0] = new
    apply_theme(new)
    session['theme'] = new
    try: save_json(SESSION_FILE, session)
    except Exception: pass
    log(f"Theme: {new}")
    try:
        if ground_ent: ground_ent.color = C_GROUND
        if grid_ent:
            grid_ent.color = C(255,255,255, 45 if new=='light' else 25)
    except Exception: pass
    rebuild_all_ui()

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

EXP_HDR_H   = 24
EXP_SRCH_H  = 20
EXP_AREA_H  = 260   # высота области дерева
PROPS_HDR_H = 24

def right_panel_h():
    return REF_H() - VIEW_TOP - OUTPUT_H

def explorer_area_y0():
    return VIEW_TOP + EXP_HDR_H + 6 + EXP_SRCH_H + 6

def explorer_area_y1():
    return explorer_area_y0() + EXP_AREA_H

def props_area_y0():
    return explorer_area_y1() + 6

def props_area_y1():
    return REF_H() - OUTPUT_H - 4

explorer_bottom = [0]
prop_widgets = []
prop_fields = []
explorer_widgets = []

# ============================================================
# DROPDOWN
# ============================================================
dropdown_state = {'open': None, 'widgets': []}

def close_dropdown():
    for w in dropdown_state['widgets']:
        try: destroy(w)
        except Exception: pass
    dropdown_state['widgets'] = []
    dropdown_state['open'] = None

def open_dropdown(name, x_px, items):
    if dropdown_state['open'] == name:
        close_dropdown(); return
    close_dropdown()
    dropdown_state['open'] = name
    item_h = 22; sep_h = 6; W = 220
    H = 6
    for it in items:
        H += sep_h if it == '-' else item_h
    y = MENU_H
    dropdown_state['widgets'].append(panel(x_px, y, W, H, C_MENU_BG, z=0.55, track=False))
    dropdown_state['widgets'].append(panel(x_px, y + H - 1, W, 1, C_BORDER, z=0.57, track=False))
    dropdown_state['widgets'].append(panel(x_px, y, 1, H, C_BORDER, z=0.57, track=False))
    iy = y + 3
    for it in items:
        if it == '-':
            dropdown_state['widgets'].append(
                panel(x_px + 6, iy + sep_h//2, W - 12, 1, C_BORDER, z=0.56, track=False))
            iy += sep_h; continue
        label, cb, shortcut = it
        def make_cb(c=cb):
            def _():
                close_dropdown()
                try:
                    if c: c()
                except Exception as e: print("[menu]", e)
            return _
        b = rect_btn(x_px + 2, iy, W - 4, item_h, C_MENU_BG, make_cb(), z=0.58, track=False)
        dropdown_state['widgets'].append(b)
        dropdown_state['widgets'].append(
            text_at(label, x_px + 10, iy + item_h/2, C_TEXT, 0.82, z=0.01, track=False))
        if shortcut:
            t2 = text_at(shortcut, x_px + W - 12, iy + item_h/2,
                         C_TEXT_DIM, 0.75, z=0.01, track=False)
            try: t2.origin = (0.5, 0.5)
            except Exception: pass
            dropdown_state['widgets'].append(t2)
        iy += item_h

# ============================================================
# CONTEXT MENU
# ============================================================
ctx_state = {'open': False, 'widgets': [], 'part': None}

def close_ctx_menu():
    for w in ctx_state['widgets']:
        try: destroy(w)
        except Exception: pass
    ctx_state['widgets'] = []
    ctx_state['open'] = False
    ctx_state['part'] = None

def open_ctx_menu(part, x_px, y_px):
    close_ctx_menu()
    ctx_state['open'] = True; ctx_state['part'] = part
    items = [
        ("Copy", lambda: copy_to_clip(part), None),
        ("Duplicate", lambda: (select_part(part['id']), duplicate_selected()), None),
        ("Delete", lambda: (select_part(part['id']), delete_selected()), None),
        "-",
        ("Open Script Editor", lambda: open_script_editor(part), None),
    ]
    item_h = 22; sep_h = 6; W = 180
    H = 6
    for it in items:
        H += sep_h if it == '-' else item_h
    ctx_state['widgets'].append(panel(x_px, y_px, W, H, C_MENU_BG, z=0.70, track=False))
    ctx_state['widgets'].append(panel(x_px, y_px + H - 1, W, 1, C_BORDER, z=0.72, track=False))
    iy = y_px + 3
    for it in items:
        if it == '-':
            ctx_state['widgets'].append(
                panel(x_px + 6, iy + sep_h//2, W - 12, 1, C_BORDER, z=0.71, track=False))
            iy += sep_h; continue
        label, cb, _ = it
        def make_cb(c=cb):
            def _():
                close_ctx_menu()
                try:
                    if c: c()
                except Exception as e: print("[ctx]", e)
            return _
        b = rect_btn(x_px + 2, iy, W - 4, item_h, C_MENU_BG, make_cb(), z=0.73, track=False)
        ctx_state['widgets'].append(b)
        ctx_state['widgets'].append(
            text_at(label, x_px + 10, iy + item_h/2, C_TEXT, 0.82, z=0.005, track=False))
        iy += item_h

# ============================================================
# SCRIPT EDITOR
# ============================================================
editor_state = {'open': False, 'part': None, 'lines': [''], 'cur_line': 0,
                'cur_col': 0, 'widgets': [], 'display': None}

def _editor_text(): return '\n'.join(editor_state['lines'])

def _refresh_editor_display():
    t_ = editor_state['display']
    if not t_: return
    try:
        lines = editor_state['lines'][:]
        cur = editor_state['cur_line']; col = editor_state['cur_col']
        if cur < len(lines):
            line = lines[cur]; lines[cur] = line[:col] + '|' + line[col:]
        txt = '\n'.join(lines)
        if not txt.strip(): txt = '|'
        if len(txt) > 1500: txt = txt[:1500] + '\n...'
        t_.text = txt
    except Exception: pass

def _editor_insert(ch):
    lines = editor_state['lines']; cur = editor_state['cur_line']; col = editor_state['cur_col']
    line = lines[cur]; lines[cur] = line[:col] + ch + line[col:]
    editor_state['cur_col'] = col + len(ch); _refresh_editor_display()

def _editor_backspace():
    lines = editor_state['lines']; cur = editor_state['cur_line']; col = editor_state['cur_col']
    if col > 0:
        line = lines[cur]; lines[cur] = line[:col-1] + line[col:]
        editor_state['cur_col'] = col - 1
    elif cur > 0:
        prev = lines[cur-1]; cur_line = lines[cur]
        lines[cur-1] = prev + cur_line
        del lines[cur]
        editor_state['cur_line'] = cur - 1; editor_state['cur_col'] = len(prev)
    _refresh_editor_display()

def _editor_enter():
    lines = editor_state['lines']; cur = editor_state['cur_line']; col = editor_state['cur_col']
    line = lines[cur]; lines[cur] = line[:col]
    lines.insert(cur + 1, line[col:])
    editor_state['cur_line'] = cur + 1; editor_state['cur_col'] = 0
    _refresh_editor_display()

def open_script_editor(part):
    close_script_editor()
    editor_state['open'] = True; editor_state['part'] = part
    src = part.get('script', '')
    editor_state['lines'] = src.split('\n') if src else ['']
    editor_state['cur_line'] = len(editor_state['lines']) - 1
    editor_state['cur_col'] = len(editor_state['lines'][-1])

    W, H = 760, 500
    X = (REF_W - W) / 2.0; Y = (REF_H() - H) / 2.0

    editor_state['widgets'].append(panel(0, 0, REF_W, REF_H(), C(0,0,0,130), z=0.5, track=False))
    editor_state['widgets'].append(panel(X, Y, W, H, C_PANEL, z=0.6, track=False))
    editor_state['widgets'].append(panel(X, Y, W, 26, C_PANEL_HDR, z=0.65, track=False))
    editor_state['widgets'].append(
        text_at(f"Script Editor — {part.get('name','Part')}",
                X + 10, Y + 13, C_TEXT, 0.95, z=0.02, track=False))
    hint = text_at("Lua: part.Position.Y = ... | wait(1) | Color3.new(r,g,b)",
                   X + W - 10, Y + 13, C_TEXT_DIM, 0.75, z=0.02, track=False)
    try: hint.origin = (0.5, 0.5)
    except Exception: pass
    editor_state['widgets'].append(hint)

    editor_state['widgets'].append(panel(X + 10, Y + 40, W - 20, H - 100,
                                          C_EDITOR_BG, z=0.62, track=False))
    try:
        disp = Text(parent=camera.ui, text="",
                    position=(NX(X + 18), NY(Y + 48)),
                    scale=0.9, color=C_EDITOR_FG,
                    origin=(-0.5, 0.5), z=0.02)
        try: disp.ignore = True
        except Exception: pass
        editor_state['display'] = disp
        editor_state['widgets'].append(disp)
    except Exception as e:
        print("[editor display]", e)

    def on_save():
        part['script'] = _editor_text()
        log(f"Script saved ({part.get('name','?')})")
        set_status(msg="Script saved"); refresh_properties()
    def on_run():
        on_save()
        play_state['running'] = True; play_state['paused'] = False
        th = threading.Thread(target=run_one_script, args=(part,), daemon=True)
        th.start(); script_threads.append(th)
        log("Running script"); set_status(msg="Script running")
    def on_close(): on_save(); close_script_editor()

    btn_y = Y + H - 32; bx = X + 10
    for label, cb, col in [("Save", on_save, C_BTN),
                            ("Save & Run", on_run, C_GREEN),
                            ("Close", on_close, C_BTN)]:
        bw = 100
        editor_state['widgets'].append(
            rect_btn(bx, btn_y, bw, 24, col, cb, z=0.7, track=False))
        editor_state['widgets'].append(
            text_at(label, bx + bw/2, btn_y + 12, C_TEXT, 0.85, z=0.02, track=False))
        bx += bw + 8
    _refresh_editor_display()

def close_script_editor():
    for w in editor_state['widgets']:
        try: destroy(w)
        except Exception: pass
    editor_state['widgets'] = []; editor_state['display'] = None
    editor_state['open'] = False; editor_state['part'] = None

# ============================================================
# BUILDERS
# ============================================================
TABS = ["Home", "Avatar", "UI", "Script", "Model", "Plugins"]
current_tab = ['Home']

def build_menubar():
    FILE_ITEMS = [
        ("New Place", new_place, "Ctrl+N"),
        ("Open Last", load_last_saved, "Ctrl+O"),
        "-",
        ("Save", save_place, "Ctrl+S"),
        ("Save As...", save_place, None),
        "-",
        ("Publish to PyBlox", publish_place, None),
        "-",
        ("Exit", lambda: sys.exit(0), None),
    ]
    EDIT_ITEMS = [
        ("Undo", undo, "Ctrl+Z"),
        ("Redo", redo, "Ctrl+Y"),
        "-",
        ("Copy", lambda: copy_to_clip(get_selected()), "Ctrl+C"),
        ("Paste", paste_from_clip, "Ctrl+V"),
        ("Duplicate", duplicate_selected, "Ctrl+D"),
        ("Delete", delete_selected, "Del"),
        "-",
        ("Select All", select_all_parts, "Ctrl+A"),
    ]
    VIEW_ITEMS = [
        ("Toggle Grid", toggle_grid, None),
        ("Toggle Helpers", toggle_helpers, None),
        ("Toggle Theme (Light/Dark)", toggle_theme, None),
        "-",
        ("Top View", lambda: camera_view('top'), "1"),
        ("Front View", lambda: camera_view('front'), "2"),
        ("Side View", lambda: camera_view('side'), "3"),
        ("Perspective", lambda: camera_view('persp'), "4"),
        "-",
        ("Focus Selected", focus_selected, "F"),
    ]
    PLUGINS_ITEMS = [
        ("Manage Plugins...", lambda: log("Plugins"), None),
        ("Open Plugin Folder", lambda: log("plugins/"), None),
    ]
    TEST_ITEMS = [
        ("Play", do_play, "F5"),
        ("Pause", do_pause, "F6"),
        ("Stop", do_stop, "F7"),
        "-",
        ("Start Server", lambda: log("Start Server"), None),
        ("Start Player", lambda: log("Start Player"), None),
    ]
    WINDOW_ITEMS = [
        ("Explorer", lambda: log("Explorer"), None),
        ("Properties", lambda: log("Properties"), None),
        ("Output", lambda: log("Output"), None),
        "-",
        ("Reset Layout", lambda: log("Reset Layout"), None),
    ]
    HELP_ITEMS = [
        ("PyBlox Studio Help", open_welcome, None),
        ("About PyBlox Studio", open_welcome, None),
        ("Documentation", lambda: log("Docs"), None),
    ]
    menu_defs = [
        ("File", 8, FILE_ITEMS), ("Edit", 56, EDIT_ITEMS),
        ("View", 100, VIEW_ITEMS), ("Plugins", 148, PLUGINS_ITEMS),
        ("Test", 216, TEST_ITEMS), ("Window", 260, WINDOW_ITEMS),
        ("Help", 324, HELP_ITEMS),
    ]
    for name, x_pos, items in menu_defs:
        w = 48 if name != "Plugins" else 62
        def make_open(n=name, xx=x_pos, its=items):
            def _(): open_dropdown(n, xx, its)
            return _
        rect_btn(x_pos, 0, w, MENU_H, C_MENU, make_open(), z=0.20)
        t_ = text_at(name, x_pos + w/2, MENU_H/2, C_TEXT, 0.9, z=0.01)
        try: t_.origin = (0.5, 0.5)
        except Exception: pass

def build_tabrow():
    y_mid = MENU_H + TABROW_H/2
    PLAY_X, PLAY_W = 78, 44
    rect_btn(PLAY_X, MENU_H + 4, PLAY_W, TABROW_H - 8, C(220,245,220), do_play, z=0.10)
    text_at("Play", PLAY_X + PLAY_W/2, y_mid, C_GREEN, 0.75, z=0.01)
    PAUSE_X, PAUSE_W = PLAY_X + PLAY_W + 4, 52
    rect_btn(PAUSE_X, MENU_H + 4, PAUSE_W, TABROW_H - 8, C(245,240,220), do_pause, z=0.10)
    text_at("Pause", PAUSE_X + PAUSE_W/2, y_mid, C(130,100,30), 0.7, z=0.01)
    STOP_X, STOP_W = PAUSE_X + PAUSE_W + 4, 44
    rect_btn(STOP_X, MENU_H + 4, STOP_W, TABROW_H - 8, C(250,220,220), do_stop, z=0.10)
    text_at("Stop", STOP_X + STOP_W/2, y_mid, C_RED, 0.75, z=0.01)

    tab_x = STOP_X + STOP_W + 20
    for label in TABS:
        tw = 70
        active = (label == current_tab[0])
        if active:
            panel(tab_x, MENU_H + 3, tw, TABROW_H - 3, C_TAB_ACT, z=0.06)
            panel(tab_x, MENU_H + TABROW_H - 3, tw, 2, C_BLUE, z=0.08)
        tcol = C_TEXT if active else C_TEXT_DIM
        tscale = 0.95 if active else 0.9
        def make_switch(l=label):
            def _():
                current_tab[0] = l
                rebuild_all_ui()
                set_status(msg=f"Tab: {l}")
            return _
        b = rect_btn(tab_x, MENU_H + 3, tw, TABROW_H - 3,
                     C_BTN if not active else C_TAB_ACT, make_switch(), z=0.15)
        t_ = text_at(label, tab_x + tw/2, y_mid, tcol, tscale, z=0.01)
        try: t_.origin = (0.5, 0.5)
        except Exception: pass
        tab_x += tw + 3

    text_at("Untitled", REF_W - 230, y_mid, C_TEXT_DIM, 0.9, z=0.01)
    text_at("+", REF_W - 160, y_mid, C_TEXT_DIM, 1.1, z=0.01)

def build_ribbon(tab):
    RIB_Y = MENU_H + TABROW_H
    BTN_Y = RIB_Y + 8
    BTN_H = RIBBON_H - 16
    BTN_W = 58
    GAP = 3
    def rb(icon, label, x, cb=None, color=None):
        if color is None: color = C_BTN
        rect_btn(x, BTN_Y, BTN_W, BTN_H, color, cb, z=0.10)
        text_at(icon, x + BTN_W/2, BTN_Y + 22, C_TEXT, 1.4, z=0.01)
        text_at(label, x + BTN_W/2, BTN_Y + BTN_H - 10, C_TEXT, 0.75, z=0.01)
    def sep(x): vline(x, RIB_Y + 12, RIBBON_H - 24, C_BORDER, z=0.06)

    items_home = [
        ('N', 'New',     new_place, C_GREEN),
        ('S', 'Save',    save_place, None),
        ('L', 'Load',    load_last_saved, None),
        ('P', 'Publish', publish_place, C_ORANGE),
        '|',
        ('#', 'Block',    lambda: add_part('cube', viewport_center()), None),
        ('O', 'Sphere',   lambda: add_part('sphere', viewport_center()), None),
        ('C', 'Cylinder', lambda: add_part('cylinder', viewport_center()), None),
        '|',
        ('X', 'Copy',  lambda: copy_to_clip(get_selected()) if get_selected() else log("No sel"), None),
        ('V', 'Paste', paste_from_clip, None),
        ('D', 'Dup',   duplicate_selected, None),
        ('U', 'Undo',  undo, None),
        ('R', 'Redo',  redo, None),
    ]
    items_script = [
        ('+', 'New Lua', lambda: log("Выдели блок → Open Script Editor"), None),
        ('E', 'Editor',  lambda: (open_script_editor(get_selected())
                                   if get_selected() else log("Выдели блок")), C_BLUE),
        ('R', 'Run',     do_play, C_GREEN),
        ('S', 'Stop',    do_stop, C_RED),
    ]
    items_model = [
        ('#', 'Block',    lambda: add_part('cube', viewport_center()), None),
        ('O', 'Sphere',   lambda: add_part('sphere', viewport_center()), None),
        ('C', 'Cylinder', lambda: add_part('cylinder', viewport_center()), None),
        '|',
        ('W', 'Weld',  lambda: log("Weld"), None),
        ('G', 'Group', lambda: log("Group"), None),
        ('M', 'Move',  lambda: log("Move"), None),
    ]
    items_avatar = [
        ('B', 'Rig',    lambda: log("Rig"), None),
        ('A', 'Anim',   lambda: log("Anim"), None),
        ('E', 'Avatar', lambda: log("Avatar Editor"), None),
    ]
    items_ui = [
        ('T', 'Text',   lambda: log("UI Text"), None),
        ('B', 'Button', lambda: log("UI Button"), None),
        ('F', 'Frame',  lambda: log("UI Frame"), None),
        ('I', 'Image',  lambda: log("UI Image"), None),
    ]
    items_plugins = [
        ('P', 'Manage', lambda: log("Manage Plugins"), None),
        ('F', 'Folder', lambda: log("plugins/"), None),
    ]
    tab_map = {'Home': items_home, 'Script': items_script, 'Model': items_model,
               'Avatar': items_avatar, 'UI': items_ui, 'Plugins': items_plugins}
    items = tab_map.get(tab, items_home)
    x = 8
    for it in items:
        if it == '|':
            x += 8; sep(x); x += 10; continue
        icon, label, cb, color = it
        rb(icon, label, x, cb, color)
        x += BTN_W + GAP

def build_toolbar():
    TOOLBAR_X = 6
    TOOL_SIZE = 30
    TOOL_GAP = 3
    TOOLBAR_Y0 = VIEW_TOP + 8

    panel(TOOLBAR_X - 2, TOOLBAR_Y0 - 2,
          TOOL_SIZE + 4, TOOL_SIZE*8 + TOOL_GAP*8 + 20, C_TOOLBAR, z=0.09)

    y = TOOLBAR_Y0 + 2
    for icon, key, label in [('S','select','Select'),('M','move','Move'),
                              ('Z','scale','Scale'),('R','rotate','Rotate')]:
        is_sel = (st.tool == key)
        col = C_BTN_SEL if is_sel else C_BTN
        def make_tool(k=key, l=label):
            def _():
                st.tool = k
                rebuild_all_ui()
                set_status(msg=f"Tool: {l}")
            return _
        rect_btn(TOOLBAR_X, y, TOOL_SIZE, TOOL_SIZE, col, make_tool(), z=0.11)
        t_ = text_at(icon, TOOLBAR_X + TOOL_SIZE/2, y + TOOL_SIZE/2, C_TEXT, 1.1, z=0.005)
        try: t_.origin = (0.5, 0.5)
        except Exception: pass
        y += TOOL_SIZE + TOOL_GAP

    panel(TOOLBAR_X, y + 2, TOOL_SIZE, 1, C_BORDER, z=0.11)
    y += 8

    shapes = [('#', 'cube', 'Block'), ('O', 'sphere', 'Sphere'),
              ('C', 'cylinder', 'Cylinder'), ('_', 'plane', 'Plane')]
    for icon, shape, label in shapes:
        def make_add(sh=shape):
            def _(): add_part(sh, viewport_center())
            return _
        rect_btn(TOOLBAR_X, y, TOOL_SIZE, TOOL_SIZE, C_BTN, make_add(), z=0.11)
        t_ = text_at(icon, TOOLBAR_X + TOOL_SIZE/2, y + TOOL_SIZE/2, C_TEXT, 1.1, z=0.005)
        try: t_.origin = (0.5, 0.5)
        except Exception: pass
        y += TOOL_SIZE + TOOL_GAP

def build_placetab():
    if place_tab_active[0]:
        panel(0, TOP_TOTAL, 130, PLACETAB_H, C_WHITE, z=0.06)
        panel(0, TOP_TOTAL + PLACETAB_H - 1, 130, 1, C_BORDER, z=0.07)
        text_at("[P]", 14, TOP_TOTAL + PLACETAB_H/2, C_BLUE, 1.0, z=0.01)
        text_at(st.place_name, 38, TOP_TOTAL + PLACETAB_H/2, C_TEXT, 0.9, z=0.01)
        def close_tab():
            place_tab_active[0] = False
            rebuild_all_ui()
        rect_btn(104, TOP_TOTAL + 3, 20, PLACETAB_H - 6, C_WHITE, close_tab, z=0.15)
        text_at("x", 114, TOP_TOTAL + PLACETAB_H/2, C_TEXT_DIM, 1.0, z=0.01)
    else:
        text_at("+ Открыть Place", 12, TOP_TOTAL + PLACETAB_H/2, C_TEXT_DIM, 0.85, z=0.01)
        def reopen():
            place_tab_active[0] = True
            rebuild_all_ui()
        rect_btn(0, TOP_TOTAL, 130, PLACETAB_H, C_WHITE, reopen, z=0.15)

place_tab_active = [True]

# ============================================================
# EXPLORER (со скроллом)
# ============================================================
static_tree = [
    ("Workspace", True),
    ("Players", False),
    ("Lighting", False),
    ("ReplicatedStorage", False),
    ("ServerScriptService", False),
    ("ServerStorage", False),
    ("StarterGui", False),
    ("StarterPack", False),
    ("StarterPlayer", True),
    ("Teams", False),
    ("SoundService", False),
]

def build_explorer_header():
    EXP_X = REF_W - RIGHT_W
    EXP_W = RIGHT_W
    panel(EXP_X, VIEW_TOP, EXP_W, EXP_HDR_H, C_PANEL_HDR, z=0.07)
    hline(EXP_X, VIEW_TOP + EXP_HDR_H - 1, EXP_W)
    text_at("Explorer", EXP_X + 12, VIEW_TOP + EXP_HDR_H/2, C_TEXT, 0.95, z=0.01)
    text_at("R M X", EXP_X + EXP_W - 46, VIEW_TOP + EXP_HDR_H/2, C_TEXT_DIM, 0.85, z=0.01)
    search_y = VIEW_TOP + EXP_HDR_H + 6
    panel(EXP_X + 6, search_y, EXP_W - 12, EXP_SRCH_H, C_WHITE, z=0.08)
    panel(EXP_X + 6, search_y + EXP_SRCH_H - 1, EXP_W - 12, 1, C_BORDER, z=0.09)
    text_at("Search", EXP_X + 14, search_y + EXP_SRCH_H/2, C_TEXT_DIM, 0.88, z=0.01)

def refresh_explorer():
    global explorer_widgets
    for w in explorer_widgets:
        try: destroy(w)
        except Exception: pass
    explorer_widgets = []

    EXP_X = REF_W - RIGHT_W
    EXP_W = RIGHT_W
    area_y0 = explorer_area_y0()
    area_y1 = explorer_area_y1()
    area_h  = area_y1 - area_y0

    # Панель области дерева
    p = panel(EXP_X + 4, area_y0, EXP_W - 8, area_h, C_PANEL, z=0.075)
    explorer_widgets.append(p)

    # Контент
    rows = []
    for name, is_branch in static_tree:
        rows.append((name, 0, is_branch, None, "."))
        if name == "Workspace" and st.workspace_open:
            for part in st.parts:
                m = "-" if part.get('script','').strip() else "."
                rows.append((part['name'], 20, False, part['id'], m))
    row_h = 16
    total_h = len(rows) * row_h + 8
    EXPLORER_CONTENT_H[0] = total_h
    max_scroll = max(0, total_h - area_h)
    if scroll_explorer[0] > max_scroll: scroll_explorer[0] = max_scroll
    if scroll_explorer[0] < 0: scroll_explorer[0] = 0

    yy = area_y0 + 4 - scroll_explorer[0]
    for (name, x_off, is_branch, pid, marker) in rows:
        # пропуск того, что вне области
        if yy + row_h < area_y0 or yy > area_y1:
            yy += row_h
            continue
        is_sel = (pid and pid == st.sel_id)
        bg = C_SEL if is_sel else C_PANEL

        def make_click(p_id=pid, ws=is_branch, nm=name):
            def _():
                if ws and nm == "Workspace":
                    st.workspace_open = not st.workspace_open
                    refresh_explorer()
                elif p_id:
                    select_part(p_id)
            return _
        b = rect_btn(EXP_X + 8 + x_off, yy, EXP_W - 16 - x_off, row_h - 2, bg,
                     make_click(), z=0.155, track=False)
        if b: explorer_widgets.append(b)

        mrk = "-" if is_branch else marker
        col = C_TEXT if not is_sel else C_WHITE
        t_ = text_at(f"{mrk} {name}", EXP_X + 14 + x_off, yy + row_h/2 - 1,
                     C_TEXT, 0.82, z=0.005, track=False)
        if t_: explorer_widgets.append(t_)
        yy += row_h

    explorer_bottom[0] = area_y1

# ============================================================
# PROPERTIES (со скроллом)
# ============================================================
def clear_props():
    global prop_widgets, prop_fields
    for w in prop_widgets:
        try: destroy(w)
        except Exception: pass
    prop_widgets = []; prop_fields = []

def refresh_properties():
    clear_props()
    EXP_X = REF_W - RIGHT_W
    EXP_W = RIGHT_W
    p = get_selected()
    area_y0 = props_area_y0()
    area_y1 = props_area_y1()
    area_h  = area_y1 - area_y0

    # Панель Properties
    pnl = panel(EXP_X + 4, area_y0, EXP_W - 8, area_h, C_PANEL, z=0.075)
    prop_widgets.append(pnl)

    # Заголовок
    hdr = panel(EXP_X + 4, area_y0, EXP_W - 8, PROPS_HDR_H, C_PANEL_HDR, z=0.078)
    prop_widgets.append(hdr)
    ttl = text_at("- Properties", EXP_X + 12, area_y0 + PROPS_HDR_H/2, C_BLUE, 0.95, z=0.01)
    prop_widgets.append(ttl)

    # Координаты контента
    content_y0 = area_y0 + PROPS_HDR_H + 4

    # Локальный Y, считаем от 0 (учитывая скролл)
    local_y = [4 - scroll_props[0]]

    def row(lbl, key, val, place_kind=None, w=90):
        nonlocal local_y
        y_abs = content_y0 + local_y[0]
        # пропуск того, что вне области
        if y_abs + 20 < area_y0 + PROPS_HDR_H or y_abs > area_y1:
            local_y[0] += 20
            return
        t_ = text_at(lbl, EXP_X + 14, y_abs, C_TEXT, 0.8, z=0.005, track=False)
        if t_: prop_widgets.append(t_)
        f = field_at(EXP_X + 145, y_abs - 9, w, 18, str(val), z=0.155, track=False)
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
                    elif pk == 'transparency':
                        if not p: return
                        v = max(0.0, min(1.0, float(fo.text)))
                        p['transparency'] = v; fo.text = f"{v:.2f}"
                        push_history(); sync_part(p)
                    elif pk == 'part_name':
                        if not p: return
                        new_name = (fo.text or "Part").strip()[:32] or "Part"
                        p['name'] = new_name; fo.text = new_name
                        push_history(); st.dirty = True; refresh_explorer()
                    elif pk in ('color_r', 'color_g', 'color_b'):
                        if not p: return
                        idx = {'color_r': 0, 'color_g': 1, 'color_b': 2}[pk]
                        v = max(0, min(255, int(float(fo.text))))
                        p['color'][idx] = v; fo.text = str(v)
                        push_history(); sync_part(p)
                    else:
                        if not p: return
                        v = float(fo.text)
                        push_history(); p[k] = v; sync_part(p)
                except Exception: pass
            try: f.on_submit = submit
            except Exception: pass
            prop_fields.append(f); prop_widgets.append(f)
        local_y[0] += 20

    def label(text, col=None):
        nonlocal local_y
        y_abs = content_y0 + local_y[0]
        if col is None: col = C_TEXT
        if y_abs < area_y0 + PROPS_HDR_H - 20 or y_abs > area_y1: 
            local_y[0] += 20; return
        t_ = text_at(text, EXP_X + 14, y_abs, col, 0.85, z=0.005, track=False)
        if t_: prop_widgets.append(t_)
        local_y[0] += 20

    def button(lbl, x_off, w, cb, col):
        nonlocal local_y
        y_abs = content_y0 + local_y[0]
        if y_abs < area_y0 + PROPS_HDR_H - 20 or y_abs > area_y1:
            return
        b = rect_btn(EXP_X + x_off, y_abs - 9, w, 20, col, cb, z=0.155, track=False)
        if b: prop_widgets.append(b)
        t_ = text_at(lbl, EXP_X + x_off + w/2, y_abs, C_WHITE, 0.78, z=0.005, track=False)
        if t_: prop_widgets.append(t_)

    if p:
        row("Name", 'name', p.get('name', ''), 'part_name', w=110)
        row("Position X", 'x', f"{p['x']:.2f}")
        row("Position Y", 'y', f"{p['y']:.2f}")
        row("Position Z", 'z', f"{p['z']:.2f}")
        row("Size X", 'sx', f"{p['sx']:.2f}")
        row("Size Y", 'sy', f"{p['sy']:.2f}")
        row("Size Z", 'sz', f"{p['sz']:.2f}")
        row("Rotation X", 'rx', f"{p['rx']:.2f}")
        row("Rotation Y", 'ry', f"{p['ry']:.2f}")
        row("Rotation Z", 'rz', f"{p['rz']:.2f}")
        row("Transparency", 'tr', f"{p.get('transparency',0):.2f}", 'transparency', w=50)
        c = p.get('color', [163,162,165])
        row("Color R", 'cr', c[0], 'color_r', w=50)
        row("Color G", 'cg', c[1], 'color_g', w=50)
        row("Color B", 'cb', c[2], 'color_b', w=50)

        local_y[0] += 6
        label("- Script (Lua)", C_PURPLE)

        has_script = bool(p.get('script', '').strip())
        status = "Yes" if has_script else "Empty"
        label(f"Content: {status}")

        def on_open_editor(pp=p): open_script_editor(pp)
        button("Open Script Editor", 14, 140, on_open_editor, C_BLUE)
        local_y[0] += 6

        def run_this(pp=p):
            play_state['running'] = True; play_state['paused'] = False
            th = threading.Thread(target=run_one_script, args=(pp,), daemon=True)
            th.start(); script_threads.append(th)
            log(f"Running script ({pp.get('name','?')})"); set_status(msg="Script running")
        def clear_this(pp=p):
            pp['script'] = ''; st.dirty = True; refresh_properties()
        button("Run", 14, 60, run_this, C_GREEN)
        button("Clear", 80, 60, clear_this, C_RED)
        local_y[0] += 6
    else:
        row("Place name", 'place_name', st.place_name, 'place_name', w=110)
        row("Max players", 'max_players', st.max_players, 'max_pl', w=60)
        row("Spawn X", 'spawn_x', st.spawn[0], 'spawn_x', w=60)
        row("Spawn Y", 'spawn_y', st.spawn[1], 'spawn_y', w=60)
        row("Spawn Z", 'spawn_z', st.spawn[2], 'spawn_z', w=60)
        local_y[0] += 8
        label("Select a part in Explorer", C_TEXT_DIM)
        label("to edit it", C_TEXT_DIM)

    PROPS_CONTENT_H[0] = local_y[0] + scroll_props[0] + 12

# ============================================================
# OUTPUT / STATUS
# ============================================================
def build_output_status():
    log_label[0] = text_at("Output: Ready", 12, REF_H() - OUTPUT_H/2, C_TEXT, 0.9, z=0.01)
    status_label[0] = text_at("Tool: SELECT  |  Ready", REF_W - 12,
                               REF_H() - OUTPUT_H/2, C_TEXT, 0.9, z=0.01)
    try: status_label[0].origin = (0.5, 0.5)
    except Exception: pass

# ============================================================
# MASTER REBUILD
# ============================================================
def rebuild_all_ui():
    close_dropdown(); close_ctx_menu()
    destroy_all_ui()

    # фоны
    panel(0, 0, REF_W, MENU_H, C_MENU, z=0.04)
    hline(0, MENU_H - 1, REF_W)
    panel(0, MENU_H, REF_W, TABROW_H, C_TABROW, z=0.04)
    hline(0, MENU_H + TABROW_H - 1, REF_W)
    panel(0, MENU_H + TABROW_H, REF_W, RIBBON_H, C_RIBBON, z=0.04)
    hline(0, TOP_TOTAL - 1, REF_W)
    panel(0, TOP_TOTAL, REF_W, PLACETAB_H, C_PLACETAB, z=0.04)
    hline(0, VIEW_TOP - 1, REF_W)
    panel(REF_W - RIGHT_W, VIEW_TOP, RIGHT_W, right_panel_h(), C_PANEL, z=0.04)
    vline(REF_W - RIGHT_W, VIEW_TOP, right_panel_h())
    panel(0, REF_H() - OUTPUT_H, REF_W, OUTPUT_H, C_PANEL_HDR, z=0.04)
    hline(0, REF_H() - OUTPUT_H, REF_W)

    build_menubar()
    build_tabrow()
    build_ribbon(current_tab[0])
    build_toolbar()
    build_placetab()
    build_explorer_header()
    build_output_status()

    refresh_explorer()
    refresh_properties()
    set_status(msg="Ready")

# ============================================================
# INPUT
# ============================================================
def is_ui_entity(ent):
    e = ent
    while e:
        try:
            if e.parent is camera.ui: return True
        except Exception: pass
        e = getattr(e, 'parent', None)
    return False

def field_active():
    try:
        for f in prop_fields:
            if f and getattr(f, 'active', False): return True
    except Exception: pass
    return False

def mouse_on_right_panel():
    try:
        mx_px = (mouse.x + 0.5) / current_aspect() * REF_W
        return mx_px > REF_W - RIGHT_W
    except Exception: return False

def mouse_y_px():
    try:
        return (0.5 - mouse.y) * REF_H()
    except Exception: return 0

def do_scroll(dy):
    """dy: +1 прокрутить вверх (показать верх), -1 вниз."""
    my_px = mouse_y_px()
    if not mouse_on_right_panel():
        return
    if my_px < explorer_area_y1():
        # скролл Explorer
        new = scroll_explorer[0] - dy * 20
        area_h = explorer_area_y1() - explorer_area_y0()
        max_s = max(0, EXPLORER_CONTENT_H[0] - area_h)
        new = max(0, min(new, max_s))
        if new != scroll_explorer[0]:
            scroll_explorer[0] = new
            refresh_explorer()
    else:
        # скролл Properties
        new = scroll_props[0] - dy * 20
        area_h = props_area_y1() - props_area_y0() - PROPS_HDR_H
        max_s = max(0, PROPS_CONTENT_H[0] - area_h)
        new = max(0, min(new, max_s))
        if new != scroll_props[0]:
            scroll_props[0] = new
            refresh_properties()

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

def on_right_click():
    try:
        ent = mouse.hovered_entity
        if ent and is_ui_entity(ent): return
        e = ent; found = None
        while e:
            if hasattr(e, 'part_id'): found = e; break
            e = getattr(e, 'parent', None)
        if found:
            for p in st.parts:
                if p['id'] == found.part_id:
                    mx_px = (mouse.x + 0.5) / current_aspect() * REF_W
                    my_px = (0.5 - mouse.y) * REF_H()
                    open_ctx_menu(p, mx_px, my_px)
                    break
    except Exception as ex:
        print("[rclick]", ex)

def input(key):
    try:
        if editor_state['open']:
            if key == 'escape': close_script_editor(); return
            if key == 'enter': _editor_enter(); return
            if key == 'backspace': _editor_backspace(); return
            if key == 'space': _editor_insert(' '); return
            if key == 'tab': _editor_insert('    '); return
            if len(key) == 1 and key.isprintable():
                _editor_insert(key); return
            return

        # Скролл
        if key == 'scroll up':
            do_scroll(+1); return
        if key == 'scroll down':
            do_scroll(-1); return

        if key == 'left mouse down':
            if dropdown_state['open']:
                my_px = mouse_y_px()
                if my_px > MENU_H + 2: close_dropdown()
            if ctx_state['open']: close_ctx_menu()
            on_scene_click(); return

        if key == 'right mouse down':
            on_right_click(); return

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
        if key == 'o' or key == 'page up':   p['y'] += step; changed = True
        if key == 'i' or key == 'page down': p['y'] -= step; changed = True

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
            if key == 'o':           p['sz'] += step; changed = True
            if key == 'i':           p['sz'] -= step; changed = True

        if changed:
            push_history(); sync_part(p); refresh_properties()
    except Exception as ex:
        print("[input]", ex)

def update():
    try: apply_script_updates()
    except Exception: pass

# ============================================================
# START
# ============================================================
if len(sys.argv) >= 3 and sys.argv[1] == '--load':
    load_path = sys.argv[2]
    if os.path.exists(load_path):
        try: load_place_file(load_path)
        except Exception as e: print("[auto-load]", e)
    else:
        print(f"[auto-load] not found: {load_path}")

push_history()
rebuild_all_ui()
log(f"PyBlox Studio ready. Тема: {current_theme[0]}.")
print("[Studio] === READY ===")
app.run()