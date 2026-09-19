"""
WebRTC screen sharing для PyBlox.
Установка: pip install aiortc av

Один экземпляр WebRTCScreen на приложение. Умеет:
  - Отправлять свой экран всем пеерам в комнате (P2P)
  - Принимать видео от нескольких пееров одновременно
  - Автоматически переключаться на TURN, если P2P не работает

Сигналинг (offer/answer/ice) идёт через MQTT (функция send_signal).
"""
import asyncio
import threading
import time
import numpy as np
from PIL import Image, ImageGrab
import av
from aiortc import (
    RTCPeerConnection, RTCSessionDescription, RTCConfiguration,
    RTCIceServer, VideoStreamTrack, RTCIceCandidate,
)

WEBRTC_AVAILABLE = True

# Пресеты качества (W, H, fps)
RESOLUTIONS = {
    "144p":  (256, 144, 15),
    "360p":  (640, 360, 30),
    "480p":  (854, 480, 30),
    "720p":  (1280, 720, 30),
}

# Публичные STUN/TURN серверы
ICE_SERVERS = [
    RTCIceServer(urls="stun:stun.l.google.com:19302"),
    RTCIceServer(urls="stun:stun1.l.google.com:19302"),
    RTCIceServer(urls="stun:stun.cloudflare.com:3478"),
    # Бесплатный TURN — спасёт при симметричном NAT (частая ситуация в РФ)
    RTCIceServer(
        urls="turn:openrelay.metered.ca:80",
        username="openrelayproject",
        credential="openrelayproject",
    ),
    RTCIceServer(
        urls="turn:openrelay.metered.ca:443",
        username="openrelayproject",
        credential="openrelayproject",
    ),
    RTCIceServer(
        urls="turn:openrelay.metered.ca:443?transport=tcp",
        username="openrelayproject",
        credential="openrelayproject",
    ),
]


class ScreenVideoTrack(VideoStreamTrack):
    """Захватывает экран и отдаёт кадры как VP8 видео."""
    kind = "video"

    def __init__(self, quality=(854, 480), fps=30, scale_mode="fit"):
        super().__init__()
        self.w, self.h = quality[0], quality[1]
        self.fps = fps
        self.scale_mode = scale_mode
        self._interval = 1.0 / fps
        self._last = 0.0
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    async def recv(self):
        if self._stop_flag:
            # отдаём чёрный кадр, чтобы трек корректно завершился
            blank = np.zeros((self.h, self.w, 3), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(blank, format='rgb24')
            pts, time_base = await self.next_timestamp()
            frame.pts = pts
            frame.time_base = time_base
            return frame

        pts, time_base = await self.next_timestamp()

        # троттлинг до целевого fps
        now = time.time()
        wait = self._interval - (now - self._last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last = time.time()

        try:
            img = ImageGrab.grab()
            img = img.resize((self.w, self.h), Image.LANCZOS)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            arr = np.array(img)
            frame = av.VideoFrame.from_ndarray(arr, format='rgb24')
        except Exception as e:
            print(f"[WebRTC/Screen] grab error: {e}")
            blank = np.zeros((self.h, self.w, 3), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(blank, format='rgb24')

        frame.pts = pts
        frame.time_base = time_base
        return frame


class WebRTCScreen:
    """
    Управляет peer connections для screen share.

    my_id              — мой ник
    send_signal(tgt,msg) — функция, публикующая сигналинг в MQTT-топик tgt
    on_remote_frame(peer_id, pil_image) — пришёл кадр от пира
    on_peer_state(peer_id, state) — изменение состояния соединения
    """
    def __init__(self, my_id, send_signal, on_remote_frame, on_peer_state=None):
        self.my_id = my_id
        self.send_signal = send_signal
        self.on_remote_frame = on_remote_frame
        self.on_peer_state = on_peer_state or (lambda *a: None)

        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.pcs = {}          # peer_id -> RTCPeerConnection
        self.sending = False   # я транслирую свой экран?
        self.quality_name = "480p"
        self.fps = 30
        self._local_track = None
        self._lock = threading.Lock()

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    # ---------- СТАРТ/СТОП СВОЕГО ЭКРАНА ----------
    def start_screen(self, quality_name="480p", fps=30):
        if quality_name not in RESOLUTIONS:
            quality_name = "480p"
        w, h, _ = RESOLUTIONS[quality_name]
        # переопределяем fps вручную если задан
        self.quality_name = quality_name
        self.fps = int(fps)
        self.sending = True
        self._local_track = ScreenVideoTrack((w, h), self.fps)
        return True

    def stop_screen(self):
        self.sending = False
        if self._local_track:
            try: self._local_track.stop()
            except Exception: pass
            self._local_track = None
        # закрываем все pc, где мы были офферором
        for peer in list(self.pcs.keys()):
            self._submit(self._close_peer(peer))

    def set_quality(self, quality_name, fps):
        """Меняет качество. Если стрим идёт — перезапускает трек."""
        if quality_name not in RESOLUTIONS:
            return
        self.quality_name = quality_name
        self.fps = int(fps)
        if self.sending:
            # перезапуск: гасим трек и отправляем новые офферы всем
            old_peers = list(self.pcs.keys())
            self.stop_screen()
            self.start_screen(quality_name, fps)
            for peer in old_peers:
                self._submit(self._create_offer(peer))

    # ---------- ОТПРАВКА ПРЕДЛОЖЕНИЙ ----------
    def offer_to(self, peer_id):
        """Послать offer конкретному пиру."""
        self._submit(self._create_offer(peer_id))

    def offer_to_all(self, peer_ids):
        for p in peer_ids:
            self._submit(self._create_offer(p))

    async def _create_offer(self, peer_id):
        if not self.sending or not self._local_track:
            return
        try:
            await self._close_peer(peer_id)
            pc = self._make_pc(peer_id)
            pc.addTrack(self._local_track)
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            self.send_signal(peer_id, {
                'type': 'offer',
                'sdp': pc.localDescription.sdp,
                'sdpType': pc.localDescription.type,
                'from': self.my_id,
            })
        except Exception as e:
            print(f"[WebRTC] offer error → {peer_id}: {e}")

    # ---------- ОБРАБОТКА ВХОДЯЩИХ СИГНАЛОВ ----------
    def handle_offer(self, peer_id, sdp, sdp_type):
        self._submit(self._handle_offer(peer_id, sdp, sdp_type))

    async def _handle_offer(self, peer_id, sdp, sdp_type):
        try:
            await self._close_peer(peer_id)
            pc = self._make_pc(peer_id)
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=sdp, type=sdp_type))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            self.send_signal(peer_id, {
                'type': 'answer',
                'sdp': pc.localDescription.sdp,
                'sdpType': pc.localDescription.type,
                'from': self.my_id,
            })
        except Exception as e:
            print(f"[WebRTC] handle_offer error from {peer_id}: {e}")

    def handle_answer(self, peer_id, sdp, sdp_type):
        self._submit(self._handle_answer(peer_id, sdp, sdp_type))

    async def _handle_answer(self, peer_id, sdp, sdp_type):
        pc = self.pcs.get(peer_id)
        if not pc: return
        try:
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=sdp, type=sdp_type))
        except Exception as e:
            print(f"[WebRTC] handle_answer error: {e}")

    def handle_ice(self, peer_id, cand):
        self._submit(self._handle_ice(peer_id, cand))

    async def _handle_ice(self, peer_id, c):
        pc = self.pcs.get(peer_id)
        if not pc: return
        try:
            ic = RTCIceCandidate(
                component=c.get('component', 1),
                foundation=c.get('foundation', ''),
                ip=c.get('ip', ''),
                port=int(c.get('port', 0)),
                priority=int(c.get('priority', 0)),
                protocol=c.get('protocol', 'udp'),
                type=c.get('type', 'host'),
                sdpMid=c.get('sdpMid'),
                sdpMLineIndex=c.get('sdpMLineIndex'),
            )
            await pc.addIceCandidate(ic)
        except Exception as e:
            print(f"[WebRTC] handle_ice error: {e}")

    # ---------- PEER CONNECTION ----------
    def _make_pc(self, peer_id):
        config = RTCConfiguration(iceServers=ICE_SERVERS)
        pc = RTCPeerConnection(configuration=config)
        self.pcs[peer_id] = pc

        @pc.on("icecandidate")
        def on_ice(candidate):
            if candidate:
                try:
                    self.send_signal(peer_id, {
                        'type': 'ice',
                        'candidate': {
                            'component': candidate.component,
                            'foundation': candidate.foundation,
                            'ip': candidate.ip,
                            'port': candidate.port,
                            'priority': candidate.priority,
                            'protocol': candidate.protocol,
                            'type': candidate.type,
                            'sdpMid': candidate.sdpMid,
                            'sdpMLineIndex': candidate.sdpMLineIndex,
                        },
                        'from': self.my_id,
                    })
                except Exception as e:
                    print(f"[WebRTC] ice send error: {e}")

        @pc.on("track")
        def on_track(track):
            if track.kind == "video":
                self._submit(self._consume_video(peer_id, track))

        @pc.on("connectionstatechange")
        async def on_state():
            state = pc.connectionState
            print(f"[WebRTC] peer {peer_id}: {state}")
            try: self.on_peer_state(peer_id, state)
            except Exception: pass
            if state in ("failed", "closed", "disconnected"):
                await self._close_peer(peer_id)

        return pc

    async def _consume_video(self, peer_id, track):
        """Читает кадры из входящего трека и отдаёт их в коллбэк."""
        while True:
            try:
                frame = await track.recv()
            except Exception as e:
                print(f"[WebRTC] consume error ({peer_id}): {e}")
                break
            try:
                img = frame.to_image()
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                try:
                    self.on_remote_frame(peer_id, img)
                except Exception as e:
                    print(f"[WebRTC] frame cb error: {e}")
            except Exception as e:
                print(f"[WebRTC] frame convert: {e}")

    async def _close_peer(self, peer_id):
        pc = self.pcs.pop(peer_id, None)
        if pc:
            try: await pc.close()
            except Exception: pass

    def close_peer(self, peer_id):
        self._submit(self._close_peer(peer_id))

    def close_all(self):
        for p in list(self.pcs.keys()):
            self._submit(self._close_peer(p))

    def shutdown(self):
        self.stop_screen()
        self.close_all()
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            pass