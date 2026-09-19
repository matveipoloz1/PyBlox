import os, sys, json, hashlib, threading, time, ssl, socket, io, queue, subprocess, tempfile, random
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog, ttk
from tkinter import filedialog as _fd
import webbrowser

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("pip install paho-mqtt"); sys.exit(1)

try:
    import sounddevice as sd
    import numpy as np
    VOICE_OK = True
except ImportError:
    VOICE_OK = False
    print("[!] Голос: pip install sounddevice numpy")

try:
    from PIL import Image, ImageTk, ImageDraw, ImageGrab
    PIL_OK = True
except ImportError:
    PIL_OK = False; ImageGrab = None
    print("[!] Аватары/видео/экран: pip install pillow")

try:
    import cv2
    CAM_OK = True
except ImportError:
    CAM_OK = False
    print("[!] Камера: pip install opencv-python")

try:
    from webrtc_screen import WebRTCScreen, RESOLUTIONS as WEBRTC_RESOLUTIONS
    WEBRTC_LIB_OK = True
except Exception as _e:
    WEBRTC_LIB_OK = False; WEBRTC_RESOLUTIONS = {}
    print(f"[i] WebRTC недоступен ({_e})")

try:
    from updater import check_for_update, download_file
    UPDATER_OK = True
except Exception as _e:
    UPDATER_OK = False

try:
    import importlib.util
    URSINA_OK = importlib.util.find_spec("ursina") is not None
except Exception:
    URSINA_OK = False

try:
    from i18n import t, load_lang, set_lang, LANG
    load_lang()
except Exception as _e:
    print(f"[i] i18n недоступен ({_e})")
    def t(k, **kw): return k
    def set_lang(l): pass
    LANG = 'ru'

# ============ Files ============
try:
    import files as files_mod
    FILES_OK = True
except Exception as _e:
    FILES_OK = False
    print(f"[i] files.py не найден ({_e})")

CURRENT_VERSION = "11.7.0"
GITHUB_REPO = "yourname/pyblox"

ACCOUNTS_FILE, LAST_USER_FILE, PROFILE_FILE = 'accounts.json', 'last_user.json', 'profile.json'
SESSION_FILE = 'session.json'
TOPIC_ROOT = "pyblox/v11"
DISCOVERY_TOPIC = f"{TOPIC_ROOT}/discovery"
PLACES_TOPIC = f"{TOPIC_ROOT}/places"
PLAY_TOPIC = f"{TOPIC_ROOT}/play"
USERS_TOPIC = f"{TOPIC_ROOT}/users"
ONLINE_TTL = 30
SERVER_HIDE_DAYS = 30
LIST_REFRESH_MS = 30000

VOICE_RATE, VOICE_CHUNK, VOICE_THRESHOLD, SPEAKING_TIMEOUT = 8000, 480, 300, 0.6
CAM_W, CAM_H, CAM_FPS, CAM_QUALITY = 200, 150, 5, 35

SCREEN_RESOLUTIONS = {
    "640x360":   (640, 360, 45),
    "854x480":   (854, 480, 35),
    "1280x720":  (1280, 720, 28),
    "1600x900":  (1600, 900, 22),
    "1920x1080": (1920, 1080, 18),
    "2560x1440": (2560, 1440, 12),
}
LEGACY_RES_MAP = {"144p":"640x360","360p":"640x360","480p":"854x480","720p":"1280x720"}
SCREEN_FPS_CHOICES = [15, 30, 60]
SCREEN_TIMEOUT = 2.0

STATUS_TYPES = {
    'online': {'label':'🟢 Онлайн',       'color':'#4caf50', 'short':'Онлайн'},
    'dnd':    {'label':'🔴 Не беспокоить','color':'#f44336', 'short':'Не беспокоить'},
    'custom': {'label':'🎭 Свой статус',  'color':'#ff9800', 'short':'Свой'},
}
MAX_STATUS_TEXT = 60

SIMILAR_MAX_DISTANCE = 15
SIMILAR_LIMIT = 8

BROKER_CANDIDATES = [
    ("broker.emqx.io", 8084, "websockets", True, "/mqtt", "EMQX (WSS 8084)"),
    ("broker.emqx.io", 8083, "websockets", False, "/mqtt", "EMQX (WS 8083)"),
    ("test.mosquitto.org", 8081, "websockets", True, "/mqtt", "Mosquitto (WSS 8081)"),
    ("test.mosquitto.org", 8080, "websockets", False, "/mqtt", "Mosquitto (WS 8080)"),
    ("broker.hivemq.com", 8884, "websockets", True, "/mqtt", "HiveMQ (WSS 8884)"),
    ("broker.hivemq.com", 8000, "websockets", False, "/mqtt", "HiveMQ (WS 8000)"),
    ("mqtt.eclipseprojects.io", 443, "websockets", True, "/mqtt", "Eclipse (WSS 443)"),
    ("mqtt.eclipseprojects.io", 80, "websockets", False, "/mqtt", "Eclipse (WS 80)"),
]

# ==================== PLAYER ====================
PLAYER_SOURCE = r'''# -*- coding: utf-8 -*-
import sys, os, json, time, math, ssl, threading
import time as pytime
from ursina import *
from ursina import Ursina
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("pip install paho-mqtt"); sys.exit(1)

username = sys.argv[1]
place_file = sys.argv[2]
with open(place_file, 'r', encoding='utf-8') as f:
    place = json.load(f)

place_id = place.get('id', 'unknown')
place_name = place.get('name', 'Place')
spawn = place.get('spawn', [0, 2, 0])
blocks_data = place.get('blocks', [])

BROKER, BROKER_PORT, BROKER_PATH = "broker.emqx.io", 8084, "/mqtt"
TOPIC = "pyblox/v11/play/" + place_id

def hex_to_ursina(h):
    h = h.lstrip('#')
    try:
        r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        return color.rgba32(r, g, b, 255)
    except Exception:
        return color.rgba32(52, 152, 219, 255)

net_client = [None]; users = {}; remote_ents = {}

def on_conn(cl, u, f, rc, p=None):
    if rc == 0:
        cl.subscribe(TOPIC + "/pos", qos=0)
        cl.subscribe(TOPIC + "/users/+", qos=1)
        cl.publish(TOPIC + "/users/" + username,
                   json.dumps({'ts': pytime.time()}), qos=1, retain=True)

def on_msg(cl, u, m):
    t = m.topic
    try:
        if t == TOPIC + "/pos":
            d = json.loads(m.payload.decode('utf-8', 'ignore'))
            u2 = d.get('user')
            if not u2 or u2 == username: return
            if u2 not in remote_ents:
                col = hex_to_ursina(d.get('c', '#e67e22'))
                e = Entity(model='cube', color=col, scale=(1, 1.8, 1), unlit=True)
                Text(text=u2, parent=e, position=(0, 1.5, 0), scale=8,
                     billboard=True, origin=(0, -0.5))
                remote_ents[u2] = e
            remote_ents[u2].position = Vec3(d.get('x',0), d.get('y',0), d.get('z',0))
        elif t.startswith(TOPIC + "/users/"):
            u2 = t[len(TOPIC + "/users/"):]
            if not m.payload:
                users.pop(u2, None)
                if u2 in remote_ents:
                    destroy(remote_ents[u2]); del remote_ents[u2]
            else:
                users[u2] = pytime.time()
    except Exception: pass

def net_start():
    def run():
        try:
            try:
                c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, transport="websockets",
                                client_id="pl-"+str(int(pytime.time()*1000)%1000000))
            except Exception:
                c = mqtt.Client(transport="websockets",
                                client_id="pl-"+str(int(pytime.time()*1000)%1000000))
            c.ws_set_options(path=BROKER_PATH)
            c.tls_set(cert_reqs=ssl.CERT_NONE); c.tls_insecure_set(True)
            c.on_connect = on_conn; c.on_message = on_msg
            c.connect(BROKER, BROKER_PORT, keepalive=30); c.loop_start()
            net_client[0] = c
        except Exception as e:
            print("[Net]", e)
    threading.Thread(target=run, daemon=True).start()

app = Ursina(title="PyBlox Play - " + place_name)
window.color = color.rgba32(135, 206, 235, 255)
try: window.fps_counter.enabled = True
except Exception: pass

Entity(model='plane', scale=200, color=color.rgba32(100, 140, 80, 255),
       collider='box', unlit=True)

block_entities = []
for b in blocks_data:
    try:
        col = color.rgba32(int(b['color'][0]), int(b['color'][1]),
                            int(b['color'][2]), 255)
    except Exception:
        col = color.rgba32(150, 120, 90, 255)
    e = Entity(model='cube', position=(b['x'], b['y'], b['z']),
               scale=(b['sx'], b['sy'], b['sz']),
               rotation=(b['rx'], b['ry'], b['rz']),
               color=col, collider='box', unlit=True)
    block_entities.append(e)

player_spawn = (spawn[0], spawn[1] + 1, spawn[2])
player = Entity(model='cube', color=color.rgba32(52, 152, 219, 255),
                scale=(1, 1.8, 1), position=player_spawn, unlit=True)
player.velocity = Vec3(0, 0, 0); player.on_ground = False
PHH, PHW, PHD = 0.9, 0.5, 0.5
cam_yaw, cam_pitch = 45.0, 25.0
mouse.locked = False
GRAVITY, JUMP_SPEED, MOVE_SPEED, SPRINT = -30.0, 12.0, 9.0, 1.5

Text(text=place_name + "  [" + username + "]",
     position=window.top_left + Vec2(0.15, -0.05), scale=1.3, background=True)
Text(text="WASD  Space  R respawn  RMB rotate  Esc exit",
     position=window.bottom, origin=(0,-0.5), scale=0.75, background=True)

def input(key):
    if key == 'escape':
        try:
            if net_client[0]:
                net_client[0].publish(TOPIC + "/users/" + username, b'',
                                       qos=1, retain=True)
                net_client[0].disconnect()
        except Exception: pass
        application.quit()
    elif key == 'r':
        player.position = Vec3(*player_spawn); player.velocity = Vec3(0, 0, 0)

last_send = [0.0]
net_start()

def update():
    global cam_yaw, cam_pitch
    dt = min(time.dt, 0.1)
    if mouse.right:
        if not mouse.locked: mouse.locked = True
        cam_yaw += mouse.velocity[0] * 40
        cam_pitch -= mouse.velocity[1] * 40
        cam_pitch = max(-10, min(70, cam_pitch))
    else:
        if mouse.locked: mouse.locked = False

    yr = math.radians(cam_yaw)
    fwd = Vec3(math.sin(yr), 0, math.cos(yr))
    rgt = Vec3(math.cos(yr), 0, -math.sin(yr))
    mv = Vec3(0, 0, 0)
    if held_keys['w']: mv += fwd
    if held_keys['s']: mv -= fwd
    if held_keys['d']: mv += rgt
    if held_keys['a']: mv -= rgt
    if mv.length() > 0:
        mv = mv.normalized()
        sp = MOVE_SPEED * (SPRINT if held_keys['shift'] else 1.0)
        player.velocity.x = mv.x * sp; player.velocity.z = mv.z * sp
    else:
        player.velocity.x = 0; player.velocity.z = 0
    if player.on_ground and held_keys['space']:
        player.velocity.y = JUMP_SPEED; player.on_ground = False
    player.velocity.y += GRAVITY * dt
    if player.velocity.y < -30: player.velocity.y = -30

    old = Vec3(player.position); new = old + player.velocity * dt
    player.on_ground = False
    if player.velocity.y <= 0:
        for e in block_entities:
            ex, ey, ez = e.world_position
            ehw, ehh, ehd = e.scale.x/2, e.scale.y/2, e.scale.z/2
            if not (new.x+PHW > ex-ehw and new.x-PHW < ex+ehw and
                    new.z+PHD > ez-ehd and new.z-PHD < ez+ehd): continue
            top = ey + ehh
            if old.y-PHH >= top-0.05 and new.y-PHH <= top+0.3:
                new.y = top + PHH; player.velocity.y = 0; player.on_ground = True
                break
    if new.y < -50:
        new = Vec3(*player_spawn); player.velocity = Vec3(0,0,0)
    player.position = new

    target = player.position + Vec3(0, 1, 0)
    pr = math.radians(cam_pitch)
    camera.position = Vec3(
        target.x - math.sin(yr) * 10 * math.cos(pr),
        target.y + math.sin(pr) * 10 + 1,
        target.z - math.cos(yr) * 10 * math.cos(pr))
    camera.look_at(target)

    t = pytime.time()
    if t - last_send[0] > 0.06:
        last_send[0] = t
        try:
            net_client[0].publish(TOPIC + "/pos", json.dumps({
                'user': username, 'x': round(player.position.x, 2),
                'y': round(player.position.y, 2), 'z': round(player.position.z, 2),
                'c': '#3498db'}), qos=0)
            net_client[0].publish(TOPIC + "/users/" + username,
                                   json.dumps({'ts': t}), qos=1, retain=True)
        except Exception: pass

    for u in list(users.keys()):
        if t - users[u] > 30:
            users.pop(u, None)
            if u in remote_ents:
                destroy(remote_ents[u]); del remote_ents[u]

app.run()
'''
# ==================== КОНЕЦ PLAYER ====================


# ---------- Утилиты ----------
def load_json(p, d):
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f: return json.load(f)
        except Exception: pass
    return d

def save_json(p, d):
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

def delete_file(p):
    try:
        if os.path.exists(p): os.remove(p)
    except Exception: pass

def hash_pw(pw): return hashlib.sha256(pw.encode('utf-8')).hexdigest()

def sanitize(name):
    return "".join(ch for ch in name.lower().strip() if ch.isalnum() or ch == '-')

def tcp_precheck(host, port, timeout=2.5):
    try:
        s = socket.create_connection((host, port), timeout=timeout); s.close(); return True
    except Exception: return False

def levenshtein(a, b):
    a = a.lower(); b = b.lower()
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(cur[j-1] + 1, prev[j] + 1, prev[j-1] + cost)
        prev = cur
    return prev[-1]

def similarity_score(query, nick):
    q = query.lower(); n = nick.lower()
    if q == n: return 0
    if q and (n.startswith(q) or q.startswith(n)):
        return 1 + abs(len(n) - len(q))
    if q and (q in n or n in q):
        return 3 + abs(len(n) - len(q))
    return 6 + levenshtein(q, n)

def make_mqtt_client(transport, tls, path):
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, transport=transport,
                        client_id=f"pyblox-{int(time.time()*1000) % 1000000}")
    except (AttributeError, TypeError):
        c = mqtt.Client(transport=transport,
                        client_id=f"pyblox-{int(time.time()*1000) % 1000000}")
    if transport == "websockets" and path:
        try: c.ws_set_options(path=path)
        except Exception: pass
    if tls:
        try:
            c.tls_set(cert_reqs=ssl.CERT_NONE); c.tls_insecure_set(True)
        except Exception: pass
    return c

def circular_avatar(path, size=72):
    img = Image.open(path).convert("RGBA")
    w, h = img.size; m = min(w, h)
    img = img.crop(((w-m)//2,(h-m)//2,(w+m)//2,(h+m)//2)).resize((size,size), Image.LANCZOS)
    mask = Image.new("L", (size,size), 0)
    ImageDraw.Draw(mask).ellipse((0,0,size,size), fill=255)
    out = Image.new("RGBA", (size,size), (0,0,0,0))
    out.paste(img, (0,0), mask)
    return out

def default_avatar(username, size=72):
    colors = ["#e57373","#64b5f6","#81c784","#ffb74d","#ba68c8","#4db6ac","#f06292","#7986cb"]
    c = colors[hash(username) % len(colors)]
    img = Image.new("RGBA", (size,size), (0,0,0,0))
    d = ImageDraw.Draw(img); d.ellipse((0,0,size,size), fill=c)
    letter = username[0].upper() if username else "?"
    try: d.text((size//2,size//2), letter, fill="white", anchor="mm")
    except Exception: pass
    return img

def fmt_age(s):
    s = int(max(0, s))
    if s < 60: return f"{s} " + ("с" if LANG=='ru' else "s")
    if s < 3600: return f"{s//60} " + ("мин" if LANG=='ru' else "min")
    if s < 86400: return f"{s//3600} " + ("ч" if LANG=='ru' else "h")
    return f"{s//86400} " + ("дн" if LANG=='ru' else "d")

def new_msg_id(prefix='msg'):
    return f"{prefix}_{int(time.time()*1000)}_{random.randint(100,999)}"


# ---------- Голос ----------
class VoiceEngine:
    def __init__(self, on_send, on_speaking):
        self.on_send=on_send; self.on_speaking=on_speaking
        self.in_stream=None; self.out_stream=None
        self.enabled=False; self.device_index=None
        self.play_q=queue.Queue(maxsize=30)
        self._last_speak=0; self._speak_state=False
    def list_input_devices(self):
        if not VOICE_OK: return []
        try:
            return [(i,d['name']) for i,d in enumerate(sd.query_devices())
                    if d['max_input_channels']>0]
        except Exception: return []
    def start_output(self):
        if not VOICE_OK or self.out_stream: return
        try:
            self.out_stream=sd.OutputStream(samplerate=VOICE_RATE, channels=1,
                dtype='int16', blocksize=VOICE_CHUNK, callback=self._out_cb)
            self.out_stream.start()
        except Exception as e: print("[Voice] out:", e)
    def stop_output(self):
        try:
            if self.out_stream: self.out_stream.stop(); self.out_stream.close()
        except Exception: pass
        self.out_stream=None
    def _out_cb(self, outdata, frames, time_, status):
        try: data=self.play_q.get_nowait()
        except queue.Empty: outdata.fill(0); return
        if len(data)<frames:
            data=np.concatenate([data, np.zeros(frames-len(data), dtype=np.int16)])
        outdata[:]=data[:frames].reshape(-1,1)
    def feed(self, arr):
        try: self.play_q.put_nowait(arr)
        except queue.Full:
            try: self.play_q.get_nowait()
            except Exception: pass
            try: self.play_q.put_nowait(arr)
            except Exception: pass
    def set_device(self, idx):
        self.device_index=idx
        if self.enabled: self.stop_capture(); self.start_capture()
    def toggle(self):
        if self.enabled: self.stop_capture()
        else: self.start_capture()
        return self.enabled
    def start_capture(self):
        if not VOICE_OK: return False
        try:
            self.start_output()
            self.in_stream=sd.InputStream(samplerate=VOICE_RATE, channels=1,
                dtype='int16', blocksize=VOICE_CHUNK, device=self.device_index,
                callback=self._in_cb)
            self.in_stream.start(); self.enabled=True; return True
        except Exception as e:
            print("[Voice] in:", e); self.enabled=False; return False
    def stop_capture(self):
        try:
            if self.in_stream: self.in_stream.stop(); self.in_stream.close()
        except Exception: pass
        self.in_stream=None; self.enabled=False; self._speak_state=False
        try: self.on_speaking(False)
        except Exception: pass
    def _in_cb(self, indata, frames, time_, status):
        if status: return
        try:
            raw=indata.copy().flatten()
            rms=float(np.sqrt(np.mean(raw.astype(np.float32)**2)))
            sp=rms > VOICE_THRESHOLD
            if sp: self._last_speak=time.time()
            if sp != self._speak_state:
                self._speak_state=sp
                try: self.on_speaking(sp)
                except Exception: pass
            try: self.on_send(raw.tobytes())
            except Exception: pass
        except Exception: pass
    def tick_speaking_timeout(self):
        if self._speak_state and (time.time()-self._last_speak) > SPEAKING_TIMEOUT:
            self._speak_state=False
            try: self.on_speaking(False)
            except Exception: pass


# ---------- Камера ----------
class CameraEngine:
    if CAM_OK:
        if os.name == 'nt':
            BACKENDS = [(cv2.CAP_DSHOW,"DSHOW"),(cv2.CAP_MSMF,"MSMF"),(cv2.CAP_ANY,"ANY")]
        else:
            BACKENDS = [(cv2.CAP_V4L2,"V4L2"),(cv2.CAP_ANY,"ANY")]
    else:
        BACKENDS = []

    def __init__(self, on_frame):
        self.on_frame=on_frame; self.cap=None; self.thread=None
        self.running=False; self.device_index=0; self.fps=CAM_FPS
        self.backend_name="?"; self._stop_event=threading.Event()

    @staticmethod
    def _try_open_static(idx, bidx):
        cap=None
        try:
            cap=cv2.VideoCapture(idx, bidx)
            if not cap.isOpened():
                try: cap.release()
                except Exception: pass
                return None
            for _ in range(20):
                ret, frame=cap.read()
                if ret and frame is not None and frame.size>0:
                    return cap
                time.sleep(0.05)
            try: cap.release()
            except Exception: pass
            return None
        except Exception:
            try:
                if cap: cap.release()
            except Exception: pass
            return None

    @staticmethod
    def probe_cameras(max_check=6):
        if not CAM_OK: return []
        found=[]
        for bidx,bname in CameraEngine.BACKENDS:
            for i in range(max_check):
                if i in found: continue
                cap=CameraEngine._try_open_static(i, bidx)
                if cap is not None:
                    found.append(i)
                    try: cap.release()
                    except Exception: pass
            if found: break
        return sorted(found)

    def set_device(self, idx):
        self.device_index=int(idx)
        if self.running: self.stop(); time.sleep(0.3); self.start()
    def toggle(self):
        if self.running: self.stop(); return False
        return self.start()
    def start(self):
        if not CAM_OK:
            messagebox.showerror(t('error'), "pip install opencv-python"); return False
        if self.running: return True
        tried=[]; cap=None; used="?"
        for bidx,bname in self.BACKENDS:
            tried.append(bname)
            cap=self._try_open_static(self.device_index, bidx)
            if cap is not None: used=bname; break
        if cap is None:
            messagebox.showerror(t('error'),
                t('camera_fail', n=self.device_index) + "\n" + ", ".join(tried))
            return False
        try: cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        except Exception: pass
        try: cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        except Exception: pass
        self.cap=cap; self.backend_name=used; self.running=True
        self._stop_event.clear()
        self.thread=threading.Thread(target=self._loop, daemon=True); self.thread.start()
        return True
    def stop(self):
        self.running=False; self._stop_event.set()
        try:
            if self.cap: self.cap.release()
        except Exception: pass
        self.cap=None
    def _loop(self):
        period=1.0/max(1,self.fps); fails=0
        while self.running and not self._stop_event.is_set():
            t0=time.time()
            try:
                ret, frame=self.cap.read()
                if not ret or frame is None or frame.size==0:
                    fails+=1
                    if fails>60: self.running=False; break
                    time.sleep(0.02); continue
                fails=0
                frame=cv2.resize(frame, (CAM_W,CAM_H), interpolation=cv2.INTER_AREA)
                ok, buf=cv2.imencode('.jpg', frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), CAM_QUALITY])
                if ok:
                    try: self.on_frame(buf.tobytes())
                    except Exception: pass
            except Exception:
                fails+=1
                if fails>60: self.running=False; break
                time.sleep(0.1)
            dt=time.time()-t0
            if dt<period: time.sleep(period-dt)


# ---------- Экран ----------
class ScreenEngine:
    def __init__(self, on_frame, resolution="1280x720", fps=30):
        self.on_frame=on_frame; self.running=False; self.thread=None
        self.resolution=resolution; self.fps=fps
        self._lock=threading.Lock()
    def get_res_wh(self):
        with self._lock:
            return SCREEN_RESOLUTIONS.get(self.resolution, SCREEN_RESOLUTIONS["1280x720"])
    def set_quality(self, resolution=None, fps=None):
        with self._lock:
            if resolution in SCREEN_RESOLUTIONS: self.resolution=resolution
            if fps and int(fps) in SCREEN_FPS_CHOICES: self.fps=int(fps)
            return self.resolution, self.fps
    def toggle(self):
        if self.running: self.stop(); return False
        return self.start()
    def start(self):
        if not PIL_OK or ImageGrab is None: return False
        if self.running: return True
        self.running=True
        self.thread=threading.Thread(target=self._loop, daemon=True); self.thread.start()
        return True
    def stop(self): self.running=False
    def _loop(self):
        while self.running:
            t0=time.time()
            try:
                w,h,q=self.get_res_wh()
                img=ImageGrab.grab()
                img=img.resize((w,h), Image.LANCZOS)
                if img.mode!='RGB': img=img.convert('RGB')
                buf=io.BytesIO(); img.save(buf, format='JPEG', quality=q)
                try: self.on_frame(buf.getvalue())
                except Exception: pass
            except Exception as e:
                print("[Screen]", e); time.sleep(0.2)
            with self._lock: fps=self.fps
            period=1.0/max(1,fps)
            dt=time.time()-t0
            if dt<period: time.sleep(period-dt)


# ==================== ОСНОВНОЕ ПРИЛОЖЕНИЕ ====================
class PyBlox:
    def __init__(self):
        self.root=tk.Tk()
        self.root.title(f"PyBlox v{CURRENT_VERSION}")
        self.root.geometry("900x760")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.is_fullscreen=False
        self.root.bind('<F11>', lambda e: self.toggle_fullscreen())

        self.root.bind_all("<MouseWheel>", self._global_mousewheel)
        self.root.bind_all("<Button-4>",   self._global_mousewheel)
        self.root.bind_all("<Button-5>",   self._global_mousewheel)

        self.accounts=load_json(ACCOUNTS_FILE, {})
        self.last_user=load_json(LAST_USER_FILE, {}).get('user','')
        self.session=load_json(SESSION_FILE, {})

        self.profile=load_json(PROFILE_FILE, {
            'avatar_path':'','mic_device':None,'cam_device':0,
            'screen_res':'1280x720','screen_fps':30,'use_webrtc':False,
            'language':'ru',
            'status_type':'online', 'status_text':''})
        if self.profile.get('screen_res') not in SCREEN_RESOLUTIONS:
            old=self.profile.get('screen_res','')
            self.profile['screen_res']=LEGACY_RES_MAP.get(old,'1280x720')
        if self.profile.get('screen_fps') not in SCREEN_FPS_CHOICES:
            self.profile['screen_fps']=30
        if 'use_webrtc' not in self.profile: self.profile['use_webrtc']=False
        if 'language' not in self.profile: self.profile['language']='ru'
        if 'status_type' not in self.profile: self.profile['status_type']='online'
        if 'status_text' not in self.profile: self.profile['status_text']=''
        try: set_lang(self.profile.get('language','ru'))
        except Exception: pass

        self.my_status = {
            'type': self.profile.get('status_type','online'),
            'text': self.profile.get('status_text',''),
        }

        self.username=None
        self.mqtt=None; self.mqtt_connected=False; self.broker_label=""
        self.connect_log=[]; self._finding=False

        # Друзья
        self.friends=[]
        self.incoming_requests=[]
        self.outgoing_requests=[]
        self.all_profiles={}
        self.dm_history={}
        self.friend_req_topics={}
        self.inbox_topics={}
        self.dm_windows={}
        self.friends_window=[None]
        self.requests_window=[None]

        self.known_users=set(self.accounts.keys())

        self.current_server=None
        self.chat_topic=None; self.users_topic=None
        self.voice_topic_prefix=None; self.avatar_topic_prefix=None
        self.video_topic_prefix=None; self.screen_topic_prefix=None
        self.my_voice_topic=None; self.my_avatar_topic=None
        self.my_video_topic=None; self.my_screen_topic=None
        self.my_heartbeat_topic=None; self.hosting_topic=None

        self.webrtc_signal_prefix=None; self.my_webrtc_signal_topic=None
        self.webrtc=None
        self.webrtc_enabled=WEBRTC_LIB_OK and bool(self.profile.get('use_webrtc', False))
        self._webrtc_known_peers=set()

        self.is_host=False
        self.online={}
        self.user_avatars={}; self.user_speaking={}; self.avatar_widgets={}
        self.last_frames={}; self.last_frame_ts={}; self.video_widgets={}
        self._video_render_job=None

        self.discovered={}; self.list_refresh_job=None
        self.list_debounce_job=None; self._broker_status_job=None
        self.hb_stop=threading.Event(); self.speak_tick_job=None
        self._update_info=None; self._update_checked=False

        self.places={}; self.places_debounce_job=None
        self.on_places=False; self.on_server_list=False

        self.file_server = None
        self.remote_files = {}

        self.voice=VoiceEngine(on_send=self._voice_send, on_speaking=self._my_speaking_changed)
        if VOICE_OK and self.profile.get('mic_device') is not None:
            self.voice.device_index=self.profile.get('mic_device')
        self.camera=CameraEngine(on_frame=self._camera_frame)
        try: self.camera.device_index=int(self.profile.get('cam_device',0))
        except Exception: self.camera.device_index=0
        self.screen=ScreenEngine(on_frame=self._screen_frame,
            resolution=self.profile.get('screen_res','1280x720'),
            fps=self.profile.get('screen_fps',30))

        self.my_avatar_img=None; self._load_my_avatar()

        auto_user=self.session.get('user') if isinstance(self.session, dict) else None
        if auto_user and auto_user in self.accounts:
            self.username=auto_user
            save_json(LAST_USER_FILE, {'user':auto_user})
            self.show_menu()
            try: self.root.after(500, self._subscribe_user_topics)
            except Exception: pass
        else:
            self.show_auth()

        self._start_broker_search()
        self._schedule_speaking_tick()
        if UPDATER_OK:
            self.root.after(3000, self._check_updates_async)

    def _global_mousewheel(self, event):
        try:
            w = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        while w:
            try:
                if isinstance(w, tk.Canvas) and getattr(w, '_scrollable', False):
                    delta = 0
                    num = getattr(event, 'num', 0)
                    d = getattr(event, 'delta', 0)
                    if num == 4 or d > 0: delta = -3
                    elif num == 5 or d < 0: delta = 3
                    if delta:
                        w.yview_scroll(delta, "units")
                    return
            except Exception:
                pass
            try:
                w = w.master
            except Exception:
                break

    # ============================================================
    # ПОИСК ПОХОЖИХ НИКОВ
    # ============================================================
    def _known_pool(self):
        pool = set(self.known_users)
        pool |= set(self.accounts.keys())
        pool |= set(self.all_profiles.keys())
        pool.discard(self.username)
        pool -= set(self.friends)
        pool -= set(self.outgoing_requests)
        pool -= set(self.incoming_requests)
        pool.discard('')
        return pool

    def find_similar_users(self, query, limit=SIMILAR_LIMIT):
        q = (query or '').strip()
        pool = self._known_pool()
        now = time.time()
        results = []
        for nick in pool:
            if q:
                score = similarity_score(q, nick)
                if score > SIMILAR_MAX_DISTANCE: continue
            else:
                score = 100
            prof = self.all_profiles.get(nick, {})
            ts = prof.get('ts', 0)
            is_online = bool(ts and (now - ts) < ONLINE_TTL)
            results.append((nick, score, is_online))
        results.sort(key=lambda x: (x[1], not x[2], x[0].lower()))
        return results[:limit]

    # ============================================================
    # СТАТУСЫ
    # ============================================================
    def _status_for(self, nick):
        if nick == self.username:
            return self.my_status
        prof = self.all_profiles.get(nick, {})
        st = prof.get('status')
        if isinstance(st, dict):
            return st
        return {'type':'online','text':''}

    def _status_info(self, nick):
        st = self._status_for(nick)
        t = st.get('type','online')
        info = STATUS_TYPES.get(t, STATUS_TYPES['online'])
        if t == 'custom':
            txt = (st.get('text') or '').strip()
            label = txt if txt else "Свой статус"
            return ('🟡', label, info['color'])
        return (info['label'].split()[0], info['short'], info['color'])

    def _status_emoji(self, nick): return self._status_info(nick)[0]
    def _status_color(self, nick): return self._status_info(nick)[2]
    def _status_label(self, nick): return self._status_info(nick)[1]

    def _set_my_status(self, stype, stext=''):
        if stype not in STATUS_TYPES: stype = 'online'
        stext = (stext or '').strip()[:MAX_STATUS_TEXT]
        self.my_status = {'type': stype, 'text': stext}
        self.profile['status_type'] = stype
        self.profile['status_text'] = stext
        try: save_json(PROFILE_FILE, self.profile)
        except Exception: pass
        self._publish_my_profile()
        try: self._refresh_friends_ui()
        except Exception: pass
        self._notify_info(f"🎭 Статус: {STATUS_TYPES[stype]['short']}" +
                          (f" — {stext}" if stext else ""))

    def show_status_menu(self):
        w = tk.Toplevel(self.root)
        w.title("Мой статус")
        w.geometry("420x420")
        w.configure(bg="#eceff1")
        tk.Label(w, text="🎭 Мой статус", bg="#eceff1", fg="#263238",
                 font=("Arial",16,"bold")).pack(pady=(18,6))

        var = tk.StringVar(value=self.my_status.get('type','online'))
        for code, info in STATUS_TYPES.items():
            rf = tk.Frame(w, bg="#eceff1"); rf.pack(anchor='w', padx=30, pady=6)
            tk.Radiobutton(rf, text=info['label'], variable=var, value=code,
                           bg="#eceff1", font=("Arial",11,"bold"),
                           activebackground="#eceff1").pack(anchor='w')

        tk.Label(w, text="Текст (для «Свой статус», до 60 символов):",
                 bg="#eceff1", fg="#333", font=("Arial",9)).pack(pady=(14,4))
        text_entry = tk.Entry(w, width=42, font=("Arial",11))
        text_entry.pack(pady=2)
        text_entry.insert(0, self.my_status.get('text',''))

        hint = tk.Label(w, text="", bg="#eceff1", fg="#666", font=("Arial",8))
        hint.pack(pady=2)
        def upd_hint(*_):
            n = len(text_entry.get())
            hint.config(text=f"{n}/{MAX_STATUS_TEXT}")
        text_entry.bind('<KeyRelease>', upd_hint); upd_hint()

        def do_save():
            t = var.get()
            txt = text_entry.get() if t == 'custom' else ''
            self._set_my_status(t, txt)
            w.destroy()

        btns = tk.Frame(w, bg="#eceff1"); btns.pack(pady=14)
        tk.Button(btns, text="💾 Сохранить", bg="#43a047", fg="white", bd=0,
                  font=("Arial",11,"bold"), padx=18, pady=6,
                  command=do_save).pack(side='left', padx=6)
        tk.Button(btns, text="Отмена", bg="#b0bec5", fg="white", bd=0,
                  font=("Arial",11,"bold"), padx=18, pady=6,
                  command=w.destroy).pack(side='left', padx=6)
        tk.Label(w, text="Статус виден друзьям и в чате",
                 bg="#eceff1", fg="#777", font=("Arial",8)).pack()

    # ============================================================
    # ДРУЗЬЯ — MQTT
    # ============================================================
    def _subscribe_user_topics(self):
        if not self.mqtt or not self.username: return
        try:
            self.mqtt.subscribe(f"{USERS_TOPIC}/{self.username}/inbox/+", qos=1)
        except Exception: pass
        try:
            self.mqtt.subscribe(f"{USERS_TOPIC}/{self.username}/friends", qos=1)
        except Exception: pass
        try:
            self.mqtt.subscribe(f"{USERS_TOPIC}/+/profile", qos=1)
        except Exception: pass
        self._publish_my_profile()

    def _publish_my_profile(self):
        if not self.mqtt or not self.username: return
        try:
            data = {
                'nick': self.username,
                'ts': time.time(),
                'status': self.my_status,
            }
            self.mqtt.publish(f"{USERS_TOPIC}/{self.username}/profile",
                              json.dumps(data), qos=1, retain=True)
        except Exception: pass

    def _publish_my_friends(self):
        if not self.mqtt or not self.username: return
        try:
            self.mqtt.publish(f"{USERS_TOPIC}/{self.username}/friends",
                              json.dumps(self.friends), qos=1, retain=True)
        except Exception: pass

    def _handle_user_message(self, topic, payload):
        try:
            parts = topic.split("/")
            if len(parts) < 5: return
            owner = parts[3]
            subtype = parts[4]

            if subtype == "profile":
                if owner == self.username: return
                if not payload:
                    self.all_profiles.pop(owner, None); return
                try:
                    d = json.loads(payload.decode('utf-8', 'ignore'))
                    self.all_profiles[owner] = d
                    self.known_users.add(owner)
                except Exception: pass
                try: self.root.after(0, self._refresh_friends_ui)
                except Exception: pass
                try: self.root.after(0, self._refresh_requests_ui)
                except Exception: pass
                try: self.root.after(0, self._refresh_dm_window_all)
                except Exception: pass
                return

            if owner != self.username: return

            if subtype == "friends":
                if not payload:
                    self.friends = []
                else:
                    try:
                        self.friends = json.loads(payload.decode('utf-8','ignore')) or []
                    except Exception: self.friends = []
                for f in self.friends:
                    self.known_users.add(f)
                try: self.root.after(0, self._refresh_friends_ui)
                except Exception: pass
                return

            if subtype == "inbox" and len(parts) >= 6:
                msg_id = parts[5]
                if not payload:
                    self.inbox_topics.pop(msg_id, None); return
                try:
                    d = json.loads(payload.decode('utf-8','ignore'))
                except Exception: return
                mtype = d.get('type')
                frm = d.get('from')
                if not frm or frm == self.username: return
                self.known_users.add(frm)

                if mtype == 'friend_request':
                    if frm not in self.friends and frm not in self.incoming_requests:
                        self.incoming_requests.append(frm)
                        self.friend_req_topics[frm] = topic
                    self._notify_info(f"👥 {frm} хочет добавить вас в друзья")
                    try: self.root.after(0, self._refresh_friends_ui)
                    except Exception: pass
                    try: self.root.after(0, self._refresh_requests_ui)
                    except Exception: pass

                elif mtype == 'friend_accepted':
                    if frm not in self.friends:
                        self.friends.append(frm)
                        self._publish_my_friends()
                    if frm in self.outgoing_requests:
                        self.outgoing_requests.remove(frm)
                    self._notify_info(f"✅ {frm} принял(а) заявку в друзья")
                    try: self.root.after(0, self._refresh_friends_ui)
                    except Exception: pass
                    try: self.root.after(0, self._refresh_requests_ui)
                    except Exception: pass

                elif mtype == 'friend_declined':
                    if frm in self.outgoing_requests:
                        self.outgoing_requests.remove(frm)
                    self._notify_info(f"❌ {frm} отклонил(а) вашу заявку")
                    try: self.root.after(0, self._refresh_friends_ui)
                    except Exception: pass
                    try: self.root.after(0, self._refresh_requests_ui)
                    except Exception: pass

                elif mtype == 'friend_deleted':
                    if frm in self.friends:
                        self.friends.remove(frm)
                        self._publish_my_friends()
                    self._notify_info(f"👋 {frm} удалил(а) вас из друзей")
                    try: self.root.after(0, self._refresh_friends_ui)
                    except Exception: pass
                    try: self.root.after(0, self._refresh_requests_ui)
                    except Exception: pass

                elif mtype == 'message':
                    text = d.get('text','')
                    ts = d.get('ts', time.time())
                    self.dm_history.setdefault(frm, []).append(
                        {'from': frm, 'text': text, 'ts': ts})
                    try:
                        self.root.after(0, lambda u=frm, txt=text: self._on_new_dm(u, txt))
                    except Exception: pass
                try:
                    self.mqtt.publish(topic, b'', qos=1, retain=True)
                except Exception: pass
        except Exception as e:
            print("[user msg]", e)

    def send_friend_request(self, nick):
        nick = sanitize(nick)
        if not nick or not self.mqtt_connected or not self.mqtt: return False, "Нет сети"
        if nick == self.username: return False, "Это твой ник"
        if nick in self.friends: return False, "Уже друг"
        if nick in self.outgoing_requests: return False, "Заявка уже отправлена"
        try:
            mid = new_msg_id('req')
            self.mqtt.publish(f"{USERS_TOPIC}/{nick}/inbox/{mid}",
                json.dumps({'type':'friend_request','from':self.username,'ts':time.time()}),
                qos=1, retain=True)
            self.outgoing_requests.append(nick)
            return True, "Заявка отправлена"
        except Exception as e:
            return False, str(e)

    def accept_friend_request(self, nick):
        if nick not in self.incoming_requests: return
        if nick not in self.friends:
            self.friends.append(nick)
            self._publish_my_friends()
        self.incoming_requests.remove(nick)
        topic = self.friend_req_topics.pop(nick, None)
        if topic and self.mqtt:
            try: self.mqtt.publish(topic, b'', qos=1, retain=True)
            except Exception: pass
        try:
            mid = new_msg_id('acc')
            self.mqtt.publish(f"{USERS_TOPIC}/{nick}/inbox/{mid}",
                json.dumps({'type':'friend_accepted','from':self.username,'ts':time.time()}),
                qos=1, retain=True)
        except Exception: pass
        self._refresh_friends_ui()
        self._refresh_requests_ui()

    def decline_friend_request(self, nick):
        """Отклонить одну входящую заявку."""
        if nick not in self.incoming_requests:
            return
        self.incoming_requests.remove(nick)
        # очистить retained заявку у брокера (чтобы не вернулась при реконнекте)
        topic = self.friend_req_topics.pop(nick, None)
        if topic and self.mqtt:
            try: self.mqtt.publish(topic, b'', qos=1, retain=True)
            except Exception: pass
        # уведомить отправителя
        try:
            if self.mqtt:
                mid = new_msg_id('dec')
                self.mqtt.publish(f"{USERS_TOPIC}/{nick}/inbox/{mid}",
                    json.dumps({'type':'friend_declined','from':self.username,'ts':time.time()}),
                    qos=1, retain=True)
        except Exception: pass
        self._notify_info(f"✖ Заявка от {nick} отклонена")
        self._refresh_friends_ui()
        self._refresh_requests_ui()

    def decline_all_requests(self):
        """Отклонить все входящие заявки разом."""
        if not self.incoming_requests:
            return
        if not messagebox.askyesno("Отклонить все заявки?",
            f"Отклонить все {len(self.incoming_requests)} заявок?\n\n"
            "Отправители получат уведомление."):
            return
        names = list(self.incoming_requests)
        for nick in names:
            self.decline_friend_request(nick)
        self._notify_info(f"✖ Отклонено заявок: {len(names)}")

    def cancel_outgoing_request(self, nick):
        """Отменить свою исходящую заявку."""
        if nick not in self.outgoing_requests: return
        self.outgoing_requests.remove(nick)
        # уведомить получателя (хоть как-то — пусть знает что заявка отозвана)
        try:
            if self.mqtt:
                mid = new_msg_id('cancel')
                self.mqtt.publish(f"{USERS_TOPIC}/{nick}/inbox/{mid}",
                    json.dumps({'type':'friend_cancelled','from':self.username,'ts':time.time()}),
                    qos=1, retain=True)
        except Exception: pass
        self._notify_info(f"↩ Заявка к {nick} отменена")
        self._refresh_friends_ui()
        self._refresh_requests_ui()

    def remove_friend(self, nick):
        if nick not in self.friends: return
        self.friends.remove(nick)
        self._publish_my_friends()
        try:
            mid = new_msg_id('del')
            self.mqtt.publish(f"{USERS_TOPIC}/{nick}/inbox/{mid}",
                json.dumps({'type':'friend_deleted','from':self.username,'ts':time.time()}),
                qos=1, retain=True)
        except Exception: pass
        self._refresh_friends_ui()

    def send_dm(self, nick, text):
        if not self.mqtt_connected or not self.mqtt: return False
        text = (text or '').strip()
        if not text: return False
        try:
            mid = new_msg_id('dm')
            self.mqtt.publish(f"{USERS_TOPIC}/{nick}/inbox/{mid}",
                json.dumps({'type':'message','from':self.username,
                            'text':text,'ts':time.time()}),
                qos=1, retain=True)
            self.dm_history.setdefault(nick, []).append(
                {'from': self.username, 'text': text, 'ts': time.time()})
            return True
        except Exception as e:
            print("[dm]", e); return False

    def _notify_info(self, text):
        try:
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.configure(bg="#263238")
            tk.Label(w, text=text, bg="#263238", fg="white",
                     font=("Arial",11), padx=18, pady=10).pack()
            self.root.update_idletasks()
            sw = self.root.winfo_screenwidth()
            w.geometry(f"+{max(20, sw - 420)}+20")
            w.attributes("-topmost", True)
            w.after(4500, w.destroy)
        except Exception: pass

    def _on_new_dm(self, nick, text):
        self._notify_info(f"💬 {nick}: {text[:60]}")
        self._refresh_dm_window(nick)

    def _refresh_friends_ui(self):
        try:
            if self.friends_window[0] and self.friends_window[0].winfo_exists():
                self._render_friends_content()
        except Exception: pass

    def _refresh_requests_ui(self):
        try:
            if self.requests_window[0] and self.requests_window[0].winfo_exists():
                self._render_requests_content()
        except Exception: pass

    def _refresh_dm_window_all(self):
        for nick in list(self.dm_windows.keys()):
            self._refresh_dm_window(nick)

    # ============================================================
    # ДРУЗЬЯ — ОКНО
    # ============================================================
    def show_friends(self):
        if self.friends_window[0] and self.friends_window[0].winfo_exists():
            try:
                self.friends_window[0].lift()
                self.friends_window[0].focus_force()
                self._render_friends_content()
                return
            except Exception: pass

        w = tk.Toplevel(self.root)
        w.title("PyBlox — Друзья")
        w.geometry("680x680")
        w.configure(bg="#eceff1")
        self.friends_window[0] = w
        w.protocol("WM_DELETE_WINDOW",
                   lambda: (w.destroy(), self.friends_window.__setitem__(0, None)))
        self._render_friends_content()

    def _render_friends_content(self):
        w = self.friends_window[0]
        if not w or not w.winfo_exists(): return
        for child in w.winfo_children(): child.destroy()

        top = tk.Frame(w, bg="#263238"); top.pack(fill='x')
        tk.Label(top, text="  👥 Друзья", bg="#263238", fg="white",
                 font=("Arial",14,"bold")).pack(side='left', pady=8)
        tk.Button(top, text="🎭 Мой статус", bg="#ff9800", fg="white", bd=0,
                  font=("Arial",10,"bold"),
                  command=self.show_status_menu).pack(side='right', padx=6, pady=6)
        tk.Button(top, text="➕ Добавить", bg="#43a047", fg="white", bd=0,
                  font=("Arial",10,"bold"),
                  command=self.show_add_friend).pack(side='right', padx=6, pady=6)
        req_label = f"📬 Заявки ({len(self.incoming_requests)})" if self.incoming_requests else "📬 Заявки"
        tk.Button(top, text=req_label,
                  bg="#ff9800" if self.incoming_requests else "#546e7a",
                  fg="white", bd=0, font=("Arial",10,"bold"),
                  command=self.show_friend_requests).pack(side='right', padx=6, pady=6)

        # Мой статус
        my_st_emoji, my_st_label, my_st_color = self._status_info(self.username)
        me_row = tk.Frame(w, bg="#37474f"); me_row.pack(fill='x')
        tk.Label(me_row, text=f"  {my_st_emoji}  {self.username} — {my_st_label}",
                 bg="#37474f", fg="#eceff1", font=("Arial",10)).pack(side='left', padx=8, pady=4)
        tk.Button(me_row, text="изменить", bg="#37474f", fg="#80cbc4", bd=0,
                  font=("Arial",9,"italic"),
                  command=self.show_status_menu).pack(side='right', padx=8)

        hint = tk.Label(w, anchor='w', bg="#455a64", fg="#cfd8dc",
                        font=("Arial",9), padx=8, pady=3)
        hint.pack(fill='x')
        hint.config(text=f"🌐 {self.broker_label or '—'}   •   "
                         f"Друзей: {len(self.friends)}   •   "
                         f"Заявок: {len(self.incoming_requests)}   •   "
                         f"Отправлено: {len(self.outgoing_requests)}")

        body = tk.Frame(w, bg="#fafafa"); body.pack(fill='both', expand=True)
        cvs = tk.Canvas(body, bg="#fafafa", highlightthickness=0)
        cvs._scrollable = True
        scr = tk.Scrollbar(body, orient='vertical', command=cvs.yview)
        cvs.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y'); cvs.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(cvs, bg="#fafafa")
        cvs.create_window((0,0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: cvs.configure(scrollregion=cvs.bbox('all')))

        nothing = (not self.friends and not self.outgoing_requests
                   and not self.incoming_requests)
        if nothing:
            tk.Label(inner, text="Пока нет друзей", bg="#fafafa", fg="#888",
                     font=("Arial",12)).pack(pady=30)
            tk.Label(inner, text="Нажми ➕ Добавить чтобы отправить заявку по нику",
                     bg="#fafafa", fg="#aaa", font=("Arial",10)).pack()
        else:
            # === Входящие заявки — ВВЕРХУ, с inline кнопками ===
            if self.incoming_requests:
                header = tk.Frame(inner, bg="#ffe0b2"); header.pack(fill='x', pady=(10,4))
                tk.Label(header, text=f"  📬 Входящие заявки ({len(self.incoming_requests)})",
                         bg="#ffe0b2", fg="#4e342e",
                         font=("Arial",12,"bold")).pack(side='left', pady=6)
                tk.Button(header, text="❌ Отклонить все",
                          bg="#e53935", fg="white", bd=0,
                          font=("Arial",9,"bold"),
                          command=self.decline_all_requests).pack(side='right', padx=8, pady=4)
                for nick in list(self.incoming_requests):
                    self._render_friend_row(inner, nick, kind='incoming')

            # === Отправленные заявки ===
            if self.outgoing_requests:
                tk.Label(inner, text="Отправленные заявки", bg="#fafafa", fg="#333",
                         font=("Arial",12,"bold"), anchor='w'
                         ).pack(fill='x', padx=14, pady=(14,4))
                for nick in sorted(self.outgoing_requests):
                    self._render_friend_row(inner, nick, kind='outgoing')

            # === Друзья ===
            if self.friends:
                tk.Label(inner, text="Друзья", bg="#fafafa", fg="#333",
                         font=("Arial",12,"bold"), anchor='w'
                         ).pack(fill='x', padx=14, pady=(14,4))
                for nick in sorted(self.friends):
                    self._render_friend_row(inner, nick, kind='friend')

    def _render_friend_row(self, parent, nick, kind='friend'):
        bg = "white"
        if kind == 'incoming':
            bg = "#fff3e0"      # светло-оранжевый — входящая заявка
        elif kind == 'outgoing':
            bg = "#eceff1"      # серый — отправленная заявка

        row = tk.Frame(parent, bg=bg, bd=1, relief='solid')
        row.pack(fill='x', padx=12, pady=4)

        av = default_avatar(nick, 44)
        if PIL_OK:
            if kind == 'incoming':
                ring_color = "#ff9800"
            elif kind == 'outgoing':
                ring_color = "#90a4ae"
            else:
                ring_color = self._status_color(nick)
            ringed = Image.new("RGBA", (50,50), (0,0,0,0))
            rd = ImageDraw.Draw(ringed)
            rd.ellipse((0,0,50,50), fill=ring_color)
            ringed.paste(av, (3,3), av)
            ph = ImageTk.PhotoImage(ringed)
            lbl = tk.Label(row, image=ph, bg=bg)
            lbl.image = ph
            lbl.pack(side='left', padx=8, pady=6)
            lbl.bind('<Button-3>', lambda e, n=nick, k=kind: self._row_context_menu(e, n, k))
            lbl.bind('<Control-Button-1>', lambda e, n=nick, k=kind: self._row_context_menu(e, n, k))

        emoji = self._status_emoji(nick)
        label = self._status_label(nick)
        name_frame = tk.Frame(row, bg=bg); name_frame.pack(side='left', padx=4)
        tk.Label(name_frame, text=f"{emoji} {nick}", bg=bg, fg="#222",
                 font=("Arial",12,"bold")).pack(anchor='w')

        sub = label
        if kind == 'incoming':
            sub = "хочет добавить вас в друзья"
        elif kind == 'outgoing':
            sub = "ожидает подтверждения"
        tk.Label(name_frame, text=sub, bg=bg,
                 fg="#e65100" if kind == 'incoming' else "#666",
                 font=("Arial",9, "italic" if kind != 'friend' else "normal")
                 ).pack(anchor='w')

        right = tk.Frame(row, bg=bg); right.pack(side='right', padx=8)

        if kind == 'friend':
            tk.Button(right, text="💬", bg="#2196f3", fg="white", bd=0,
                      font=("Arial",10,"bold"), width=3,
                      command=lambda n=nick: self.show_dm(n)).pack(side='right', padx=2)
            tk.Button(right, text="👤", bg="#607d8b", fg="white", bd=0,
                      font=("Arial",10,"bold"), width=3,
                      command=lambda n=nick: self.show_profile(n)).pack(side='right', padx=2)
            tk.Button(right, text="🗑", bg="#e53935", fg="white", bd=0,
                      font=("Arial",10,"bold"), width=3,
                      command=lambda n=nick: self._confirm_remove_friend(n)
                      ).pack(side='right', padx=2)

        elif kind == 'incoming':
            def mk_accept(n=nick):
                def _():
                    self.accept_friend_request(n)
                    self._notify_info(f"✔ {n} теперь ваш друг")
                return _
            def mk_decline(n=nick):
                def _():
                    self.decline_friend_request(n)
                return _
            tk.Button(right, text="✔ Принять", bg="#43a047", fg="white", bd=0,
                      font=("Arial",10,"bold"),
                      command=mk_accept()).pack(side='right', padx=2)
            tk.Button(right, text="✖ Отклонить", bg="#e53935", fg="white", bd=0,
                      font=("Arial",10,"bold"),
                      command=mk_decline()).pack(side='right', padx=2)

        elif kind == 'outgoing':
            def mk_cancel(n=nick):
                def _():
                    self.cancel_outgoing_request(n)
                return _
            tk.Button(right, text="↩ Отменить", bg="#78909c", fg="white", bd=0,
                      font=("Arial",10,"bold"),
                      command=mk_cancel()).pack(side='right', padx=2)

    # ---- ПКМ меню для строки списка ----
    def _row_context_menu(self, event, nick, kind):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="👤 Посмотреть профиль",
                      command=lambda: self.show_profile(nick))
        if kind == 'friend':
            m.add_command(label="💬 Написать другу",
                          command=lambda: self.show_dm(nick))
            m.add_command(label="📞 Позвонить другу",
                          command=lambda: self.call_friend(nick))
            m.add_separator()
            m.add_command(label="🗑 УДАЛИТЬ ДРУГА",
                          command=lambda: self._confirm_remove_friend(nick))
        elif kind == 'incoming':
            m.add_separator()
            m.add_command(label="✔ Принять заявку",
                          command=lambda: self.accept_friend_request(nick))
            m.add_command(label="✖ Отклонить заявку",
                          command=lambda: self.decline_friend_request(nick))
        elif kind == 'outgoing':
            m.add_separator()
            m.add_command(label="↩ Отменить заявку",
                          command=lambda: self.cancel_outgoing_request(nick))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            try: m.grab_release()
            except Exception: pass

    # ============================================================
    # ОТДЕЛЬНОЕ ОКНО ЗАЯВОК (дублирует, но с расширенными действиями)
    # ============================================================
    def show_friend_requests(self):
        if self.requests_window[0] and self.requests_window[0].winfo_exists():
            try:
                self.requests_window[0].lift()
                self.requests_window[0].focus_force()
                self._render_requests_content()
                return
            except Exception: pass
        w = tk.Toplevel(self.root)
        w.title("Заявки в друзья")
        w.geometry("620x560")
        w.configure(bg="#eceff1")
        self.requests_window[0] = w
        w.protocol("WM_DELETE_WINDOW",
                   lambda: (w.destroy(), self.requests_window.__setitem__(0, None)))
        self._render_requests_content()

    def _render_requests_content(self):
        w = self.requests_window[0]
        if not w or not w.winfo_exists(): return
        for child in w.winfo_children(): child.destroy()

        top = tk.Frame(w, bg="#263238"); top.pack(fill='x')
        tk.Label(top, text="  📬 Заявки в друзья", bg="#263238", fg="white",
                 font=("Arial",13,"bold")).pack(side='left', pady=8)
        if self.incoming_requests:
            tk.Button(top, text="❌ Отклонить все", bg="#e53935", fg="white", bd=0,
                      font=("Arial",10,"bold"),
                      command=self.decline_all_requests).pack(side='right', padx=6, pady=6)

        body = tk.Frame(w, bg="#fafafa"); body.pack(fill='both', expand=True)
        cvs = tk.Canvas(body, bg="#fafafa", highlightthickness=0)
        cvs._scrollable = True
        scr = tk.Scrollbar(body, orient='vertical', command=cvs.yview)
        cvs.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y'); cvs.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(cvs, bg="#fafafa")
        cvs.create_window((0,0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: cvs.configure(scrollregion=cvs.bbox('all')))

        # ---- ВХОДЯЩИЕ ----
        tk.Label(inner, text="Входящие", bg="#fafafa", fg="#333",
                 font=("Arial",12,"bold"), anchor='w').pack(fill='x', padx=14, pady=(10,4))
        if not self.incoming_requests:
            tk.Label(inner, text="Пока нет входящих заявок", bg="#fafafa", fg="#888",
                     font=("Arial",10,"italic")).pack(pady=8)
        else:
            for nick in list(self.incoming_requests):
                self._render_friend_row(inner, nick, kind='incoming')

        # ---- ИСХОДЯЩИЕ ----
        tk.Label(inner, text="Исходящие", bg="#fafafa", fg="#333",
                 font=("Arial",12,"bold"), anchor='w').pack(fill='x', padx=14, pady=(18,4))
        if not self.outgoing_requests:
            tk.Label(inner, text="Нет отправленных заявок", bg="#fafafa", fg="#888",
                     font=("Arial",10,"italic")).pack(pady=8)
        else:
            for nick in sorted(self.outgoing_requests):
                self._render_friend_row(inner, nick, kind='outgoing')

    # ============================================================
    # ДОБАВИТЬ ДРУГА (с автопоиском похожих)
    # ============================================================
    def show_add_friend(self):
        w = tk.Toplevel(self.root)
        w.title("Добавить друга")
        w.geometry("460x520")
        w.configure(bg="#eceff1")

        tk.Label(w, text="➕ Добавить друга", bg="#eceff1", fg="#263238",
                 font=("Arial",14,"bold")).pack(pady=(16,4))
        tk.Label(w, text="Начни вводить ник — найдём похожие:",
                 bg="#eceff1", fg="#555", font=("Arial",9)).pack()

        entry = tk.Entry(w, width=34, font=("Arial",13))
        entry.pack(pady=8)
        entry.focus_set()

        status = tk.Label(w, text="", bg="#eceff1", fg="#d32f2f",
                          font=("Arial",10), wraplength=420, justify='center')
        status.pack(pady=(0,6))

        tk.Label(w, text="Похожие пользователи:", bg="#eceff1", fg="#333",
                 font=("Arial",10,"bold"), anchor='w').pack(fill='x', padx=30, pady=(4,2))

        list_frame = tk.Frame(w, bg="#eceff1"); list_frame.pack(fill='both', expand=True, padx=30, pady=(0,6))
        sb = tk.Scrollbar(list_frame, orient='vertical')
        sb.pack(side='right', fill='y')
        lb = tk.Listbox(list_frame, font=("Consolas",10), height=11,
                        yscrollcommand=sb.set, activestyle='dotbox')
        lb.pack(side='left', fill='both', expand=True)
        sb.config(command=lb.yview)

        row_nicks = []

        def refresh_list(*_):
            row_nicks.clear()
            lb.delete(0, 'end')
            q = entry.get().strip()
            matches = self.find_similar_users(q, limit=SIMILAR_LIMIT)
            if not matches:
                if q:
                    lb.insert('end', f"  (нет похожих на «{q}»)")
                else:
                    lb.insert('end', "  (пока никого не знаем — начни вводить ник)")
                return
            for nick, score, is_online in matches:
                emoji = self._status_emoji(nick)
                if score == 0:
                    tag = "точное совпадение"
                elif score <= 3:
                    tag = "очень похоже"
                elif score <= 7:
                    tag = f"похоже ({score})"
                else:
                    tag = f"lev={score}"
                onl = "🟢" if is_online else "⚫"
                lb.insert('end', f"  {emoji} {onl} {nick:<18}  — {tag}")
                row_nicks.append(nick)

        def pick_suggestion(event=None):
            sel = lb.curselection()
            if not sel: return
            idx = sel[0]
            if idx < len(row_nicks):
                entry.delete(0, 'end')
                entry.insert(0, row_nicks[idx])
                refresh_list()

        def pick_and_send(event=None):
            sel = lb.curselection()
            if not sel: return
            idx = sel[0]
            if idx < len(row_nicks):
                nick = row_nicks[idx]
                entry.delete(0, 'end')
                entry.insert(0, nick)
                do_send()

        lb.bind('<ButtonRelease-1>', lambda e: pick_suggestion())
        lb.bind('<Double-Button-1>', pick_and_send)
        lb.bind('<Return>', pick_and_send)

        entry.bind('<KeyRelease>', refresh_list)

        def do_send():
            nick = entry.get().strip()
            if not nick:
                status.config(text="Введи ник", fg="#d32f2f"); return
            target = sanitize(nick)
            pool = self._known_pool()
            for k in pool:
                if k.lower() == nick.lower():
                    target = k; break
            ok, msg = self.send_friend_request(target)
            if ok:
                status.config(text=f"✅ {msg} → {target}", fg="#2e7d32")
                entry.delete(0, 'end')
                self._refresh_friends_ui()
                self._refresh_requests_ui()
                refresh_list()
            else:
                status.config(text=f"❌ {msg}", fg="#d32f2f")

        entry.bind('<Return>', lambda e: do_send())

        btns = tk.Frame(w, bg="#eceff1"); btns.pack(pady=8)
        tk.Button(btns, text="Отправить заявку", bg="#43a047", fg="white",
                  font=("Arial",11,"bold"), bd=0, padx=20, pady=6,
                  command=do_send).pack(side='left', padx=4)
        tk.Button(btns, text="Обновить", bg="#546e7a", fg="white",
                  font=("Arial",11,"bold"), bd=0, padx=14, pady=6,
                  command=refresh_list).pack(side='left', padx=4)

        tk.Label(w, text="Клик — подставить • Двойной клик — отправить заявку\n" +
                          "Заявка дойдёт даже если человек офлайн",
                 bg="#eceff1", fg="#777", font=("Arial",8)).pack(pady=(0,8))

        refresh_list()

    def show_profile(self, nick):
        w = tk.Toplevel(self.root)
        w.title(f"Профиль — {nick}")
        w.geometry("380x520")
        w.configure(bg="#eceff1")
        tk.Label(w, text="👤 Профиль", bg="#eceff1", fg="#263238",
                 font=("Arial",16,"bold")).pack(pady=(18,6))
        av = default_avatar(nick, 120)
        if PIL_OK:
            ring_color = self._status_color(nick)
            ringed = Image.new("RGBA", (132,132), (0,0,0,0))
            rd = ImageDraw.Draw(ringed)
            rd.ellipse((0,0,132,132), fill=ring_color)
            ringed.paste(av, (6,6), av)
            ph = ImageTk.PhotoImage(ringed)
            lbl = tk.Label(w, image=ph, bg="#eceff1"); lbl.image = ph
            lbl.pack(pady=6)
        tk.Label(w, text=nick, bg="#eceff1", fg="#222",
                 font=("Arial",18,"bold")).pack(pady=4)

        st_emoji, st_label, st_color = self._status_info(nick)
        st_frame = tk.Frame(w, bg="#eceff1"); st_frame.pack(pady=4)
        tk.Label(st_frame, text=st_emoji, bg="#eceff1",
                 font=("Arial",14)).pack(side='left', padx=(0,6))
        tk.Label(st_frame, text=st_label, bg="#eceff1", fg=st_color,
                 font=("Arial",11,"bold")).pack(side='left')

        is_friend = nick in self.friends
        is_incoming = nick in self.incoming_requests
        is_outgoing = nick in self.outgoing_requests

        if is_friend:
            tk.Label(w, text="✅ Друг", bg="#eceff1", fg="#2e7d32",
                     font=("Arial",10,"italic")).pack()
        elif is_incoming:
            tk.Label(w, text="📬 Хочет добавить вас в друзья", bg="#eceff1", fg="#e65100",
                     font=("Arial",10,"italic")).pack()
        elif is_outgoing:
            tk.Label(w, text="⏳ Ждёт подтверждения", bg="#eceff1", fg="#666",
                     font=("Arial",10,"italic")).pack()
        else:
            tk.Label(w, text="Не в друзьях", bg="#eceff1", fg="#999",
                     font=("Arial",10,"italic")).pack()

        prof = self.all_profiles.get(nick, {})
        if prof.get('ts'):
            tk.Label(w, text=f"Последний онлайн: {fmt_age(time.time()-prof['ts'])} назад",
                     bg="#eceff1", fg="#666", font=("Arial",9)).pack(pady=(4,0))

        btns = tk.Frame(w, bg="#eceff1"); btns.pack(pady=20)
        if is_friend:
            tk.Button(btns, text="💬 Написать", bg="#2196f3", fg="white",
                      bd=0, font=("Arial",11,"bold"), padx=16, pady=8,
                      command=lambda: (w.destroy(), self.show_dm(nick))).pack(pady=4, fill='x')
            tk.Button(btns, text="📞 Позвонить", bg="#7e57c2", fg="white",
                      bd=0, font=("Arial",11,"bold"), padx=16, pady=8,
                      command=lambda: (w.destroy(), self.call_friend(nick))).pack(pady=4, fill='x')
            tk.Button(btns, text="🗑 Удалить из друзей", bg="#e53935", fg="white",
                      bd=0, font=("Arial",11,"bold"), padx=16, pady=8,
                      command=lambda: (w.destroy(), self._confirm_remove_friend(nick))
                      ).pack(pady=4, fill='x')
        elif is_incoming:
            tk.Button(btns, text="✔ Принять заявку", bg="#43a047", fg="white",
                      bd=0, font=("Arial",11,"bold"), padx=16, pady=8,
                      command=lambda: (self.accept_friend_request(nick), w.destroy())
                      ).pack(pady=4, fill='x')
            tk.Button(btns, text="✖ Отклонить заявку", bg="#e53935", fg="white",
                      bd=0, font=("Arial",11,"bold"), padx=16, pady=8,
                      command=lambda: (self.decline_friend_request(nick), w.destroy())
                      ).pack(pady=4, fill='x')
        elif is_outgoing:
            tk.Button(btns, text="↩ Отменить заявку", bg="#78909c", fg="white",
                      bd=0, font=("Arial",11,"bold"), padx=16, pady=8,
                      command=lambda: (self.cancel_outgoing_request(nick), w.destroy())
                      ).pack(pady=4, fill='x')
        else:
            tk.Button(btns, text="➕ Добавить в друзья", bg="#43a047", fg="white",
                      bd=0, font=("Arial",11,"bold"), padx=16, pady=8,
                      command=lambda: (self._quick_add_friend(nick), w.destroy())
                      ).pack(pady=4, fill='x')
            tk.Button(btns, text="💬 Написать", bg="#2196f3", fg="white",
                      bd=0, font=("Arial",11,"bold"), padx=16, pady=8,
                      command=lambda: (w.destroy(), self.show_dm(nick))).pack(pady=4, fill='x')

    def show_dm(self, nick):
        existing = self.dm_windows.get(nick)
        if existing:
            try:
                existing.lift(); existing.focus_force()
                self._refresh_dm_window(nick)
                return
            except Exception: pass

        w = tk.Toplevel(self.root)
        w.title(f"Чат с {nick}")
        w.geometry("520x540")
        w.configure(bg="#eceff1")
        self.dm_windows[nick] = w
        def on_close():
            try: w.destroy()
            except Exception: pass
            self.dm_windows.pop(nick, None)
        w.protocol("WM_DELETE_WINDOW", on_close)

        st_emoji, st_label, st_color = self._status_info(nick)
        top = tk.Frame(w, bg="#263238"); top.pack(fill='x')
        tk.Label(top, text=f"  💬 {nick}", bg="#263238", fg="white",
                 font=("Arial",13,"bold")).pack(side='left', pady=8)
        tk.Label(top, text=f"  {st_emoji} {st_label}  ", bg="#263238", fg=st_color,
                 font=("Arial",10)).pack(side='left')
        tk.Button(top, text="👤 Профиль", bg="#455a64", fg="white", bd=0,
                  font=("Arial",9,"bold"),
                  command=lambda: self.show_profile(nick)).pack(side='right', padx=6, pady=6)

        chat = tk.Text(w, bg="#1b1b1b", fg="#e0e0e0", font=("Consolas",11),
                       wrap='word', state='disabled')
        chat.pack(fill='both', expand=True)
        bottom = tk.Frame(w); bottom.pack(fill='x')
        entry = tk.Entry(bottom, font=("Arial",12))
        entry.pack(side='left', fill='x', expand=True, padx=6, pady=6)
        entry.focus_set()

        def do_send(event=None):
            text = entry.get().strip()
            if not text: return
            if self.send_dm(nick, text):
                entry.delete(0, 'end')
                self._refresh_dm_window(nick)

        entry.bind('<Return>', do_send)
        tk.Button(bottom, text="Отправить", bg="#2196f3", fg="white",
                  font=("Arial",11,"bold"), bd=0,
                  command=do_send).pack(side='right', padx=6, pady=6)

        w._chat_widget = chat
        self._refresh_dm_window(nick)

    def _refresh_dm_window(self, nick):
        w = self.dm_windows.get(nick)
        if not w: return
        try:
            if not w.winfo_exists(): return
            chat = getattr(w, '_chat_widget', None)
            if not chat: return
            chat.config(state='normal')
            chat.delete('1.0', 'end')
            for m in self.dm_history.get(nick, []):
                who = "Я" if m.get('from') == self.username else m.get('from', '?')
                ts = time.strftime("%H:%M", time.localtime(m.get('ts', time.time())))
                chat.insert('end', f"[{ts}] {who}: {m.get('text','')}\n")
            chat.see('end')
            chat.config(state='disabled')
        except Exception: pass

    def call_friend(self, nick):
        self._notify_info(f"📞 Звонок {nick}... (скоро)")

    def _quick_add_friend(self, nick):
        ok, msg = self.send_friend_request(nick)
        if ok:
            self._notify_info(f"✅ Заявка отправлена → {sanitize(nick)}")
        else:
            self._notify_info(f"❌ {msg}")

    def _confirm_remove_friend(self, nick):
        if not messagebox.askyesno("Удалить из друзей?",
            f"Удалить {nick} из друзей?\n\nЭто действие необратимо."):
            return
        self.remove_friend(nick)
        self._notify_info(f"🗑 {nick} удалён из друзей")

    def _avatar_right_click(self, event, nick):
        """ПКМ по аватару в чате (использует статус: друг / не друг)."""
        if nick in self.friends:
            kind = 'friend'
        elif nick in self.incoming_requests:
            kind = 'incoming'
        elif nick in self.outgoing_requests:
            kind = 'outgoing'
        else:
            kind = 'stranger'
        if kind == 'stranger':
            m = tk.Menu(self.root, tearoff=0)
            m.add_command(label="👤 Посмотреть профиль",
                          command=lambda: self.show_profile(nick))
            m.add_command(label="➕ Добавить в друзья",
                          command=lambda: self._quick_add_friend(nick))
            try: m.tk_popup(event.x_root, event.y_root)
            finally:
                try: m.grab_release()
                except Exception: pass
            return
        self._row_context_menu(event, nick, kind)

    # ============================================================
    # UPDATER
    # ============================================================
    def _check_updates_async(self):
        threading.Thread(target=self._check_updates_worker, daemon=True).start()
    def _check_updates_worker(self):
        try: info=check_for_update(GITHUB_REPO, CURRENT_VERSION, timeout=6)
        except Exception: info=None
        self.root.after(0, lambda: self._on_update_checked(info))
    def _on_update_checked(self, info):
        self._update_checked=True
        if not info: return
        self._update_info=info
        try:
            if hasattr(self,'update_banner') and self.update_banner.winfo_exists():
                self._refresh_update_banner()
        except Exception: pass
        self._show_update_dialog(info)
    def _show_update_dialog(self, info):
        if not info: return
        try:
            if messagebox.askyesno(t('update_available'),
                t('update_msg', current=CURRENT_VERSION, new=info['version'])):
                self._open_release_page(info)
        except Exception: pass
    def _open_release_page(self, info=None):
        info=info or self._update_info
        if not info: return
        url=info.get('html_url') or info.get('asset_url') or ""
        if url:
            try: webbrowser.open(url)
            except Exception: pass
    def manual_check_updates(self):
        if not UPDATER_OK:
            messagebox.showwarning(t('error'), t('no_updater')); return
        if self._update_info: self._show_update_dialog(self._update_info); return
        messagebox.showinfo(t('check_updates'),
            f"{t('version')}: {CURRENT_VERSION}\n{t('search_updates')}")
        threading.Thread(target=self._manual_check_worker, daemon=True).start()
    def _manual_check_worker(self):
        try: info=check_for_update(GITHUB_REPO, CURRENT_VERSION, timeout=8)
        except Exception: info=None
        self.root.after(0, lambda: self._on_manual_check(info))
    def _on_manual_check(self, info):
        if info:
            self._update_info=info
            try:
                if hasattr(self,'update_banner') and self.update_banner.winfo_exists():
                    self._refresh_update_banner()
            except Exception: pass
            self._show_update_dialog(info)
        else:
            messagebox.showinfo(t('no_updates'), t('no_updates_msg', v=CURRENT_VERSION))
    def _refresh_update_banner(self):
        if not hasattr(self,'update_banner') or not self.update_banner.winfo_exists(): return
        if self._update_info:
            self.update_banner.config(
                text="⬆️ " + t('update_banner', v=self._update_info['version']),
                bg="#ffb74d", fg="#3e2723", cursor="hand2")
            self.update_banner.pack(fill='x', pady=(0,10))
        else:
            self.update_banner.pack_forget()

    def toggle_fullscreen(self):
        self.is_fullscreen=not self.is_fullscreen
        try: self.root.attributes('-fullscreen', self.is_fullscreen)
        except Exception:
            try: self.root.attributes('-zoomed', self.is_fullscreen)
            except Exception: pass

    # ---------- АВАТАР ----------
    def _load_my_avatar(self):
        if not PIL_OK: return
        p=self.profile.get('avatar_path','')
        if p and os.path.exists(p):
            try: self.my_avatar_img=circular_avatar(p); return
            except Exception: pass
        self.my_avatar_img=None
    def _get_avatar_image(self, u):
        if u == self.username and self.my_avatar_img is not None: return self.my_avatar_img
        if u in self.user_avatars: return self.user_avatars[u]
        if PIL_OK: return default_avatar(u)
        return None
    def _publish_my_avatar(self):
        if not self.mqtt_connected or not self.my_avatar_topic: return
        try:
            if self.my_avatar_img is not None:
                buf=io.BytesIO(); self.my_avatar_img.save(buf, format='PNG')
                self.mqtt.publish(self.my_avatar_topic, buf.getvalue(), qos=1, retain=True)
            else:
                self.mqtt.publish(self.my_avatar_topic, b'', qos=1, retain=True)
        except Exception: pass

    # ---------- СТРИМЫ ----------
    def _voice_send(self, payload):
        if not self.mqtt_connected or not self.my_voice_topic: return
        try: self.mqtt.publish(self.my_voice_topic, payload, qos=0)
        except Exception: pass
    def _my_speaking_changed(self, sp):
        try: self.root.after(0, lambda: self._set_user_speaking(self.username, sp))
        except Exception: pass
    def _camera_frame(self, b): self._local_frame('cam', b)
    def _screen_frame(self, b): self._local_frame('screen', b)
    def _local_frame(self, src, b):
        if not PIL_OK: return
        key=(self.username, src)
        try:
            img=Image.open(io.BytesIO(b)).convert("RGB")
            self.last_frames[key]=img; self.last_frame_ts[key]=time.time()
        except Exception: pass
        if self.mqtt_connected and self.mqtt:
            topic=self.my_video_topic if src=='cam' else self.my_screen_topic
            if topic:
                try: self.mqtt.publish(topic, b, qos=0)
                except Exception: pass

    # ---------- MQTT ----------
    def _start_broker_search(self):
        if self._finding: return
        self._finding=True
        threading.Thread(target=self._find_broker, daemon=True).start()
    def _log(self, tx):
        self.connect_log.append(tx); print("[CONNECT]", tx)
        try: self.root.after(0, self._render_connect_log)
        except Exception: pass
    def _render_connect_log(self):
        if not getattr(self,'log_box',None): return
        try:
            if not self.log_box.winfo_exists(): return
            self.log_box.config(state='normal')
            self.log_box.delete('1.0','end')
            self.log_box.insert('end', "\n".join(self.connect_log[-6:]))
            self.log_box.see('end'); self.log_box.config(state='disabled')
        except Exception: pass
    def _find_broker(self):
        self._log("🌐 Connecting...")
        for host, port, transport, tls, path, label in BROKER_CANDIDATES:
            if self.mqtt_connected: break
            try:
                self._log(f"→ {label}")
                if not tcp_precheck(host, port, timeout=2.5):
                    self._log(f"✗ {label}: port"); continue
                c=make_mqtt_client(transport, tls, path)
                c.on_connect=self._on_connect
                c.on_disconnect=self._on_disconnect
                c.on_message=self._on_message
                c.connect_async(host, port, keepalive=30); c.loop_start()
                for _ in range(40):
                    if self.mqtt_connected: break
                    time.sleep(0.1)
                if self.mqtt_connected:
                    self.mqtt=c; self.broker_label=label
                    self._log(f"✅ {label}"); return
                try: c.loop_stop(); c.disconnect()
                except Exception: pass
            except Exception as e:
                self._log(f"✗ {label}: {e}")
        if not self.mqtt_connected: self._log("❌ Failed")
        self._finding=False
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc != 0: return
        self.mqtt_connected=True
        try: client.subscribe(DISCOVERY_TOPIC + "/+", qos=1)
        except Exception: pass
        try: client.subscribe(PLACES_TOPIC + "/+", qos=1)
        except Exception: pass
        try: self._subscribe_user_topics()
        except Exception as e: print("[subs]", e)
        if self.chat_topic:
            for tt,q in ((self.chat_topic,1),(self.users_topic+"/+",1),
                        (self.voice_topic_prefix+"/+",0),
                        (self.avatar_topic_prefix+"/+",1),
                        (self.video_topic_prefix+"/+",0),
                        (self.screen_topic_prefix+"/+",0)):
                try: client.subscribe(tt, qos=q)
                except Exception: pass
            if self.webrtc_signal_prefix:
                try: client.subscribe(f"{self.webrtc_signal_prefix}/{self.username}", qos=1)
                except Exception: pass
        if self.is_host and self.hosting_topic: self._publish_host_announce()
        self._publish_my_avatar()
    def _on_disconnect(self, client, userdata, rc, properties=None):
        self.mqtt_connected=False
    def _on_message(self, client, userdata, msg):
        try:
            topic=msg.topic; payload=msg.payload

            if topic.startswith(USERS_TOPIC + "/"):
                self._handle_user_message(topic, payload); return

            if topic.startswith(PLACES_TOPIC + "/"):
                pid=topic[len(PLACES_TOPIC)+1:]
                if not payload: self.places.pop(pid, None)
                else:
                    try:
                        d=json.loads(payload.decode('utf-8','ignore'))
                        if isinstance(d,dict) and d.get('id'): self.places[pid]=d
                    except Exception: pass
                try: self.root.after(0, self._schedule_places_refresh)
                except Exception: pass
                return
            if topic.startswith(DISCOVERY_TOPIC + "/"):
                name=topic[len(DISCOVERY_TOPIC)+1:]
                if not payload: self.discovered.pop(name,None)
                else:
                    try:
                        d=json.loads(payload.decode('utf-8','ignore'))
                        if isinstance(d,dict) and 'name' in d:
                            self.discovered[name]=d
                    except Exception: pass
                try: self.root.after(0, self._schedule_list_refresh)
                except Exception: pass
                return
            if self.voice_topic_prefix and topic.startswith(self.voice_topic_prefix+"/"):
                user=topic[len(self.voice_topic_prefix)+1:]
                if user == self.username or not payload: return
                try:
                    arr=np.frombuffer(payload, dtype=np.int16)
                    if arr.size == 0: return
                    rms=float(np.sqrt(np.mean(arr.astype(np.float32)**2)))
                    if rms > VOICE_THRESHOLD:
                        self.user_speaking[user]=time.time()
                        self.voice.feed(arr.copy())
                        self.root.after(0, lambda u=user: self._set_user_speaking(u, True))
                except Exception: pass
                return
            if self.avatar_topic_prefix and topic.startswith(self.avatar_topic_prefix+"/"):
                user=topic[len(self.avatar_topic_prefix)+1:]
                if user == self.username: return
                if not payload: self.user_avatars.pop(user,None)
                else:
                    try:
                        img=Image.open(io.BytesIO(payload)).convert("RGBA")
                        self.user_avatars[user]=img
                    except Exception: pass
                self.root.after(0, lambda u=user: self._refresh_avatar_widget(u))
                return
            if self.video_topic_prefix and topic.startswith(self.video_topic_prefix+"/"):
                user=topic[len(self.video_topic_prefix)+1:]
                if user == self.username: return
                self._handle_stream(user,'cam',payload); return
            if self.screen_topic_prefix and topic.startswith(self.screen_topic_prefix+"/"):
                user=topic[len(self.screen_topic_prefix)+1:]
                if user == self.username: return
                if self.webrtc and user in self.webrtc.pcs: return
                self._handle_stream(user,'screen',payload); return
            if self.webrtc and self.webrtc_signal_prefix and topic.startswith(self.webrtc_signal_prefix+"/"):
                target=topic[len(self.webrtc_signal_prefix)+1:]
                if target != self.username: return
                try: d=json.loads(payload.decode('utf-8','ignore'))
                except Exception: return
                frm=d.get('from','')
                if not frm or frm == self.username: return
                typ=d.get('type')
                if typ=='offer': self.webrtc.handle_offer(frm, d.get('sdp',''), d.get('sdpType','offer'))
                elif typ=='answer': self.webrtc.handle_answer(frm, d.get('sdp',''), d.get('sdpType','answer'))
                elif typ=='ice': self.webrtc.handle_ice(frm, d.get('candidate',{}))
                return
            if self.users_topic and topic.startswith(self.users_topic+"/"):
                nick=topic.rsplit("/",1)[-1]
                if not payload:
                    self.online.pop(nick,None)
                    self.remote_files.pop(nick, None)
                else:
                    try:
                        d = json.loads(payload.decode('utf-8','ignore'))
                        self.online[nick] = d.get('ts', time.time())
                        furl = d.get('file_url') or ''
                        if furl: self.remote_files[nick] = furl
                        else: self.remote_files.pop(nick, None)
                    except Exception:
                        self.online[nick]=time.time()
                self.root.after(0, self.refresh_online)
                if self.is_host: self._publish_host_announce()
                return
            if self.chat_topic and topic == self.chat_topic:
                try: d=json.loads(payload.decode('utf-8','ignore'))
                except Exception: return
                typ=d.get('type'); user=d.get('user','?')
                if user != self.username:
                    self.online[user]=time.time()
                    self.root.after(0, self.refresh_online)
                    if self.is_host: self._publish_host_announce()
                if typ=='chat':
                    self.root.after(0, self.append_chat, f"{user}: {d.get('text','')}")
                elif typ=='join':
                    self.root.after(0, self.append_chat, f"[SYS] {user} joined")
                elif typ=='leave':
                    self.root.after(0, self.append_chat, f"[SYS] {user} left")
                    if self.is_host:
                        self.online.pop(user,None); self._publish_host_announce()
                elif typ=='file':
                    self.root.after(0, self.append_file_link,
                                    user, d.get('name','file'),
                                    d.get('url',''), d.get('size',0))
                return
        except Exception as e: print("[MQTT msg]", e)
    def _handle_stream(self, user, src, payload):
        key=(user,src)
        if not payload:
            self.last_frames.pop(key,None); self.last_frame_ts.pop(key,None)
            self.root.after(0, self._rebuild_video_row); return
        if not PIL_OK: return
        try:
            img=Image.open(io.BytesIO(payload)).convert("RGB")
            self.last_frames[key]=img; self.last_frame_ts[key]=time.time()
        except Exception: pass
    def _schedule_list_refresh(self):
        if self.list_debounce_job:
            try: self.root.after_cancel(self.list_debounce_job)
            except Exception: pass
        self.list_debounce_job=self.root.after(250, self._rebuild_server_list_ui)
    def _schedule_places_refresh(self):
        if self.places_debounce_job:
            try: self.root.after_cancel(self.places_debounce_job)
            except Exception: pass
        self.places_debounce_job=self.root.after(250, self._rebuild_places_ui)

    def _schedule_speaking_tick(self):
        def tick():
            try:
                self.voice.tick_speaking_timeout()
                now=time.time()
                for u,t0 in list(self.user_speaking.items()):
                    if now-t0 > SPEAKING_TIMEOUT:
                        self.user_speaking.pop(u,None); self._set_user_speaking(u, False)
            except Exception: pass
            try: self.speak_tick_job=self.root.after(200, tick)
            except Exception: pass
        self.speak_tick_job=self.root.after(200, tick)
    def _set_user_speaking(self, username, sp):
        w=self.avatar_widgets.get(username)
        if not w: return
        try:
            c=w['canvas']
            if not c.winfo_exists(): return
            if sp:
                c.itemconfig(w['ring_id'], outline="#00e5ff")
            else:
                c.itemconfig(w['ring_id'], outline=self._status_color(username))
        except Exception: pass

    # ---------- АВТОРИЗАЦИЯ ----------
    def show_auth(self):
        for w in self.root.winfo_children(): w.destroy()
        f=tk.Frame(self.root); f.pack(expand=True)
        tk.Label(f, text="PyBlox", font=("Arial",32,"bold"), fg="#1e88e5").pack(pady=(0,4))
        tk.Label(f, text=f"v{CURRENT_VERSION}", font=("Arial",9), fg="#999").pack(pady=(0,14))
        tk.Label(f, text=t('nickname'), font=("Arial",12)).pack()
        self.nick_entry=tk.Entry(f, width=32, font=("Arial",12)); self.nick_entry.pack(pady=4)
        if self.last_user: self.nick_entry.insert(0, self.last_user)
        tk.Label(f, text=t('password'), font=("Arial",12)).pack()
        self.pw_entry=tk.Entry(f, width=32, show="*", font=("Arial",12)); self.pw_entry.pack(pady=4)
        self.pw_entry.bind('<Return>', lambda e: self.login())
        tk.Button(f, text=t('login'), width=24, bg="#43a047", fg="white",
                  font=("Arial",11,"bold"), command=self.login).pack(pady=(14,4))
        tk.Button(f, text=t('register'), width=24, font=("Arial",11),
                  command=self.register).pack(pady=4)
        self.status=tk.Label(f, text="", fg="red", font=("Arial",10)); self.status.pack(pady=4)
        tk.Label(f, text="💡 " + t('auto_login_hint'),
                 font=("Arial",9), fg="#777").pack(pady=(6,4))
        logf=tk.Frame(f, bd=1, relief='solid'); logf.pack(fill='x', padx=20, pady=(8,4))
        tk.Label(logf, text="Network:", font=("Arial",8,"bold"),
                 anchor='w').pack(fill='x', padx=6, pady=(4,0))
        self.log_box=tk.Text(logf, height=6, font=("Consolas",9),
                              bg="#f5f5f5", fg="#333", state='disabled', wrap='word')
        self.log_box.pack(fill='x', padx=6, pady=4)
        tk.Button(f, text="🔄 " + t('reconnect'), font=("Arial",10),
                  command=self.reconnect_broker).pack(pady=4)
        self.broker_status=tk.Label(f, text="", fg="gray", font=("Arial",9))
        self.broker_status.pack(side='bottom', pady=6)
        self._render_connect_log(); self._update_broker_status()
    def reconnect_broker(self):
        try:
            if self.mqtt: self.mqtt.loop_stop(); self.mqtt.disconnect()
        except Exception: pass
        self.mqtt=None; self.mqtt_connected=False
        self.connect_log=[]; self.broker_label=""; self._finding=False
        self._start_broker_search()
    def _update_broker_status(self):
        if self._broker_status_job:
            try: self.root.after_cancel(self._broker_status_job)
            except Exception: pass
            self._broker_status_job=None
        if getattr(self,'broker_status',None) and self.broker_status.winfo_exists():
            if self.mqtt_connected:
                self.broker_status.config(text=f"🌐 {self.broker_label}", fg="#43a047")
            else:
                self.broker_status.config(text="connecting...", fg="gray")
        try: self._broker_status_job=self.root.after(1500, self._update_broker_status)
        except Exception: pass
    def login(self):
        n,p=self.nick_entry.get().strip(), self.pw_entry.get()
        if not n or not p: self.status.config(text=t('fill_fields'), fg="red"); return
        if n not in self.accounts: self.status.config(text=t('player_not_found'), fg="red"); return
        if self.accounts[n] != hash_pw(p): self.status.config(text=t('wrong_password'), fg="red"); return
        self.username=n
        save_json(LAST_USER_FILE, {'user':n})
        save_json(SESSION_FILE, {'user':n, 'ts':time.time()})
        self.show_menu()
        try: self.root.after(400, self._subscribe_user_topics)
        except Exception: pass
    def register(self):
        n,p=self.nick_entry.get().strip(), self.pw_entry.get()
        if not n or not p: self.status.config(text=t('fill_fields'), fg="red"); return
        if len(n) < 3: self.status.config(text=t('nick_short'), fg="red"); return
        if not n.replace('_','').isalnum(): self.status.config(text=t('nick_chars'), fg="red"); return
        if n in self.accounts: self.status.config(text=t('nick_busy'), fg="red"); return
        self.accounts[n]=hash_pw(p); save_json(ACCOUNTS_FILE, self.accounts)
        self.status.config(text=t('account_created'), fg="green")

    # ---------- МЕНЮ ----------
    def show_menu(self):
        self.on_places=False; self.on_server_list=False
        for w in self.root.winfo_children(): w.destroy()
        f=tk.Frame(self.root); f.pack(expand=True)

        st_emoji, st_label, st_color = self._status_info(self.username)
        hello_row = tk.Frame(f); hello_row.pack(pady=(0,4))
        tk.Label(hello_row, text=t('hello', name=self.username),
                 font=("Arial",22,"bold")).pack(side='left')
        st_lbl = tk.Label(hello_row, text=f"  {st_emoji} {st_label}", fg=st_color,
                          font=("Arial",11,"bold"), cursor="hand2")
        st_lbl.pack(side='left', padx=(8,0))
        st_lbl.bind("<Button-1>", lambda e: self.show_status_menu())

        tk.Label(f, text="🔓 " + t('auto_login_on'),
                 font=("Arial",9), fg="#4caf50").pack(pady=(0,6))
        self.update_banner=tk.Label(f, text="", font=("Arial",11,"bold"),
                                     padx=12, pady=10, anchor='w', justify='left')
        self.update_banner.bind("<Button-1>",
                                lambda e: self._show_update_dialog(self._update_info))
        self._refresh_update_banner()
        mode=("🚀 WebRTC" if self.webrtc_enabled else "📡 MQTT") if WEBRTC_LIB_OK else "📡 MQTT"
        tk.Label(f, text=mode, font=("Arial",11), fg="gray").pack(pady=(0,8))
        if PIL_OK and self.my_avatar_img is not None:
            ph=ImageTk.PhotoImage(self.my_avatar_img)
            lbl=tk.Label(f, image=ph); lbl.image=ph; lbl.pack(pady=(0,8))
        tk.Button(f, text="🌐  " + t('servers'), width=32, height=2,
                  bg="#1e88e5", fg="white", font=("Arial",12,"bold"),
                  command=self.show_server_list).pack(pady=5)
        tk.Button(f, text="🛠  " + t('create_server'), width=32, height=2,
                  bg="#43a047", fg="white", font=("Arial",12,"bold"),
                  command=self.create_server).pack(pady=5)
        tk.Button(f, text="🎮  " + t('play_places'), width=32, height=2,
                  bg="#9b59b6", fg="white", font=("Arial",12,"bold"),
                  command=self.show_places).pack(pady=5)
        friends_btn_text = f"👥  Друзья"
        if self.incoming_requests:
            friends_btn_text = f"👥  Друзья ({len(self.incoming_requests)} заявок)"
        tk.Button(f, text=friends_btn_text, width=32, height=2,
                  bg="#e91e63", fg="white", font=("Arial",12,"bold"),
                  command=self.show_friends).pack(pady=5)
        tk.Button(f, text="🎭  Мой статус", width=32, height=2,
                  bg="#ff9800", fg="white", font=("Arial",12,"bold"),
                  command=self.show_status_menu).pack(pady=5)
        tk.Button(f, text="⚙️  " + t('settings'), width=32, font=("Arial",11),
                  command=self.show_settings).pack(pady=(10,4))
        tk.Button(f, text="🚪  " + t('logout'), width=32, font=("Arial",11),
                  command=self.logout).pack(pady=4)
        tk.Label(f, text=f"PyBlox v{CURRENT_VERSION}",
                 font=("Arial",8), fg="#999").pack(pady=(8,0))
        self.broker_status=tk.Label(f, text="", fg="gray", font=("Arial",9))
        self.broker_status.pack(side='bottom', pady=6)
        self._update_broker_status()
    def logout(self):
        self.leave_current(); self.username=None
        delete_file(SESSION_FILE); self.show_auth()

    # ---------- ФАЙЛЫ ----------
    def share_file(self):
        if not FILES_OK:
            messagebox.showerror("Files", "files.py не найден рядом с client.py"); return
        if not self.current_server: return
        if not (self.file_server and self.file_server.running):
            messagebox.showerror("Files", "Твой файловый сервер не запущен"); return

        path = _fd.askopenfilename(title="Выбери файл (до 250 МБ)")
        if not path: return
        size = os.path.getsize(path)
        if size > files_mod.MAX_FILE:
            messagebox.showerror("Files", f"Файл больше 250 МБ\n({size/1024/1024:.0f} МБ)")
            return
        name = os.path.basename(path)
        self.append_chat(f"[FILES] Загружаю {name} ({size/1024/1024:.1f} МБ)...")

        def worker():
            ok, res = files_mod.upload_file(self.file_server.base_url(), path)
            self.root.after(0, lambda: self._after_upload(ok, res, name, size))

        threading.Thread(target=worker, daemon=True).start()

    def _after_upload(self, ok, res, name, size):
        if not ok:
            self.append_chat(f"[FILES] ❌ Ошибка: {res}"); return
        url = self.file_server.file_url(name)
        try:
            self.mqtt.publish(self.chat_topic, json.dumps({
                'type': 'file', 'user': self.username,
                'name': name, 'url': url, 'size': size,
                'ts': time.time()
            }), qos=1)
        except Exception as e:
            self.append_chat(f"[FILES] ❌ {e}"); return
        self.append_chat(f"[FILES] ✅ Ссылка отправлена: {url}")

    def append_file_link(self, user, name, url, size):
        if not getattr(self, 'chat', None) or not self.chat.winfo_exists(): return
        mb = size / 1024 / 1024
        try:
            self.chat.config(state='normal')
            self.chat.insert('end', f"{user}: 📎 ")

            tag_name = f"link_{int(time.time()*1000) % 999999}"
            self.chat.tag_configure(tag_name, foreground="#4da3ff", underline=True)

            link_text = f"{name} ({mb:.1f} МБ)"
            self.chat.insert('end', link_text, tag_name)

            def on_click(event, u=url):
                try: webbrowser.open(u)
                except Exception as e: print("[open]", e)

            self.chat.tag_bind(tag_name, '<Button-1>', on_click)
            self.chat.tag_bind(tag_name, '<Enter>',
                lambda e: self.chat.config(cursor="hand2"))
            self.chat.tag_bind(tag_name, '<Leave>',
                lambda e: self.chat.config(cursor=""))

            self.chat.insert('end', "\n")
            self.chat.see('end')
            self.chat.config(state='disabled')
        except Exception as e:
            print("[link]", e)

    # ---------- ПЛЕЙСЫ ----------
    def show_places(self):
        self.on_places=True; self.on_server_list=False
        if self.mqtt_connected and self.mqtt:
            try: self.mqtt.subscribe(PLACES_TOPIC + "/+", qos=1)
            except Exception: pass
        self._rebuild_places_ui()
    def _rebuild_places_ui(self):
        if not getattr(self, 'on_places', False): return
        if self.places_debounce_job:
            try: self.root.after_cancel(self.places_debounce_job)
            except Exception: pass
            self.places_debounce_job=None
        for w in self.root.winfo_children(): w.destroy()
        top=tk.Frame(self.root, bg="#263238"); top.pack(fill='x')
        tk.Label(top, text="  🎮 " + t('places_title') + "  ", bg="#263238", fg="white",
                 font=("Arial",14,"bold")).pack(side='left')
        tk.Button(top, text="⟳ " + t('refresh'), bg="#455a64", fg="white", bd=0,
                  font=("Arial",10,"bold"),
                  command=self.refresh_places).pack(side='left', padx=8, pady=6)
        tk.Button(top, text="🎨 " + t('open_studio_short'), bg="#9b59b6", fg="white", bd=0,
                  font=("Arial",10,"bold"),
                  command=self.open_studio).pack(side='left', padx=8, pady=6)
        tk.Button(top, text="← " + t('back'), bg="#546e7a", fg="white", bd=0,
                  command=self.back_from_places).pack(side='right', padx=6, pady=6)
        hint=tk.Label(self.root, anchor='w', bg="#37474f", fg="#b0bec5",
                      font=("Arial",9), padx=8, pady=3); hint.pack(fill='x')
        hint.config(text=f"🌐 {self.broker_label}   •   {len(self.places)}")
        body=tk.Frame(self.root); body.pack(fill='both', expand=True)
        cvs=tk.Canvas(body, bg="#fafafa", highlightthickness=0)
        cvs._scrollable = True
        scr=tk.Scrollbar(body, orient='vertical', command=cvs.yview)
        cvs.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y'); cvs.pack(side='left', fill='both', expand=True)
        inner=tk.Frame(cvs, bg="#fafafa")
        cvs.create_window((0,0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: cvs.configure(scrollregion=cvs.bbox('all')))
        if not self.mqtt_connected:
            tk.Label(inner, text="⚠️ " + t('no_network'), font=("Arial",13,"bold"),
                     bg="#fafafa", fg="#e53935").pack(pady=20)
        elif not self.places:
            tk.Label(inner, text=t('no_places'), font=("Arial",13),
                     bg="#fafafa", fg="#757575").pack(pady=30)
            tk.Label(inner, text=t('no_places_hint'),
                     font=("Arial",11), bg="#fafafa", fg="#9e9e9e").pack(pady=(0,10))
            tk.Button(inner, text="🎨 " + t('open_studio'), bg="#9b59b6", fg="white",
                      font=("Arial",12,"bold"), padx=20, pady=8,
                      command=self.open_studio).pack(pady=10)
        else:
            for pid, data in sorted(self.places.items(),
                                     key=lambda kv: -(kv[1].get('updated') or 0)):
                self._render_place_row(inner, pid, data)
        if self.list_refresh_job:
            try: self.root.after_cancel(self.list_refresh_job)
            except Exception: pass
        self.list_refresh_job=self.root.after(LIST_REFRESH_MS, self._auto_refresh_places)
    def _auto_refresh_places(self):
        if not getattr(self,'on_places',False): return
        self._rebuild_places_ui()
    def refresh_places(self):
        if not self.mqtt_connected:
            self.reconnect_broker(); self.root.after(800, self._rebuild_places_ui); return
        try: self.mqtt.unsubscribe(PLACES_TOPIC + "/+")
        except Exception: pass
        self.places={}
        try: self.mqtt.subscribe(PLACES_TOPIC + "/+", qos=1)
        except Exception: pass
        self._rebuild_places_ui()
    def _render_place_row(self, parent, pid, data):
        is_mine = (data.get('author') == self.username)
        bg = "#e8f5e9" if is_mine else "white"
        row=tk.Frame(parent, bg=bg, bd=1, relief='solid'); row.pack(fill='x', padx=12, pady=6)
        left=tk.Frame(row, bg=bg); left.pack(side='left', fill='both', expand=True, padx=10, pady=8)
        title=tk.Frame(left, bg=bg); title.pack(anchor='w')
        tk.Label(title, text=data.get('name','Untitled'), font=("Arial",14,"bold"),
                 bg=bg).pack(side='left')
        if is_mine:
            tk.Label(title, text="  " + t('my_server'), font=("Arial",10,"italic"),
                     fg="#43a047", bg=bg).pack(side='left')
        n_blocks = len(data.get('blocks', []))
        info=f"{t('author')}: {data.get('author','?')}   •   "
        info += f"{t('blocks_count')}: {n_blocks}   •   "
        info += f"{t('max_players_short')}: {data.get('max_players', 15)}"
        tk.Label(left, text=info, font=("Arial",9), bg=bg, fg="#757575").pack(anchor='w')
        right=tk.Frame(row, bg=bg); right.pack(side='right', padx=10, pady=8)
        tk.Button(right, text="  🎮 " + t('play') + "  ", bg="#9b59b6", fg="white",
                  font=("Arial",11,"bold"), bd=0,
                  command=lambda d=data: self.join_place(d)).pack(side='right')
    def back_from_places(self):
        self.on_places=False
        if self.list_refresh_job:
            try: self.root.after_cancel(self.list_refresh_job)
            except Exception: pass
            self.list_refresh_job=None
        self.show_menu()
    def open_studio(self):
        studio_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio.py")
        if not os.path.exists(studio_path):
            messagebox.showerror(t('error'),
                t('client_only_studio', path=studio_path)); return
        try:
            if os.name == "nt":
                subprocess.Popen([sys.executable, studio_path],
                                 creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen([sys.executable, studio_path], start_new_session=True)
        except Exception as e:
            messagebox.showerror(t('error'), str(e))
    def check_place_capacity(self, place_id, max_players):
        result={'count':0}
        def run():
            try:
                try:
                    c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                                  transport="websockets",
                                  client_id="cap-"+str(int(time.time()*1000)%1000000))
                except Exception:
                    c=mqtt.Client(transport="websockets",
                                  client_id="cap-"+str(int(time.time()*1000)%1000000))
                c.ws_set_options(path="/mqtt")
                c.tls_set(cert_reqs=ssl.CERT_NONE); c.tls_insecure_set(True)
                got=[]
                def on_conn(cl,u,f,rc,p=None):
                    if rc==0: cl.subscribe(f"{PLAY_TOPIC}/{place_id}/users/+", qos=1)
                def on_msg(cl,u,m):
                    if m.payload: got.append(m.topic)
                c.on_connect=on_conn; c.on_message=on_msg
                c.connect("broker.emqx.io", 8084, keepalive=10); c.loop_start()
                time.sleep(1.2)
                try: c.loop_stop(); c.disconnect()
                except Exception: pass
                result['count']=len(set(got))
            except Exception: pass
        t2=threading.Thread(target=run); t2.start(); t2.join(3.0)
        return result['count'] < max_players, result['count']
    def join_place(self, place_data):
        if not URSINA_OK:
            if messagebox.askyesno(t('need_ursina'), t('install_ursina_q')):
                try:
                    subprocess.Popen([sys.executable, "-m", "pip", "install", "ursina"])
                    messagebox.showinfo(t('install_started'), t('install_started_msg'))
                except Exception as e:
                    messagebox.showerror(t('error'), str(e))
            return
        pid=place_data.get('id'); max_pl=int(place_data.get('max_players', 15))
        ok, count=self.check_place_capacity(pid, max_pl)
        if not ok:
            messagebox.showerror(t('room_full'),
                t('room_full_msg', name=place_data.get('name','?'),
                  count=count, max=max_pl)); return
        try:
            path=os.path.join(tempfile.gettempdir(), f"pyblox_place_{pid}.json")
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(place_data, f, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror(t('error'), str(e)); return
        try:
            player_path=os.path.join(tempfile.gettempdir(), "pyblox_player_runtime.py")
            with open(player_path, 'w', encoding='utf-8') as f:
                f.write(PLAYER_SOURCE)
        except Exception as e:
            messagebox.showerror(t('error'), str(e)); return
        try:
            if os.name == "nt":
                subprocess.Popen([sys.executable, player_path, self.username, path],
                                 creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen([sys.executable, player_path, self.username, path],
                                 start_new_session=True)
        except Exception as e:
            messagebox.showerror(t('error'), str(e))

    # ---------- СПИСОК СЕРВЕРОВ ----------
    def show_server_list(self):
        self.on_server_list=True; self.on_places=False
        if self.mqtt_connected and self.mqtt:
            try: self.mqtt.subscribe(DISCOVERY_TOPIC + "/+", qos=1)
            except Exception: pass
        self._rebuild_server_list_ui()
    def _rebuild_server_list_ui(self, first=False):
        if not getattr(self,'on_server_list',False): return
        if self.list_debounce_job:
            try: self.root.after_cancel(self.list_debounce_job)
            except Exception: pass
            self.list_debounce_job=None
        for w in self.root.winfo_children(): w.destroy()
        top=tk.Frame(self.root, bg="#263238"); top.pack(fill='x')
        tk.Label(top, text="  🌐 " + t('servers_title') + "  ", bg="#263238", fg="white",
                 font=("Arial",14,"bold")).pack(side='left')
        tk.Button(top, text="⟳ " + t('refresh'), bg="#455a64", fg="white", bd=0,
                  font=("Arial",10,"bold"),
                  command=self.refresh_server_list).pack(side='left', padx=8, pady=6)
        tk.Button(top, text="← " + t('back'), bg="#546e7a", fg="white", bd=0,
                  command=self.back_to_menu).pack(side='right', padx=6, pady=6)
        now=time.time()
        oc=sum(1 for d in self.discovered.values()
               if isinstance(d,dict) and d.get('online') and now-d.get('ts',0)<ONLINE_TTL)
        fc=len(self.discovered)-oc
        hint=tk.Label(self.root, anchor='w', bg="#37474f", fg="#b0bec5",
                      font=("Arial",9), padx=8, pady=3); hint.pack(fill='x')
        if self.mqtt_connected:
            hint.config(text=f"🌐 {self.broker_label}   •   🟢 {oc}   •   ⚫ {fc}")
        else:
            hint.config(text="⚠️ " + t('no_network'))
        body=tk.Frame(self.root); body.pack(fill='both', expand=True)
        cvs=tk.Canvas(body, bg="#fafafa", highlightthickness=0)
        cvs._scrollable = True
        scr=tk.Scrollbar(body, orient='vertical', command=cvs.yview)
        cvs.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y'); cvs.pack(side='left', fill='both', expand=True)
        inner=tk.Frame(cvs, bg="#fafafa")
        cvs.create_window((0,0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: cvs.configure(scrollregion=cvs.bbox('all')))
        cutoff=now - SERVER_HIDE_DAYS*86400
        alive={n:d for n,d in self.discovered.items()
               if isinstance(d,dict) and d.get('ts',0)>=cutoff}
        self.discovered=alive
        if not self.mqtt_connected:
            tk.Label(inner, text="⚠️ " + t('no_network'), font=("Arial",13,"bold"),
                     bg="#fafafa", fg="#e53935").pack(pady=20)
        elif not alive:
            tk.Label(inner, text=t('no_servers'), font=("Arial",13),
                     bg="#fafafa", fg="#757575").pack(pady=30)
            tk.Label(inner, text=t('create_first'),
                     font=("Arial",11), bg="#fafafa", fg="#9e9e9e").pack(pady=(0,10))
        else:
            def sort_key(it):
                d=it[1]
                is_on=1 if (d.get('online') and now-d.get('ts',0)<ONLINE_TTL) else 0
                return (-is_on, -d.get('ts',0))
            for name,d in sorted(alive.items(), key=sort_key):
                self._render_server_row(inner, name, d, now)
        if self.list_refresh_job:
            try: self.root.after_cancel(self.list_refresh_job)
            except Exception: pass
        self.list_refresh_job=self.root.after(LIST_REFRESH_MS, self._auto_refresh_list)
    def _render_server_row(self, parent, name, data, now):
        ts=data.get('ts',0)
        is_on=bool(data.get('online')) and now-ts<ONLINE_TTL
        is_mine=(name==self.current_server and self.is_host)
        bg="#e8f5e9" if is_on else "#f0f0f0"
        st="🟢 " + t('online_status') if is_on else "⚫ " + t('offline_status')
        row=tk.Frame(parent, bg=bg, bd=1, relief='solid'); row.pack(fill='x', padx=12, pady=6)
        left=tk.Frame(row, bg=bg); left.pack(side='left', fill='both', expand=True, padx=10, pady=8)
        title=tk.Frame(left, bg=bg); title.pack(anchor='w')
        tk.Label(title, text=name, font=("Arial",14,"bold"), bg=bg).pack(side='left')
        if is_mine:
            tk.Label(title, text="  " + t('my_server'), font=("Arial",10,"italic"),
                     fg="#43a047", bg=bg).pack(side='left')
        host=data.get('host','?'); o=data.get('online_users', data.get('online','?'))
        info=f"{t('host')}: {host}   •   {st}"
        if is_on: info+=f"   •   {t('players')}: {o}"
        info+=f"   •   {fmt_age(now-ts)}"
        tk.Label(left, text=info, font=("Arial",9), bg=bg, fg="#757575").pack(anchor='w')
        right=tk.Frame(row, bg=bg); right.pack(side='right', padx=10, pady=8)
        tk.Button(right, text="  " + t('join') + "  ", bg="#43a047", fg="white",
                  font=("Arial",11,"bold"), bd=0,
                  command=lambda n=name: self.join_from_list(n)).pack(side='right')
        if is_mine:
            tk.Button(right, text="🗑", bg="#e53935", fg="white",
                      font=("Arial",10,"bold"), bd=0,
                      command=lambda n=name: self.delete_server(n)
                      ).pack(side='right', padx=(0,6))
    def delete_server(self, name):
        if not messagebox.askyesno(t('yes'), f"'{name}'?"): return
        if self.mqtt_connected and self.mqtt:
            try:
                self.mqtt.publish(f"{DISCOVERY_TOPIC}/{name}", b'', qos=1, retain=True)
                self.discovered.pop(name,None)
            except Exception: pass
        self._rebuild_server_list_ui()
    def _auto_refresh_list(self):
        if not getattr(self,'on_server_list',False): return
        if self.list_debounce_job:
            try:
                self.root.after_cancel(self.list_debounce_job); self.list_debounce_job=None
            except Exception: pass
        self._rebuild_server_list_ui()
    def refresh_server_list(self):
        if not self.mqtt_connected:
            self.reconnect_broker(); self.root.after(800, self._rebuild_server_list_ui); return
        try: self.mqtt.unsubscribe(DISCOVERY_TOPIC + "/+")
        except Exception: pass
        self.discovered={}
        try: self.mqtt.subscribe(DISCOVERY_TOPIC + "/+", qos=1)
        except Exception: pass
        self._rebuild_server_list_ui()
    def join_from_list(self, name):
        self.on_server_list=False
        for j in ('list_refresh_job','list_debounce_job'):
            jb=getattr(self,j,None)
            if jb:
                try: self.root.after_cancel(jb)
                except Exception: pass
                setattr(self,j,None)
        self.is_host=False; self.enter_server(name)
    def back_to_menu(self):
        self.on_server_list=False
        for j in ('list_refresh_job','list_debounce_job'):
            jb=getattr(self,j,None)
            if jb:
                try: self.root.after_cancel(jb)
                except Exception: pass
                setattr(self,j,None)
        self.show_menu()

    # ---------- НАСТРОЙКИ ----------
    def change_language(self, lang):
        self.profile['language']=lang
        save_json(PROFILE_FILE, self.profile)
        try: set_lang(lang)
        except Exception: pass
        self.show_settings()
    def show_settings(self):
        for w in self.root.winfo_children(): w.destroy()
        outer=tk.Frame(self.root); outer.pack(fill='both', expand=True)
        cvs=tk.Canvas(outer, highlightthickness=0)
        cvs._scrollable = True
        scr=tk.Scrollbar(outer, orient='vertical', command=cvs.yview)
        cvs.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y'); cvs.pack(side='left', fill='both', expand=True)
        f=tk.Frame(cvs); cvs.create_window((0,0), window=f, anchor='nw')
        f.bind('<Configure>', lambda e: cvs.configure(scrollregion=cvs.bbox('all')))
        tk.Label(f, text="⚙️ " + t('settings'), font=("Arial",22,"bold")).pack(pady=(16,16))

        st_frame=tk.LabelFrame(f, text="🎭 Мой статус",
                                font=("Arial",10,"bold"), padx=14, pady=10)
        st_frame.pack(pady=8, padx=20, fill='x')
        st_emoji, st_label, st_color = self._status_info(self.username)
        info_row = tk.Frame(st_frame); info_row.pack(fill='x')
        tk.Label(info_row, text=f"Сейчас: {st_emoji} {st_label}",
                 font=("Arial",10,"bold"), fg=st_color).pack(side='left')
        tk.Button(info_row, text="🎭 Изменить статус",
                  bg="#ff9800", fg="white", font=("Arial",10,"bold"),
                  bd=0, padx=14, pady=6,
                  command=self.show_status_menu).pack(side='right')
        tk.Label(st_frame, text="Статус виден друзьям в чате и профиле",
                 font=("Arial",9), fg="#666", anchor='w').pack(fill='x', pady=(6,0))

        lang_frame=tk.LabelFrame(f, text="🌍 " + t('language_label'),
                                  font=("Arial",10,"bold"), padx=14, pady=10)
        lang_frame.pack(pady=8, padx=20, fill='x')
        lr=tk.Frame(lang_frame); lr.pack(fill='x')
        cur_lang=self.profile.get('language','ru')
        for code, label in (('ru','🇷🇺 Русский'), ('en','🇬🇧 English')):
            b=tk.Button(lr, text=label, width=12, font=("Arial",11,"bold"),
                        bg="#1976d2" if cur_lang==code else "#e0e0e0",
                        fg="white" if cur_lang==code else "#333",
                        command=lambda c=code: self.change_language(c))
            b.pack(side='left', padx=4)

        av=tk.LabelFrame(f, text=t('avatar_in_chat'), font=("Arial",10,"bold"),
                         padx=14, pady=10)
        av.pack(pady=8, padx=20, fill='x')
        r=tk.Frame(av); r.pack(fill='x')
        if PIL_OK and self.my_avatar_img is not None:
            ph=ImageTk.PhotoImage(self.my_avatar_img)
            lbl=tk.Label(r, image=ph); lbl.image=ph; lbl.pack(side='left', padx=(0,12))
        else:
            tk.Label(r, text=t('no_avatar'), fg="#888").pack(side='left', padx=(0,12))
        bc=tk.Frame(r); bc.pack(side='left')
        tk.Button(bc, text="📁 " + t('upload'), width=24,
                  command=self.choose_avatar).pack(anchor='w', pady=2)
        tk.Button(bc, text="🗑 " + t('remove'), width=24,
                  command=self.clear_avatar).pack(anchor='w', pady=2)

        mic=tk.LabelFrame(f, text=t('mic_key'), font=("Arial",10,"bold"), padx=14, pady=10)
        mic.pack(pady=8, padx=20, fill='x')
        if not VOICE_OK:
            tk.Label(mic, text="pip install sounddevice numpy", fg="#e53935").pack(anchor='w')
        else:
            devices=self.voice.list_input_devices()
            labels=[f"{i}: {n}" for i,n in devices] or ["(none)"]
            self.mic_var=tk.StringVar()
            cur=self.profile.get('mic_device')
            if cur is not None:
                for i,n in devices:
                    if i==cur: self.mic_var.set(f"{i}: {n}"); break
            if not self.mic_var.get() and labels: self.mic_var.set(labels[0])
            cb=ttk.Combobox(mic, textvariable=self.mic_var, values=labels,
                            state='readonly', width=52); cb.pack(anchor='w', pady=4)
            cb.bind('<<ComboboxSelected>>', lambda e: self.save_mic_choice())

        cam=tk.LabelFrame(f, text=t('camera_key'), font=("Arial",10,"bold"),
                          padx=14, pady=10)
        cam.pack(pady=8, padx=20, fill='x')
        if not CAM_OK:
            tk.Label(cam, text="pip install opencv-python", fg="#e53935").pack(anchor='w')
        else:
            cr=tk.Frame(cam); cr.pack(fill='x')
            self.cam_var=tk.StringVar()
            cur=int(self.profile.get('cam_device',0)); self.cam_var.set(f"Camera {cur}")
            self.cam_combo=ttk.Combobox(cr, textvariable=self.cam_var,
                values=[f"Camera {i}" for i in range(6)], state='readonly', width=24)
            self.cam_combo.pack(side='left', padx=(0,8))
            self.cam_combo.bind('<<ComboboxSelected>>', lambda e: self.save_cam_choice())
            tk.Button(cr, text="🔍 " + t('find'),
                      command=self.probe_cameras).pack(side='left', padx=(0,6))
            tk.Button(cr, text="▶ " + t('test'),
                      command=self.test_camera).pack(side='left')
            self.cam_test_status=tk.Label(cam, text=t('status') + ": —",
                                          font=("Arial",9), fg="#666", anchor='w')
            self.cam_test_status.pack(anchor='w', pady=(6,0))

        scr_f=tk.LabelFrame(f, text=t('screen_share_key'), font=("Arial",10,"bold"),
                            padx=14, pady=10)
        scr_f.pack(pady=8, padx=20, fill='x')
        wr=tk.Frame(scr_f); wr.pack(fill='x', pady=(0,6))
        if WEBRTC_LIB_OK:
            self.webrtc_var=tk.BooleanVar(value=self.webrtc_enabled)
            tk.Checkbutton(wr, text="🚀 " + t('webrtc_label'),
                           variable=self.webrtc_var,
                           command=self.save_webrtc_choice,
                           font=("Arial",10,"bold")).pack(anchor='w')
        else:
            tk.Label(wr, text="⚠️ " + t('webrtc_unavailable'),
                     font=("Arial",9), fg="#e53935").pack(anchor='w')
            self.webrtc_var=tk.BooleanVar(value=False)
        qr=tk.Frame(scr_f); qr.pack(fill='x', pady=4)
        tk.Label(qr, text=t('resolution')).pack(side='left')
        self.screen_res_var=tk.StringVar(value=self.profile.get('screen_res','1280x720'))
        rc=ttk.Combobox(qr, textvariable=self.screen_res_var,
                        values=list(SCREEN_RESOLUTIONS.keys()),
                        state='readonly', width=12)
        rc.pack(side='left', padx=(6,18))
        rc.bind('<<ComboboxSelected>>', lambda e: self.save_screen_choice())
        tk.Label(qr, text=t('fps_label')).pack(side='left')
        self.screen_fps_var=tk.StringVar(value=str(self.profile.get('screen_fps',30)))
        fc=ttk.Combobox(qr, textvariable=self.screen_fps_var,
                        values=[str(x) for x in SCREEN_FPS_CHOICES],
                        state='readonly', width=6)
        fc.pack(side='left', padx=6)
        fc.bind('<<ComboboxSelected>>', lambda e: self.save_screen_choice())
        self.screen_hint=tk.Label(scr_f, text="", font=("Arial",9), fg="#666")
        self.screen_hint.pack(anchor='w', pady=(6,0))
        self._update_screen_hint()

        studio_frame=tk.LabelFrame(f, text="🎨 " + t('studio_section'),
                                    font=("Arial",10,"bold"), padx=14, pady=10)
        studio_frame.pack(pady=8, padx=20, fill='x')
        tk.Label(studio_frame, text=t('studio_hint'),
                 font=("Arial",9), fg="#666", justify='left').pack(anchor='w')
        tk.Button(studio_frame, text="🎨 " + t('open_studio'),
                  bg="#9b59b6", fg="white", font=("Arial",11,"bold"),
                  padx=20, pady=6,
                  command=self.open_studio).pack(pady=(10,0))

        tk.Button(f, text="🔗  " + t('manual_connect'), width=34, height=2,
                  bg="#1e88e5", fg="white", font=("Arial",11,"bold"),
                  command=self.manual_connect).pack(pady=(14,6))
        tk.Button(f, text="🔄  " + t('reconnect'), width=34, font=("Arial",10),
                  command=self.reconnect_broker).pack(pady=4)
        tk.Button(f, text="⬆️  " + t('check_updates'), width=34, font=("Arial",10,"bold"),
                  bg="#ffb74d", fg="#3e2723",
                  command=self.manual_check_updates).pack(pady=4)
        tk.Label(f, text=f"{t('version')}: {CURRENT_VERSION}   •   {GITHUB_REPO}",
                 font=("Arial",8), fg="#999").pack(pady=(2,0))
        tk.Button(f, text="↩  " + t('back'), width=34, font=("Arial",10),
                  command=self.show_menu).pack(pady=6)
        info=tk.Frame(f, bd=1, relief='solid', padx=14, pady=8); info.pack(pady=10)
        tk.Label(info, text=f"Broker: {self.broker_label or '—'}   •   "
                            f"{'✅' if self.mqtt_connected else '❌'}",
                 font=("Arial",9), fg="#555").pack()

    def test_camera(self):
        if not CAM_OK: return
        idx=0
        try: idx=int(self.cam_var.get().split()[-1])
        except Exception: pass
        def set_status(text, color="#666"):
            try:
                if hasattr(self,'cam_test_status') and self.cam_test_status.winfo_exists():
                    self.cam_test_status.config(text=text, fg=color)
            except Exception: pass
        set_status(f"... {idx}", "#1976d2")
        def run():
            ok=False; backend_used="?"
            for bidx, bname in CameraEngine.BACKENDS:
                cap=CameraEngine._try_open_static(idx, bidx)
                if cap is not None:
                    ok=True; backend_used=bname
                    try: cap.release()
                    except Exception: pass
                    break
            if ok:
                self.root.after(0, lambda: set_status(
                    f"✅ {idx} — {backend_used}", "#2e7d32"))
            else:
                self.root.after(0, lambda: set_status(f"❌ {idx}", "#c62828"))
        threading.Thread(target=run, daemon=True).start()

    def save_webrtc_choice(self):
        val=bool(self.webrtc_var.get())
        self.webrtc_enabled=val and WEBRTC_LIB_OK
        self.profile['use_webrtc']=val; save_json(PROFILE_FILE, self.profile)
        if self.current_server:
            if self.webrtc_enabled:
                if self._ensure_webrtc_instance():
                    if self.mqtt_connected and self.webrtc_signal_prefix:
                        try: self.mqtt.subscribe(
                            f"{self.webrtc_signal_prefix}/{self.username}", qos=1)
                        except Exception: pass
            else:
                if self.webrtc and self.webrtc.sending:
                    self.webrtc.stop_screen()
                    key=(self.username,'screen')
                    self.last_frames.pop(key,None); self.last_frame_ts.pop(key,None)
                    self._rebuild_video_row()
                self._destroy_webrtc_instance()
        self._refresh_screen_btn_label()
        self.show_settings()
    def _update_screen_hint(self):
        if not hasattr(self,'screen_hint') or not self.screen_hint.winfo_exists(): return
        res=self.profile.get('screen_res','1280x720')
        fps=self.profile.get('screen_fps',30)
        if res in SCREEN_RESOLUTIONS: w,h,q=SCREEN_RESOLUTIONS[res]
        else: w,h,q=1280,720,28
        kbps=(w*h)/5000*(q/40)*fps
        rate=f"{kbps/1024:.1f} MB/s" if kbps>1024 else f"{kbps:.0f} KB/s"
        mode="WebRTC" if self.webrtc_enabled and WEBRTC_LIB_OK else "MQTT"
        self.screen_hint.config(text=f"📺 {res} @ {fps}fps • {mode} • ~{rate}")
    def save_screen_choice(self):
        res=self.screen_res_var.get()
        try: fps=int(self.screen_fps_var.get())
        except Exception: fps=30
        if res not in SCREEN_RESOLUTIONS: res='1280x720'
        if fps not in SCREEN_FPS_CHOICES: fps=30
        self.profile['screen_res']=res; self.profile['screen_fps']=fps
        save_json(PROFILE_FILE, self.profile)
        self.screen.set_quality(res,fps)
        if self.webrtc and self.webrtc.sending:
            r='720p' if '720' in res else ('1080p' if '1080' in res else '480p')
            try: self.webrtc.set_quality(r, fps)
            except Exception: pass
        self._update_screen_hint(); self._refresh_screen_btn_label()
    def _refresh_screen_btn_label(self):
        if not getattr(self,'screen_btn',None) or not self.screen_btn.winfo_exists(): return
        if self.webrtc: on=self.webrtc.sending; mode="WebRTC"
        else: on=self.screen.running; mode="MQTT"
        res=self.profile.get('screen_res','1280x720')
        fps=self.profile.get('screen_fps',30)
        if on: self.screen_btn.config(text=f"🖥 ON {res}@{fps} ({mode}) (I)", bg="#43a047")
        else: self.screen_btn.config(text="🖥 Screen: OFF (I)", bg="#546e7a")
    def probe_cameras(self):
        if not CAM_OK: return
        messagebox.showinfo(t('find'), "0-5...")
        def run():
            found=CameraEngine.probe_cameras(max_check=6)
            self.root.after(0, lambda: self._show_cameras_found(found))
        threading.Thread(target=run, daemon=True).start()
    def _show_cameras_found(self, found):
        if not found:
            messagebox.showwarning(t('error'), t('no_cameras')); return
        labels=[f"Camera {i}" for i in found]
        try: self.cam_combo.config(values=labels)
        except Exception: pass
        if labels: self.cam_var.set(labels[0]); self.save_cam_choice()
        messagebox.showinfo(t('ok'), t('cameras_found', n=len(found)) + "\n" + ", ".join(labels))
    def save_cam_choice(self):
        try: idx=int(self.cam_var.get().split()[-1])
        except Exception: return
        self.profile['cam_device']=idx; save_json(PROFILE_FILE, self.profile)
        self.camera.set_device(idx)
    def choose_avatar(self):
        if not PIL_OK: return
        path=filedialog.askopenfilename(title=t('upload'),
            filetypes=[("Images","*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                       ("All","*.*")])
        if not path: return
        try: img=circular_avatar(path, size=72)
        except Exception as e: messagebox.showerror(t('error'), str(e)); return
        self.my_avatar_img=img
        self.profile['avatar_path']=path; save_json(PROFILE_FILE, self.profile)
        self._publish_my_avatar(); self._refresh_avatar_widget(self.username)
        self.show_settings()
    def clear_avatar(self):
        self.my_avatar_img=None
        self.profile['avatar_path']=''; save_json(PROFILE_FILE, self.profile)
        self._publish_my_avatar(); self._refresh_avatar_widget(self.username)
        self.show_settings()
    def save_mic_choice(self):
        if not VOICE_OK: return
        try:
            idx=int(self.mic_var.get().split(':',1)[0])
            self.profile['mic_device']=idx; save_json(PROFILE_FILE, self.profile)
            self.voice.set_device(idx)
        except Exception: pass
    def manual_connect(self):
        name=simpledialog.askstring(t('manual_connect'), t('servers') + ":", parent=self.root)
        if not name: return
        name=sanitize(name)
        if not name: return
        self.is_host=False; self.enter_server(name)

    # ---------- СОЗДАНИЕ СЕРВЕРА ----------
    def create_server(self):
        name=simpledialog.askstring(t('create_server'), t('servers') + ":", parent=self.root)
        if not name: return
        name=sanitize(name)
        if not name: return
        self.is_host=True; self.enter_server(name)

    # ---------- ВХОД НА СЕРВЕР ----------
    def enter_server(self, name):
        if not self.mqtt_connected:
            self.reconnect_broker()
            dlg=tk.Toplevel(self.root); dlg.title(t('connecting'))
            dlg.geometry("360x120"); dlg.transient(self.root)
            tk.Label(dlg, text=t('connecting') + "\n" + t('connecting_wait'),
                     font=("Arial",10)).pack(expand=True)
            threading.Thread(target=self._wait_broker_then_enter,
                             args=(name,dlg), daemon=True).start()
            return
        self._enter_server_ready(name)
    def _wait_broker_then_enter(self, name, dlg):
        for _ in range(200):
            if self.mqtt_connected: break
            time.sleep(0.1)
        try: self.root.after(0, dlg.destroy)
        except Exception: pass
        if not self.mqtt_connected:
            self.root.after(0, lambda: messagebox.showerror(t('error'), t('no_network_msg')))
            return
        self.root.after(0, lambda: self._enter_server_ready(name))
    def _enter_server_ready(self, name):
        self.leave_current()
        self.current_server=name
        base=f"{TOPIC_ROOT}/servers/{name}"
        self.chat_topic=f"{base}/chat"
        self.users_topic=f"{base}/users"
        self.voice_topic_prefix=f"{base}/voice"
        self.avatar_topic_prefix=f"{base}/avatar"
        self.video_topic_prefix=f"{base}/video"
        self.screen_topic_prefix=f"{base}/screen"
        self.my_heartbeat_topic=f"{self.users_topic}/{self.username}"
        self.my_voice_topic=f"{self.voice_topic_prefix}/{self.username}"
        self.my_avatar_topic=f"{self.avatar_topic_prefix}/{self.username}"
        self.my_video_topic=f"{self.video_topic_prefix}/{self.username}"
        self.my_screen_topic=f"{self.screen_topic_prefix}/{self.username}"
        self.hosting_topic=f"{DISCOVERY_TOPIC}/{name}" if self.is_host else None
        self.webrtc_signal_prefix=f"{base}/signal"
        self.my_webrtc_signal_topic=f"{self.webrtc_signal_prefix}/{self.username}"
        self.online={}; self.user_avatars={}; self.user_speaking={}
        self.last_frames={}; self.last_frame_ts={}; self.video_widgets={}
        self._webrtc_known_peers=set()
        self.mqtt.subscribe(self.chat_topic, qos=1)
        self.mqtt.subscribe(self.users_topic+"/+", qos=1)
        self.mqtt.subscribe(self.voice_topic_prefix+"/+", qos=0)
        self.mqtt.subscribe(self.avatar_topic_prefix+"/+", qos=1)
        self.mqtt.subscribe(self.video_topic_prefix+"/+", qos=0)
        self.mqtt.subscribe(self.screen_topic_prefix+"/+", qos=0)
        if WEBRTC_LIB_OK and self.webrtc_enabled:
            self._ensure_webrtc_instance()
            if self.webrtc:
                try: self.mqtt.subscribe(f"{self.webrtc_signal_prefix}/{self.username}", qos=1)
                except Exception: pass

        if FILES_OK:
            try:
                self.file_server = files_mod.FileServer(self.username)
                self.file_server.start()
            except Exception as e:
                print("[FileServer]", e); self.file_server = None

        self.mqtt.publish(self.chat_topic, json.dumps({
            'type':'join','user':self.username,'ts':time.time()}), qos=1)
        self.mqtt.publish(self.my_heartbeat_topic, json.dumps({
            'nick':self.username,'ts':time.time(),
            'file_url': self.file_server.base_url() if self.file_server else ''
        }), qos=1, retain=True)
        self._publish_my_avatar()
        if self.is_host: self._publish_host_announce()
        if VOICE_OK: self.voice.start_output()
        self.screen.set_quality(self.profile.get('screen_res','1280x720'),
                                self.profile.get('screen_fps',30))
        self.show_chat(name)
        self._start_heartbeat()
        self._schedule_video_render()
    def _publish_host_announce(self, online=True):
        if not self.hosting_topic or not self.mqtt_connected: return
        try:
            self.mqtt.publish(self.hosting_topic, json.dumps({
                'name':self.current_server,'host':self.username,
                'online':bool(online),
                'online_users':max(1,len(self.online)) if online else 0,
                'ts':time.time()}), qos=1, retain=True)
        except Exception: pass

    # ---------- WEBRTC ----------
    def _webrtc_send_signal(self, target, msg):
        if not self.mqtt_connected or not self.webrtc_signal_prefix: return
        try: self.mqtt.publish(f"{self.webrtc_signal_prefix}/{target}",
                              json.dumps(msg), qos=1)
        except Exception: pass
    def _webrtc_on_frame(self, peer_id, img):
        self.last_frames[(peer_id,'screen')]=img
        self.last_frame_ts[(peer_id,'screen')]=time.time()
    def _webrtc_on_peer_state(self, peer_id, st):
        if st in ("failed","closed","disconnected"):
            self.last_frames.pop((peer_id,'screen'),None)
            self.last_frame_ts.pop((peer_id,'screen'),None)
            try: self.root.after(0, self._rebuild_video_row)
            except Exception: pass
    def _webrtc_broadcast_offer(self):
        if not self.webrtc: return
        for p in [u for u in self.online.keys() if u != self.username]:
            self.webrtc.offer_to(p)
    def _webrtc_notify_new_peer(self, p):
        if self.webrtc and self.webrtc.sending: self.webrtc.offer_to(p)
    def _ensure_webrtc_instance(self):
        if not (WEBRTC_LIB_OK and self.webrtc_enabled): return False
        if self.webrtc: return True
        try:
            self.webrtc=WebRTCScreen(my_id=self.username,
                send_signal=self._webrtc_send_signal,
                on_remote_frame=self._webrtc_on_frame,
                on_peer_state=self._webrtc_on_peer_state)
            return True
        except Exception as e:
            print("[WebRTC init]", e); self.webrtc=None; return False
    def _destroy_webrtc_instance(self):
        try:
            if self.webrtc: self.webrtc.shutdown()
        except Exception: pass
        self.webrtc=None; self._webrtc_known_peers=set()

    # ---------- HEARTBEAT ----------
    def _start_heartbeat(self):
        self.hb_stop.clear()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
    def _stop_heartbeat(self): self.hb_stop.set()
    def _heartbeat_loop(self):
        while not self.hb_stop.is_set():
            try:
                if self.mqtt_connected and self.my_heartbeat_topic:
                    self.mqtt.publish(self.my_heartbeat_topic, json.dumps({
                        'nick':self.username,'ts':time.time(),
                        'file_url': self.file_server.base_url() if self.file_server else ''
                    }), qos=0, retain=True)
                    if self.is_host and self.hosting_topic:
                        self._publish_host_announce(online=True)
                now=time.time(); changed=False
                for k in list(self.online.keys()):
                    if now-self.online[k]>30:
                        self.online.pop(k,None); changed=True
                if changed: self.root.after(0, self.refresh_online)
            except Exception: pass
            for _ in range(60):
                if self.hb_stop.is_set(): return
                time.sleep(0.1)
    def refresh_online(self):
        if self.webrtc and self.webrtc.sending:
            cur=set(self.online.keys()) | {self.username}
            known=set(getattr(self,'_webrtc_known_peers',set()))
            for np in cur - known - {self.username}:
                self._webrtc_notify_new_peer(np)
            self._webrtc_known_peers=cur
        if getattr(self,'online_label',None) and self.online_label.winfo_exists():
            users=sorted(self.online.keys())
            self.online_label.config(
                text=f"🌐 {t('online')} ({len(users)}): " + (", ".join(users) if users else "—"))
        self._rebuild_avatar_row(); self._rebuild_video_row()

    # ---------- АВАТАРЫ В ЧАТЕ ----------
    def _rebuild_avatar_row(self):
        if not getattr(self,'avatar_row',None) or not self.avatar_row.winfo_exists(): return
        wanted=set(self.online.keys()) | {self.username}
        for u in list(self.avatar_widgets.keys()):
            if u not in wanted:
                try: self.avatar_widgets[u]['container'].destroy()
                except Exception: pass
                self.avatar_widgets.pop(u,None)
        for u in wanted:
            if u not in self.avatar_widgets: self._create_avatar_widget(u)
        for u in wanted: self._refresh_avatar_widget(u)
    def _create_avatar_widget(self, username):
        c=tk.Frame(self.avatar_row, bg="#263238"); c.pack(side='left', padx=8, pady=4)
        cvs=tk.Canvas(c, width=72, height=72, bg="#263238", highlightthickness=0); cvs.pack()
        cvs.create_oval(2,2,70,70, fill="#546e7a", outline="")
        ring=cvs.create_oval(1,1,71,71, outline=self._status_color(username), width=3)
        st_emoji = self._status_emoji(username)
        emoji_id = cvs.create_text(64, 10, text=st_emoji, font=("Arial",10), anchor='ne')
        tk.Label(c, text=username, bg="#263238", fg="#eceff1", font=("Arial",9)).pack()
        cvs.bind('<Button-3>', lambda e, u=username: self._avatar_right_click(e, u))
        try:
            cvs.bind('<Control-Button-1>', lambda e, u=username: self._avatar_right_click(e, u))
        except Exception: pass
        try:
            cvs.bind('<Enter>', lambda e: cvs.config(cursor="hand2"))
        except Exception: pass
        self.avatar_widgets[username]={'container':c,'canvas':cvs,'ring_id':ring,
                                        'img_id':None,'photo_ref':None,
                                        'emoji_id':emoji_id}
        self._refresh_avatar_widget(username)
    def _refresh_avatar_widget(self, username):
        w=self.avatar_widgets.get(username)
        if not w: return
        try:
            cvs=w['canvas']
            if not cvs.winfo_exists(): return
            if w['img_id'] is not None:
                try: cvs.delete(w['img_id'])
                except Exception: pass
            img=self._get_avatar_image(username)
            if img is not None:
                ph=ImageTk.PhotoImage(img); w['photo_ref']=ph
                w['img_id']=cvs.create_image(36,36,image=ph)
                cvs.tag_raise(w['ring_id'])
                if w.get('emoji_id') is not None:
                    cvs.tag_raise(w['emoji_id'])
            if not self.user_speaking.get(username, False):
                cvs.itemconfig(w['ring_id'], outline=self._status_color(username))
            try:
                cvs.itemconfig(w['emoji_id'], text=self._status_emoji(username))
            except Exception: pass
        except Exception: pass

    # ---------- ВИДЕО ----------
    def _schedule_video_render(self):
        def tick():
            try: self._rebuild_video_row()
            except Exception: pass
            try: self._video_render_job=self.root.after(150, tick)
            except Exception: pass
        self._video_render_job=self.root.after(150, tick)
    def _rebuild_video_row(self):
        if not getattr(self,'video_row',None) or not self.video_row.winfo_exists(): return
        now=time.time(); active=set()
        for k,ts in self.last_frame_ts.items():
            if now-ts > SCREEN_TIMEOUT: continue
            if k[0] not in (set(self.online) | {self.username}): continue
            active.add(k)
        for k in list(self.video_widgets.keys()):
            if k not in active:
                try: self.video_widgets[k]['container'].destroy()
                except Exception: pass
                self.video_widgets.pop(k,None)
                self.last_frames.pop(k,None); self.last_frame_ts.pop(k,None)
        for k in active:
            if k not in self.video_widgets: self._create_video_widget(k)
        for k in active: self._update_video_widget(k)
        try:
            if active:
                if self.video_row.winfo_manager()=='':
                    self.video_row.pack(fill='x', after=self.avatar_row)
            else:
                if self.video_row.winfo_manager(): self.video_row.pack_forget()
        except Exception: pass
    def _create_video_widget(self, key):
        user, src=key
        icon="🎥" if src=='cam' else "🖥"
        c=tk.Frame(self.video_row, bg="#1b1b1b", bd=1, relief='solid')
        c.pack(side='left', padx=8, pady=6)
        img=self.last_frames.get(key)
        w_,h_=img.size if img is not None else ((CAM_W,CAM_H) if src=='cam' else (854,480))
        lbl=tk.Label(c, bg="#000", width=w_, height=h_); lbl.pack()
        st_emoji = self._status_emoji(user)
        tk.Label(c, text=f"{st_emoji} {user}  {icon}", bg="#1b1b1b", fg="#eceff1",
                 font=("Arial",9)).pack(fill='x')
        self.video_widgets[key]={'container':c,'label':lbl,'photo_ref':None}
    def _update_video_widget(self, key):
        w=self.video_widgets.get(key)
        if not w or not PIL_OK: return
        img=self.last_frames.get(key)
        if img is None: return
        try:
            if not w['label'].winfo_exists(): return
            ph=ImageTk.PhotoImage(img); w['photo_ref']=ph
            w['label'].config(image=ph, width=0, height=0)
        except Exception: pass

    # ---------- ЧАТ ----------
    def show_chat(self, name):
        for w in self.root.winfo_children(): w.destroy()
        self.avatar_widgets={}; self.video_widgets={}
        top=tk.Frame(self.root, bg="#263238"); top.pack(fill='x')
        tk.Label(top, text=f"  {name}  ", bg="#263238", fg="white",
                 font=("Arial",13,"bold")).pack(side='left')
        role="host" if self.is_host else "player"
        tk.Label(top, text=f"  ({role})  ",
                 bg="#263238", fg="#90a4ae", font=("Arial",9)).pack(side='left')

        st_emoji, st_label, st_color = self._status_info(self.username)
        my_st_lbl = tk.Label(top, text=f"  {st_emoji} {st_label}  ",
                             bg="#263238", fg=st_color,
                             font=("Arial",10,"bold"), cursor="hand2")
        my_st_lbl.pack(side='left', padx=4)
        my_st_lbl.bind("<Button-1>", lambda e: self.show_status_menu())

        tk.Button(top, text=t('exit'), command=self.leave_chat,
                  bg="#e53935", fg="white", bd=0,
                  font=("Arial",10,"bold")).pack(side='right', padx=(4,8), pady=6)
        self.screen_btn=tk.Button(top, text="🖥 Screen: OFF (I)", bg="#546e7a",
                                  fg="white", font=("Arial",10,"bold"), bd=0,
                                  command=self.toggle_screen)
        self.screen_btn.pack(side='right', padx=4, pady=6)
        self.cam_btn=tk.Button(top, text="🎥 Cam: OFF (O)", bg="#546e7a",
                                fg="white", font=("Arial",10,"bold"), bd=0,
                                command=self.toggle_camera)
        self.cam_btn.pack(side='right', padx=4, pady=6)
        self.mic_btn=tk.Button(top, text="🎤 Mic: OFF (P)", bg="#546e7a",
                                fg="white", font=("Arial",10,"bold"), bd=0,
                                command=self.toggle_mic)
        self.mic_btn.pack(side='right', padx=4, pady=6)
        tk.Button(top, text="📎 Share", bg="#8e24aa", fg="white",
                  font=("Arial",10,"bold"), bd=0,
                  command=self.share_file).pack(side='right', padx=4, pady=6)
        tk.Button(top, text="👥 Друзья", bg="#e91e63", fg="white",
                  font=("Arial",10,"bold"), bd=0,
                  command=self.show_friends).pack(side='right', padx=4, pady=6)
        tk.Button(top, text="🎭", bg="#ff9800", fg="white",
                  font=("Arial",10,"bold"), bd=0, width=3,
                  command=self.show_status_menu).pack(side='right', padx=4, pady=6)
        self.avatar_row=tk.Frame(self.root, bg="#263238"); self.avatar_row.pack(fill='x')
        self.video_row=tk.Frame(self.root, bg="#111")
        self.online_label=tk.Label(self.root, text="🌐 " + t('online') + ": —", anchor='w',
                                    bg="#37474f", fg="#b0bec5", font=("Arial",10),
                                    padx=8, pady=4)
        self.online_label.pack(fill='x')
        self.chat=tk.Text(self.root, bg="#1b1b1b", fg="#e0e0e0",
                          font=("Consolas",11), wrap='word', state='disabled')
        self.chat.pack(fill='both', expand=True)
        bottom=tk.Frame(self.root); bottom.pack(fill='x')
        self.msg_entry=tk.Entry(bottom, font=("Arial",12))
        self.msg_entry.pack(side='left', fill='x', expand=True, padx=6, pady=6)
        self.msg_entry.bind('<Return>', lambda e: self.send_msg())
        self.msg_entry.bind('<Escape>', lambda e: self.root.focus_set())
        tk.Button(bottom, text=t('send'), bg="#1e88e5", fg="white",
                  font=("Arial",11,"bold"),
                  command=self.send_msg).pack(side='right', padx=6, pady=6)
        self.msg_entry.focus_set()
        self.append_chat(f"[SYS] {t('joined_server', name=name)}")
        if FILES_OK and self.file_server:
            self.append_chat(f"[FILES] Твой файловый сервер: {self.file_server.base_url()}")
        self.refresh_online()
        self._refresh_screen_btn_label()
        self.root.bind_all('<KeyPress>', self._on_global_key)

    def _on_global_key(self, event):
        key=event.keysym.lower()
        if key == 'f11': self.toggle_fullscreen(); return
        try:
            if isinstance(event.widget, (tk.Entry, tk.Text)): return
        except Exception: pass
        if key == 'p': self.toggle_mic()
        elif key == 'o': self.toggle_camera()
        elif key == 'i': self.toggle_screen()
    def toggle_mic(self):
        if not VOICE_OK: return
        if not self.current_server: return
        enabled=self.voice.toggle()
        if getattr(self,'mic_btn',None) and self.mic_btn.winfo_exists():
            if enabled: self.mic_btn.config(text="🎤 Mic: ON (P)", bg="#43a047")
            else: self.mic_btn.config(text="🎤 Mic: OFF (P)", bg="#546e7a")
    def toggle_camera(self):
        if not CAM_OK: return
        if not self.current_server: return
        running=self.camera.toggle()
        if getattr(self,'cam_btn',None) and self.cam_btn.winfo_exists():
            if running: self.cam_btn.config(text="🎥 Cam: ON (O)", bg="#43a047")
            else: self.cam_btn.config(text="🎥 Cam: OFF (O)", bg="#546e7a")
        if not running:
            key=(self.username,'cam')
            self.last_frames.pop(key,None); self.last_frame_ts.pop(key,None)
            if self.mqtt_connected and self.my_video_topic:
                try: self.mqtt.publish(self.my_video_topic, b'', qos=0, retain=True)
                except Exception: pass
            self._rebuild_video_row()
    def toggle_screen(self):
        if not self.current_server: return
        if self.webrtc_enabled and WEBRTC_LIB_OK:
            if self._ensure_webrtc_instance():
                if self.mqtt_connected and self.webrtc_signal_prefix:
                    try: self.mqtt.subscribe(f"{self.webrtc_signal_prefix}/{self.username}", qos=1)
                    except Exception: pass
        if self.webrtc:
            if self.webrtc.sending:
                self.webrtc.stop_screen()
                key=(self.username,'screen')
                self.last_frames.pop(key,None); self.last_frame_ts.pop(key,None)
                self._rebuild_video_row()
            else:
                res=self.profile.get('screen_res','1280x720')
                if res not in WEBRTC_RESOLUTIONS: res='720p'
                fps=int(self.profile.get('screen_fps',30))
                if self.webrtc.start_screen(res, fps):
                    self._webrtc_broadcast_offer()
            self._refresh_screen_btn_label(); return
        if not PIL_OK or ImageGrab is None: return
        self.screen.set_quality(self.profile.get('screen_res','1280x720'),
                                self.profile.get('screen_fps',30))
        running=self.screen.toggle()
        self._refresh_screen_btn_label()
        if not running:
            key=(self.username,'screen')
            self.last_frames.pop(key,None); self.last_frame_ts.pop(key,None)
            if self.mqtt_connected and self.my_screen_topic:
                try: self.mqtt.publish(self.my_screen_topic, b'', qos=0, retain=True)
                except Exception: pass
            self._rebuild_video_row()
    def append_chat(self, text):
        if not getattr(self,'chat',None) or not self.chat.winfo_exists(): return
        self.chat.config(state='normal'); self.chat.insert('end', text + "\n")
        self.chat.see('end'); self.chat.config(state='disabled')
    def send_msg(self):
        if not self.mqtt_connected or not self.chat_topic: return
        txt=self.msg_entry.get().strip()
        if not txt: return
        self.msg_entry.delete(0, 'end')
        try:
            self.mqtt.publish(self.chat_topic, json.dumps({
                'type':'chat','user':self.username,'text':txt,'ts':time.time()}), qos=1)
        except Exception as e: self.append_chat(f"[ERR] {e}")
    def leave_current(self):
        try: self.camera.stop()
        except Exception: pass
        try: self.screen.stop()
        except Exception: pass
        self._destroy_webrtc_instance()
        self.webrtc_signal_prefix=None; self.my_webrtc_signal_topic=None
        try:
            if self.file_server: self.file_server.stop()
        except Exception: pass
        self.file_server = None
        self.remote_files = {}
        try:
            if self.mqtt_connected and self.mqtt:
                for tp in (self.my_video_topic, self.my_screen_topic):
                    if tp:
                        try: self.mqtt.publish(tp, b'', qos=0, retain=True)
                        except Exception: pass
                if self.chat_topic:
                    self.mqtt.publish(self.chat_topic, json.dumps({
                        'type':'leave','user':self.username,'ts':time.time()}), qos=1)
                if self.my_heartbeat_topic:
                    self.mqtt.publish(self.my_heartbeat_topic, b'', qos=1, retain=True)
                if self.my_avatar_topic:
                    self.mqtt.publish(self.my_avatar_topic, b'', qos=1, retain=True)
                if self.hosting_topic and self.current_server:
                    try:
                        self.mqtt.publish(self.hosting_topic, json.dumps({
                            'name':self.current_server,'host':self.username,
                            'online':False,'online_users':0,'ts':time.time()}),
                            qos=1, retain=True)
                    except Exception: pass
                if self.chat_topic:
                    for tt in (self.chat_topic, self.users_topic+"/+",
                              self.voice_topic_prefix+"/+",
                              self.avatar_topic_prefix+"/+",
                              self.video_topic_prefix+"/+",
                              self.screen_topic_prefix+"/+"):
                        try: self.mqtt.unsubscribe(tt)
                        except Exception: pass
        except Exception: pass
        self._stop_heartbeat()
        try: self.voice.stop_capture()
        except Exception: pass
        try: self.root.unbind_all('<KeyPress>')
        except Exception: pass
        if self._video_render_job:
            try: self.root.after_cancel(self._video_render_job)
            except Exception: pass
            self._video_render_job=None
        self.current_server=None
        self.chat_topic=None; self.users_topic=None
        self.voice_topic_prefix=None; self.avatar_topic_prefix=None
        self.video_topic_prefix=None; self.screen_topic_prefix=None
        self.my_voice_topic=None; self.my_avatar_topic=None
        self.my_video_topic=None; self.my_screen_topic=None
        self.my_heartbeat_topic=None; self.hosting_topic=None
        self.is_host=False; self.online={}
        self.user_avatars={}; self.user_speaking={}; self.avatar_widgets={}
        self.last_frames={}; self.last_frame_ts={}; self.video_widgets={}
    def leave_chat(self):
        self.leave_current(); self.show_menu()
    def on_close(self):
        self.leave_current()
        try:
            if self.mqtt: self.mqtt.loop_stop(); self.mqtt.disconnect()
        except Exception: pass
        try: self.voice.stop_output()
        except Exception: pass
        try: self.camera.stop()
        except Exception: pass
        try: self.screen.stop()
        except Exception: pass
        self.root.destroy()
    def run(self): self.root.mainloop()


if __name__ == '__main__':
    PyBlox().run()