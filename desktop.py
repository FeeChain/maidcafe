#!/usr/bin/env python3
"""Double-click desktop entry point. Resources are read-only, progress is per-user."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import traceback

from app_paths import ROOT, VERSION, configure_desktop


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--generate', help=argparse.SUPPRESS)
    parser.add_argument('--self-check', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--headless', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--smoke-test', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--speech-check', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    home = configure_desktop()
    if args.generate:
        import dialogue
        dialogue.generate(json.loads(args.generate))
        return
    if args.speech_check:
        import dialogue
        import ai_runtime
        files = dialogue.synthesize([{'speaker': 'Momo', 'text': 'Welcome to our cafe.'}], {}, str(home / 'speech-check'))
        (home / 'speech-check.json').write_text(json.dumps({'backend': ai_runtime.audio_backend(), 'files': files}), encoding='utf-8')
        return
    import server
    server.build_words()
    server.db().close()
    if args.self_check:
        result = json.dumps({'app': 'maidcafe', 'version': VERSION, 'words': len(server.WORDS),
                             'audio': len(server.AUDIO), 'data_dir': str(home)}, ensure_ascii=False)
        (home / 'self-check.json').write_text(result, encoding='utf-8')
        print(result)
        return
    # A free loopback port avoids collisions with the source edition or another app.
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    address = 'http://127.0.0.1:%d/' % httpd.server_port
    if args.headless:
        (home / 'server.json').write_text(json.dumps({'url': address}), encoding='utf-8')
        print(address, flush=True)
        try:
            httpd.serve_forever()
        finally:
            server.stop_generation()
            httpd.server_close()
        return
    import webview
    webview.settings['ALLOW_DOWNLOADS'] = True
    window = webview.create_window('maidcafe · 窗边的位置', address,
                                  width=1160, height=820, min_size=(620, 620),
                                  background_color='#f7f2e7', text_select=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    def smoke():
        # Own-app development QA only, never connects to an external browser.
        check = window.evaluate_js("({title: document.title, welcome: !!document.getElementById('vNew'), bridge: !!window.pywebview})")
        (home / 'native-smoke.json').write_text(json.dumps(check), encoding='utf-8')
        window.destroy()
    if args.smoke_test:
        window.events.loaded += smoke
    try:
        webview.start(gui='edgechromium' if sys.platform == 'win32' else None,
                      private_mode=False, storage_path=str(home / 'webview'))
    finally:
        server.stop_generation()
        httpd.shutdown()
        httpd.server_close()


if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        logdir = configure_desktop() / 'logs'
        # Windowed builds have no console. Keep errors available for support.
        if sys.stdout is None:
            sys.stdout = open(logdir / 'desktop.log', 'a', encoding='utf-8', buffering=1)
        if sys.stderr is None:
            sys.stderr = sys.stdout
    try:
        main()
    except Exception:
        traceback.print_exc()
        if not any(arg.startswith('--') for arg in sys.argv[1:]):
            message = ('maidcafe 暂时没能打开。学习记录仍保存在本机。\n\n'
                       '请查看数据目录里的 logs/desktop.log。\n'
                       'Windows 请确认已安装 Microsoft Edge WebView2 Runtime。')
            if sys.platform == 'win32':
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, message, 'maidcafe', 0x10)
            elif sys.platform == 'darwin':
                from AppKit import NSAlert
                alert = NSAlert.alloc().init()
                alert.setMessageText_('maidcafe 暂时没能打开')
                alert.setInformativeText_(message + '\n~/Library/Application Support/maidcafe/')
                alert.runModal()
        sys.exit(1)
