"""PyBlox — HTTP-файловый сервер для отправки файлов ссылкой."""
import os, json, time, socket, hashlib, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote, quote

MAX_FILE = 250 * 1024 * 1024


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]; s.close(); return ip
    except Exception:
        return '127.0.0.1'


def file_port(username):
    """Стабильный порт по нику — чтобы перезапуск не менял адрес."""
    h = int(hashlib.md5(('files_' + username).encode()).hexdigest(), 16)
    return 8700 + (h % 200)


class FileServerHandler(BaseHTTPRequestHandler):
    upload_dir = ''

    def log_message(self, fmt, *args): pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith('/file/'):
            name = os.path.basename(unquote(path[len('/file/'):]))
            fp = os.path.join(FileServerHandler.upload_dir, name)
            if not os.path.exists(fp):
                self.send_error(404); return
            size = os.path.getsize(fp)
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(size))
            self.send_header('Content-Disposition', f'attachment; filename="{name}"')
            self.end_headers()
            try:
                with open(fp, 'rb') as f:
                    while True:
                        c = f.read(64 * 1024)
                        if not c: break
                        self.wfile.write(c)
            except (BrokenPipeError, ConnectionResetError): pass
            return
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if not path.startswith('/upload/'):
            self.send_error(404); return
        name = os.path.basename(unquote(path[len('/upload/'):]))
        if not name:
            self.send_error(400); return
        try: length = int(self.headers.get('Content-Length', 0))
        except Exception: length = 0
        if length <= 0 or length > MAX_FILE:
            self.send_error(413); return
        os.makedirs(FileServerHandler.upload_dir, exist_ok=True)
        fp = os.path.join(FileServerHandler.upload_dir, name)
        received = 0
        try:
            with open(fp, 'wb') as f:
                while received < length:
                    c = self.rfile.read(min(64 * 1024, length - received))
                    if not c: break
                    f.write(c); received += len(c)
        except Exception: return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        body = json.dumps({'ok': True, 'name': name, 'size': received}).encode()
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FileServer:
    def __init__(self, username, base_dir='server_files'):
        self.username = username
        self.port = file_port(username)
        self.dir = os.path.join(base_dir, username)
        os.makedirs(self.dir, exist_ok=True)
        self.httpd = None
        self.thread = None
        self.lan_ip = get_lan_ip()
        self.running = False

    def start(self):
        if self.running: return
        FileServerHandler.upload_dir = self.dir
        try:
            self.httpd = ThreadingHTTPServer(('0.0.0.0', self.port), FileServerHandler)
        except Exception as e:
            print(f"[FileServer] bind {self.port}: {e}")
            self.httpd = None; return
        self.running = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        print(f"[FileServer] {self.lan_ip}:{self.port}")

    def stop(self):
        self.running = False
        try:
            if self.httpd: self.httpd.shutdown()
        except Exception: pass
        self.httpd = None

    def base_url(self):
        return f"http://{self.lan_ip}:{self.port}"

    def file_url(self, name):
        return f"{self.base_url()}/file/{quote(name)}"


def upload_file(url_base, filepath, timeout=600):
    import urllib.request
    try:
        name = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        if size > MAX_FILE:
            return False, f"Файл > {MAX_FILE//1024//1024} МБ"
        with open(filepath, 'rb') as f:
            data = f.read()
        url = f"{url_base}/upload/{quote(name)}"
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/octet-stream')
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return False, str(e)