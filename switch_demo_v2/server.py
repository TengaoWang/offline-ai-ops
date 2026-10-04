"""Run with Python 3.10+, standard library only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import os
import random
import re
import sys
import threading
import webbrowser
from engine import Lab, DEVICES, SCENES

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
BUNDLED_MANUAL=ROOT/'assets'/'华为S系列园区交换机维护宝典.pdf'
MANUAL_PAGES=ROOT/'assets'/'manual-pages'
MANUAL_PATH=Path(os.environ.get('SWITCH_DEMO_MANUAL',str(BUNDLED_MANUAL)))
LAB=Lab()
LOCK=threading.RLock()


def assistant_observation():
    """Return evidence available to an external assistant, without scenario answers."""
    snapshot=LAB.snapshot()
    return {'api_version':'1.0','epoch':snapshot['epoch'],'revision':snapshot['revision'],
            'symptom':snapshot['brief'],'devices':list(DEVICES),'links':snapshot['links'],
            'last_probe':snapshot['probe']}


def assistant_health():
    return {'api_version':'1.0','service':'fieldnote-switch-simulator','status':'ready',
            'transport':'loopback','epoch':LAB.epoch,'revision':LAB.revision,
            'devices':list(DEVICES),'capabilities':['observation','context','command','probe','logs','diagnose','repair']}


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_): pass

    def send(self,value,status=200):
        body=json.dumps(value,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers();self.wfile.write(body)

    def manual_status(self):
        available=MANUAL_PATH.is_file()
        return {'available':available,'filename':MANUAL_PATH.name,
                'bundled':available and MANUAL_PATH.resolve()==BUNDLED_MANUAL.resolve(),
                'size':MANUAL_PATH.stat().st_size if available else None,
                'message':None if available else '未找到随程序打包的手册原件。请检查 switch_demo_v2/assets/，或用 SWITCH_DEMO_MANUAL 指定 PDF 路径。'}

    def send_manual(self,head_only=False):
        if not MANUAL_PATH.is_file():
            self.send({'error':self.manual_status()['message']},404);return
        size=MANUAL_PATH.stat().st_size;start,end=0,size-1;status=200
        requested=self.headers.get('Range')
        if requested:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested.strip())
            if not match:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
            left,right=match.groups()
            if not left:
                length=int(right or 0);start=max(0,size-length)
            else:start=int(left)
            if right:end=min(size-1,int(right))
            if start>end or start>=size:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
            status=206
        length=end-start+1
        self.send_response(status)
        self.send_header('Content-Type','application/pdf')
        self.send_header('Content-Disposition','inline; filename="huawei-s-series-maintenance-manual.pdf"')
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Cache-Control','private, max-age=3600')
        self.send_header('Content-Length',str(length))
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        if head_only:return
        try:
            with MANUAL_PATH.open('rb') as source:
                source.seek(start);remaining=length
                while remaining:
                    chunk=source.read(min(1024*1024,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
        except (BrokenPipeError,ConnectionResetError):
            pass

    def send_manual_page(self,path):
        match=re.fullmatch(r'/manual-pages/(\d+)\.png',path)
        if not match:
            self.send({'error':'页面不存在'},404);return
        page_path=MANUAL_PAGES/f'{int(match.group(1))}.png'
        if not page_path.is_file():
            self.send({'error':'该引用页预览未打包'},404);return
        data=page_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type','image/png')
        self.send_header('Cache-Control','private, max-age=3600')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers();self.wfile.write(data)

    def do_GET(self):
        path=self.path.split('?',1)[0]
        if path=='/api/v1/health':
            with LOCK:self.send(assistant_health())
            return
        if path=='/api/v1/observation':
            with LOCK:self.send(assistant_observation())
            return
        if path=='/api/v1/logs':
            with LOCK:self.send({'api_version':'1.0','epoch':LAB.epoch,'revision':LAB.revision,
                                 'logs':list(LAB.logs[-100:])})
            return
        if self.path=='/api/state':
            with LOCK:self.send(LAB.snapshot())
            return
        if self.path=='/api/scenes':self.send(SCENES);return
        if path=='/api/manual/status':self.send(self.manual_status());return
        if path=='/manual.pdf':self.send_manual();return
        if path.startswith('/manual-pages/'):self.send_manual_page(path);return
        filename={'/':'index.html','/device':'index.html','/assistant':'index.html','/app.js':'app.js','/style.css':'style.css','/legacy.css':'legacy.css'}.get(path)
        if not filename:self.send({'error':'页面不存在'},404);return
        data=(ROOT/filename).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',{'html':'text/html','js':'text/javascript','css':'text/css'}[filename.rsplit('.',1)[1]]+'; charset=utf-8')
        self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)))
        self.end_headers();self.wfile.write(data)

    def do_HEAD(self):
        if self.path.split('?',1)[0]=='/manual.pdf':self.send_manual(head_only=True);return
        self.send_response(404);self.end_headers()

    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and origin!=f'http://{self.headers.get("Host")}':self.send({'error':'只接受本机同源请求'},403);return
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<32768:raise ValueError('请求长度不正确。')
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):raise ValueError('请求应为 JSON 对象。')
            with LOCK:
                if self.path=='/api/v1/context':
                    device=data.get('device');session=data.get('session')
                    if device not in DEVICES or not isinstance(session,str) or not 1<=len(session)<=100:
                        raise ValueError('设备或会话标识不正确。')
                    ctx=LAB.context(session,device)
                    self.send({'api_version':'1.0','device':device,'prompt':LAB.prompt(device,ctx),
                               'epoch':LAB.epoch,'revision':LAB.revision})
                elif self.path=='/api/v1/command':
                    if data.get('epoch')!=LAB.epoch:self.send({'error':'实验已切换，请重新读取 observation。'},409);return
                    device=data.get('device');session=data.get('session');command=data.get('command')
                    if device not in DEVICES or not isinstance(session,str) or not 1<=len(session)<=100:
                        raise ValueError('设备或会话标识不正确。')
                    if not isinstance(command,str):raise ValueError('命令应为文本。')
                    commands=[line.strip() for line in command.splitlines() if line.strip()]
                    if not commands or len(commands)>40:raise ValueError('每次输入 1～40 行命令。')
                    records=[]
                    for line in commands:
                        record=LAB.execute(device,line,session);records.append(record)
                        if not record['ok']:break
                    self.send({'api_version':'1.0','records':records,'skipped':len(commands)-len(records),
                               'observation':assistant_observation()})
                elif self.path=='/api/v1/probe':
                    if data and set(data)!={'epoch'}:raise ValueError('probe 只接受当前实验编号。')
                    if data.get('epoch')!=LAB.epoch:self.send({'error':'实验已切换，请重新读取 observation。'},409);return
                    self.send({'api_version':'1.0','probe':LAB.probe()})
                elif self.path=='/api/v1/diagnose':
                    if data.get('epoch')!=LAB.epoch:self.send({'error':'实验已切换，请重新读取 observation。'},409);return
                    self.send({'api_version':'1.0','diagnosis':LAB.external_diagnosis()})
                elif self.path=='/api/v1/repair':
                    if data.get('epoch')!=LAB.epoch:self.send({'error':'实验已切换，请重新读取 observation。'},409);return
                    self.send({'api_version':'1.0','repair':LAB.auto_repair(data.get('session','offline-assistant'),data.get('expected'))})
                elif self.path=='/api/scene':
                    code=data.get('code');code=random.choice(list(SCENES)) if code=='random' else code
                    LAB.reset(code);self.send(LAB.snapshot())
                elif self.path=='/api/command':
                    if data.get('epoch')!=LAB.epoch:self.send({'error':'实验已切换，请等待终端同步后重试。'},409);return
                    device=data.get('device');session=data.get('session')
                    if device not in DEVICES or not isinstance(session,str) or len(session)>100:raise ValueError('设备或终端标识不正确。')
                    command=data.get('command')
                    if not isinstance(command,str):raise ValueError('命令应为文本。')
                    commands=[line.strip() for line in command.splitlines() if line.strip()]
                    if not commands or len(commands)>40:raise ValueError('每次输入 1～40 行命令。')
                    records=[]
                    for line in commands:
                        r=LAB.execute(device,line,session);records.append(r)
                        if not r['ok']:break
                    self.send({'records':records,'skipped':len(commands)-len(records),'state':LAB.snapshot()})
                elif self.path=='/api/context':
                    device=data.get('device');session=data.get('session')
                    if not isinstance(session,str) or len(session)>100:raise ValueError('终端标识不正确。')
                    ctx=LAB.context(session,device)
                    self.send({'prompt':LAB.prompt(device,ctx),'epoch':LAB.epoch})
                elif self.path=='/api/probe':self.send(LAB.probe())
                elif self.path=='/api/assistant':
                    before=data.get('before')
                    if before is not None and not isinstance(before,str):raise ValueError('报告编号不正确。')
                    self.send(LAB.assistant(before))
                else:self.send({'error':'接口不存在'},404)
        except (ValueError,TypeError,KeyError) as e:self.send({'error':str(e)},400)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8878);p.add_argument('--open',action='store_true');args=p.parse_args()
    print(f'Fieldnote lab v2: http://127.0.0.1:{args.port}',flush=True)
    if args.open:threading.Timer(0.8,webbrowser.open,args=(f'http://127.0.0.1:{args.port}',)).start()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.daemon_threads=True
    server.serve_forever()
