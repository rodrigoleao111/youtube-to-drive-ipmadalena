"""
player_window.py — Seleção de trecho via player YouTube.

Abre o vídeo em janela pywebview (Edge WebView2) com botões de marcação
sobrepostos. O painel de controles (CTkToplevel) fica ao lado com os campos
de tempo e os botões de confirmação.
"""

import threading

import customtkinter as ctk
import webview


# ---------------------------------------------------------------------------
# Bridge singleton — exposta ao JS como window.pywebview.api
# ---------------------------------------------------------------------------

class _Bridge:
    """
    Único objeto bridge por processo. O PlayerWindow registra seu callback
    via set_callback(); ao fechar, limpa com clear_callback().
    Os métodos são chamados da thread do webview — NÃO atualizar Tk diretamente.
    """
    def __init__(self):
        self._cb = None

    def set_callback(self, cb):
        self._cb = cb

    def clear_callback(self):
        self._cb = None

    # Chamados pelo JavaScript
    def on_player_ready(self):
        if self._cb:
            self._cb("ready", None)

    def on_time_result(self, seconds, target):
        if self._cb:
            self._cb("time", (float(seconds), str(target)))

    def on_player_error(self, code):
        if self._cb:
            self._cb("error", int(code))

    def on_window_closed(self):
        if self._cb:
            self._cb("closed", None)


_bridge   = _Bridge()
_wv_win   = None    # webview.Window atual
_wv_alive = False   # True enquanto webview.start() está rodando


def _webview_thread_fn(html: str, width: int, height: int, x: int, y: int):
    global _wv_win, _wv_alive
    _wv_win = webview.create_window(
        "IPMadalena — Player",
        html=html,
        js_api=_bridge,
        width=width,
        height=height,
        x=x,
        y=y,
        resizable=True,
        on_top=False,
        confirm_close=False,
    )
    # Notifica quando a janela for destruída pelo usuário
    _wv_win.events.closed += _bridge.on_window_closed
    _wv_alive = True
    webview.start(gui="edgechromium")
    # webview.start() retorna quando todas as janelas forem fechadas
    _wv_alive = False
    _bridge.clear_callback()


def _open_webview(html: str, width: int, height: int, x: int, y: int):
    """Abre o webview ou recarrega com novo HTML se já estiver vivo."""
    global _wv_alive
    if _wv_alive and _wv_win is not None:
        try:
            _wv_win.load_html(html)
            return
        except Exception:
            pass  # janela foi fechada, recria
    threading.Thread(
        target=_webview_thread_fn,
        args=(html, width, height, x, y),
        daemon=True,
    ).start()


def _close_webview():
    """Destrói a janela do webview programaticamente."""
    if _wv_alive and _wv_win is not None:
        try:
            _wv_win.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Utilitários de tempo
# ---------------------------------------------------------------------------

def _seconds_to_hms(seconds: float) -> str:
    """1234.0 → '00:20:34'"""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _hms_to_seconds(hms: str):
    """'00:20:34' → 1234.0 — retorna None se inválido."""
    parts = hms.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        if not (0 <= m < 60 and 0 <= s < 60):
            return None
        return float(h * 3600 + m * 60 + s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# HTML do player (constante — sem arquivo externo para funcionar no bundle)
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0f0f0f; overflow: hidden; font-family: sans-serif; }
  #player-wrap { width: 100vw; height: 100vh; position: relative; }
  #player { width: 100%; height: 100%; }
  #overlay {
    position: absolute;
    bottom: 0; left: 0; right: 0;
    padding: 10px 16px;
    background: linear-gradient(transparent, rgba(0,0,0,0.88));
    display: flex;
    gap: 12px;
    align-items: center;
    justify-content: center;
  }
  .mark-btn {
    background: rgba(255,255,255,0.14);
    border: 1.5px solid rgba(255,255,255,0.45);
    color: #fff;
    font-size: 13px;
    font-weight: bold;
    padding: 8px 20px;
    border-radius: 6px;
    cursor: pointer;
    backdrop-filter: blur(4px);
    transition: background 0.15s;
  }
  .mark-btn:hover  { background: rgba(255,255,255,0.28); }
  .mark-btn:active { background: rgba(255,255,255,0.40); }
  .mark-btn:disabled { opacity: 0.35; cursor: default; }
  #status-lbl {
    color: rgba(255,255,255,0.65);
    font-size: 12px;
    min-width: 180px;
    text-align: center;
  }
</style>
</head>
<body>
<div id="player-wrap">
  <div id="player"></div>
  <div id="overlay">
    <button class="mark-btn" id="btn-start" onclick="markTime('start')" disabled>
      &#9654; Marcar In&iacute;cio
    </button>
    <span id="status-lbl">Carregando player...</span>
    <button class="mark-btn" id="btn-end" onclick="markTime('end')" disabled>
      &#9632; Marcar Fim
    </button>
  </div>
</div>

<script>
var player;

// Carrega a YouTube IFrame API
var tag = document.createElement('script');
tag.src = 'https://www.youtube.com/iframe_api';
document.head.appendChild(tag);

function onYouTubeIframeAPIReady() {
  player = new YT.Player('player', {
    videoId: '{{VIDEO_ID}}',
    playerVars: { autoplay: 0, controls: 1, rel: 0, modestbranding: 1 },
    events: {
      onReady: function() {
        document.getElementById('btn-start').disabled = false;
        document.getElementById('btn-end').disabled  = false;
        document.getElementById('status-lbl').textContent = 'Player pronto';
        withBridge(function(api) { api.on_player_ready(); });
      },
      onError: function(e) {
        document.getElementById('status-lbl').textContent = 'Erro no player (' + e.data + ')';
        withBridge(function(api) { api.on_player_error(e.data); });
      }
    }
  });
}

function markTime(target) {
  var t = (player && player.getCurrentTime) ? player.getCurrentTime() : 0;
  var label = (target === 'start') ? 'In\u00edcio: ' : 'Fim: ';
  document.getElementById('status-lbl').textContent = label + toHMS(t);
  withBridge(function(api) { api.on_time_result(t, target); });
}

function toHMS(s) {
  var h   = Math.floor(s / 3600);
  var m   = Math.floor((s % 3600) / 60);
  var sec = Math.floor(s % 60);
  return (h < 10 ? '0' : '') + h + ':'
       + (m < 10 ? '0' : '') + m + ':'
       + (sec < 10 ? '0' : '') + sec;
}

// Chama o bridge com retry caso ainda não esteja injetado
function withBridge(fn) {
  if (window.pywebview && window.pywebview.api) {
    fn(window.pywebview.api);
  } else {
    setTimeout(function() { withBridge(fn); }, 100);
  }
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# PlayerWindow
# ---------------------------------------------------------------------------

class PlayerWindow(ctk.CTkToplevel):
    """
    Painel de controles lateral ao player YouTube.

    Parâmetros
    ----------
    master      : janela pai (App)
    videos      : list[{id, title, upload_date}]
    on_complete : callback(segments: list[{id, title, start, end}])
                  start/end são strings "HH:MM:SS" ou None (vídeo completo)
    on_cancel   : callback()
    """

    _CTRL_W = 380
    _CTRL_H = 500
    _PLAY_W = 860
    _PLAY_H = 580

    def __init__(self, master, videos: list, on_complete, on_cancel):
        super().__init__(master)
        self.title("Seleção de Trecho")
        self.geometry(f"{self._CTRL_W}x{self._CTRL_H}")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._videos      = videos
        self._on_complete = on_complete
        self._on_cancel   = on_cancel
        self._idx         = 0
        self._segments    = []

        _bridge.set_callback(self._on_bridge_event)

        self._build_ui()
        self._load_video(0)

    # -----------------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------------

    def _build_ui(self):
        # Título e contador
        self._title_lbl = ctk.CTkLabel(
            self, font=ctk.CTkFont(size=13, weight="bold"),
            wraplength=340, justify="left", anchor="w",
        )
        self._title_lbl.pack(anchor="w", padx=20, pady=(16, 2))

        self._counter_lbl = ctk.CTkLabel(
            self, font=ctk.CTkFont(size=11), text_color="gray", anchor="w",
        )
        self._counter_lbl.pack(anchor="w", padx=20, pady=(0, 6))

        ctk.CTkFrame(self, height=1, fg_color=("gray78", "gray28")).pack(
            fill="x", padx=16, pady=(0, 10)
        )

        # Status do player
        self._status_lbl = ctk.CTkLabel(
            self, text="⏳ Abrindo player...",
            font=ctk.CTkFont(size=11), text_color="gray", anchor="w",
        )
        self._status_lbl.pack(anchor="w", padx=20, pady=(0, 12))

        # Campos de tempo
        fields = ctk.CTkFrame(self, fg_color="transparent")
        fields.pack(fill="x", padx=20, pady=(0, 4))
        fields.columnconfigure(1, weight=1)

        for row_i, (label_text, var_attr, btn_attr, target) in enumerate([
            ("Início:", "_start_var", "_btn_start", "start"),
            ("Fim:",    "_end_var",   "_btn_end",   "end"),
        ]):
            ctk.CTkLabel(
                fields, text=label_text,
                font=ctk.CTkFont(size=12), width=52, anchor="e",
            ).grid(row=row_i, column=0, padx=(0, 8), pady=6, sticky="e")

            var = ctk.StringVar(value="00:00:00")
            setattr(self, var_attr, var)
            var.trace_add("write", lambda *_: self._update_duration())

            ctk.CTkEntry(
                fields, textvariable=var,
                width=100, font=ctk.CTkFont(size=13),
            ).grid(row=row_i, column=1, pady=6, sticky="w")

            btn = ctk.CTkButton(
                fields, text="◀ Marcar", width=88, state="disabled",
                command=lambda t=target: self._request_mark(t),
            )
            btn.grid(row=row_i, column=2, padx=(8, 0), pady=6)
            setattr(self, btn_attr, btn)

        # Duração calculada
        dur_row = ctk.CTkFrame(self, fg_color="transparent")
        dur_row.pack(fill="x", padx=20, pady=(2, 14))
        ctk.CTkLabel(
            dur_row, text="Duração:", font=ctk.CTkFont(size=12), width=52, anchor="e",
        ).pack(side="left")
        self._dur_lbl = ctk.CTkLabel(
            dur_row, text="--:--:--",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self._dur_lbl.pack(side="left", padx=8)

        # Aviso de precisão
        ctk.CTkLabel(
            self,
            text="⚠ Precisão ±2 s em transmissões ao vivo (corte no keyframe mais próximo).",
            font=ctk.CTkFont(size=10), text_color="gray",
            wraplength=340, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 6))

        # Feedback de erro
        self._err_lbl = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11),
            text_color="#e05252", anchor="w",
        )
        self._err_lbl.pack(anchor="w", padx=20, pady=(0, 8))

        ctk.CTkFrame(self, height=1, fg_color=("gray78", "gray28")).pack(
            fill="x", padx=16, pady=(0, 12)
        )

        # Botões de ação
        self._confirm_btn = ctk.CTkButton(
            self,
            text="Confirmar trecho →",
            font=ctk.CTkFont(size=13, weight="bold"),
            state="disabled",
            command=self._confirm,
        )
        self._confirm_btn.pack(fill="x", padx=20, pady=(0, 8))

        self._full_btn = ctk.CTkButton(
            self,
            text="Usar vídeo completo",
            fg_color=("gray75", "gray30"), hover_color=("gray65", "gray25"),
            state="disabled",
            command=self._use_full,
        )
        self._full_btn.pack(fill="x", padx=20, pady=(0, 8))

        ctk.CTkButton(
            self,
            text="Cancelar",
            fg_color="transparent",
            border_width=1,
            text_color=("gray40", "gray70"),
            hover_color=("gray85", "gray20"),
            command=self._cancel,
        ).pack(fill="x", padx=20, pady=(0, 14))

    # -----------------------------------------------------------------------
    # Carregamento de vídeo
    # -----------------------------------------------------------------------

    def _load_video(self, idx: int):
        video = self._videos[idx]
        total = len(self._videos)

        self._title_lbl.configure(text=video["title"])
        self._counter_lbl.configure(text=f"Vídeo {idx + 1} de {total}")
        self._status_lbl.configure(text="⏳ Carregando player...", text_color="gray")
        self._err_lbl.configure(text="")
        self._start_var.set("00:00:00")
        self._end_var.set("00:00:00")
        self._btn_start.configure(state="disabled")
        self._btn_end.configure(state="disabled")
        self._confirm_btn.configure(state="disabled")
        self._full_btn.configure(state="disabled")
        self._update_duration()

        html = _HTML_TEMPLATE.replace("{{VIDEO_ID}}", video["id"])
        px, py = self._calc_player_pos()
        _open_webview(html, self._PLAY_W, self._PLAY_H, px, py)

    def _calc_player_pos(self):
        """Posiciona player à esquerda e controles à direita, centralizados."""
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        total_w = self._PLAY_W + 12 + self._CTRL_W
        base_x  = max(0, (sw - total_w) // 2)
        base_y  = max(0, (sh - self._PLAY_H) // 2)
        ctrl_x  = base_x + self._PLAY_W + 12
        ctrl_y  = base_y + (self._PLAY_H - self._CTRL_H) // 2
        self.geometry(f"{self._CTRL_W}x{self._CTRL_H}+{ctrl_x}+{ctrl_y}")
        return base_x, base_y

    # -----------------------------------------------------------------------
    # Bridge callback (recebido da thread do webview)
    # -----------------------------------------------------------------------

    def _on_bridge_event(self, kind: str, data):
        """Despacha para a thread Tk via after()."""
        self.after(0, lambda: self._handle_bridge(kind, data))

    def _handle_bridge(self, kind: str, data):
        if kind == "ready":
            self._status_lbl.configure(text="✓ Player pronto — assista e marque os tempos.",
                                        text_color="#2fa84f")
            self._btn_start.configure(state="normal")
            self._btn_end.configure(state="normal")
            self._confirm_btn.configure(state="normal")
            self._full_btn.configure(state="normal")

        elif kind == "time":
            seconds, target = data
            hms = _seconds_to_hms(seconds)
            if target == "start":
                self._start_var.set(hms)
            else:
                self._end_var.set(hms)

        elif kind == "error":
            self._status_lbl.configure(
                text="⚠ Erro no player — insira os tempos manualmente.",
                text_color="#e0a020",
            )
            self._confirm_btn.configure(state="normal")
            self._full_btn.configure(state="normal")

        elif kind == "closed":
            self._status_lbl.configure(
                text="⚠ Player fechado — insira os tempos manualmente.",
                text_color="#e0a020",
            )
            self._confirm_btn.configure(state="normal")
            self._full_btn.configure(state="normal")

    # -----------------------------------------------------------------------
    # Ações do usuário
    # -----------------------------------------------------------------------

    def _request_mark(self, target: str):
        """Chama markTime() no JS do player."""
        if _wv_alive and _wv_win is not None:
            try:
                _wv_win.evaluate_js(f"markTime('{target}')")
            except Exception:
                pass

    def _update_duration(self):
        start_s = _hms_to_seconds(self._start_var.get())
        end_s   = _hms_to_seconds(self._end_var.get())
        if start_s is not None and end_s is not None and end_s > start_s:
            self._dur_lbl.configure(text=_seconds_to_hms(end_s - start_s))
        else:
            self._dur_lbl.configure(text="--:--:--")

    def _confirm(self):
        start_str = self._start_var.get().strip()
        end_str   = self._end_var.get().strip()
        start_s   = _hms_to_seconds(start_str)
        end_s     = _hms_to_seconds(end_str)
        if start_s is None or end_s is None:
            self._err_lbl.configure(text="Tempo inválido. Use o formato HH:MM:SS.")
            return
        if end_s <= start_s:
            self._err_lbl.configure(text="O tempo de fim deve ser maior que o início.")
            return
        self._save_segment(start_str, end_str)
        self._advance()

    def _use_full(self):
        self._save_segment(None, None)
        self._advance()

    def _save_segment(self, start, end):
        v = self._videos[self._idx]
        self._segments.append({
            "id":    v["id"],
            "title": v["title"],
            "start": start,
            "end":   end,
        })

    def _advance(self):
        self._idx += 1
        if self._idx >= len(self._videos):
            self._finish()
        else:
            self._load_video(self._idx)

    def _finish(self):
        _close_webview()
        _bridge.clear_callback()
        self.grab_release()
        self.destroy()
        self._on_complete(self._segments)

    def _cancel(self):
        _close_webview()
        _bridge.clear_callback()
        self.grab_release()
        self.destroy()
        self._on_cancel()
