"""PyBlox — управление своими плейсами. Запуск: python deleter.py [username]"""
import os, sys, json, time, ssl, threading, subprocess
import tkinter as tk
from tkinter import messagebox

PLACES_DIR = 'places'
PLACES_TOPIC = "pyblox/v11/places"
BROKER, BROKER_PORT, BROKER_PATH = "broker.emqx.io", 8084, "/mqtt"


def load_json(p, d):
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f: return json.load(f)
        except Exception: pass
    return d


def get_session_user():
    s = load_json('session.json', {})
    return s.get('user')


username = sys.argv[1] if len(sys.argv) > 1 else (get_session_user() or "guest")


def mqtt_delete(place_id):
    """Убирает retained-топик плейса из брокера — он исчезнет у всех."""
    def run():
        try:
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                print("[Deleter] pip install paho-mqtt")
                return
            try:
                c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, transport="websockets",
                                client_id="del-" + str(int(time.time()*1000) % 1000000))
            except (AttributeError, TypeError):
                c = mqtt.Client(transport="websockets",
                                client_id="del-" + str(int(time.time()*1000) % 1000000))
            c.ws_set_options(path=BROKER_PATH)
            c.tls_set(cert_reqs=ssl.CERT_NONE)
            c.tls_insecure_set(True)
            c.connect(BROKER, BROKER_PORT, keepalive=10)
            c.loop_start()
            time.sleep(1.0)
            c.publish(f"{PLACES_TOPIC}/{place_id}", b"", qos=1, retain=True)
            time.sleep(1.0)
            try: c.loop_stop(); c.disconnect()
            except Exception: pass
            print(f"[Deleter] {place_id} — удалён из сети")
        except Exception as e:
            print(f"[Deleter] MQTT error: {e}")
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(4.0)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"PyBlox Studio — Мои плейсы ({username})")
        self.root.geometry("680x540")
        self.root.configure(bg="#1a1f2a")

        top = tk.Frame(self.root, bg="#0f131a")
        top.pack(fill='x')
        tk.Label(top, text="  📚 Мои плейсы", bg="#0f131a", fg="#ffd93d",
                 font=("Arial", 15, "bold")).pack(side='left', pady=8)
        tk.Button(top, text="⟳ Обновить", bg="#3a4a5c", fg="white", bd=0,
                  font=("Arial", 10, "bold"),
                  command=self.reload).pack(side='right', padx=6, pady=6)
        tk.Button(top, text="🗑 Удалить все мои", bg="#c62828", fg="white", bd=0,
                  font=("Arial", 10, "bold"),
                  command=self.delete_all_mine).pack(side='right', padx=6, pady=6)

        body = tk.Frame(self.root, bg="#1a1f2a")
        body.pack(fill='both', expand=True)
        self.cvs = tk.Canvas(body, bg="#1a1f2a", highlightthickness=0)
        scr = tk.Scrollbar(body, orient='vertical', command=self.cvs.yview)
        self.cvs.configure(yscrollcommand=scr.set)
        scr.pack(side='right', fill='y')
        self.cvs.pack(side='left', fill='both', expand=True)
        self.inner = tk.Frame(self.cvs, bg="#1a1f2a")
        self.cvs.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>',
                        lambda e: self.cvs.configure(scrollregion=self.cvs.bbox('all')))

        self.status = tk.Label(self.root, text="", bg="#1a1f2a", fg="#888",
                                font=("Arial", 9), anchor='w')
        self.status.pack(fill='x', pady=(0, 4))

        self.reload()

    def reload(self):
        for w in self.inner.winfo_children():
            w.destroy()

        if not os.path.isdir(PLACES_DIR):
            tk.Label(self.inner, text="Папка places/ не найдена",
                     bg="#1a1f2a", fg="#c62828", font=("Arial", 11)).pack(pady=20)
            self.status.config(text="0 плейсов"); return

        files = sorted(
            [f for f in os.listdir(PLACES_DIR) if f.endswith('.json')],
            key=lambda f: -os.path.getmtime(os.path.join(PLACES_DIR, f)))

        if not files:
            tk.Label(self.inner, text="Нет сохранённых плейсов",
                     bg="#1a1f2a", fg="#888", font=("Arial", 11)).pack(pady=20)
            self.status.config(text="0 плейсов"); return

        for fname in files:
            path = os.path.join(PLACES_DIR, fname)
            data = load_json(path, {})
            self._render_row(path, fname, data)

        self.status.config(text=f"Найдено плейсов: {len(files)}")

    def _render_row(self, path, fname, data):
        is_mine = (data.get('author') == username)
        bg = "#243041" if is_mine else "#2a2525"

        row = tk.Frame(self.inner, bg=bg, bd=1, relief='solid')
        row.pack(fill='x', padx=8, pady=4)

        left = tk.Frame(row, bg=bg)
        left.pack(side='left', fill='both', expand=True, padx=10, pady=8)

        title_row = tk.Frame(left, bg=bg); title_row.pack(anchor='w')
        tk.Label(title_row, text=data.get('name', 'Untitled'),
                 bg=bg, fg="white", font=("Arial", 12, "bold")).pack(side='left')
        if is_mine:
            tk.Label(title_row, text="  (мой)", bg=bg, fg="#4caf50",
                     font=("Arial", 9, "italic")).pack(side='left')

        n = len(data.get('blocks', []))
        info = f"автор: {data.get('author','?')}  •  блоков: {n}  "
        info += f"•  макс: {data.get('max_players',15)}  •  {fname}"
        tk.Label(left, text=info, bg=bg, fg="#9e9e9e",
                 font=("Arial", 8), anchor='w').pack(anchor='w')

        right = tk.Frame(row, bg=bg); right.pack(side='right', padx=10, pady=8)

        tk.Button(right, text="📂 Открыть в Studio",
                  bg="#3a4a5c", fg="white", bd=0, font=("Arial", 9, "bold"),
                  command=lambda p=path: self.open_in_studio(p)
                  ).pack(side='top', fill='x', pady=2)

        if is_mine:
            tk.Button(right, text="🗑 Удалить",
                      bg="#c62828", fg="white", bd=0, font=("Arial", 9, "bold"),
                      command=lambda p=path, f=fname, d=data: self.delete_one(p, f, d)
                      ).pack(side='top', fill='x', pady=2)
        else:
            tk.Label(right, text="(чужой)", bg=bg, fg="#777",
                     font=("Arial", 8)).pack()

    def open_in_studio(self, path):
        studio = os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio.py")
        if not os.path.exists(studio):
            messagebox.showerror("Ошибка", f"studio.py не найден:\n{studio}"); return
        exe = sys.executable
        if os.name == "nt":
            cand = exe.replace("python.exe", "pythonw.exe")
            if os.path.exists(cand): exe = cand
        try:
            subprocess.Popen([exe, studio, "--load", path])
            self.status.config(text=f"Открываю Studio: {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def delete_one(self, path, fname, data):
        if not messagebox.askyesno("Удалить плейс?",
                f"Удалить «{data.get('name','?')}»\n\n"
                f"Локальный файл: удалится.\n"
                f"Из сети: {'ДА (автор — ты)' if data.get('author')==username else 'НЕТ (чужой)'}\n\n"
                f"Продолжить?"):
            return
        try:
            os.remove(path)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e)); return

        pid = data.get('id')
        if pid and data.get('author') == username:
            self.status.config(text=f"Убираю из сети: {pid}...")
            self.root.update()
            mqtt_delete(pid)

        self.reload()

    def delete_all_mine(self):
        mine = []
        if os.path.isdir(PLACES_DIR):
            for f in os.listdir(PLACES_DIR):
                if not f.endswith('.json'): continue
                path = os.path.join(PLACES_DIR, f)
                d = load_json(path, {})
                if d.get('author') == username:
                    mine.append((path, f, d))
        if not mine:
            messagebox.showinfo("Нет моих плейсов",
                                "В places/ нет плейсов с твоим ником")
            return
        if not messagebox.askyesno("Удалить все мои?",
                f"Найдено: {len(mine)} твоих плейсов.\n"
                f"Они исчезнут у всех игроков.\n\nПродолжить?"):
            return
        for path, f, d in mine:
            try: os.remove(path)
            except Exception: pass
            pid = d.get('id')
            if pid:
                self.status.config(text=f"Убираю {pid}...")
                self.root.update()
                mqtt_delete(pid)
        messagebox.showinfo("Готово", f"Удалено: {len(mine)}")
        self.reload()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()