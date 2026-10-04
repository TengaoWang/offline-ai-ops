"""Bounded network behavior and VRP-style command interpreter, never host shell."""
from collections import deque
from copy import deepcopy
from datetime import datetime
import ipaddress as ip
import re
import uuid

DEVICES = ['PC1', 'PC2', 'SW1', 'SW2', 'SW3', 'SERVER']
MACS = {'PC1':'00e0-1000-0010', 'PC2':'00e0-1000-0011', 'SW1':'00e0-1000-0001',
        'SW2':'00e0-fc12-3456', 'SW3':'00e0-fc65-4321', 'SERVER':'00e0-3000-0010'}
LINKS = [('PC1','eth0','SW1','1'), ('PC2','eth0','SW1','2'),
         ('SW1','24','SW2','1'), ('SW2','24','SW3','24'), ('SW3','1','SERVER','eth0')]
SCENES = {
 'A': {'title':'只诊断 · 接口与上联异常', 'brief':'PC1 无法与同事电脑、网关及业务服务器通信。',
       'sources':[{'section':'§8.2.1 人为因素导致接口物理 DOWN','pdf_pages':'208–209','printed_pages':'130–131','basis':'接口显示 Administratively down 时，应检查人为 shutdown 并使用 undo shutdown 恢复。'},
                  {'section':'§22.53.3.2 VLAN 的划分（Trunk 接口）','pdf_pages':'2455','printed_pages':'2377','basis':'Trunk 接口需要通过 allow-pass 配置允许业务 VLAN 通过。'}]},
 'B': {'title':'只诊断 · 接入口 VLAN 错误', 'brief':'调整接入配置后，办公电脑访问业务异常。',
       'sources':[{'section':'§15.2.2 检查配置是否正确','pdf_pages':'957–958','printed_pages':'879–880','basis':'排查两端接口类型、VLAN 配置及 VLANIF 地址是否一致。'},
                  {'section':'§22.53.3.2 VLAN 的划分（Access 接口）','pdf_pages':'2454','printed_pages':'2376','basis':'Access 接口通过 port default vlan 加入指定 VLAN。'}]},
 'C': {'title':'自动修复 · 去程与回程路由', 'brief':'办公网关可以访问，业务服务器没有响应。',
       'sources':[{'section':'§15.2.4 检查路由是否正常','pdf_pages':'959–960','printed_pages':'881–882','basis':'使用路由表检查目的网段的路由、出接口和下一跳。'},
                  {'section':'§21.7.4.14 VLAN 间互访不通怎么办','pdf_pages':'1600–1601','printed_pages':'1522–1523','basis':'跨三层交换机互访要求两端均存在相应路由表项。'}]},
 'D': {'title':'自动修复 · 静态 ARP 绑定', 'brief':'更换设备后，链路亮着，但跨网段业务不通。',
       'sources':[{'section':'§15.3.2 错误的静态 ARP 表项导致直连设备两端不能 Ping 通','pdf_pages':'971–972','printed_pages':'893–894','basis':'设备更换后，如果静态 IP/MAC 绑定未同步刷新，可能造成通信失败。'}]},
 'E': {'title':'转人工 · 物理链路无信号', 'brief':'维护窗口结束后，办公区仍无法访问服务器。',
       'sources':[{'section':'§15.2.3 检查物理链路状态是否正常','pdf_pages':'958–959','printed_pages':'880–881','basis':'接口与 VLANIF 异常时，需要检查连接、网线、光纤、模块及接口状态。'},
                  {'section':'§15.2.4 检查路由是否正常','pdf_pages':'959–960','printed_pages':'881–882','basis':'物理问题之外，还需要独立核对目的网段及回程路由。'}]},
}

def ge(n): return f'GigabitEthernet0/0/{n}'
def network(addr): return ip.ip_interface(addr).network
def port(mode='access', vlan=10, allowed=None):
    return {'admin':True,'mode':mode,'pvid':vlan,'allowed':allowed or [vlan]}


class Lab:
    def __init__(self): self.reset('A')

    def reset(self, scene=None):
        if scene is not None and scene not in SCENES: raise ValueError('未知实验场景。')
        self.epoch = str(uuid.uuid4()); self.revision = 0; self.scene = scene
        self.sessions = {}; self.logs = []; self.reports = {}; self.last_probe = None
        self.physical_fault = False
        self.switches = {
            'SW1': {'ports':{'1':port(), '2':port(), '24':port('trunk',1,[1,10,20])},
                    'vlans':[1,10,20,30,99], 'svis':{}, 'routes':[], 'arp':{}},
            'SW2': {'ports':{'1':port('trunk',1,[1,10,20]), '2':port('access',20), '24':port('access',99)},
                    'vlans':[1,10,20,30,99], 'svis':{10:{'address':'192.168.10.1/24','admin':True},99:{'address':'192.168.99.1/24','admin':True}},
                    'routes':[{'prefix':'192.168.30.0/24','via':'192.168.99.2'}], 'arp':{'192.168.99.2':MACS['SW3']}},
            'SW3': {'ports':{'1':port('access',30), '2':port('access',30), '24':port('access',99)},
                    'vlans':[1,10,20,30,99], 'svis':{30:{'address':'192.168.30.1/24','admin':True},99:{'address':'192.168.99.2/24','admin':True}},
                    'routes':[{'prefix':'192.168.10.0/24','via':'192.168.99.1'}], 'arp':{'192.168.99.1':MACS['SW2']}},
        }
        self.hosts = {'PC1':{'address':'192.168.10.10/24','gateway':'192.168.10.1'},
                      'PC2':{'address':'192.168.10.11/24','gateway':'192.168.10.1'},
                      'SERVER':{'address':'192.168.30.10/24','gateway':'192.168.30.1'}}
        if scene == 'A':
            self.switches['SW1']['ports']['1']['admin'] = False
            self.switches['SW1']['ports']['24']['allowed'] = [1,20]
        elif scene == 'B':
            self.switches['SW1']['ports']['1']['pvid'] = 20
            self.switches['SW3']['ports']['1']['pvid'] = 20
        elif scene == 'C':
            self.switches['SW2']['routes'] = []
            self.switches['SW3']['routes'][0]['via'] = '192.168.99.254'
        elif scene == 'D':
            self.switches['SW2']['arp']['192.168.99.2'] = '00e0-0000-0002'
            self.switches['SW3']['arp']['192.168.99.1'] = '00e0-0000-0001'
        elif scene == 'E':
            self.physical_fault = True
            self.switches['SW3']['routes'] = []
        self.log('实验控制', '启动新的实验；设备与终端视图已初始化。', False)

    def log(self, device, text, mutation=False):
        if mutation: self.revision += 1
        self.logs.append({'time':datetime.now().strftime('%H:%M:%S'), 'device':device,
                          'text':text,'mutation':mutation,'revision':self.revision})
        self.logs = self.logs[-200:]

    def link_up(self, link):
        a,pa,b,pb=link
        if {a,b} == {'SW2','SW3'} and self.physical_fault: return False
        return all(d not in self.switches or self.switches[d]['ports'][p]['admin'] for d,p in [(a,pa),(b,pb)])

    def iface_up(self, device, num):
        return any(self.link_up(l) for l in LINKS if (device,num) in [(l[0],l[1]),(l[2],l[3])])

    def carries(self, device, num, vlan):
        if device not in self.switches: return True
        sw=self.switches[device]; p=sw['ports'][num]
        return p['admin'] and vlan in sw['vlans'] and (p['pvid']==vlan if p['mode']=='access' else vlan in p['allowed'])

    def svi_up(self, device, vlan):
        sw=self.switches[device]; s=sw['svis'].get(vlan)
        return bool(s and s['admin'] and vlan in sw['vlans'] and any(self.iface_up(device,n) and self.carries(device,n,vlan) for n in sw['ports']))

    def l2(self, start, end, vlan):
        queue=deque([(start,[start])]); seen={start}
        while queue:
            node,path=queue.popleft()
            if node==end: return path
            for a,pa,b,pb in LINKS:
                if node not in (a,b) or not self.link_up((a,pa,b,pb)): continue
                other=b if node==a else a
                # Both ports must carry this VLAN with compatible on-wire tagging.
                if not self.carries(a,pa,vlan) or not self.carries(b,pb,vlan): continue
                def tagged(d,p):
                    if d not in self.switches: return False
                    cfg=self.switches[d]['ports'][p]
                    return cfg['mode']=='trunk' and cfg['pvid']!=vlan
                if tagged(a,pa)!=tagged(b,pb): continue
                if other in seen: continue
                seen.add(other)
                if other in self.hosts and other!=end: continue
                queue.append((other,path+[other]))
        return None

    def addresses(self, device, active=True):
        if device in self.hosts:
            h=self.hosts[device]; link=next(l for l in LINKS if device in (l[0],l[2]))
            sw,num=(link[2],link[3]) if link[0]==device else (link[0],link[1])
            return [(h['address'],self.switches[sw]['ports'][num]['pvid'])]
        return [(s['address'],v) for v,s in self.switches[device]['svis'].items() if not active or self.svi_up(device,v)]

    def owner(self, address):
        for d in DEVICES:
            for addr,v in self.addresses(d,False):
                if str(ip.ip_interface(addr).ip)==address: return d,v
        return None,None

    def direct(self, device, target):
        addr=ip.ip_address(target)
        return next(((a,v) for a,v in self.addresses(device) if addr in network(a)),None)

    def route(self, device, target):
        direct=self.direct(device,target)
        if direct: return target,direct[1]
        if device in self.hosts:
            h=self.hosts[device]; return h['gateway'],self.addresses(device)[0][1]
        candidates=sorted([r for r in self.switches[device]['routes'] if ip.ip_address(target) in ip.ip_network(r['prefix'])],
                          key=lambda r:ip.ip_network(r['prefix']).prefixlen,reverse=True)
        for r in candidates:
            conn=self.direct(device,r['via'])
            if conn: return r['via'],conn[1]
        return None,None

    def forward(self, device, target):
        path=[device]; current=device; visited=set()
        for _ in range(12):
            owner,_=self.owner(target)
            if current==owner:
                return True,path,'目标已收到报文'
            if current in visited: return False,path,'路由循环'
            visited.add(current)
            nexthop,vlan=self.route(current,target)
            if not nexthop: return False,path,'没有有效的匹配路由或接口未就绪'
            peer,_=self.owner(nexthop)
            if peer is None: return False,path,'下一跳地址无法解析'
            physical=self.l2(current,peer,vlan)
            if not physical: return False,path,'下一跳不可达；需检查接口与 VLAN'
            if peer in self.switches and not any(str(ip.ip_interface(a).ip)==nexthop and v==vlan for a,v in self.addresses(peer)):
                return False,path,'对端三层接口未就绪'
            static=self.switches.get(current,{}).get('arp',{}).get(nexthop)
            if static and static!=MACS[peer]: return False,path,'地址解析与对端 MAC 不一致'
            path+=physical[1:];current=peer
        return False,path,'超过模拟跳数限制'

    def ping(self, device, target):
        ip.ip_address(target)
        forward,path,reason=self.forward(device,target)
        # Choose a source address corresponding to the first next hop, when possible.
        nh,vlan=self.route(device,target)
        addresses=self.addresses(device)
        source=next((str(ip.ip_interface(a).ip) for a,v in addresses if v==vlan),
                    str(ip.ip_interface(addresses[0][0]).ip) if addresses else None)
        backward=False; reverse=[]
        peer,_=self.owner(target)
        if forward and peer and source: backward,reverse,reason=self.forward(peer,source)
        passed=forward and backward
        return {'source':device,'target':target,'passed':passed,'sent':3,'received':3 if passed else 0,
                'forward':path,'reverse':reverse,'stage':'complete' if passed else 'return' if forward else 'request',
                'detail':reason}

    def preserved(self):
        checks=[]
        for d,n in [('SW1','24'),('SW2','1')]:
            if 20 not in self.switches[d]['ports'][n]['allowed']: checks.append(f'{d} {ge(n)} 需要保留 VLAN 20')
        for d,target,peer in [('SW2','192.168.99.2','SW3'),('SW3','192.168.99.1','SW2')]:
            if self.switches[d]['arp'].get(target)!=MACS[peer]: checks.append(f'{d} 需要保留 {target} 的正确静态 ARP 绑定')
        return checks

    def probe(self):
        results=[self.ping('PC1',t) for t in ['192.168.10.11','192.168.10.1','192.168.30.10']]
        issues=self.preserved()
        passed=all(r['passed'] for r in results) and not issues
        result={'epoch':self.epoch,'revision':self.revision,'results':results,'passed':passed,'requirements':issues,
                'status':'healthy' if passed else 'partial' if any(r['passed'] for r in results) else 'failed'}
        self.last_probe=result
        return deepcopy(result)

    def prompt(self, device, ctx):
        if device in self.hosts: return device+'> '
        if ctx['view']=='user': return '<'+device+'> '
        if ctx['view']=='system': return '['+device+'] '
        return '['+device+'-'+ctx['iface']+'] '

    def context(self, session, device):
        if device not in DEVICES: raise ValueError('设备不存在。')
        if len(self.sessions)>500: self.sessions.clear()
        return self.sessions.setdefault((session,device), {'view':'user','iface':None})

    def configuration(self, d, selected=None):
        sw=self.switches[d]; rows=[]
        for n,p in sw['ports'].items():
            if selected and selected!=ge(n): continue
            rows += ['#','interface '+ge(n),' port link-type '+p['mode']]
            if p['mode']=='access': rows.append(' port default vlan '+str(p['pvid']))
            else: rows.append(' port trunk allow-pass vlan '+' '.join(map(str,p['allowed'])))
            if not p['admin']: rows.append(' shutdown')
        for v,s in sw['svis'].items():
            if selected and selected!='Vlanif'+str(v): continue
            addr=ip.ip_interface(s['address']);rows+=['#','interface Vlanif'+str(v),f' ip address {addr.ip} {addr.network.netmask}']
            if not s['admin']: rows.append(' shutdown')
        if not selected:
            for r in sw['routes']: rows.append(f"ip route-static {r['prefix'].replace('/', ' ')} {r['via']}")
            for addr,mac in sw['arp'].items(): rows.append(f'arp static {addr} {mac} vid 99 interface GigabitEthernet 0/0/24')
        return '\n'.join(rows+['#'])

    def iface_name(self,text):
        m=re.fullmatch(r'(?:gigabitethernet|ge)\s*0/0/(1|2|24)',text,re.I)
        if m: return ge(m[1])
        m=re.fullmatch(r'vlanif\s*(\d+)',text,re.I)
        if m: return 'Vlanif'+str(int(m[1]))
        raise ValueError('本实验接口为 GE0/0/1、GE0/0/2、GE0/0/24 或已有 Vlanif。')

    def display(self,d,cmd,ctx):
        if d not in self.switches: raise ValueError('PC 终端使用 ipconfig、ping、help。')
        sw=self.switches[d]
        if cmd=='display version': return 'FIELDNOTE behavior simulator / Huawei-style CLI subset\n模拟设备，不运行真实 VRP 镜像。'
        if cmd in ('display current-configuration','display this'):
            return self.configuration(d,ctx['iface'] if cmd=='display this' and ctx['view']=='interface' else None)
        m=re.fullmatch('display current-configuration interface (.+)',cmd)
        if m:return self.configuration(d,self.iface_name(m[1]))
        if cmd=='display interface brief':
            rows=['Interface                       PHY                   Protocol']
            for n,p in sw['ports'].items():
                state='UP' if self.iface_up(d,n) else 'DOWN' if p['admin'] else '*DOWN'
                rows.append(f'{ge(n):32}{state:22}{"UP" if state=="UP" else "DOWN"}')
            return '\n'.join(rows+['*DOWN: administratively down'])
        if cmd.startswith('display interface '):
            name=self.iface_name(cmd[len('display interface '):])
            if name.startswith('Vlanif'):
                v=int(name[6:]); s=sw['svis'].get(v)
                if not s: raise ValueError('该 VLANIF 不存在。')
                state='UP' if self.svi_up(d,v) else 'DOWN' if s['admin'] else 'Administratively DOWN'
                return f'{name} current state : {state}\nLine protocol current state : {"UP" if state=="UP" else "DOWN"}\nInternet Address is {s["address"]}\nHardware address is {MACS[d]}'
            n=name.split('/')[-1];p=sw['ports'][n]
            state='UP' if self.iface_up(d,n) else 'DOWN' if p['admin'] else 'Administratively DOWN'
            signal='\nPhysical observation: receive signal absent (simulated)' if self.physical_fault and d in ('SW2','SW3') and n=='24' else ''
            return f'{name} current state : {state}\nLine protocol current state : {"UP" if state=="UP" else "DOWN"}\nLink-type : {p["mode"]}\nPVID : {p["pvid"]}\nHardware address is {MACS[d]}'+signal
        if cmd=='display ip interface brief':
            return 'Interface   IP Address/Mask          Physical Protocol\n'+'\n'.join(f'Vlanif{v:<5} {s["address"]:24} '+('UP       UP' if self.svi_up(d,v) else 'DOWN     DOWN') for v,s in sw['svis'].items())
        if cmd=='display port vlan' or cmd.startswith('display port vlan '):
            selected=self.iface_name(cmd[18:]) if cmd.startswith('display port vlan ') else None
            return 'Port                          Link Type PVID  Trunk VLAN List\n'+'\n'.join(f'{ge(n):30}{p["mode"]:10}{p["pvid"]:<6}'+(' '.join(map(str,p['allowed'])) if p['mode']=='trunk' else '-') for n,p in sw['ports'].items() if not selected or selected==ge(n))
        if cmd in ('display vlan','display vlan summary'):
            return 'Static VLAN: '+' '.join(map(str,sw['vlans']))
        if cmd=='display arp all':
            rows=['IP ADDRESS       MAC ADDRESS       TYPE']
            rows += [f'{str(ip.ip_interface(a).ip):17}{MACS[d]:18}Interface' for a,v in self.addresses(d,False)]
            rows += [f'{a:17}{mac:18}Static' for a,mac in sw['arp'].items()]
            return '\n'.join(rows)
        if cmd=='display ip routing-table' or cmd.startswith('display ip routing-table '):
            query=cmd[25:].strip() if cmd.startswith('display ip routing-table ') else ''
            if query: ip.ip_address(query)
            rows=['Destination/Mask      Proto    NextHop           Interface']
            for a,v in self.addresses(d):
                if not query or ip.ip_address(query) in network(a): rows.append(f'{str(network(a)):22}Direct   {str(ip.ip_interface(a).ip):18}Vlanif{v}')
            for r in sw['routes']:
                conn=self.direct(d,r['via'])
                if conn and (not query or ip.ip_address(query) in ip.ip_network(r['prefix'])): rows.append(f'{r["prefix"]:22}Static   {r["via"]:18}Vlanif{conn[1]}')
            return '\n'.join(rows) if len(rows)>1 else 'No matching active route. 配置中的路由可能因接口 DOWN 而未生效。'
        if cmd=='display logbuffer':
            return ('SIMULATED OBSERVATION: GigabitEthernet0/0/24 link DOWN; receive signal absent.\n该证据不能区分线缆、连接或模块故障。' if self.physical_fault and d in ('SW2','SW3') else 'No link alarm in this simulated observation window.')
        raise ValueError('此 display 命令暂不支持。输入 ? 查看支持范围。')

    def execute(self,device,command,session='default'):
        ctx=self.context(session,device); before=self.prompt(device,ctx); cmd=' '.join(command.strip().split()); lower=cmd.lower()
        output='';mutated=False;probe=None;ok=True
        try:
            if len(cmd)>500: raise ValueError('命令过长。')
            if lower in ('?','help') or lower.endswith(' ?'):
                output=('PC commands: ipconfig | ping <IPv4> | help | clear' if device in self.hosts else
                        '查看：display interface brief | display interface GE0/0/24\n      display port vlan | display ip interface brief\n      display ip routing-table | display arp all\n      display current-configuration | display this | display logbuffer\n探测：ping <IPv4>\n视图：system-view | interface GE0/0/1 | quit | return\n配置：shutdown | undo shutdown | port default vlan <ID>\n      port trunk allow-pass vlan <IDs>\n      ip route-static <network> <mask> <next-hop>\n      undo ip route-static <network> <mask> <next-hop>\n      arp static <IP> <MAC> vid 99 interface GigabitEthernet 0/0/24\n      undo arp static <IP>\n以上为模拟器支持的命令子集。')
            elif lower in ('clear','cls'): output=''
            elif lower=='ipconfig' and device in self.hosts:
                h=self.hosts[device];output=f'IPv4 Address : {h["address"]}\nDefault Gateway : {h["gateway"]}\nMAC Address : {MACS[device]}'
            elif lower.startswith('ping '):
                match=re.fullmatch(r'ping(?: -c 3)? (\d+\.\d+\.\d+\.\d+)',lower)
                if not match: raise ValueError('本实验支持：ping <IPv4> 或 ping -c 3 <IPv4>。')
                probe=self.ping(device,match[1]);n=probe['received']
                output=f'PING {match[1]}: 3 simulated probes\n'+('\n'.join(f'Reply from {match[1]}: sequence={i}' for i in range(1,4)) if n else 'Request timeout\nRequest timeout\nRequest timeout')+f'\n3 packet(s) transmitted\n{n} packet(s) received\n{0 if n else 100}% packet loss\n[模拟探测，不代表真实设备报文]'
            elif lower.startswith('display '): output=self.display(device,lower,ctx)
            elif device in self.hosts: raise ValueError('PC 终端只支持 ipconfig、ping、help、clear。请选择交换机进行配置。')
            elif lower=='system-view':
                if ctx['view']!='user': raise ValueError('已经处于配置视图，可使用 return 返回用户视图。')
                ctx.update(view='system',iface=None);output='Enter system view, return user view with return command.'
            elif lower=='return': ctx.update(view='user',iface=None)
            elif lower=='quit':
                ctx.update(view='system' if ctx['view']=='interface' else 'user',iface=None)
            elif lower.startswith('interface '):
                if ctx['view']!='system': raise ValueError('请先进入 system-view；从其他接口退出后再选择目标接口。')
                iface=self.iface_name(lower[10:])
                if iface.startswith('Vlanif') and int(iface[6:]) not in self.switches[device]['svis']: raise ValueError('本实验仅支持已有 VLANIF。')
                ctx.update(view='interface',iface=iface)
            elif lower in ('shutdown','undo shutdown') or lower.startswith('port ' ) or lower.startswith('undo port '):
                if ctx['view']!='interface': raise ValueError('请先进入正确的 interface 视图。')
                iface=ctx['iface']; sw=self.switches[device]
                p=sw['svis'][int(iface[6:])] if iface.startswith('Vlanif') else sw['ports'][iface.split('/')[-1]]
                if lower in ('shutdown','undo shutdown'): p['admin']=lower=='undo shutdown'
                elif iface.startswith('Vlanif'): raise ValueError('VLANIF 不支持二层 port 命令。')
                elif lower in ('port link-type access','port link-type trunk'): p['mode']=lower.split()[-1]
                elif lower.startswith('port default vlan '):
                    if p['mode']!='access': raise ValueError('此命令要求 Access 接口。')
                    value=int(lower[18:]);self.valid_vlan(value);p['pvid']=value
                elif re.fullmatch(r'(undo )?port trunk allow-pass vlan [0-9 ]+',lower):
                    if p['mode']!='trunk': raise ValueError('此命令要求 Trunk 接口。')
                    values=[int(v) for v in lower.split('vlan ',1)[1].split()]
                    for v in values:self.valid_vlan(v)
                    p['allowed']=sorted(set(p['allowed']).difference(values) if lower.startswith('undo ') else set(p['allowed']).union(values))
                else: raise ValueError('不支持或不完整的接口配置命令。')
                mutated=True
            elif re.match(r'(undo )?ip route-static ',lower):
                if ctx['view']!='system':raise ValueError('静态路由需要在系统视图配置，请先 quit 或 system-view。')
                parts=lower.split();undo=parts[0]=='undo';args=parts[3:] if undo else parts[2:]
                if len(args)!=3:raise ValueError('格式：ip route-static <network> <mask> <next-hop>')
                prefix=str(ip.IPv4Network(args[0]+'/'+args[1],strict=True));via=str(ip.IPv4Address(args[2]));r={'prefix':prefix,'via':via}
                routes=self.switches[device]['routes']
                if undo:
                    if r not in routes:raise ValueError('未找到指定静态路由，请核对网络、掩码和下一跳。')
                    routes.remove(r)
                elif r not in routes:routes.append(r)
                mutated=True
            elif lower.startswith('arp static ') or lower.startswith('undo arp static '):
                if ctx['view']!='system':raise ValueError('静态 ARP 需要在系统视图配置。')
                table=self.switches[device]['arp']
                if lower.startswith('undo '):
                    args=lower.split()
                    if len(args)!=4: raise ValueError('格式：undo arp static <IP>')
                    target=str(ip.IPv4Address(args[3]))
                    if target not in table:raise ValueError('指定静态 ARP 不存在。')
                    del table[target]
                else:
                    m=re.fullmatch(r'arp static (\S+) ([0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}) vid 99 interface (?:gigabitethernet\s*|ge)0/0/24',lower)
                    if not m:raise ValueError('格式：arp static <IP> xxxx-xxxx-xxxx vid 99 interface GigabitEthernet 0/0/24')
                    target=str(ip.IPv4Address(m[1]));table[target]=m[2]
                mutated=True
            else:raise ValueError('无法识别或尚未支持的模拟命令。输入 ? 查看帮助。')
        except (ValueError,KeyError) as e:
            ok=False;output='Error: '+str(e)
        if mutated:self.log(device,cmd,True);output='配置已更新。请重新探测确认业务结果。'
        elif cmd:self.log(device,cmd,False)
        return {'device':device,'command':cmd,'before_prompt':before,'prompt':self.prompt(device,ctx),'output':output,
                'ok':ok,'mutation':mutated,'probe':probe,'revision':self.revision,'epoch':self.epoch}

    @staticmethod
    def valid_vlan(v):
        if not 1<=v<=4094:raise ValueError('VLAN 范围为 1～4094。')

    def snapshot(self):
        return {'epoch':self.epoch,'revision':self.revision,'scene':self.scene,
                'brief':SCENES[self.scene]['brief'] if self.scene else '健康基线已加载，可以自由检查。',
                'sources':deepcopy(SCENES[self.scene]['sources']) if self.scene else [],
                'links':[{'a':a,'b':b,'pa':pa,'pb':pb,'up':self.link_up((a,pa,b,pb))} for a,pa,b,pb in LINKS],
                'probe':deepcopy(self.last_probe),'logs':deepcopy(self.logs[-40:])}

    def assistant(self,before_id=None):
        """Observe equipment, choose one next repair; no scene ID consulted."""
        probe=self.probe(); checks=[]
        for d,cmd in [('SW1','display interface brief'),('SW1','display port vlan'),('SW2','display port vlan'),
                      ('SW3','display port vlan'),('SW2','display ip routing-table'),('SW3','display current-configuration'),
                      ('SW2','display arp all'),('SW3','display arp all'),('SW2','display interface GigabitEthernet0/0/24')]:
            checks.append({'device':d,'command':cmd,'output':self.display(d,cmd.lower(),{'view':'user','iface':None})})
        task=None
        def set_task(device,title,reason,commands,page,section):
            return {'device':device,'title':title,'reason':reason,'commands':commands,'page':page,'section':section}
        # Work from the user's access path outward, one evidence-backed step at a time.
        for d,n in [('SW1','1'),('SW1','2'),('SW1','24'),('SW2','1'),('SW2','24'),('SW3','24'),('SW3','1')]:
            if not self.switches[d]['ports'][n]['admin']:
                task=set_task(d,'先恢复被关闭的接口',f'{d} 的 {ge(n)} 为管理关闭。先恢复这一处，再检查仍然失败的路径。',
                              ['return','system-view','interface '+ge(n),'undo shutdown','return'],209,'§8.2.1');break
        if not task:
            for d,n,v in [('SW1','1',10),('SW1','2',10),('SW3','1',30),('SW2','24',99),('SW3','24',99)]:
                p=self.switches[d]['ports'][n]
                if p['mode']!='access' or p['pvid']!=v:
                    task=set_task(d,'核对并修正接入口 VLAN',f'{d} {ge(n)} 当前为 {p["mode"]} / VLAN {p["pvid"]}，网络规划要求 Access VLAN {v}。',
                                  ['return','system-view','interface '+ge(n),'port link-type access',f'port default vlan {v}','return'],2454,'§22.53.3.2');break
        if not task:
            for d,n in [('SW1','24'),('SW2','1')]:
                p=self.switches[d]['ports'][n]
                if p['mode']!='trunk' or not {10,20}.issubset(p['allowed']):
                    task=set_task(d,'补齐上联允许的 VLAN',f'{d} {ge(n)} 允许列表为 {p["allowed"]}。办公 VLAN 10 需要通过，同时保留 VLAN 20。',
                                  ['return','system-view','interface '+ge(n),'port link-type trunk','port trunk allow-pass vlan 10 20','return'],2455,'§22.53.3.2');break
        if not task:
            for d,prefix,via in [('SW2','192.168.30.0/24','192.168.99.2'),('SW3','192.168.10.0/24','192.168.99.1')]:
                routes=self.switches[d]['routes']; expected={'prefix':prefix,'via':via}
                wrong=[r for r in routes if r['prefix']==prefix and r['via']!=via]
                if expected not in routes or wrong:
                    commands=['return','system-view']+[f'undo ip route-static {r["prefix"].replace("/"," ")} {r["via"]}' for r in wrong]
                    commands += [f'ip route-static {prefix.replace("/"," ")} {via}','return']
                    task=set_task(d,'补齐去程路由' if d=='SW2' else '修正返回办公区的路由',
                                  f'{d} 到 {prefix} 的配置需要经 {via}。请求和响应都需要有路可走。'+(' 同时观测到互联口信号缺失；补齐配置不会解决物理链路问题。' if not self.link_up(LINKS[3]) else ''),
                                  commands,1601,'§21.7.4.14 / §15.2.4');break
        if not task and not self.link_up(LINKS[3]):
            task=set_task('SW2','需要现场检查，不能用配置命令彻底修好',
                          '两端管理配置开启，但互联口仍为 DOWN，模拟观测显示接收信号缺失。需检查连接、线缆或模块；现有证据无法确定是哪一个部件。',
                          ['return','display interface GigabitEthernet0/0/24','display logbuffer'],958,'§15.2.3')
            task['handoff']=True
        if not task:
            for d,target,peer in [('SW2','192.168.99.2','SW3'),('SW3','192.168.99.1','SW2')]:
                current=self.switches[d]['arp'].get(target)
                if current!=MACS[peer]:
                    commands=['return','system-view']+([f'undo arp static {target}'] if current else [])
                    commands += [f'arp static {target} {MACS[peer]} vid 99 interface GigabitEthernet 0/0/24','return']
                    task=set_task(d,'更新旧设备的静态地址绑定',f'{d} 为 {target} 保存 {current or "无静态绑定"}；对端 {peer} 的实际 MAC 为 {MACS[peer]}。需要比较并核对两端。',commands,972,'§15.3.2');break
        if not task and not probe['passed']:
            task=set_task('SW2','证据不足，继续检查接口与配置','当前设置超出预置排障分支，不能确认根因或恢复。请核对 VLANIF 状态及网络规划。',
                          ['return','display ip interface brief','display current-configuration'],958,'§15.2.3')
        before=self.reports.get(before_id)
        recovered=probe['passed'] and before is not None and before['epoch']==self.epoch and not before['passed']
        report={'id':str(uuid.uuid4()),'epoch':self.epoch,'revision':self.revision,'passed':probe['passed'],
                'recovered':recovered,'probe':probe,'task':task,'checks':checks,'mode':'rule_demo'}
        self.reports[report['id']]=report
        if len(self.reports)>50: del self.reports[next(iter(self.reports))]
        return deepcopy(report)

    def external_diagnosis(self):
        """Return a compact, distinct diagnosis for the offline assistant demo."""
        specs = {
            'A': ('diagnosis', '接口被关闭且上联缺少业务 VLAN',
                  'SW1 GE0/0/1 处于管理关闭，上联口未允许 VLAN 10。助手只给出诊断和建议，不自动改配置。'),
            'B': ('diagnosis', '接入口 VLAN 配置错误',
                  'PC1 与服务器接入口被划入错误 VLAN。助手只给出诊断和建议，不自动改配置。'),
            'C': ('auto_repair', '去程路由缺失且回程下一跳错误',
                  'SW2 缺少服务器网段路由，SW3 返回办公网段的下一跳错误；允许助手在模拟器内自动修复。'),
            'D': ('auto_repair', '设备更换后静态 ARP 仍绑定旧 MAC',
                  'SW2、SW3 保存了对端旧 MAC，允许助手在模拟器内更新静态 ARP 并复检。'),
            'E': ('handoff', '互联链路接收信号缺失',
                  '软件配置检查后仍可见物理链路无信号，需要现场检查网线、光纤或光模块。'),
        }
        category, title, reason = specs.get(self.scene, ('diagnosis', '未识别的实验状态', '需要人工继续检查。'))
        report = self.assistant()
        return {'epoch': self.epoch, 'revision': self.revision, 'fault_code': self.scene or 'healthy',
                'category': category, 'title': title, 'reason': reason,
                'source': deepcopy(SCENES[self.scene]['sources'][0]) if self.scene else None,
                'probe': report['probe'], 'suggested_task': report.get('task')}

    def auto_repair(self, session='offline-assistant', expected=None):
        """Apply bounded repair tasks only for the two auto-repair demo scenes."""
        diagnosis = self.external_diagnosis()
        if expected and diagnosis['fault_code'] != expected:
            return {'epoch': self.epoch, 'revision': self.revision, 'eligible': False, 'repaired': False,
                    'message': f'当前故障不是场景 {expected}，所选修复技能未执行。',
                    'records': [], 'probe': diagnosis['probe']}
        if diagnosis['category'] != 'auto_repair':
            return {'epoch': self.epoch, 'revision': self.revision, 'eligible': False, 'repaired': False,
                    'message': '本场景仅诊断或需要现场处理，助手未执行配置命令。',
                    'records': [], 'probe': diagnosis['probe']}
        records = []
        previous = None
        for _ in range(4):
            report = self.assistant(previous)
            if report['passed'] or not report.get('task') or report['task'].get('handoff'):
                break
            task = report['task']
            for command in task['commands']:
                record = self.execute(task['device'], command, session)
                records.append(record)
                if not record['ok']:
                    break
            previous = report['id']
            if records and not records[-1]['ok']:
                break
        probe = self.probe()
        return {'epoch': self.epoch, 'revision': self.revision, 'eligible': True,
                'repaired': probe['passed'],
                'message': '助手已执行受控配置并复检通过。' if probe['passed'] else '已执行配置，但复检仍未通过。',
                'records': records, 'probe': probe}
