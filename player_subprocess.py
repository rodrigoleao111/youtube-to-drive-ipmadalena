#!/usr/bin/env python3
"""
player_subprocess.py — Subprocesso do player YouTube.

Carrega a página completa do YouTube (sem embed) para evitar erros de
restrição de incorporação (ex: erro 153).  Roda webview.start() na thread
principal deste processo (isolado do Tkinter).

Protocolo stdout -> pai:
  {"type": "ready"}
  {"type": "mark",  "target": "start"|"end", "seconds": <float>}
  {"type": "error", "code": <int>}
  {"type": "closed"}

Protocolo stdin <- pai:
  {"cmd": "load",     "video_id": "..."}  -> navega para outro vídeo
  {"cmd": "get_time", "target": "..."}    -> captura currentTime e envia mark
  {"cmd": "eval",     "js": "..."}        -> executa JS arbitrário
  {"cmd": "quit"}                          -> fecha e encerra
"""

import json
import sys
import threading

import webview


# ---------------------------------------------------------------------------
# JS injetado após carregamento da página para adicionar botões de marcação
# ---------------------------------------------------------------------------

_OVERLAY_JS = r"""
(function() {
  if (document.getElementById('_ipm_ov')) return;

  function tryInject() {
    var v = document.querySelector('video');
    if (!v || !document.body) { setTimeout(tryInject, 700); return; }

    var d = document.createElement('div');
    d.id = '_ipm_ov';
    d.style.cssText = [
      'position:fixed',
      'bottom:88px',
      'left:0', 'right:0',
      'display:flex',
      'justify-content:center',
      'gap:14px',
      'z-index:2147483647',
      'pointer-events:none'
    ].join(';');

    function mkBtn(label, tgt) {
      var b = document.createElement('button');
      b.textContent = label;
      b.style.cssText = [
        'pointer-events:auto',
        'background:rgba(10,10,10,0.80)',
        'color:#fff',
        'border:2px solid rgba(255,255,255,0.65)',
        'padding:9px 24px',
        'border-radius:7px',
        'font-size:13px',
        'font-weight:bold',
        'cursor:pointer',
        'transition:background 0.12s'
      ].join(';');
      b.onmouseenter = function() { this.style.background = 'rgba(40,40,40,0.95)'; };
      b.onmouseleave = function() { this.style.background = 'rgba(10,10,10,0.80)'; };
      b.onclick = function() {
        var vid = document.querySelector('video');
        var t   = vid ? vid.currentTime : 0;
        if (window.pywebview && window.pywebview.api) {
          window.pywebview.api.on_time_result(t, tgt);
        }
      };
      return b;
    }

    d.appendChild(mkBtn('\u25b6 Marcar In\u00edcio', 'start'));
    d.appendChild(mkBtn('\u25a0 Marcar Fim',         'end'));
    document.body.appendChild(d);
  }

  setTimeout(tryInject, 1000);
})();
"""


# ---------------------------------------------------------------------------
# Bridge (métodos chamados pelo JS)
# ---------------------------------------------------------------------------

class _Bridge:
    def on_player_ready(self):
        _send({"type": "ready"})

    def on_time_result(self, seconds, target):
        _send({"type": "mark", "target": str(target), "seconds": float(seconds)})

    def on_player_error(self, code):
        _send({"type": "error", "code": int(code)})

    def on_window_closed(self):
        _send({"type": "closed"})


def _send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _yt_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# ---------------------------------------------------------------------------
# Estado global do processo
# ---------------------------------------------------------------------------

_win_ref = None
_bridge  = _Bridge()


# ---------------------------------------------------------------------------
# Handlers de eventos da janela
# ---------------------------------------------------------------------------

def _on_loaded():
    """Chamado quando a página termina de carregar — injeta overlay."""
    if _win_ref:
        try:
            _win_ref.evaluate_js(_OVERLAY_JS)
        except Exception:
            pass
    # Notifica o pai que o player está pronto (sem IFrame API, dispara aqui)
    _send({"type": "ready"})


# ---------------------------------------------------------------------------
# Thread de leitura de stdin (recebe comandos do processo pai)
# ---------------------------------------------------------------------------

def _stdin_reader():
    global _win_ref
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            cmd = json.loads(raw)
            action = cmd.get("cmd")

            if action == "load" and _win_ref:
                _win_ref.load_url(_yt_url(cmd["video_id"]))

            elif action == "get_time" and _win_ref:
                target = cmd.get("target", "start")
                try:
                    t = _win_ref.evaluate_js(
                        "(function(){"
                        "var v=document.querySelector('video');"
                        "return v?v.currentTime:0;"
                        "})()"
                    )
                    _send({"type": "mark", "target": target,
                           "seconds": float(t or 0)})
                except Exception:
                    _send({"type": "mark", "target": target, "seconds": 0.0})

            elif action == "eval" and _win_ref:
                try:
                    _win_ref.evaluate_js(cmd.get("js", ""))
                except Exception:
                    pass

            elif action == "quit" and _win_ref:
                try:
                    _win_ref.destroy()
                except Exception:
                    pass
                break

        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _win_ref

    args = sys.argv[1:]
    if not args:
        sys.exit(1)

    video_id = args[0]
    x        = int(args[1]) if len(args) > 1 else 100
    y        = int(args[2]) if len(args) > 2 else 100
    width    = int(args[3]) if len(args) > 3 else 860
    height   = int(args[4]) if len(args) > 4 else 480

    _win_ref = webview.create_window(
        "IPMadalena \u2014 Player",
        url=_yt_url(video_id),
        js_api=_bridge,
        width=width,
        height=height,
        x=x,
        y=y,
        resizable=True,
        confirm_close=False,
    )
    _win_ref.events.closed  += _bridge.on_window_closed
    _win_ref.events.loaded  += _on_loaded

    threading.Thread(target=_stdin_reader, daemon=True).start()

    webview.start(gui="edgechromium")


if __name__ == "__main__":
    main()
