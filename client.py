import os, sys, json, hashlib, threading, time, ssl, socket, io, queue
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog, ttk

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

# ============ WebRTC (опционально) ============
try:
    from webrtc_screen import WebRTCScreen, RESOLUTIONS as WEBRTC_RESOLUTIONS
    WEBRTC_LIB_OK = True
except Exception as _e:
    WEBRTC_LIB_OK = False
    WEBRTC_RESOLUTIONS = {}
    print(f"[i] WebRTC-библиотека недоступна ({_e})")
    print("    Установи: pip install aiortc av — тогда в настройках появится переключатель.")

# ============ Updater ============
try:
    from updater import check_for_update, download_file
    UPDATER_OK = True
except Exception as _e:
    UPDATER_OK = False
    print(f"[i] Проверка обновлений недоступна ({_e})")

# >>> ПОМЕНЯЙ НА СВОИ ЗНАЧЕНИЯ <<<
CURRENT_VERSION = "10.3.0"
GITHUB_REPO     = "yourname/pyblox"     # например: "matvei/pyblox"


ACCOUNTS_FILE, LAST_USER_FILE, PROFILE_FILE = 'accounts.json', 'last_user.json', 'profile.json'
SESSION_FILE = 'session.json'
TOPIC_ROOT = "pyblox/v10"
DISCOVERY_TOPIC = f"{TOPIC_ROOT}/discovery"
ONLINE_TTL = 30
SERVER_HIDE_DAYS = 30
LIST_REFRESH_MS = 30000

VOICE_RATE = 8000
VOICE_CHUNK = 480
VOICE_THRESHOLD = 300
SPEAKING_TIMEOUT = 0.6

CAM_W, CAM_H = 200, 150
CAM_FPS = 5
CAM_QUALITY = 35

SCREEN_RESOLUTIONS = {
    "144p": (256, 144, 50),
    "360p": (640, 360, 40),
    "480p": (854, 480, 30),
    "720p": (1280, 720, 25),
}
SCREEN_FPS_CHOICES = [15, 30, 60]
SCREEN_TIMEOUT = 2.0

BROKER_CANDIDATES = [
    ("broker.emqx.io",          8084, "websockets", True,  "/mqtt", "EMQX (WSS 8084)"),
    ("broker.emqx.io",          8083, "websockets", False, "/mqtt", "EMQX (WS 8083)"),
    ("test.mosquitto.org",      8081, "websockets", True,  "/mqtt", "Mosquitto (WSS 8081)"),
    ("test.mosquitto.org",      8080, "websockets", False, "/mqtt", "Mosquitto (WS 8080)"),
    ("broker.hivemq.com",       8884, "websockets", True,  "/mqtt", "HiveMQ (WSS 8884)"),
    ("broker.hivemq.com",       8000, "websockets", False, "/mqtt", "HiveMQ (WS 8000)"),
    ("mqtt.eclipseprojects.io",  443, "websockets", True,  "/mqtt", "Eclipse (WSS 443)"),
    ("mqtt.eclipseprojects.io",   80, "websockets", False, "/mqtt", "Eclipse (WS 80)"),
    ("broker.emqx.io",          1883, "tcp",        False, None,    "EMQX (TCP 1883)"),
    ("test.mosquitto.org",      1883, "tcp",        False, None,    "Mosquitto (TCP 1883)"),
]


# ---------- утилиты ----------
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
    img = img.crop(((w-m)//2, (h-m)//2, (w+m)//2, (h+m)//2)).resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out

def default_avatar(username, size=72):
    colors = ["#e57373","#64b5f6","#81c784","#ffb74d","#ba68c8","#4db6ac","#f06292","#7986cb"]
    c = colors[hash(username) % len(colors)]
    img = Image.new("RGBA", (size, size), (0,0,0,0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, size, size), fill=c)
    letter = username[0].upper() if username else "?"
    try: d.text((size//2, size//2), letter, fill="white", anchor="mm")
    except Exception: pass
    return img

def fmt_age(seconds):
    seconds = int(max(0, seconds))
    if seconds < 60: return f"{seconds} с назад"
    if seconds < 3600: return f"{seconds//60} мин назад"
    if seconds < 86400: return f"{seconds//3600} ч назад"
    return f"{seconds//86400} дн назад"


# ============ АУДИО ============
class VoiceEngine:
    def __init__(self, on_send, on_speaking_change):
        self.on_send = on_send; self.on_speaking = on_speaking_change
        self.in_stream = None; self.out_stream = None
        self.enabled = False; self.device_index = None
        self.play_q = queue.Queue(maxsize=30)
        self._last_speak = 0; self._speak_state = False

    def list_input_devices(self):
        if not VOICE_OK: return []
        try:
            return [(i, d['name']) for i, d in enumerate(sd.query_devices())
                    if d['max_input_channels'] > 0]
        except Exception: return []

    def start_output(self):
        if not VOICE_OK or self.out_stream: return
        try:
            self.out_stream = sd.OutputStream(
                samplerate=VOICE_RATE, channels=1, dtype='int16',
                blocksize=VOICE_CHUNK, callback=self._out_cb)
            self.out_stream.start()
        except Exception as e: print("[Voice] output:", e)

    def stop_output(self):
        try:
            if self.out_stream: self.out_stream.stop(); self.out_stream.close()
        except Exception: pass
        self.out_stream = None

    def _out_cb(self, outdata, frames, time_, status):
        try: data = self.play_q.get_nowait()
        except queue.Empty: outdata.fill(0); return
        if len(data) < frames:
            data = np.concatenate([data, np.zeros(frames-len(data), dtype=np.int16)])
        outdata[:] = data[:frames].reshape(-1, 1)

    def feed(self, arr):
        try: self.play_q.put_nowait(arr)
        except queue.Full:
            try: self.play_q.get_nowait()
            except Exception: pass
            try: self.play_q.put_nowait(arr)
            except Exception: pass

    def set_device(self, idx):
        self.device_index = idx
        if self.enabled: self.stop_capture(); self.start_capture()

    def toggle(self):
        if self.enabled: self.stop_capture()
        else: self.start_capture()
        return self.enabled

    def start_capture(self):
        if not VOICE_OK: return False
        try:
            self.start_output()
            self.in_stream = sd.InputStream(
                samplerate=VOICE_RATE, channels=1, dtype='int16',
                blocksize=VOICE_CHUNK, device=self.device_index, callback=self._in_cb)
            self.in_stream.start(); self.enabled = True; return True
        except Exception as e:
            print("[Voice] input:", e)
            messagebox.showerror("Микрофон", f"Не удалось открыть микрофон:\n{e}")
            self.enabled = False; return False

    def stop_capture(self):
        try:
            if self.in_stream: self.in_stream.stop(); self.in_stream.close()
        except Exception: pass
        self.in_stream = None; self.enabled = False; self._speak_state = False
        try: self.on_speaking(False)
        except Exception: pass

    def _in_cb(self, indata, frames, time_, status):
        if status: return
        try:
            raw = indata.copy().flatten()
            rms = float(np.sqrt(np.mean(raw.astype(np.float32) ** 2)))
            speaking = rms > VOICE_THRESHOLD
            now = time.time()
            if speaking: self._last_speak = now
            if speaking != self._speak_state:
                self._speak_state = speaking
                try: self.on_speaking(speaking)
                except Exception: pass
            try: self.on_send(raw.tobytes())
            except Exception: pass
        except Exception: pass

    def tick_speaking_timeout(self):
        if self._speak_state and (time.time() - self._last_speak) > SPEAKING_TIMEOUT:
            self._speak_state = False
            try: self.on_speaking(False)
            except Exception: pass


# ============ КАМЕРА ============
class CameraEngine:
    def __init__(self, on_frame):
        self.on_frame = on_frame; self.cap = None; self.thread = None
        self.running = False; self.device_index = 0; self.fps = CAM_FPS

    @staticmethod
    def probe_cameras(max_check=5):
        found = []
        if not CAM_OK: return found
        backend = cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY
        for i in range(max_check):
            try:
                cap = cv2.VideoCapture(i, backend)
                if cap.isOpened():
                    ok, _ = cap.read()
                    if ok: found.append(i)
                cap.release()
            except Exception: pass
        return found

    def set_device(self, idx):
        self.device_index = int(idx)
        if self.running:
            self.stop(); time.sleep(0.2); self.start()

    def toggle(self):
        if self.running: self.stop(); return False
        return self.start()

    def start(self):
        if not CAM_OK:
            messagebox.showwarning("Камера", "pip install opencv-python"); return False
        if self.running: return True
        try:
            backend = cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY
            self.cap = cv2.VideoCapture(self.device_index, backend)
            if not self.cap.isOpened():
                raise RuntimeError(f"Камера {self.device_index} не открылась")
            try:
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            except Exception: pass
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True); self.thread.start()
            return True
        except Exception as e:
            messagebox.showerror("Камера", str(e))
            try:
                if self.cap: self.cap.release()
            except Exception: pass
            self.cap = None; self.running = False; return False

    def stop(self):
        self.running = False
        try:
            if self.cap: self.cap.release()
        except Exception: pass
        self.cap = None

    def _loop(self):
        period = 1.0 / self.fps
        while self.running:
            t0 = time.time()
            try:
                ok, frame = self.cap.read()
                if not ok: time.sleep(0.1); continue
                frame = cv2.resize(frame, (CAM_W, CAM_H), interpolation=cv2.INTER_AREA)
                ok, buf = cv2.imencode('.jpg', frame,
                                       [int(cv2.IMWRITE_JPEG_QUALITY), CAM_QUALITY])
                if ok:
                    try: self.on_frame(buf.tobytes())
                    except Exception: pass
            except Exception: pass
            dt = time.time() - t0
            if dt < period: time.sleep(period - dt)


# ============ MQTT-ЭКРАН ============
class ScreenEngine:
    def __init__(self, on_frame, resolution="480p", fps=30):
        self.on_frame = on_frame
        self.running = False
        self.thread = None
        self.resolution = resolution
        self.fps = fps
        self._lock = threading.Lock()

    def get_res_wh(self):
        with self._lock:
            return SCREEN_RESOLUTIONS.get(self.resolution, SCREEN_RESOLUTIONS["480p"])

    def set_quality(self, resolution=None, fps=None):
        with self._lock:
            if resolution and resolution in SCREEN_RESOLUTIONS:
                self.resolution = resolution
            if fps and int(fps) in SCREEN_FPS_CHOICES:
                self.fps = int(fps)
            return self.resolution, self.fps

    def toggle(self):
        if self.running: self.stop(); return False
        return self.start()

    def start(self):
        if not PIL_OK or ImageGrab is None:
            messagebox.showwarning("Экран", "pip install pillow"); return False
        if self.running: return True
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True); self.thread.start()
        return True

    def stop(self):
        self.running = False

    def _loop(self):
        while self.running:
            t0 = time.time()
            try:
                w, h, q = self.get_res_wh()
                img = ImageGrab.grab()
                img = img.resize((w, h), Image.LANCZOS)
                if img.mode != 'RGB': img = img.convert('RGB')
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=q)
                try: self.on_frame(buf.getvalue())
                except Exception: pass
            except Exception as e:
                print("[Screen]", e)
                time.sleep(0.5)
            with self._lock:
                fps = self.fps
            period = 1.0 / max(1, fps)
            dt = time.time() - t0
            if dt < period: time.sleep(period - dt)


# ============ ПРИЛОЖЕНИЕ ============
class PyBlox:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"PyBlox v{CURRENT_VERSION}")
        self.root.geometry("900x760")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.is_fullscreen = False
        self.root.bind('<F11>', self._on_f11_key)

        self.accounts = load_json(ACCOUNTS_FILE, {})
        self.last_user = load_json(LAST_USER_FILE, {}).get('user', '')
        self.session = load_json(SESSION_FILE, {})

        self.profile = load_json(PROFILE_FILE, {
            'avatar_path': '', 'mic_device': None, 'cam_device': 0,
            'screen_res': '480p', 'screen_fps': 30, 'use_webrtc': False,
        })
        if self.profile.get('screen_res') not in SCREEN_RESOLUTIONS:
            self.profile['screen_res'] = '480p'
        if self.profile.get('screen_fps') not in SCREEN_FPS_CHOICES:
            self.profile['screen_fps'] = 30
        if 'use_webrtc' not in self.profile:
            self.profile['use_webrtc'] = False

        self.username = None
        self.mqtt = None; self.mqtt_connected = False; self.broker_label = ""
        self.connect_log = []; self._finding = False

        self.current_server = None
        self.chat_topic = None; self.users_topic = None
        self.voice_topic_prefix = None; self.avatar_topic_prefix = None
        self.video_topic_prefix = None; self.screen_topic_prefix = None
        self.my_voice_topic = None; self.my_avatar_topic = None
        self.my_video_topic = None; self.my_screen_topic = None
        self.my_heartbeat_topic = None; self.hosting_topic = None

        self.webrtc_signal_prefix = None
        self.my_webrtc_signal_topic = None
        self.webrtc = None
        self.webrtc_enabled = WEBRTC_LIB_OK and bool(self.profile.get('use_webrtc', False))
        self._webrtc_known_peers = set()

        self.is_host = False
        self.online = {}
        self.user_avatars = {}; self.user_speaking = {}; self.avatar_widgets = {}

        self.last_frames = {}; self.last_frame_ts = {}
        self.video_widgets = {}
        self._video_render_job = None

        self.discovered = {}; self.list_refresh_job = None
        self.list_debounce_job = None; self._broker_status_job = None
        self.hb_stop = threading.Event(); self.speak_tick_job = None

        # updater
        self._update_info = None
        self._update_checked = False

        self.voice = VoiceEngine(on_send=self._voice_send, on_speaking_change=self._my_speaking_changed)
        if VOICE_OK and self.profile.get('mic_device') is not None:
            self.voice.device_index = self.profile.get('mic_device')

        self.camera = CameraEngine(on_frame=self._camera_frame)
        try: self.camera.device_index = int(self.profile.get('cam_device', 0))
        except Exception: self.camera.device_index = 0

        self.screen = ScreenEngine(
            on_frame=self._screen_frame,
            resolution=self.profile.get('screen_res', '480p'),
            fps=self.profile.get('screen_fps', 30),
        )

        self.my_avatar_img = None
        self._load_my_avatar()

        # ==== АВТОВХОД ====
        auto_user = self.session.get('user') if isinstance(self.session, dict) else None
        if auto_user and auto_user in self.accounts:
            self.username = auto_user
            save_json(LAST_USER_FILE, {'user': auto_user})
            self.show_menu()
        else:
            self.show_auth()

        self._start_broker_search()
        self._schedule_speaking_tick()

        # авто-проверка обновлений через 3 сек
        if UPDATER_OK:
            self.root.after(3000, self._check_updates_async)

    # ============ UPDATER ============
    def _check_updates_async(self):
        threading.Thread(target=self._check_updates_worker, daemon=True).start()

    def _check_updates_worker(self):
        try:
            info = check_for_update(GITHUB_REPO, CURRENT_VERSION, timeout=6)
        except Exception as e:
            print(f"[Updater] {e}")
            info = None
        self.root.after(0, lambda: self._on_update_checked(info))

    def _on_update_checked(self, info):
        self._update_checked = True
        if not info:
            print(f"[Updater] Версия {CURRENT_VERSION} — последняя")
            return
        self._update_info = info
        print(f"[Updater] Доступна новая версия: {info['version']}")
        try:
            if hasattr(self, 'update_banner') and self.update_banner.winfo_exists():
                self._refresh_update_banner()
        except Exception:
            pass
        self._show_update_dialog(info)

    def _show_update_dialog(self, info):
        if not info:
            return
        try:
            ans = messagebox.askyesno(
                "Доступно обновление PyBlox",
                f"Установлена версия: {CURRENT_VERSION}\n"
                f"Доступна новая: {info['version']}\n\n"
                f"Открыть страницу загрузки в браузере?")
            if ans:
                self._open_release_page(info)
        except Exception:
            pass

    def _open_release_page(self, info=None):
        info = info or self._update_info
        if not info:
            return
        import webbrowser
        url = info.get('html_url') or info.get('asset_url') or ""
        if url:
            try:
                webbrowser.open(url)
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось открыть браузер:\n{e}")
                messagebox.showinfo("Ссылка на релиз", url)

    def manual_check_updates(self):
        if not UPDATER_OK:
            messagebox.showwarning(
                "Проверка недоступна",
                "Файл updater.py не найден рядом с client.py.\n"
                "Положи его в ту же папку и перезапусти.")
            return
        if self._update_info:
            self._show_update_dialog(self._update_info)
            return
        messagebox.showinfo("Проверка обновлений",
                            f"Текущая версия: {CURRENT_VERSION}\n"
                            f"Проверяю GitHub...")
        threading.Thread(target=self._manual_check_worker, daemon=True).start()

    def _manual_check_worker(self):
        try:
            info = check_for_update(GITHUB_REPO, CURRENT_VERSION, timeout=8)
        except Exception:
            info = None
        self.root.after(0, lambda: self._on_manual_check(info))

    def _on_manual_check(self, info):
        if info:
            self._update_info = info
            try:
                if hasattr(self, 'update_banner') and self.update_banner.winfo_exists():
                    self._refresh_update_banner()
            except Exception:
                pass
            self._show_update_dialog(info)
        else:
            messagebox.showinfo(
                "Обновлений нет",
                f"У тебя последняя версия: {CURRENT_VERSION}")

    def _refresh_update_banner(self):
        if not hasattr(self, 'update_banner') or not self.update_banner.winfo_exists():
            return
        if self._update_info:
            v = self._update_info['version']
            self.update_banner.config(
                text=f"⬆️ Доступна новая версия {v} — нажми, чтобы скачать",
                bg="#ffb74d", fg="#3e2723", cursor="hand2")
            self.update_banner.pack(fill='x', pady=(0, 10))
        else:
            self.update_banner.pack_forget()

    # ============ F11 ============
    def _on_f11_key(self, event=None): self.toggle_fullscreen()
    def toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        try: self.root.attributes('-fullscreen', self.is_fullscreen)
        except Exception:
            try: self.root.attributes('-zoomed', self.is_fullscreen)
            except Exception: pass
        try: self.root.update_idletasks()
        except Exception: pass

    # ============ АВАТАР ============
    def _load_my_avatar(self):
        if not PIL_OK: return
        p = self.profile.get('avatar_path', '')
        if p and os.path.exists(p):
            try: self.my_avatar_img = circular_avatar(p); return
            except Exception as e: print("[Avatar]", e)
        self.my_avatar_img = None

    def _get_avatar_image(self, username):
        if username == self.username and self.my_avatar_img is not None: return self.my_avatar_img
        if username in self.user_avatars: return self.user_avatars[username]
        if PIL_OK: return default_avatar(username)
        return None

    def _publish_my_avatar(self):
        if not self.mqtt_connected or not self.mqtt or not self.my_avatar_topic: return
        try:
            if self.my_avatar_img is not None:
                buf = io.BytesIO(); self.my_avatar_img.save(buf, format='PNG')
                self.mqtt.publish(self.my_avatar_topic, buf.getvalue(), qos=1, retain=True)
            else:
                self.mqtt.publish(self.my_avatar_topic, b'', qos=1, retain=True)
        except Exception: pass

    # ============ ГОЛОС/КАМЕРА/ЭКРАН ============
    def _voice_send(self, payload):
        if not self.mqtt_connected or not self.mqtt or not self.my_voice_topic: return
        try: self.mqtt.publish(self.my_voice_topic, payload, qos=0)
        except Exception: pass

    def _my_speaking_changed(self, speaking):
        self.root.after(0, lambda: self._set_user_speaking(self.username, speaking))

    def _camera_frame(self, jpeg_bytes): self._local_frame('cam', jpeg_bytes)
    def _screen_frame(self, jpeg_bytes): self._local_frame('screen', jpeg_bytes)

    def _local_frame(self, source, jpeg_bytes):
        if not PIL_OK: return
        key = (self.username, source)
        try:
            img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
            self.last_frames[key] = img
            self.last_frame_ts[key] = time.time()
        except Exception: pass
        if self.mqtt_connected and self.mqtt:
            topic = self.my_video_topic if source == 'cam' else self.my_screen_topic
            if topic:
                try: self.mqtt.publish(topic, jpeg_bytes, qos=0)
                except Exception: pass

    # ============ WEBRTC ============
    def _webrtc_send_signal(self, target, msg):
        if not self.mqtt_connected or not self.mqtt or not self.webrtc_signal_prefix: return
        try:
            topic = f"{self.webrtc_signal_prefix}/{target}"
            self.mqtt.publish(topic, json.dumps(msg), qos=1)
        except Exception as e:
            print(f"[WebRTC signal] {e}")

    def _webrtc_on_frame(self, peer_id, pil_img):
        key = (peer_id, 'screen')
        self.last_frames[key] = pil_img
        self.last_frame_ts[key] = time.time()

    def _webrtc_on_peer_state(self, peer_id, state):
        if state in ("failed", "closed", "disconnected"):
            key = (peer_id, 'screen')
            self.last_frames.pop(key, None)
            self.last_frame_ts.pop(key, None)
            try: self.root.after(0, self._rebuild_video_row)
            except Exception: pass

    def _webrtc_broadcast_offer(self):
        if not self.webrtc: return
        peers = [u for u in self.online.keys() if u != self.username]
        for p in peers:
            self.webrtc.offer_to(p)

    def _webrtc_notify_new_peer(self, peer_id):
        if self.webrtc and self.webrtc.sending:
            self.webrtc.offer_to(peer_id)

    def _ensure_webrtc_instance(self):
        if not (WEBRTC_LIB_OK and self.webrtc_enabled): return False
        if self.webrtc: return True
        try:
            self.webrtc = WebRTCScreen(
                my_id=self.username,
                send_signal=self._webrtc_send_signal,
                on_remote_frame=self._webrtc_on_frame,
                on_peer_state=self._webrtc_on_peer_state,
            )
            return True
        except Exception as e:
            print(f"[WebRTC init] {e}")
            self.webrtc = None
            return False

    def _destroy_webrtc_instance(self):
        try:
            if self.webrtc: self.webrtc.shutdown()
        except Exception: pass
        self.webrtc = None
        self._webrtc_known_peers = set()

    # ============ MQTT ============
    def _start_broker_search(self):
        if self._finding: return
        self._finding = True
        threading.Thread(target=self._find_broker, daemon=True).start()

    def _log(self, text):
        self.connect_log.append(text); print("[CONNECT]", text)
        self.root.after(0, self._render_connect_log)

    def _render_connect_log(self):
        if not getattr(self, 'log_box', None): return
        try:
            if not self.log_box.winfo_exists(): return
            self.log_box.config(state='normal')
            self.log_box.delete('1.0', 'end')
            self.log_box.insert('end', "\n".join(self.connect_log[-6:]))
            self.log_box.see('end'); self.log_box.config(state='disabled')
        except Exception: pass

    def _find_broker(self):
        self._log("🌐 Начинаю подключение к сети...")
        for host, port, transport, tls, path, label in BROKER_CANDIDATES:
            if self.mqtt_connected: break
            try:
                self._log(f"→ {label}: проверка порта...")
                if not tcp_precheck(host, port, timeout=2.5):
                    self._log(f"✗ {label}: порт недоступен"); continue
                self._log(f"→ {label}: MQTT-хендшейк...")
                c = make_mqtt_client(transport, tls, path)
                c.on_connect = self._on_connect; c.on_disconnect = self._on_disconnect
                c.on_message = self._on_message
                try: c.connect_async(host, port, keepalive=30); c.loop_start()
                except Exception as e:
                    self._log(f"✗ {label}: {e}")
                    try: c.loop_stop()
                    except Exception: pass
                    continue
                for _ in range(40):
                    if self.mqtt_connected: break
                    time.sleep(0.1)
                if self.mqtt_connected:
                    self.mqtt = c; self.broker_label = label
                    self._log(f"✅ Подключено: {label}"); return
                else:
                    self._log(f"✗ {label}: не ответил")
                    try: c.loop_stop(); c.disconnect()
                    except Exception: pass
            except Exception as e:
                self._log(f"✗ {label}: {e}")
        if not self.mqtt_connected: self._log("❌ Не удалось подключиться")
        self._finding = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc != 0: return
        self.mqtt_connected = True
        try: client.subscribe(DISCOVERY_TOPIC + "/+", qos=1)
        except Exception: pass
        if self.chat_topic:
            for t, q in ((self.chat_topic, 1), (self.users_topic + "/+", 1),
                         (self.voice_topic_prefix + "/+", 0),
                         (self.avatar_topic_prefix + "/+", 1),
                         (self.video_topic_prefix + "/+", 0),
                         (self.screen_topic_prefix + "/+", 0)):
                try: client.subscribe(t, qos=q)
                except Exception: pass
            if self.webrtc_signal_prefix:
                try: client.subscribe(f"{self.webrtc_signal_prefix}/{self.username}", qos=1)
                except Exception: pass
        if self.is_host and self.hosting_topic: self._publish_host_announce()
        self._publish_my_avatar()

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self.mqtt_connected = False

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic; payload = msg.payload

            if topic.startswith(DISCOVERY_TOPIC + "/"):
                name = topic[len(DISCOVERY_TOPIC) + 1:]
                if not payload: self.discovered.pop(name, None)
                else:
                    try:
                        d = json.loads(payload.decode('utf-8', 'ignore'))
                        if isinstance(d, dict) and 'name' in d:
                            self.discovered[name] = d
                    except Exception: pass
                self.root.after(0, self._schedule_list_refresh)
                return

            if self.voice_topic_prefix and topic.startswith(self.voice_topic_prefix + "/"):
                user = topic[len(self.voice_topic_prefix) + 1:]
                if user == self.username or not payload: return
                try:
                    arr = np.frombuffer(payload, dtype=np.int16)
                    if arr.size == 0: return
                    rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
                    if rms > VOICE_THRESHOLD:
                        self.user_speaking[user] = time.time()
                        self.voice.feed(arr.copy())
                        self.root.after(0, lambda u=user: self._set_user_speaking(u, True))
                except Exception: pass
                return

            if self.avatar_topic_prefix and topic.startswith(self.avatar_topic_prefix + "/"):
                user = topic[len(self.avatar_topic_prefix) + 1:]
                if user == self.username: return
                if not payload: self.user_avatars.pop(user, None)
                else:
                    try:
                        img = Image.open(io.BytesIO(payload)).convert("RGBA")
                        self.user_avatars[user] = img
                    except Exception: pass
                self.root.after(0, lambda u=user: self._refresh_avatar_widget(u))
                return

            if self.video_topic_prefix and topic.startswith(self.video_topic_prefix + "/"):
                user = topic[len(self.video_topic_prefix) + 1:]
                if user == self.username: return
                self._handle_stream(user, 'cam', payload); return

            if self.screen_topic_prefix and topic.startswith(self.screen_topic_prefix + "/"):
                user = topic[len(self.screen_topic_prefix) + 1:]
                if user == self.username: return
                if self.webrtc and user in self.webrtc.pcs: return
                self._handle_stream(user, 'screen', payload); return

            if (self.webrtc and self.webrtc_signal_prefix
                    and topic.startswith(self.webrtc_signal_prefix + "/")):
                target = topic[len(self.webrtc_signal_prefix) + 1:]
                if target != self.username: return
                try: d = json.loads(payload.decode('utf-8', 'ignore'))
                except Exception: return
                frm = d.get('from', '')
                if not frm or frm == self.username: return
                t = d.get('type')
                if t == 'offer':
                    self.webrtc.handle_offer(frm, d.get('sdp', ''), d.get('sdpType', 'offer'))
                elif t == 'answer':
                    self.webrtc.handle_answer(frm, d.get('sdp', ''), d.get('sdpType', 'answer'))
                elif t == 'ice':
                    self.webrtc.handle_ice(frm, d.get('candidate', {}))
                return

            if self.users_topic and topic.startswith(self.users_topic + "/"):
                nick = topic.rsplit("/", 1)[-1]
                if not payload: self.online.pop(nick, None)
                else:
                    try: self.online[nick] = json.loads(payload.decode('utf-8','ignore')).get('ts', time.time())
                    except Exception: self.online[nick] = time.time()
                self.root.after(0, self.refresh_online)
                if self.is_host: self._publish_host_announce()
                return

            if self.chat_topic and topic == self.chat_topic:
                try: d = json.loads(payload.decode('utf-8', 'ignore'))
                except Exception: return
                t = d.get('type'); user = d.get('user', '?')
                if user != self.username:
                    self.online[user] = time.time()
                    self.root.after(0, self.refresh_online)
                    if self.is_host: self._publish_host_announce()
                if t == 'chat':
                    self.root.after(0, self.append_chat, f"{user}: {d.get('text','')}")
                elif t == 'join':
                    self.root.after(0, self.append_chat, f"[СИСТЕМА] {user} зашёл на сервер")
                elif t == 'leave':
                    self.root.after(0, self.append_chat, f"[СИСТЕМА] {user} вышел")
                    if self.is_host:
                        self.online.pop(user, None); self._publish_host_announce()
                return
        except Exception as e:
            print("[MQTT msg]", e)

    def _handle_stream(self, user, source, payload):
        key = (user, source)
        if not payload:
            self.last_frames.pop(key, None); self.last_frame_ts.pop(key, None)
            self.root.after(0, self._rebuild_video_row); return
        if not PIL_OK: return
        try:
            img = Image.open(io.BytesIO(payload)).convert("RGB")
            self.last_frames[key] = img
            self.last_frame_ts[key] = time.time()
        except Exception: pass

    def _schedule_list_refresh(self):
        if self.list_debounce_job:
            try: self.root.after_cancel(self.list_debounce_job)
            except Exception: pass
        self.list_debounce_job = self.root.after(250, self._rebuild_server_list_ui)

    # ============ SPEAKING TICK ============
    def _schedule_speaking_tick(self):
        def tick():
            try:
                self.voice.tick_speaking_timeout()
                now = time.time()
                for u, t in list(self.user_speaking.items()):
                    if now - t > SPEAKING_TIMEOUT:
                        self.user_speaking.pop(u, None)
                        self._set_user_speaking(u, False)
            except Exception: pass
            self.speak_tick_job = self.root.after(200, tick)
        self.speak_tick_job = self.root.after(200, tick)

    def _set_user_speaking(self, username, speaking):
        w = self.avatar_widgets.get(username)
        if not w: return
        try:
            canvas = w['canvas']
            if not canvas.winfo_exists(): return
            canvas.itemconfig(w['ring_id'],
                              outline="#4caf50" if speaking else "#cfd8dc")
        except Exception: pass

    # ============ АВТОРИЗАЦИЯ ============
    def show_auth(self):
        for w in self.root.winfo_children(): w.destroy()
        f = tk.Frame(self.root); f.pack(expand=True)

        tk.Label(f, text="PyBlox", font=("Arial", 32, "bold"), fg="#1e88e5").pack(pady=(0, 6))
        tk.Label(f, text=f"v{CURRENT_VERSION}", font=("Arial", 9), fg="#999").pack(pady=(0, 14))

        tk.Label(f, text="Никнейм:", font=("Arial", 12)).pack()
        self.nick_entry = tk.Entry(f, width=32, font=("Arial", 12)); self.nick_entry.pack(pady=4)
        if self.last_user: self.nick_entry.insert(0, self.last_user)

        tk.Label(f, text="Пароль:", font=("Arial", 12)).pack()
        self.pw_entry = tk.Entry(f, width=32, show="*", font=("Arial", 12)); self.pw_entry.pack(pady=4)
        self.pw_entry.bind('<Return>', lambda e: self.login())

        tk.Button(f, text="Войти", width=24, bg="#43a047", fg="white",
                  font=("Arial", 11, "bold"), command=self.login).pack(pady=(14, 4))
        tk.Button(f, text="Зарегистрироваться", width=24,
                  font=("Arial", 11), command=self.register).pack(pady=4)

        self.status = tk.Label(f, text="", fg="red", font=("Arial", 10)); self.status.pack(pady=4)

        tk.Label(f, text="💡 После входа пароль больше не спросят,\n"
                         "пока ты не нажмёшь «Выйти из аккаунта»",
                 font=("Arial", 9), fg="#777").pack(pady=(8, 4))

        logf = tk.Frame(f, bd=1, relief='solid'); logf.pack(fill='x', padx=20, pady=(10, 6))
        tk.Label(logf, text="Состояние сети:", font=("Arial", 8, "bold"), anchor='w').pack(fill='x', padx=6, pady=(4, 0))
        self.log_box = tk.Text(logf, height=6, font=("Consolas", 9),
                               bg="#f5f5f5", fg="#333", state='disabled', wrap='word')
        self.log_box.pack(fill='x', padx=6, pady=4)

        tk.Button(f, text="🔄 Переподключиться к сети", font=("Arial", 10),
                  command=self.reconnect_broker).pack(pady=4)

        self.broker_status = tk.Label(f, text="", fg="gray", font=("Arial", 9))
        self.broker_status.pack(side='bottom', pady=6)
        self._render_connect_log(); self._update_broker_status()

    def reconnect_broker(self):
        try:
            if self.mqtt: self.mqtt.loop_stop(); self.mqtt.disconnect()
        except Exception: pass
        self.mqtt = None; self.mqtt_connected = False
        self.connect_log = []; self.broker_label = ""; self._finding = False
        self._start_broker_search()

    def _update_broker_status(self):
        if self._broker_status_job:
            try: self.root.after_cancel(self._broker_status_job)
            except Exception: pass
            self._broker_status_job = None
        if getattr(self, 'broker_status', None) and self.broker_status.winfo_exists():
            if self.mqtt_connected:
                self.broker_status.config(text=f"🌐 Сеть: {self.broker_label}", fg="#43a047")
            else:
                self.broker_status.config(text="подключение к сети...", fg="gray")
        try: self._broker_status_job = self.root.after(1500, self._update_broker_status)
        except Exception: pass

    def login(self):
        n, p = self.nick_entry.get().strip(), self.pw_entry.get()
        if not n or not p: self.status.config(text="Заполни все поля", fg="red"); return
        if n not in self.accounts: self.status.config(text="Игрок не найден", fg="red"); return
        if self.accounts[n] != hash_pw(p): self.status.config(text="Неверный пароль", fg="red"); return
        self.username = n
        save_json(LAST_USER_FILE, {'user': n})
        save_json(SESSION_FILE, {'user': n, 'ts': time.time()})
        self.show_menu()

    def register(self):
        n, p = self.nick_entry.get().strip(), self.pw_entry.get()
        if not n or not p: self.status.config(text="Заполни все поля", fg="red"); return
        if len(n) < 3: self.status.config(text="Ник минимум 3 символа", fg="red"); return
        if not n.replace('_', '').isalnum(): self.status.config(text="Только буквы, цифры, _", fg="red"); return
        if n in self.accounts: self.status.config(text="Ник занят", fg="red"); return
        self.accounts[n] = hash_pw(p); save_json(ACCOUNTS_FILE, self.accounts)
        self.status.config(text="Аккаунт создан! Нажми 'Войти'", fg="green")

    # ============ МЕНЮ ============
    def show_menu(self):
        for w in self.root.winfo_children(): w.destroy()
        f = tk.Frame(self.root); f.pack(expand=True)

        tk.Label(f, text=f"Привет, {self.username}!",
                 font=("Arial", 22, "bold")).pack(pady=(0, 6))

        tk.Label(f, text="🔓 Автовход активен — пароль не спросят при следующем запуске",
                 font=("Arial", 9), fg="#4caf50").pack(pady=(0, 8))

        # ---- баннер обновления ----
        self.update_banner = tk.Label(
            f, text="", font=("Arial", 11, "bold"),
            padx=12, pady=10, anchor='w', justify='left')
        self.update_banner.bind("<Button-1>",
                                lambda e: self._show_update_dialog(self._update_info))
        self._refresh_update_banner()

        if WEBRTC_LIB_OK:
            mode = "🚀 WebRTC (реальное время)" if self.webrtc_enabled else "📡 MQTT (с задержкой)"
        else:
            mode = "📡 MQTT-режим (WebRTC-библиотека не установлена)"
        tk.Label(f, text=mode, font=("Arial", 11), fg="gray").pack(pady=(0, 14))

        if PIL_OK and self.my_avatar_img is not None:
            ph = ImageTk.PhotoImage(self.my_avatar_img)
            lbl = tk.Label(f, image=ph); lbl.image = ph; lbl.pack(pady=(0, 14))

        tk.Button(f, text="🌐  Список серверов", width=30, height=2,
                  bg="#1e88e5", fg="white", font=("Arial", 12, "bold"),
                  command=self.show_server_list).pack(pady=6)
        tk.Button(f, text="🛠  Создать сервер", width=30, height=2,
                  bg="#43a047", fg="white", font=("Arial", 12, "bold"),
                  command=self.create_server).pack(pady=6)
        tk.Button(f, text="⚙️  Настройки", width=30,
                  font=("Arial", 11), command=self.show_settings).pack(pady=(14, 4))
        tk.Button(f, text="🚪  Выйти из аккаунта", width=30,
                  font=("Arial", 11), command=self.logout).pack(pady=4)

        tk.Label(f, text=f"PyBlox v{CURRENT_VERSION}",
                 font=("Arial", 8), fg="#999").pack(pady=(10, 0))

        self.broker_status = tk.Label(f, text="", fg="gray", font=("Arial", 9))
        self.broker_status.pack(side='bottom', pady=6)
        self._update_broker_status()

    def logout(self):
        self.leave_current()
        self.username = None
        delete_file(SESSION_FILE)
        self.show_auth()

    # ============ СПИСОК СЕРВЕРОВ ============
    def show_server_list(self):
        self.on_server_list = True
        if self.mqtt_connected and self.mqtt:
            try: self.mqtt.subscribe(DISCOVERY_TOPIC + "/+", qos=1)
            except Exception: pass
        self._rebuild_server_list_ui(first=True)

    def _rebuild_server_list_ui(self, first=False):
        if not getattr(self, 'on_server_list', False): return
        if self.list_debounce_job:
            try: self.root.after_cancel(self.list_debounce_job)
            except Exception: pass
            self.list_debounce_job = None

        for w in self.root.winfo_children(): w.destroy()

        top = tk.Frame(self.root, bg="#263238"); top.pack(fill='x')
        tk.Label(top, text="  🌐 Все серверы  ", bg="#263238", fg="white",
                 font=("Arial", 14, "bold")).pack(side='left')
        tk.Button(top, text="⟳ Обновить", bg="#455a64", fg="white", bd=0,
                  font=("Arial", 10, "bold"),
                  command=self.refresh_server_list).pack(side='left', padx=8, pady=6)
        tk.Button(top, text="← Назад", bg="#546e7a", fg="white", bd=0,
                  command=self.back_to_menu).pack(side='right', padx=6, pady=6)

        now = time.time()
        online_count = 0; offline_count = 0
        for d in self.discovered.values():
            if not isinstance(d, dict): continue
            ts = d.get('ts', 0)
            if d.get('online') and (now - ts) < ONLINE_TTL: online_count += 1
            else: offline_count += 1

        hint = tk.Label(self.root, anchor='w', bg="#37474f", fg="#b0bec5",
                        font=("Arial", 9), padx=8, pady=3)
        hint.pack(fill='x')
        if self.mqtt_connected:
            hint.config(text=f"🌐 {self.broker_label}   •   "
                             f"🟢 онлайн: {online_count}   •   ⚫ оффлайн: {offline_count}   •   "
                             f"обновление каждые {LIST_REFRESH_MS//1000} с")
        else:
            hint.config(text="⚠️ Нет соединения с сетью — нажми ⟳ Обновить")

        body = tk.Frame(self.root); body.pack(fill='both', expand=True)
        canvas = tk.Canvas(body, bg="#fafafa", highlightthickness=0)
        scroll = tk.Scrollbar(body, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(canvas, bg="#fafafa")
        canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))

        cutoff = now - SERVER_HIDE_DAYS * 86400
        alive = {n: d for n, d in self.discovered.items()
                 if isinstance(d, dict) and d.get('ts', 0) >= cutoff}
        self.discovered = alive

        if not self.mqtt_connected:
            tk.Label(inner, text="⚠️ Нет связи с сетью", font=("Arial", 13, "bold"),
                     bg="#fafafa", fg="#e53935").pack(pady=20)
        elif not alive:
            tk.Label(inner, text="Пока нет ни одного сервера 😔",
                     font=("Arial", 13), bg="#fafafa", fg="#757575").pack(pady=30)
            tk.Label(inner, text="Создай свой — он останется тут даже после того, как ты выйдешь",
                     font=("Arial", 11), bg="#fafafa", fg="#9e9e9e").pack(pady=(0, 10))
        else:
            def sort_key(item):
                d = item[1]
                is_on = 1 if (d.get('online') and (now - d.get('ts', 0)) < ONLINE_TTL) else 0
                return (-is_on, -d.get('ts', 0))
            for name, d in sorted(alive.items(), key=sort_key):
                self._render_server_row(inner, name, d, now)

        if self.list_refresh_job:
            try: self.root.after_cancel(self.list_refresh_job)
            except Exception: pass
        self.list_refresh_job = self.root.after(LIST_REFRESH_MS, self._auto_refresh_list)

    def _render_server_row(self, parent, name, data, now):
        ts = data.get('ts', 0)
        is_online = bool(data.get('online')) and (now - ts) < ONLINE_TTL
        is_mine = (name == self.current_server and self.is_host)

        bg = "#e8f5e9" if is_online else "#f0f0f0"
        status_txt = "🟢 онлайн" if is_online else "⚫ оффлайн"

        row = tk.Frame(parent, bg=bg, bd=1, relief='solid'); row.pack(fill='x', padx=12, pady=6)
        left = tk.Frame(row, bg=bg); left.pack(side='left', fill='both', expand=True, padx=10, pady=8)

        title = tk.Frame(left, bg=bg); title.pack(anchor='w')
        tk.Label(title, text=name, font=("Arial", 14, "bold"),
                 bg=bg, anchor='w').pack(side='left')
        if is_mine:
            tk.Label(title, text="  (мой)", font=("Arial", 10, "italic"),
                     fg="#43a047", bg=bg).pack(side='left')

        host = data.get('host', '?')
        online = data.get('online_users', data.get('online', '?'))
        age = fmt_age(now - ts)

        info_txt = f"хост: {host}   •   {status_txt}"
        if is_online: info_txt += f"   •   игроков: {online}"
        info_txt += f"   •   обновлён {age}"

        tk.Label(left, text=info_txt, font=("Arial", 9),
                 bg=bg, fg="#757575", anchor='w').pack(anchor='w')

        right = tk.Frame(row, bg=bg); right.pack(side='right', padx=10, pady=8)
        tk.Button(right, text="  Войти  ", bg="#43a047", fg="white",
                  font=("Arial", 11, "bold"), bd=0,
                  command=lambda n=name: self.join_from_list(n)).pack(side='right')
        if is_mine:
            tk.Button(right, text="🗑", bg="#e53935", fg="white",
                      font=("Arial", 10, "bold"), bd=0,
                      command=lambda n=name: self.delete_server(n)
                      ).pack(side='right', padx=(0, 6))

    def delete_server(self, name):
        if not messagebox.askyesno("Удалить сервер?",
                                   f"Убрать '{name}' из списка у всех?"): return
        if self.mqtt_connected and self.mqtt:
            try:
                self.mqtt.publish(f"{DISCOVERY_TOPIC}/{name}", b'', qos=1, retain=True)
                self.discovered.pop(name, None)
            except Exception: pass
        self._rebuild_server_list_ui()

    def _auto_refresh_list(self):
        if not getattr(self, 'on_server_list', False): return
        if self.list_debounce_job:
            try:
                self.root.after_cancel(self.list_debounce_job); self.list_debounce_job = None
            except Exception: pass
        self._rebuild_server_list_ui()

    def refresh_server_list(self):
        if not self.mqtt_connected:
            self.reconnect_broker(); self.root.after(800, self._rebuild_server_list_ui); return
        try: self.mqtt.unsubscribe(DISCOVERY_TOPIC + "/+")
        except Exception: pass
        self.discovered = {}
        try: self.mqtt.subscribe(DISCOVERY_TOPIC + "/+", qos=1)
        except Exception: pass
        self._rebuild_server_list_ui()

    def join_from_list(self, name):
        self.on_server_list = False
        for job in ('list_refresh_job', 'list_debounce_job'):
            j = getattr(self, job, None)
            if j:
                try: self.root.after_cancel(j)
                except Exception: pass
                setattr(self, job, None)
        self.is_host = False
        self.enter_server(name)

    def back_to_menu(self):
        self.on_server_list = False
        for job in ('list_refresh_job', 'list_debounce_job'):
            j = getattr(self, job, None)
            if j:
                try: self.root.after_cancel(j)
                except Exception: pass
                setattr(self, job, None)
        self.show_menu()

    # ============ НАСТРОЙКИ ============
    def show_settings(self):
        for w in self.root.winfo_children(): w.destroy()

        outer = tk.Frame(self.root); outer.pack(fill='both', expand=True)
        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = tk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
        f = tk.Frame(canvas)
        canvas.create_window((0, 0), window=f, anchor='nw')
        f.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))

        tk.Label(f, text="⚙️ Настройки", font=("Arial", 22, "bold")).pack(pady=(16, 16))

        # ---- Аватар ----
        av_frame = tk.LabelFrame(f, text="Аватар", font=("Arial", 10, "bold"), padx=14, pady=10)
        av_frame.pack(pady=8, padx=20, fill='x')
        av_row = tk.Frame(av_frame); av_row.pack(fill='x')
        if PIL_OK and self.my_avatar_img is not None:
            ph = ImageTk.PhotoImage(self.my_avatar_img)
            lbl = tk.Label(av_row, image=ph); lbl.image = ph; lbl.pack(side='left', padx=(0, 12))
        else:
            tk.Label(av_row, text="(нет аватара)", fg="#888").pack(side='left', padx=(0, 12))
        btn_col = tk.Frame(av_row); btn_col.pack(side='left')
        tk.Button(btn_col, text="📁 Загрузить картинку", width=24,
                  command=self.choose_avatar).pack(anchor='w', pady=2)
        tk.Button(btn_col, text="🗑 Удалить аватар", width=24,
                  command=self.clear_avatar).pack(anchor='w', pady=2)

        # ---- Микрофон ----
        mic_frame = tk.LabelFrame(f, text="Микрофон (клавиша P)",
                                  font=("Arial", 10, "bold"), padx=14, pady=10)
        mic_frame.pack(pady=8, padx=20, fill='x')
        if not VOICE_OK:
            tk.Label(mic_frame, text="pip install sounddevice numpy", fg="#e53935").pack(anchor='w')
        else:
            devices = self.voice.list_input_devices()
            labels = [f"{i}: {name}" for i, name in devices] or ["(нет устройств)"]
            self.mic_var = tk.StringVar()
            current = self.profile.get('mic_device')
            if current is not None:
                for i, name in devices:
                    if i == current: self.mic_var.set(f"{i}: {name}"); break
            if not self.mic_var.get() and labels: self.mic_var.set(labels[0])
            combo = ttk.Combobox(mic_frame, textvariable=self.mic_var, values=labels,
                                 state='readonly', width=52)
            combo.pack(anchor='w', pady=4)
            combo.bind('<<ComboboxSelected>>', lambda e: self.save_mic_choice())

        # ---- Камера ----
        cam_frame = tk.LabelFrame(f, text="Камера (клавиша O)",
                                  font=("Arial", 10, "bold"), padx=14, pady=10)
        cam_frame.pack(pady=8, padx=20, fill='x')
        if not CAM_OK:
            tk.Label(cam_frame, text="pip install opencv-python", fg="#e53935").pack(anchor='w')
        else:
            cam_row = tk.Frame(cam_frame); cam_row.pack(fill='x', anchor='w')
            self.cam_var = tk.StringVar()
            cur = int(self.profile.get('cam_device', 0)); self.cam_var.set(f"Камера {cur}")
            self.cam_combo = ttk.Combobox(cam_row, textvariable=self.cam_var,
                                          values=[f"Камера {i}" for i in range(6)],
                                          state='readonly', width=24)
            self.cam_combo.pack(side='left', padx=(0, 8))
            self.cam_combo.bind('<<ComboboxSelected>>', lambda e: self.save_cam_choice())
            tk.Button(cam_row, text="🔍 Найти камеры", command=self.probe_cameras).pack(side='left')

        # ---- Демонстрация экрана ----
        scr_frame = tk.LabelFrame(f, text="Демонстрация экрана (клавиша I)",
                                  font=("Arial", 10, "bold"), padx=14, pady=10)
        scr_frame.pack(pady=8, padx=20, fill='x')

        wr_row = tk.Frame(scr_frame); wr_row.pack(fill='x', anchor='w', pady=(0, 8))

        if WEBRTC_LIB_OK:
            self.webrtc_var = tk.BooleanVar(value=self.webrtc_enabled)
            cb = tk.Checkbutton(
                wr_row,
                text="🚀 Использовать WebRTC (реальное время, задержка ~200 мс)",
                variable=self.webrtc_var,
                command=self.save_webrtc_choice,
                font=("Arial", 10, "bold"),
            )
            cb.pack(anchor='w')
            mode_now = "WebRTC" if self.webrtc_enabled else "MQTT"
            tk.Label(wr_row,
                     text=f"Текущий режим: {mode_now}.",
                     font=("Arial", 9), fg="#666").pack(anchor='w', pady=(2, 0))
        else:
            tk.Label(wr_row,
                     text="⚠️ WebRTC недоступен — библиотека не установлена.\n"
                          "Установи: pip install aiortc av  (потом перезапусти клиент)",
                     font=("Arial", 9), fg="#e53935", justify='left').pack(anchor='w')
            self.webrtc_var = tk.BooleanVar(value=False)

        q_row = tk.Frame(scr_frame); q_row.pack(fill='x', anchor='w', pady=4)
        tk.Label(q_row, text="Разрешение:", font=("Arial", 10)).pack(side='left')
        self.screen_res_var = tk.StringVar(value=self.profile.get('screen_res', '480p'))
        res_combo = ttk.Combobox(q_row, textvariable=self.screen_res_var,
                                 values=list(SCREEN_RESOLUTIONS.keys()),
                                 state='readonly', width=10)
        res_combo.pack(side='left', padx=(6, 18))
        res_combo.bind('<<ComboboxSelected>>', lambda e: self.save_screen_choice())

        tk.Label(q_row, text="FPS:", font=("Arial", 10)).pack(side='left')
        self.screen_fps_var = tk.StringVar(value=str(self.profile.get('screen_fps', 30)))
        fps_combo = ttk.Combobox(q_row, textvariable=self.screen_fps_var,
                                 values=[str(x) for x in SCREEN_FPS_CHOICES],
                                 state='readonly', width=6)
        fps_combo.pack(side='left', padx=6)
        fps_combo.bind('<<ComboboxSelected>>', lambda e: self.save_screen_choice())

        self.screen_hint = tk.Label(scr_frame, text="", font=("Arial", 9),
                                    fg="#666", justify='left')
        self.screen_hint.pack(anchor='w', pady=(6, 0))
        self._update_screen_hint()

        tk.Label(scr_frame,
                 text="⚠️ 720p@60fps создаёт ~2–3 МБ/с трафика — может тормозить.\n"
                      "Для интернета с другом оптимально: 480p@30 или 360p@30.",
                 font=("Arial", 8), fg="#b71c1c", justify='left').pack(anchor='w', pady=(6, 0))

        # ---- Кнопки ----
        tk.Button(f, text="🔗  Подключиться вручную по имени", width=34, height=2,
                  bg="#1e88e5", fg="white", font=("Arial", 11, "bold"),
                  command=self.manual_connect).pack(pady=(14, 6))
        tk.Button(f, text="🔄  Переподключиться к сети", width=34,
                  font=("Arial", 10), command=self.reconnect_broker).pack(pady=4)

        tk.Button(f, text="⬆️  Проверить обновления", width=34,
                  font=("Arial", 10, "bold"),
                  bg="#ffb74d", fg="#3e2723",
                  command=self.manual_check_updates).pack(pady=4)
        tk.Label(f, text=f"Текущая версия: {CURRENT_VERSION}   •   репо: {GITHUB_REPO}",
                 font=("Arial", 8), fg="#999").pack(pady=(2, 0))

        tk.Button(f, text="↩  В главное меню", width=34,
                  font=("Arial", 10), command=self.show_menu).pack(pady=6)

        info = tk.Frame(f, bd=1, relief='solid', padx=14, pady=8); info.pack(pady=10)
        tk.Label(info, text=f"Брокер: {self.broker_label or '—'}   •   "
                            f"Статус: {'✅ онлайн' if self.mqtt_connected else '❌ нет связи'}",
                 font=("Arial", 9), fg="#555").pack()

    def save_webrtc_choice(self):
        val = bool(self.webrtc_var.get())
        self.webrtc_enabled = val and WEBRTC_LIB_OK
        self.profile['use_webrtc'] = val
        save_json(PROFILE_FILE, self.profile)

        if self.current_server:
            if self.webrtc_enabled:
                if self._ensure_webrtc_instance():
                    if self.mqtt_connected and self.mqtt and self.webrtc_signal_prefix:
                        try:
                            self.mqtt.subscribe(
                                f"{self.webrtc_signal_prefix}/{self.username}", qos=1)
                        except Exception: pass
                    self.append_chat("[СИСТЕМА] WebRTC включён (перезапусти трансляцию I)")
                else:
                    self.append_chat("[СИСТЕМА] Не удалось инициализировать WebRTC")
            else:
                if self.webrtc and self.webrtc.sending:
                    self.webrtc.stop_screen()
                    key = (self.username, 'screen')
                    self.last_frames.pop(key, None); self.last_frame_ts.pop(key, None)
                    self._rebuild_video_row()
                self._destroy_webrtc_instance()
                self.append_chat("[СИСТЕМА] WebRTC выключен, режим MQTT")

        self._refresh_screen_btn_label()
        self.show_settings()

    def _update_screen_hint(self):
        if not hasattr(self, 'screen_hint') or not self.screen_hint.winfo_exists(): return
        res = self.profile.get('screen_res', '480p')
        fps = self.profile.get('screen_fps', 30)
        if res in SCREEN_RESOLUTIONS:
            w, h, q = SCREEN_RESOLUTIONS[res]
        else:
            w, h, q = 854, 480, 30
        est_kb_frame = (w * h) / 5000 * (q / 40)
        kbps = est_kb_frame * fps
        rate = f"{kbps/1024:.1f} МБ/с" if kbps > 1024 else f"{kbps:.0f} КБ/с"
        mode = "WebRTC (реальное время)" if self.webrtc_enabled and WEBRTC_LIB_OK else "MQTT (с задержкой)"
        self.screen_hint.config(text=f"📺 Текущее: {res} ({w}×{h}) @ {fps} fps   •   "
                                     f"режим: {mode}   •   ~{rate} на зрителя")

    def save_screen_choice(self):
        res = self.screen_res_var.get()
        try: fps = int(self.screen_fps_var.get())
        except Exception: fps = 30
        if res not in SCREEN_RESOLUTIONS: res = '480p'
        if fps not in SCREEN_FPS_CHOICES: fps = 30
        self.profile['screen_res'] = res
        self.profile['screen_fps'] = fps
        save_json(PROFILE_FILE, self.profile)
        self.screen.set_quality(res, fps)
        if self.webrtc and self.webrtc.sending:
            r = res if res in WEBRTC_RESOLUTIONS else '480p'
            self.webrtc.set_quality(r, fps)
        self._update_screen_hint()
        self._refresh_screen_btn_label()

    def _refresh_screen_btn_label(self):
        if not getattr(self, 'screen_btn', None) or not self.screen_btn.winfo_exists():
            return
        if self.webrtc:
            on = self.webrtc.sending
            mode = "WebRTC"
        else:
            on = self.screen.running
            mode = "MQTT"
        res = self.profile.get('screen_res', '480p')
        fps = self.profile.get('screen_fps', 30)
        if on:
            self.screen_btn.config(text=f"🖥 Screen: ON {res}@{fps} ({mode}) (I)", bg="#43a047")
        else:
            self.screen_btn.config(text="🖥 Screen: OFF (I)", bg="#546e7a")

    def probe_cameras(self):
        if not CAM_OK: messagebox.showerror("Камера", "pip install opencv-python"); return
        messagebox.showinfo("Поиск", "Проверю камеры 0–5.\nЗаймёт пару секунд.")
        def run():
            found = CameraEngine.probe_cameras(max_check=6)
            self.root.after(0, lambda: self._show_cameras_found(found))
        threading.Thread(target=run, daemon=True).start()

    def _show_cameras_found(self, found):
        if not found:
            messagebox.showwarning("Камера", "Камеры не найдены."); return
        labels = [f"Камера {i}" for i in found]
        try: self.cam_combo.config(values=labels)
        except Exception: pass
        if labels: self.cam_var.set(labels[0]); self.save_cam_choice()
        messagebox.showinfo("Готово", f"Найдено: {', '.join(labels)}")

    def save_cam_choice(self):
        try: idx = int(self.cam_var.get().split()[-1])
        except Exception: return
        self.profile['cam_device'] = idx; save_json(PROFILE_FILE, self.profile)
        self.camera.set_device(idx)

    def choose_avatar(self):
        if not PIL_OK: messagebox.showerror("Нет Pillow", "pip install pillow"); return
        path = filedialog.askopenfilename(
            title="Выбери картинку для аватара",
            filetypes=[("Картинки", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"),
                       ("Все файлы", "*.*")])
        if not path: return
        try: img = circular_avatar(path, size=72)
        except Exception as e: messagebox.showerror("Ошибка", str(e)); return
        self.my_avatar_img = img
        self.profile['avatar_path'] = path; save_json(PROFILE_FILE, self.profile)
        self._publish_my_avatar(); self._refresh_avatar_widget(self.username)
        messagebox.showinfo("Готово", "Аватар обновлён ✨"); self.show_settings()

    def clear_avatar(self):
        self.my_avatar_img = None
        self.profile['avatar_path'] = ''; save_json(PROFILE_FILE, self.profile)
        self._publish_my_avatar(); self._refresh_avatar_widget(self.username)
        self.show_settings()

    def save_mic_choice(self):
        if not VOICE_OK: return
        try:
            idx = int(self.mic_var.get().split(':', 1)[0])
            self.profile['mic_device'] = idx; save_json(PROFILE_FILE, self.profile)
            self.voice.set_device(idx)
        except Exception: pass

    def manual_connect(self):
        name = simpledialog.askstring("Ручное подключение", "Имя сервера:", parent=self.root)
        if not name: return
        name = sanitize(name)
        if not name: messagebox.showerror("Ошибка", "Некорректное имя"); return
        self.is_host = False; self.enter_server(name)

    # ============ СОЗДАНИЕ ============
    def create_server(self):
        name = simpledialog.askstring("Создать сервер",
                                      "Имя сервера (латиница/цифры/дефис):", parent=self.root)
        if not name: return
        name = sanitize(name)
        if not name: messagebox.showerror("Ошибка", "Некорректное имя"); return
        self.is_host = True; self.enter_server(name)

    # ============ ВХОД ============
    def enter_server(self, name):
        if not self.mqtt_connected:
            self.reconnect_broker()
            dlg = tk.Toplevel(self.root); dlg.title("Подключение...")
            dlg.geometry("360x120"); dlg.transient(self.root)
            tk.Label(dlg, text="Подключаюсь к сети...\nжди до 20 секунд",
                     font=("Arial", 10)).pack(expand=True)
            threading.Thread(target=self._wait_broker_then_enter, args=(name, dlg), daemon=True).start()
            return
        self._enter_server_ready(name)

    def _wait_broker_then_enter(self, name, dlg):
        for _ in range(200):
            if self.mqtt_connected: break
            time.sleep(0.1)
        try: self.root.after(0, dlg.destroy)
        except Exception: pass
        if not self.mqtt_connected:
            self.root.after(0, lambda: messagebox.showerror(
                "Нет сети", "Не удалось подключиться к брокеру.\nПроверь интернет."))
            return
        self.root.after(0, lambda: self._enter_server_ready(name))

    def _enter_server_ready(self, name):
        self.leave_current()
        self.current_server = name
        base = f"{TOPIC_ROOT}/servers/{name}"
        self.chat_topic          = f"{base}/chat"
        self.users_topic         = f"{base}/users"
        self.voice_topic_prefix  = f"{base}/voice"
        self.avatar_topic_prefix = f"{base}/avatar"
        self.video_topic_prefix  = f"{base}/video"
        self.screen_topic_prefix = f"{base}/screen"
        self.my_heartbeat_topic  = f"{self.users_topic}/{self.username}"
        self.my_voice_topic      = f"{self.voice_topic_prefix}/{self.username}"
        self.my_avatar_topic     = f"{self.avatar_topic_prefix}/{self.username}"
        self.my_video_topic      = f"{self.video_topic_prefix}/{self.username}"
        self.my_screen_topic     = f"{self.screen_topic_prefix}/{self.username}"
        self.hosting_topic       = f"{DISCOVERY_TOPIC}/{name}" if self.is_host else None
        self.webrtc_signal_prefix = f"{base}/signal"
        self.my_webrtc_signal_topic = f"{self.webrtc_signal_prefix}/{self.username}"

        self.online = {}; self.user_avatars = {}; self.user_speaking = {}
        self.last_frames = {}; self.last_frame_ts = {}; self.video_widgets = {}
        self._webrtc_known_peers = set()

        self.mqtt.subscribe(self.chat_topic, qos=1)
        self.mqtt.subscribe(self.users_topic + "/+", qos=1)
        self.mqtt.subscribe(self.voice_topic_prefix + "/+", qos=0)
        self.mqtt.subscribe(self.avatar_topic_prefix + "/+", qos=1)
        self.mqtt.subscribe(self.video_topic_prefix + "/+", qos=0)
        self.mqtt.subscribe(self.screen_topic_prefix + "/+", qos=0)

        if WEBRTC_LIB_OK and self.webrtc_enabled:
            self._ensure_webrtc_instance()
            if self.webrtc:
                try:
                    self.mqtt.subscribe(
                        f"{self.webrtc_signal_prefix}/{self.username}", qos=1)
                except Exception: pass

        self.mqtt.publish(self.chat_topic, json.dumps({
            'type': 'join', 'user': self.username, 'ts': time.time()
        }), qos=1)
        self.mqtt.publish(self.my_heartbeat_topic, json.dumps({
            'nick': self.username, 'ts': time.time()
        }), qos=1, retain=True)

        self._publish_my_avatar()
        if self.is_host: self._publish_host_announce()
        if VOICE_OK: self.voice.start_output()

        self.screen.set_quality(self.profile.get('screen_res', '480p'),
                                self.profile.get('screen_fps', 30))

        self.show_chat(name)
        self._start_heartbeat()
        self._schedule_video_render()

    def _publish_host_announce(self, online=True):
        if not self.hosting_topic or not self.mqtt_connected or not self.mqtt: return
        try:
            self.mqtt.publish(self.hosting_topic, json.dumps({
                'name': self.current_server,
                'host': self.username,
                'online': bool(online),
                'online_users': max(1, len(self.online)) if online else 0,
                'ts': time.time()
            }), qos=1, retain=True)
        except Exception: pass

    # ============ HEARTBEAT ============
    def _start_heartbeat(self):
        self.hb_stop.clear()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _stop_heartbeat(self): self.hb_stop.set()

    def _heartbeat_loop(self):
        while not self.hb_stop.is_set():
            try:
                if self.mqtt_connected and self.mqtt and self.my_heartbeat_topic:
                    self.mqtt.publish(self.my_heartbeat_topic, json.dumps({
                        'nick': self.username, 'ts': time.time()
                    }), qos=0, retain=True)
                    if self.is_host and self.hosting_topic:
                        self._publish_host_announce(online=True)
                now = time.time()
                changed = False
                for k in list(self.online.keys()):
                    if now - self.online[k] > 30:
                        self.online.pop(k, None); changed = True
                if changed: self.root.after(0, self.refresh_online)
            except Exception: pass
            for _ in range(60):
                if self.hb_stop.is_set(): return
                time.sleep(0.1)

    def refresh_online(self):
        if self.webrtc and self.webrtc.sending:
            current = set(self.online.keys()) | {self.username}
            known = set(getattr(self, '_webrtc_known_peers', set()))
            for new_peer in current - known - {self.username}:
                self._webrtc_notify_new_peer(new_peer)
            self._webrtc_known_peers = current

        if getattr(self, 'online_label', None) and self.online_label.winfo_exists():
            users = sorted(self.online.keys())
            self.online_label.config(
                text=f"🌐 Онлайн ({len(users)}): " + (", ".join(users) if users else "—"))
        self._rebuild_avatar_row()
        self._rebuild_video_row()

    # ============ АВАТАРЫ ============
    def _rebuild_avatar_row(self):
        if not getattr(self, 'avatar_row', None) or not self.avatar_row.winfo_exists(): return
        wanted = set(self.online.keys()) | {self.username}
        for u in list(self.avatar_widgets.keys()):
            if u not in wanted:
                try: self.avatar_widgets[u]['container'].destroy()
                except Exception: pass
                self.avatar_widgets.pop(u, None)
        for u in wanted:
            if u not in self.avatar_widgets: self._create_avatar_widget(u)
        for u in wanted: self._refresh_avatar_widget(u)

    def _create_avatar_widget(self, username):
        container = tk.Frame(self.avatar_row, bg="#263238")
        container.pack(side='left', padx=8, pady=4)
        canvas = tk.Canvas(container, width=72, height=72, bg="#263238", highlightthickness=0)
        canvas.pack()
        canvas.create_oval(2, 2, 70, 70, fill="#546e7a", outline="")
        ring = canvas.create_oval(1, 1, 71, 71, outline="#cfd8dc", width=3)
        tk.Label(container, text=username, bg="#263238", fg="#eceff1",
                 font=("Arial", 9)).pack()
        self.avatar_widgets[username] = {
            'container': container, 'canvas': canvas, 'ring_id': ring,
            'img_id': None, 'photo_ref': None,
        }
        self._refresh_avatar_widget(username)

    def _refresh_avatar_widget(self, username):
        w = self.avatar_widgets.get(username)
        if not w: return
        try:
            canvas = w['canvas']
            if not canvas.winfo_exists(): return
            if w['img_id'] is not None:
                try: canvas.delete(w['img_id'])
                except Exception: pass
            img = self._get_avatar_image(username)
            if img is not None:
                photo = ImageTk.PhotoImage(img); w['photo_ref'] = photo
                w['img_id'] = canvas.create_image(36, 36, image=photo)
                canvas.tag_raise(w['ring_id'])
        except Exception: pass

    # ============ ВИДЕО РЕНДЕР ============
    def _schedule_video_render(self):
        def tick():
            try: self._rebuild_video_row()
            except Exception: pass
            self._video_render_job = self.root.after(150, tick)
        self._video_render_job = self.root.after(150, tick)

    def _rebuild_video_row(self):
        if not getattr(self, 'video_row', None) or not self.video_row.winfo_exists(): return
        now = time.time()
        active = set()
        for k, ts in self.last_frame_ts.items():
            if now - ts > SCREEN_TIMEOUT: continue
            if k[0] not in (set(self.online) | {self.username}): continue
            active.add(k)

        for k in list(self.video_widgets.keys()):
            if k not in active:
                try: self.video_widgets[k]['container'].destroy()
                except Exception: pass
                self.video_widgets.pop(k, None)
                self.last_frames.pop(k, None); self.last_frame_ts.pop(k, None)

        for k in active:
            if k not in self.video_widgets: self._create_video_widget(k)
        for k in active:
            self._update_video_widget(k)

        try:
            if active:
                if self.video_row.winfo_manager() == '':
                    self.video_row.pack(fill='x', after=self.avatar_row)
            else:
                if self.video_row.winfo_manager():
                    self.video_row.pack_forget()
        except Exception: pass

    def _create_video_widget(self, key):
        user, source = key
        icon = "🎥" if source == 'cam' else "🖥"
        container = tk.Frame(self.video_row, bg="#1b1b1b", bd=1, relief='solid')
        container.pack(side='left', padx=8, pady=6)
        img = self.last_frames.get(key)
        if img is not None:
            w_, h_ = img.size
        else:
            w_, h_ = (CAM_W, CAM_H) if source == 'cam' else (854, 480)
        lbl = tk.Label(container, bg="#000", width=w_, height=h_)
        lbl.pack()
        tk.Label(container, text=f"{user}  {icon}", bg="#1b1b1b", fg="#eceff1",
                 font=("Arial", 9)).pack(fill='x')
        self.video_widgets[key] = {'container': container, 'label': lbl, 'photo_ref': None}

    def _update_video_widget(self, key):
        w = self.video_widgets.get(key)
        if not w or not PIL_OK: return
        img = self.last_frames.get(key)
        if img is None: return
        try:
            if not w['label'].winfo_exists(): return
            photo = ImageTk.PhotoImage(img); w['photo_ref'] = photo
            w['label'].config(image=photo, width=0, height=0)
        except Exception: pass

    # ============ ЧАТ ============
    def show_chat(self, name):
        for w in self.root.winfo_children(): w.destroy()
        self.avatar_widgets = {}; self.video_widgets = {}

        top = tk.Frame(self.root, bg="#263238"); top.pack(fill='x')
        tk.Label(top, text=f"  {name}  ", bg="#263238", fg="white",
                 font=("Arial", 13, "bold")).pack(side='left')
        role = "хост" if self.is_host else "игрок"
        tk.Label(top, text=f"  ({role})   via {self.broker_label}  ",
                 bg="#263238", fg="#90a4ae", font=("Arial", 9)).pack(side='left')

        tk.Button(top, text="Выйти", command=self.leave_chat,
                  bg="#e53935", fg="white", bd=0,
                  font=("Arial", 10, "bold")).pack(side='right', padx=(4, 8), pady=6)

        self.screen_btn = tk.Button(top, text="🖥 Screen: OFF (I)", bg="#546e7a", fg="white",
                                    font=("Arial", 10, "bold"), bd=0,
                                    command=self.toggle_screen)
        self.screen_btn.pack(side='right', padx=4, pady=6)

        self.cam_btn = tk.Button(top, text="🎥 Cam: OFF (O)", bg="#546e7a", fg="white",
                                 font=("Arial", 10, "bold"), bd=0,
                                 command=self.toggle_camera)
        self.cam_btn.pack(side='right', padx=4, pady=6)

        self.mic_btn = tk.Button(top, text="🎤 Mic: OFF (P)", bg="#546e7a", fg="white",
                                 font=("Arial", 10, "bold"), bd=0,
                                 command=self.toggle_mic)
        self.mic_btn.pack(side='right', padx=4, pady=6)

        tk.Label(top, text="P=mic · O=cam · I=screen · F11=full ",
                 bg="#263238", fg="#78909c", font=("Arial", 8)).pack(side='right', padx=8)

        self.avatar_row = tk.Frame(self.root, bg="#263238"); self.avatar_row.pack(fill='x')
        self.video_row = tk.Frame(self.root, bg="#111")

        self.online_label = tk.Label(self.root, text="🌐 Онлайн: —", anchor='w',
                                     bg="#37474f", fg="#b0bec5", font=("Arial", 10),
                                     padx=8, pady=4)
        self.online_label.pack(fill='x')

        self.chat = tk.Text(self.root, bg="#1b1b1b", fg="#e0e0e0",
                            font=("Consolas", 11), wrap='word', state='disabled')
        self.chat.pack(fill='both', expand=True)

        bottom = tk.Frame(self.root); bottom.pack(fill='x')
        self.msg_entry = tk.Entry(bottom, font=("Arial", 12))
        self.msg_entry.pack(side='left', fill='x', expand=True, padx=6, pady=6)
        self.msg_entry.bind('<Return>', lambda e: self.send_msg())
        self.msg_entry.bind('<Escape>', lambda e: self.root.focus_set())
        tk.Button(bottom, text="Отправить", bg="#1e88e5", fg="white",
                  font=("Arial", 11, "bold"),
                  command=self.send_msg).pack(side='right', padx=6, pady=6)

        self.msg_entry.focus_set()
        self.append_chat(f"[СИСТЕМА] Ты вошёл на сервер '{name}'")
        if VOICE_OK: self.append_chat("[СИСТЕМА] P — микрофон")
        if CAM_OK: self.append_chat("[СИСТЕМА] O — камера")
        if self.webrtc:
            self.append_chat("[СИСТЕМА] I — демонстрация экрана (WebRTC, реальное время)")
        else:
            self.append_chat("[СИСТЕМА] I — демонстрация экрана (MQTT, с задержкой)")
            if WEBRTC_LIB_OK:
                self.append_chat("[СИСТЕМА] Включить WebRTC можно в Настройках")
        self.append_chat("[СИСТЕМА] F11 — во весь экран")
        self.refresh_online()
        self._refresh_screen_btn_label()

        self.root.bind_all('<KeyPress>', self._on_global_key)

    def _on_global_key(self, event):
        key = event.keysym.lower()
        if key == 'f11': self.toggle_fullscreen(); return
        try:
            if isinstance(event.widget, (tk.Entry, tk.Text)): return
        except Exception: pass
        if key == 'p': self.toggle_mic()
        elif key == 'o': self.toggle_camera()
        elif key == 'i': self.toggle_screen()

    def toggle_mic(self):
        if not VOICE_OK: messagebox.showwarning("Голос", "pip install sounddevice numpy"); return
        if not self.current_server: return
        enabled = self.voice.toggle()
        if getattr(self, 'mic_btn', None) and self.mic_btn.winfo_exists():
            if enabled: self.mic_btn.config(text="🎤 Mic: ON (P)", bg="#43a047")
            else: self.mic_btn.config(text="🎤 Mic: OFF (P)", bg="#546e7a")

    def toggle_camera(self):
        if not CAM_OK: messagebox.showwarning("Камера", "pip install opencv-python"); return
        if not self.current_server: return
        running = self.camera.toggle()
        if getattr(self, 'cam_btn', None) and self.cam_btn.winfo_exists():
            if running: self.cam_btn.config(text="🎥 Cam: ON (O)", bg="#43a047")
            else: self.cam_btn.config(text="🎥 Cam: OFF (O)", bg="#546e7a")
        if not running:
            key = (self.username, 'cam')
            self.last_frames.pop(key, None); self.last_frame_ts.pop(key, None)
            if self.mqtt_connected and self.mqtt and self.my_video_topic:
                try: self.mqtt.publish(self.my_video_topic, b'', qos=0, retain=True)
                except Exception: pass
            self._rebuild_video_row()

    def toggle_screen(self):
        if not self.current_server: return

        if self.webrtc_enabled and WEBRTC_LIB_OK:
            if not self._ensure_webrtc_instance():
                self.append_chat("[СИСТЕМА] WebRTC недоступен, переключаюсь на MQTT")
            else:
                if self.mqtt_connected and self.mqtt and self.webrtc_signal_prefix:
                    try:
                        self.mqtt.subscribe(
                            f"{self.webrtc_signal_prefix}/{self.username}", qos=1)
                    except Exception: pass

        if self.webrtc:
            if self.webrtc.sending:
                self.webrtc.stop_screen()
                key = (self.username, 'screen')
                self.last_frames.pop(key, None); self.last_frame_ts.pop(key, None)
                self._rebuild_video_row()
                self.append_chat("[СИСТЕМА] WebRTC-трансляция экрана остановлена")
            else:
                res = self.profile.get('screen_res', '480p')
                if res not in WEBRTC_RESOLUTIONS: res = '480p'
                fps = int(self.profile.get('screen_fps', 30))
                ok = self.webrtc.start_screen(res, fps)
                if ok:
                    self.append_chat(
                        f"[СИСТЕМА] WebRTC-трансляция экрана: {res} @ {fps} fps (реальное время)")
                    self._webrtc_broadcast_offer()
            self._refresh_screen_btn_label()
            return

        if not PIL_OK or ImageGrab is None:
            messagebox.showwarning("Экран", "pip install pillow"); return
        self.screen.set_quality(self.profile.get('screen_res', '480p'),
                                self.profile.get('screen_fps', 30))
        running = self.screen.toggle()
        self._refresh_screen_btn_label()
        if not running:
            key = (self.username, 'screen')
            self.last_frames.pop(key, None); self.last_frame_ts.pop(key, None)
            if self.mqtt_connected and self.mqtt and self.my_screen_topic:
                try: self.mqtt.publish(self.my_screen_topic, b'', qos=0, retain=True)
                except Exception: pass
            self._rebuild_video_row()
        else:
            res = self.profile.get('screen_res', '480p')
            fps = self.profile.get('screen_fps', 30)
            self.append_chat(f"[СИСТЕМА] MQTT-трансляция экрана: {res} @ {fps} fps")

    def append_chat(self, text):
        if not getattr(self, 'chat', None) or not self.chat.winfo_exists(): return
        self.chat.config(state='normal'); self.chat.insert('end', text + "\n")
        self.chat.see('end'); self.chat.config(state='disabled')

    def send_msg(self):
        if not self.mqtt_connected or not self.chat_topic or not self.mqtt: return
        t = self.msg_entry.get().strip()
        if not t: return
        self.msg_entry.delete(0, 'end')
        try:
            self.mqtt.publish(self.chat_topic, json.dumps({
                'type': 'chat', 'user': self.username, 'text': t, 'ts': time.time()
            }), qos=1)
        except Exception as e: self.append_chat(f"[СИСТЕМА] Ошибка: {e}")

    def leave_current(self):
        try: self.camera.stop()
        except Exception: pass
        try: self.screen.stop()
        except Exception: pass

        self._destroy_webrtc_instance()
        self.webrtc_signal_prefix = None
        self.my_webrtc_signal_topic = None

        try:
            if self.mqtt_connected and self.mqtt:
                for tp in (self.my_video_topic, self.my_screen_topic):
                    if tp:
                        try: self.mqtt.publish(tp, b'', qos=0, retain=True)
                        except Exception: pass
                if self.chat_topic:
                    self.mqtt.publish(self.chat_topic, json.dumps({
                        'type': 'leave', 'user': self.username, 'ts': time.time()
                    }), qos=1)
                if self.my_heartbeat_topic:
                    self.mqtt.publish(self.my_heartbeat_topic, b'', qos=1, retain=True)
                if self.my_avatar_topic:
                    self.mqtt.publish(self.my_avatar_topic, b'', qos=1, retain=True)
                if self.hosting_topic and self.current_server:
                    try:
                        self.mqtt.publish(self.hosting_topic, json.dumps({
                            'name': self.current_server,
                            'host': self.username,
                            'online': False,
                            'online_users': 0,
                            'ts': time.time()
                        }), qos=1, retain=True)
                    except Exception: pass
                if self.chat_topic:
                    for t in (self.chat_topic, self.users_topic + "/+",
                              self.voice_topic_prefix + "/+", self.avatar_topic_prefix + "/+",
                              self.video_topic_prefix + "/+", self.screen_topic_prefix + "/+"):
                        try: self.mqtt.unsubscribe(t)
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
            self._video_render_job = None

        self.current_server = None
        self.chat_topic = None; self.users_topic = None
        self.voice_topic_prefix = None; self.avatar_topic_prefix = None
        self.video_topic_prefix = None; self.screen_topic_prefix = None
        self.my_voice_topic = None; self.my_avatar_topic = None
        self.my_video_topic = None; self.my_screen_topic = None
        self.my_heartbeat_topic = None; self.hosting_topic = None
        self.is_host = False; self.online = {}
        self.user_avatars = {}; self.user_speaking = {}; self.avatar_widgets = {}
        self.last_frames = {}; self.last_frame_ts = {}; self.video_widgets = {}

    def leave_chat(self): self.leave_current(); self.show_menu()

    def on_close(self):
        # сессию НЕ трогаем — при следующем запуске автовход сработает
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