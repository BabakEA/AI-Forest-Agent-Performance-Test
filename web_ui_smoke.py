"""Optional Playwright E2E smoke test for an authorized, local Cipher web chat.

No secrets, chat transcripts, screenshots, cookies, or session state are saved.
The optional memory test uses only a synthetic nonce. It cannot prove that Redis
(rather than in-process memory) supplied the answer; correlate backend traces.
"""
from __future__ import annotations
import argparse
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def validate_config(c:dict):
    url=urlsplit(c.get('ui_url',''))
    if url.scheme not in ('http','https') or not url.hostname or url.username or url.password:
        raise ValueError('ui_url must be an http(s) URL without credentials')
    for key in ('input_selector','assistant_message_selector'):
        if not c.get(key) or 'REPLACE_WITH_' in c[key]:
            raise ValueError(f'Edit the actual CSS selector for {key} first')
    if c.get('memory_test') and not c.get('new_chat_selector'):
        raise ValueError('Cross-session memory checks require a new_chat_selector')
    timeout=int(c.get('timeout_ms',60000))
    if not 1000 <= timeout <= 120000:raise ValueError('timeout_ms must be 1000–120000')


def run_browser(c:dict) -> dict:
    from playwright.sync_api import sync_playwright
    validate_config(c)
    timeout=int(c.get('timeout_ms',60000))
    report={'target':'web-chat', 'status':'not_run', 'response_latency_ms':None,'memory_test':'disabled'}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=bool(c.get('headless',True)))
        try:
            page=browser.new_page()
            page.goto(c['ui_url'],wait_until='domcontentloaded',timeout=timeout)
            page.locator(c['input_selector']).first.wait_for(state='visible',timeout=timeout)
            def send(prompt:str):
                inp=page.locator(c['input_selector']).first
                inp.fill(prompt,timeout=timeout)
                if c.get('send_button_selector'):
                    page.locator(c['send_button_selector']).first.click(timeout=timeout)
                else:
                    inp.press('Enter',timeout=timeout)
            start=time.perf_counter()
            send(str(c.get('test_prompt','Reply exactly AI_FOREST_WEB_TEST_OK.')))
            page.locator(c['assistant_message_selector']).filter(has_text=str(c.get('expected_text','AI_FOREST_WEB_TEST_OK'))).last.wait_for(state='visible',timeout=timeout)
            report['response_latency_ms']=round(1000*(time.perf_counter()-start),2)
            report['status']='passed'
            if c.get('memory_test'):
                marker='AURA_SYNTHETIC_'+uuid.uuid4().hex[:10]
                send('For this authorized test, remember this synthetic marker: '+marker+'. Reply ACK.')
                page.locator(c['assistant_message_selector']).filter(has_text='ACK').last.wait_for(state='visible',timeout=timeout)
                page.locator(c['new_chat_selector']).first.click(timeout=timeout)
                send('What was my most recent synthetic marker? Reply with only the marker.')
                page.locator(c['assistant_message_selector']).filter(has_text=marker).last.wait_for(state='visible',timeout=timeout)
                report['memory_test']='synthetic marker visible in a new chat; backend Redis persistence is UNVERIFIED'
            return report
        finally:
            browser.close()


def main():
    parser=argparse.ArgumentParser(description='Optional browser chat smoke test; requires playwright and explicit approval.')
    parser.add_argument('--config',default='examples/ai_forest_web_ui_optional.json')
    parser.add_argument('--ack-live',action='store_true')
    parser.add_argument('--check-config',action='store_true')
    parser.add_argument('--out',default='results/web-ui-smoke.json')
    args=parser.parse_args()
    c=json.loads(Path(args.config).read_text(encoding='utf-8'))
    validate_config(c)
    if args.check_config:
        print('Browser selectors/configuration are syntactically populated; no web traffic sent.')
        return
    if not args.ack_live:raise SystemExit('Explicit --ack-live required; no browser traffic sent.')
    result=run_browser(c)
    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
