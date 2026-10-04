"""Workspace-only Playwright acceptance; run using installed Python 3.11."""
from pathlib import Path
import json
import re
import sys
import urllib.request

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parents[1]/'.demo-tools'))
from playwright.sync_api import sync_playwright, expect

BASE='http://127.0.0.1:8878'
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def post(path,data):
    req=urllib.request.Request(BASE+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with opener.open(req,timeout=5) as r:return json.load(r)

with opener.open(BASE+'/api/manual/status',timeout=5) as response:
    manual_status=json.load(response)
assert manual_status['available'] and manual_status['bundled'] and manual_status['size']==69303713
with opener.open(BASE+'/api/v1/health',timeout=5) as response:
    assistant_health=json.load(response)
assert assistant_health['status']=='ready' and assistant_health['api_version']=='1.0'
with opener.open(BASE+'/api/v1/observation',timeout=5) as response:
    assistant_observation=json.load(response)
assert 'scene' not in assistant_observation and 'sources' not in assistant_observation
manual_request=urllib.request.Request(BASE+'/manual.pdf',headers={'Range':'bytes=0-7'})
with opener.open(manual_request,timeout=5) as response:
    assert response.status==206 and response.headers['Accept-Ranges']=='bytes'
    assert response.read()==b'%PDF-1.5'
with opener.open(BASE+'/manual-pages/208.png',timeout=5) as response:
    assert response.headers.get_content_type()=='image/png'
    assert response.read(8)==b'\x89PNG\r\n\x1a\n'

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    context=browser.new_context(viewport={'width':1600,'height':1060},device_scale_factor=1)
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:external.append(r.url) if r.url.startswith('http') and not r.url.startswith(BASE) else None)
    page.goto(BASE)
    expect(page.locator('#labVersion')).to_contain_text('已连接')
    page.locator('.network-node[data-device="SW2"]').dblclick()
    expect(page.locator('#prompt')).to_contain_text('SW2')
    node=page.locator('.network-node[data-device="PC2"]')
    bounds=node.bounding_box()
    start=page.evaluate('positions.PC2')
    page.mouse.move(bounds['x']+bounds['width']/2,bounds['y']+bounds['height']/2)
    page.mouse.down();page.mouse.move(bounds['x']+bounds['width']/2+25,bounds['y']+bounds['height']/2-10,steps=5);page.mouse.up()
    assert page.evaluate('positions.PC2')!=start,'node dragging'
    page.locator('#layoutBtn').click()

    def scene(code):
        with page.expect_response(lambda r:r.url==BASE+'/api/scene') as event:
            page.locator(f'[data-code="{code}"]').click()
        epoch=event.value.json()['epoch']
        page.wait_for_function('epoch => state?.epoch === epoch',arg=epoch)
        expect(page.locator('#sourcePages')).to_contain_text('PDF p.')

    def ask(first=False):
        with page.expect_response(lambda r:r.url==BASE+'/api/assistant') as event:
            page.locator('#diagnoseBtn' if first else '#verifyBtn').click()
        report=event.value.json()
        page.wait_for_function('id => lastReport?.id === id',arg=report['id'])
        expect(page.locator('#verifyBtn')).to_be_enabled()
        return report

    def command(device,text):
        page.locator(f'#terminalTabs [data-device="{device}"]').click()
        page.locator('#commandInput').fill(text)
        with page.expect_response(lambda r:r.url==BASE+'/api/command') as event:
            page.locator('#commandInput').press('Enter')
        data=event.value.json()
        expect(page.locator('#executeBtn')).to_be_enabled()
        return data

    for code in 'ABCD':
        scene(code)
        if code=='A':
            expect(page.locator('#sourcePages')).to_contain_text('208–209')
            expect(page.locator('#sourcePages')).to_contain_text('2455')
            page.locator('#sourceBtn').click()
            expect(page.locator('#modalBody')).to_contain_text('人为因素导致接口物理 DOWN')
            expect(page.locator('#modalBody')).to_contain_text('组合构造')
            expect(page.locator('#manualPageImage')).to_have_attribute('src','/manual-pages/208.png')
            expect(page.locator('.manual-page-note')).to_contain_text('原始 PDF 直接生成')
            page.get_by_role('button',name='下一页').click()
            expect(page.locator('#manualPageImage')).to_have_attribute('src','/manual-pages/209.png')
            page.screenshot(path=str(ROOT/'preview-manual.png'),full_page=True)
            page.locator('.manual-source-button').nth(1).click()
            expect(page.locator('#manualPageImage')).to_have_attribute('src','/manual-pages/2455.png')
            page.locator('#closeModal').click()
            page.locator('#challenge').check()
            expect(page.locator('#sourcePages')).not_to_contain_text('人为因素')
            expect(page.locator('#sourcePages')).to_contain_text('208–209')
            page.locator('#challenge').uncheck()
        first=ask(True)
        assert not first['passed']
        task=first['task']
        assert all(r['ok'] for r in command(task['device'],'\n'.join(task['commands']))['records'])
        second=ask()
        assert not second['passed'],code
        if code=='A':
            assert [r['passed'] for r in second['probe']['results']]==[True,False,False]
            page.screenshot(path=str(ROOT/'preview-progress.png'),full_page=True)
        task=second['task']
        assert all(r['ok'] for r in command(task['device'],'\n'.join(task['commands']))['records'])
        final=ask()
        assert final['passed'] and final['recovered'],code
    scene('E')
    first=ask(True);task=first['task']
    command(task['device'],'\n'.join(task['commands']))
    handoff=ask();assert handoff['task']['handoff'] and not handoff['passed']
    for d in ['SW2','SW3']:
        command(d,'return\nsystem-view\ninterface GE0/0/24\nundo shutdown\nreturn')
    assert not ask()['passed']
    page.screenshot(path=str(ROOT/'preview-handoff.png'),full_page=True)

    scene('A')
    before=post('/api/probe',{})
    result=command('SW1','system-view\ninterface GE0/0/2\nport default vlan 5000\nshutdown')
    assert result['skipped']==1 and not result['records'][-1]['ok']
    assert result['records'][-1]['prompt']=='[SW1-GigabitEthernet0/0/2] '
    assert post('/api/probe',{})['results']==before['results']
    # Terminal history and completion.
    page.locator('#commandInput').fill('')
    page.locator('#commandInput').press('ArrowUp')
    assert 'port default vlan 5000' in page.locator('#commandInput').input_value()
    page.locator('#commandInput').fill('display arp')
    page.locator('#commandInput').press('Tab')
    expect(page.locator('#commandInput')).to_have_value('display arp all')
    # Independent windows share config and not terminal view.
    separate=context.new_page();separate.goto(BASE+'/assistant')
    expect(separate.locator('#diagnoseBtn')).to_be_visible()
    separate.locator('#diagnoseBtn').click()
    expect(separate.locator('#chat h3').last).to_contain_text('接口')
    with separate.expect_popup() as opened:
        separate.get_by_role('button',name='打开 SW1 终端',exact=True).click()
    device_page=opened.value
    expect(device_page.locator('#prompt')).to_contain_text('SW1')
    device_page.close()
    separate.close()
    scene('A');page.reload();expect(page.locator('#labVersion')).to_contain_text('已连接')
    page.screenshot(path=str(ROOT/'preview.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'desktop overflow'
    device_half=context.new_page();device_half.set_viewport_size({'width':960,'height':1080});device_half.goto(BASE+'/device')
    expect(device_half.locator('#commandInput')).to_be_visible()
    expect(device_half.locator('#symptom')).to_be_visible()
    assert device_half.evaluate('document.documentElement.scrollWidth <= innerWidth'),'half-screen device horizontal overflow'
    assert device_half.evaluate('document.documentElement.scrollHeight <= innerHeight'),'half-screen device vertical overflow'
    device_half.screenshot(path=str(ROOT/'preview-device-legacy.png'),full_page=True);device_half.close()
    assistant_half=context.new_page();assistant_half.set_viewport_size({'width':960,'height':1080});assistant_half.goto(BASE+'/assistant')
    expect(assistant_half.locator('#chatInput')).to_be_visible()
    assert assistant_half.evaluate('document.documentElement.scrollWidth <= innerWidth'),'half-screen assistant horizontal overflow'
    assert assistant_half.evaluate('document.documentElement.scrollHeight <= innerHeight'),'half-screen assistant vertical overflow'
    assistant_half.screenshot(path=str(ROOT/'preview-assistant-legacy.png'),full_page=True);assistant_half.close()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'mobile overflow'
    page.screenshot(path=str(ROOT/'preview-mobile.png'),full_page=True)
    assert not errors,errors
    assert not external,external
    browser.close()
print('PASS: A-D multi-round CLI repairs; E handoff; batch error pause; history/Tab; shared windows; layout; no external requests/JS errors')
