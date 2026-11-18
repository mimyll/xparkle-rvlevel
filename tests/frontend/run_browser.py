"""Finite standalone browser fixture; synthetic state/actions and no radio."""
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
import json
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[2]

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT)))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as browser:
            chrome=browser.chromium.launch(headless=True)
            page=chrome.new_page(viewport={'width':900,'height':1000})
            page.goto(f'http://127.0.0.1:{server.server_port}/tests/frontend/fixture.html')
            page.wait_for_function("document.title.startsWith('PASS') || document.title.startsWith('FAIL')",timeout=45000)
            result=page.locator('#results').inner_text();print(result)
            assert json.loads(result)['status']=='PASS'
            chrome.close()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
