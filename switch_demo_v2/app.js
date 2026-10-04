'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const NS='http://www.w3.org/2000/svg';
const session=crypto.randomUUID(), names=['PC1','PC2','SW1','SW2','SW3','SERVER'];
const subtitles={PC1:'192.168.10.10',PC2:'192.168.10.11',SW1:'接入交换机',SW2:'核心交换机',SW3:'服务器侧交换机',SERVER:'192.168.30.10'};
const defaults={PC1:[105,114],PC2:[105,303],SW1:[286,213],SW2:[524,213],SW3:[753,213],SERVER:[935,213]};
let positions=structuredClone(defaults),state=null,current='PC1',commandBusy=false,assistantBusy=false,lastReport=null;
let histories={},historyIndex=0,terminalRecords={},prompts={},scenes={},toastTimer,animationId=0;
for(const d of names){histories[d]=[];terminalRecords[d]=[];prompts[d]=d.startsWith('SW')?`<${d}> `:`${d}> `}
if(location.pathname==='/assistant'){
 document.body.classList.add('assistant-only');document.title='FIELDNOTE · 离线排障助手';
 document.querySelector('.window-caption').textContent='离线 AI 运维助手';
}
if(location.pathname==='/device'){
 document.body.classList.add('device-only');document.title='FIELDNOTE · 园区网络故障模拟器';
 document.querySelector('.window-caption').textContent='园区网络故障模拟器 · Campus_Lab.fnl';
}
function syncHalfScreenMode(){
 if(location.pathname==='/' ) document.body.classList.toggle('device-only',window.innerWidth<=1100);
}
syncHalfScreenMode();
window.addEventListener('resize',syncHalfScreenMode);

function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}
function svg(tag,attrs){const n=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);return n}
function toast(text){clearTimeout(toastTimer);$('#toast').textContent=text;$('#toast').style.display='block';toastTimer=setTimeout(()=>$('#toast').style.display='none',3600)}
async function api(path,data){const r=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error||'本地服务返回错误');return v}
function modal(title,body,kind=''){const dialog=$('#modal');dialog.className=kind;$('#modalTitle').textContent=title;$('#modalBody').replaceChildren(body);dialog.showModal()}
function closeModal(){$('#modal').close();$('#modal').className='';$('#modalBody').replaceChildren()}
$('#closeModal').onclick=closeModal;$('#modal').onclick=e=>{if(e.target===$('#modal'))closeModal()};

function initDevices(){
 for(const d of names){
  const button=el('button','device-item');button.dataset.device=d;button.append(el('span','',d.startsWith('SW')?'▱':'▣'),el('b','',d));button.onclick=()=>selectDevice(d,true);$('#devices').append(button);
  const tab=el('button','',d==='SERVER'?'SRV':d);tab.dataset.device=d;tab.onclick=()=>selectDevice(d,true);$('#terminalTabs').append(tab);
  const g=svg('g',{'class':'network-node','data-device':d,tabindex:0,role:'button','aria-label':d+'，双击打开终端'});
  g.append(svg('rect',{x:-58,y:-65,width:116,height:127,rx:13,'class':'selection'}));
  const icon=svg('use',{href:d.startsWith('SW')?'#switchIcon':d==='SERVER'?'#serverIcon':'#pcIcon',x:-47,y:-60,width:94,height:86});
  g.append(icon);const name=svg('text',{x:0,y:42,'text-anchor':'middle','class':'device-name'});name.textContent=d;g.append(name);
  const sub=svg('text',{x:0,y:59,'text-anchor':'middle','class':'device-sub'});sub.textContent=subtitles[d];g.append(sub);
  g.addEventListener('dblclick',()=>selectDevice(d,true));g.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();selectDevice(d,true)}});
  let drag=null;
  g.addEventListener('pointerdown',e=>{if(e.button!==0)return;const p=svgPoint(e);drag={pointer:e.pointerId,start:p,origin:[...positions[d]],moved:false};g.setPointerCapture(e.pointerId)});
  g.addEventListener('pointermove',e=>{if(!drag)return;const p=svgPoint(e);if(Math.abs(p.x-drag.start.x)+Math.abs(p.y-drag.start.y)>4)drag.moved=true;positions[d]=[Math.max(60,Math.min(980,drag.origin[0]+p.x-drag.start.x)),Math.max(90,Math.min(345,drag.origin[1]+p.y-drag.start.y))];drawTopology()});
  g.addEventListener('pointerup',e=>{if(drag){g.releasePointerCapture(e.pointerId);if(!drag.moved)highlight(d);drag=null}});
  $('#nodes').append(g);
 }
 drawTopology();selectDevice('PC1',false);
}
function svgPoint(e){const p=$('#topology').createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform($('#topology').getScreenCTM().inverse())}
function highlight(d){$$('.network-node').forEach(n=>n.classList.toggle('selected',n.dataset.device===d))}
function drawTopology(){
 $$('.network-node').forEach(n=>{const [x,y]=positions[n.dataset.device];n.setAttribute('transform',`translate(${x},${y})`)});
 $('#wires').replaceChildren();if(!state)return;
 for(const l of state.links){const a=positions[l.a],b=positions[l.b];$('#wires').append(svg('line',{x1:a[0],y1:a[1]-15,x2:b[0],y2:b[1]-15,'class':'wire'+(l.up?'':' down')}));
  for(const [f,label] of [[.30,l.pa==='eth0'?'Ethernet':`GE0/0/${l.pa}`],[.73,l.pb==='eth0'?'Ethernet':`GE0/0/${l.pb}`]]){const t=svg('text',{x:a[0]+(b[0]-a[0])*f,y:a[1]-15+(b[1]-a[1])*f-9,'text-anchor':'middle','class':'port-label'});t.textContent=label;$('#wires').append(t)}
 }
}
function renderScenes(){
 $('#scenes').replaceChildren();const blind=$('#challenge').checked;
 for(const [code,s]of Object.entries(scenes)){const b=el('button','scene');b.dataset.code=code;b.classList.toggle('active',!blind&&state?.scene===code);b.append(el('span','letter',code));const desc=el('div');desc.append(el('strong','',blind?'挑战场景 '+code:s.title),el('small','',blind?'只凭设备证据排查':'双击设备 · 命令行排查'));b.append(desc);b.onclick=()=>changeScene(code);$('#scenes').append(b)}
}
function renderSources(s){
 const area=$('#sourcePages');area.replaceChildren();const sources=s.sources||[],blind=$('#challenge').checked;
 if(!sources.length){area.append(el('span','','健康基线 · 无故障出处'));$('#sourceBtn').disabled=true;return}
 $('#sourceBtn').disabled=false;
 for(const source of sources){area.append(el('span','',`PDF p.${source.pdf_pages} · 正文 p.${source.printed_pages}${blind?'':' · '+source.section}`))}
}
async function showSources(){
 if(!state?.sources?.length){toast('健康基线没有故障场景出处。');return}
 let status;try{status=await api('/api/manual/status')}catch(e){status={available:false,message:e.message}}
 const layout=el('div','manual-layout'),nav=el('div','manual-nav'),viewer=el('div','manual-frame-wrap');layout.append(nav,viewer);
 const blind=$('#challenge').checked;
 nav.append(el('div','source-disclaimer',blind?'打开原件会显示该页正文，可能揭晓排查方向。':'本场景按以下手册机制组合构造，不声称手册中存在完全相同的组合案例。'));
 function openSource(source,button){
  $$('.manual-source-button').forEach(b=>b.classList.toggle('active',b===button));viewer.replaceChildren();
  const bounds=[...source.pdf_pages.matchAll(/\d+/g)].map(m=>Number(m[0])),first=bounds[0],last=bounds.at(-1)||first;
  let page=first;
  const actions=el('div','manual-actions'),location=el('span');
  const open=el('a','', '在新窗口打开完整原件 ↗');open.target='_blank';open.rel='noopener';actions.append(location,open);viewer.append(actions);
  if(status.available){
   const shell=el('div','manual-page-shell'),controls=el('div','manual-page-controls');
   const previous=el('button','','← 上一页'),counter=el('span'),next=el('button','','下一页 →');
   const preview=el('div','manual-page-preview'),image=el('img');image.id='manualPageImage';
   image.alt='';preview.append(image);controls.append(previous,counter,next);shell.append(controls,preview);viewer.append(shell);
   const note=el('div','manual-page-note','此预览由随程序打包的维护宝典原始 PDF 直接生成。');viewer.append(note);
   function showPage(value){
    page=Math.max(first,Math.min(last,value));
    location.textContent=`当前定位：PDF 第 ${page} 页 · 引用范围 ${source.pdf_pages} · 正文第 ${source.printed_pages} 页`;
    open.href=`/manual.pdf#page=${page}&zoom=page-width`;
    counter.textContent=first===last?`PDF 第 ${page} 页`:`PDF 第 ${page} 页 / ${first}–${last}`;
    previous.disabled=page<=first;next.disabled=page>=last;
    image.alt=`华为 S 系列维护宝典 PDF 第 ${page} 页原页预览`;
    image.onerror=()=>{preview.replaceChildren(el('div','manual-unavailable','该页预览未打包，请使用上方入口打开完整 PDF 原件。'))};
    image.src=`/manual-pages/${page}.png`;
   }
   previous.onclick=()=>showPage(page-1);next.onclick=()=>showPage(page+1);showPage(first);
  }
  else{const missing=el('div','manual-unavailable');missing.append(el('b','',status.message||'未找到手册原件。'),el('p','', '请确认发布包保留了 assets 目录，或启动前设置 SWITCH_DEMO_MANUAL。'),el('code','', '默认相对路径：switch_demo_v2\\assets\\华为S系列园区交换机维护宝典.pdf'));viewer.append(missing)}
 }
 for(const [index,source] of state.sources.entries()){const button=el('button','manual-source-button');button.append(el('b','',blind?`依据 ${index+1} · PDF p.${source.pdf_pages}`:source.section),el('small','',`PDF p.${source.pdf_pages} · 正文 p.${source.printed_pages}`));if(!blind)button.append(el('small','',source.basis));button.onclick=()=>openSource(source,button);nav.append(button);if(index===0)setTimeout(()=>openSource(source,button),0)}
 modal('维护宝典原件 · 对应位置',layout,'manual-viewer');
}
function freshTerminals(){for(const d of names){prompts[d]=d.startsWith('SW')?`<${d}> `:`${d}> `;terminalRecords[d]=[];histories[d]=[]}lastReport=null;$('#assistantStale').classList.add('hidden');$('#chat').replaceChildren();const m=message('排障向导','新的实验已就绪。点击「开始排查」，我会读取设备状态，再给出当前这一步的建议。');m.append(el('p','muted','先查看、再配置、再复检。无法彻底修复时，我会保留未解决的证据。'));$('#commandInput').value='';resizeInput();renderTerminal();animationId++;$('#packets').replaceChildren()}
function renderState(s){
 const old=state;state=s;if(old&&old.epoch!==s.epoch)freshTerminals();
 const latest=s.probe&&s.probe.epoch===s.epoch&&s.probe.revision===s.revision;
 $('#symptom').textContent=latest?(s.probe.passed?'检查通过：办公电脑与业务服务器通信正常。':s.probe.results[1].passed?'本地与网关通信正常，服务器仍未恢复。':s.probe.results[0].passed?'本地电脑已互通，网关和服务器仍未恢复。':s.brief):s.brief;
 $('#labVersion').textContent='已连接 · 配置 v'+s.revision;
 renderScenes();renderSources(s);drawTopology();renderProbes(s.probe);
 if(lastReport&&(lastReport.epoch!==s.epoch||lastReport.revision!==s.revision)){$('#assistantStale').textContent='配置已变化。上一次结论仅供回看，请修改后复检。';$('#assistantStale').classList.remove('hidden')}
}
function renderProbes(p){
 const titles=['同网段电脑','办公网关','业务服务器'];const strip=$('#probeStrip');strip.replaceChildren();
 const fresh=p&&state&&p.epoch===state.epoch&&p.revision===state.revision;
 for(let i=0;i<3;i++){const tile=el('div','probe-tile'+(fresh?(p.results[i].passed?' good':' bad'):''));tile.append(el('span','',titles[i]),el('strong','',fresh?(p.results[i].passed?'3/3 通过':'0/3 失败'):'待复检'));strip.append(tile)}
 const note=el('div','probe-note');note.id='probeNote';note.textContent=!fresh?'配置改变后需要重新探测；端口灯不能代替业务检查。':p.passed?'本轮模拟通信与必要配置均通过。':p.requirements.length&&p.results.every(r=>r.passed)?'通信通过，仍有配置要求未满足：'+p.requirements.join('；'):'已完成模拟探测；红色项仍未恢复，需要继续排查。';strip.append(note);
}
async function changeScene(code){if(commandBusy){toast('请等待当前命令执行结束。');return}try{renderState(await api('/api/scene',{code}));toast(code?'新场景已加载。先输入 ping 检查，或让右侧向导开始排查。':'健康基线已恢复。这是新的实验，不计为修复成功。');$('#commandInput').focus()}catch(e){toast(e.message)}}
async function selectDevice(d,focus){current=d;historyIndex=histories[d].length;$$('[data-device]').forEach(n=>n.classList.toggle('active',n.dataset.device===d));highlight(d);renderTerminal();if(focus){$('#commandInput').focus();toast('已打开 '+d+' 终端')}try{const c=await api('/api/context',{device:d,session});if(current===d&&(!state||c.epoch===state.epoch)){prompts[d]=c.prompt;$('#prompt').textContent=c.prompt}}catch(e){toast(e.message)}}
function renderTerminal(){
 $('#terminalOutput').replaceChildren();const entries=terminalRecords[current];
 if(!entries.length){const welcome=el('div','terminal-entry');welcome.append(el('div','notice',`FIELDNOTE / ${current} console · 模拟设备终端\n输入 ? 查看支持的命令。修复命令需要在正确设备和视图中执行。\n${current.startsWith('SW')?'建议先输入：display interface brief':'建议先输入：ping 192.168.30.10'}\n`));$('#terminalOutput').append(welcome)}
 for(const r of entries){const box=el('div','terminal-entry');box.append(el('div','echo',r.before_prompt+r.command),el('div',r.ok?'output':'error',r.output));$('#terminalOutput').append(box)}
 $('#prompt').textContent=prompts[current];$('#terminalOutput').scrollTop=$('#terminalOutput').scrollHeight;
}
function resizeInput(){const input=$('#commandInput');input.style.height='auto';input.style.height=Math.min(150,Math.max(26,input.scrollHeight))+'px'}
async function execute(){
 const input=$('#commandInput'),text=input.value.trim(),d=current;if(!text||commandBusy||!state)return;
 if(['clear','cls'].includes(text.toLowerCase())){terminalRecords[d]=[];input.value='';resizeInput();renderTerminal();return}
 commandBusy=true;$('#executeBtn').disabled=true;input.disabled=true;input.value='';resizeInput();histories[d].push(text);historyIndex=histories[d].length;
 try{const response=await api('/api/command',{device:d,command:text,session,epoch:state.epoch});
  renderState(response.state);for(const r of response.records){terminalRecords[d].push(r);prompts[d]=r.prompt;if(r.probe)animateProbe(r.probe)}
  if(response.skipped)toast(`命令出错，剩余 ${response.skipped} 行已暂停。核对当前视图后重试。`);
  renderTerminal();$('#commandStatus').textContent=response.records.some(r=>r.mutation)?'配置已改变，请重新探测。':'本次命令已完成 · 结果来自模拟状态';
 }catch(e){toast(e.message)}finally{commandBusy=false;$('#executeBtn').disabled=false;input.disabled=false;input.focus()}
}
$('#commandForm').onsubmit=e=>{e.preventDefault();execute()};$('#commandInput').oninput=resizeInput;
const completions=['display interface brief','display interface GigabitEthernet0/0/24','display ip interface brief','display port vlan','display ip routing-table','display arp all','display current-configuration','display this','display logbuffer','system-view','interface GigabitEthernet0/0/1','interface GigabitEthernet0/0/24','undo shutdown','shutdown','return','quit','ping 192.168.10.11','ping 192.168.10.1','ping 192.168.30.10','port trunk allow-pass vlan 10 20','port default vlan 10','ipconfig'];
$('#commandInput').onkeydown=e=>{const input=e.target;if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();execute()}else if(e.key==='Tab'){e.preventDefault();const matches=completions.filter(c=>c.toLowerCase().startsWith(input.value.toLowerCase()));if(matches.length===1){input.value=matches[0];resizeInput()}else if(matches.length){toast(matches.slice(0,4).join('  /  '))}}else if(e.key==='ArrowUp'&&!input.value.includes('\n')){e.preventDefault();historyIndex=Math.max(0,historyIndex-1);input.value=histories[current][historyIndex]||'';resizeInput()}else if(e.key==='ArrowDown'&&!input.value.includes('\n')){e.preventDefault();historyIndex=Math.min(histories[current].length,historyIndex+1);input.value=histories[current][historyIndex]||'';resizeInput()}else if(e.ctrlKey&&e.key.toLowerCase()==='l'){e.preventDefault();terminalRecords[current]=[];renderTerminal()}};
$('#clearBtn').onclick=()=>{terminalRecords[current]=[];renderTerminal();$('#commandInput').focus()};

async function animateProbe(p){
 const id=++animationId;$('#packets').replaceChildren();const dot=svg('circle',{r:6,fill:'#43a0b9',stroke:'white','stroke-width':2});$('#packets').append(dot);
 const segments=[{path:p.forward,color:'#43a0b9'},{path:p.reverse,color:'#60a378'}];
 for(const segment of segments){dot.setAttribute('fill',segment.color);for(let i=0;i<segment.path.length-1;i++){const start=positions[segment.path[i]],end=positions[segment.path[i+1]];if(!start||!end)continue;const t0=performance.now();await new Promise(resolve=>{function frame(now){if(id!==animationId){resolve();return}const t=Math.min(1,(now-t0)/430);dot.setAttribute('cx',start[0]+(end[0]-start[0])*t);dot.setAttribute('cy',start[1]-15+(end[1]-start[1])*t);if(t<1)requestAnimationFrame(frame);else resolve()}requestAnimationFrame(frame)});if(id!==animationId)return}}
 if(!p.passed){dot.setAttribute('fill','#d3876e');const last=(p.reverse.length?p.reverse:p.forward).at(-1);if(positions[last]){dot.setAttribute('cx',positions[last][0]);dot.setAttribute('cy',positions[last][1]-15)}}
 setTimeout(()=>{if(id===animationId)$('#packets').replaceChildren()},1000);
}
$('#probeBtn').onclick=async()=>{try{$('#probeBtn').disabled=true;const p=await api('/api/probe',{});if(p.epoch!==state?.epoch)return;state.probe=p;renderState(state);animateProbe(p.results[2]);toast(p.passed?'本轮通信与配置检查通过。':'探测已完成，请查看失败项并继续排查。')}catch(e){toast(e.message)}finally{$('#probeBtn').disabled=false}};

function message(who,text,user=false){const m=el('div','message'+(user?' user':''));m.append(el('span','message-label',who));if(text)m.append(el('p','',text));$('#chat').append(m);$('#chat').scrollTop=$('#chat').scrollHeight;return m}
function setAssistantBusy(v){assistantBusy=v;for(const id of ['diagnoseBtn','verifyBtn','chatSend'])$('#'+id).disabled=v}
async function diagnose(text){
 if(assistantBusy)return;setAssistantBusy(true);message('你',text,true);const m=message('排障向导','正在读取设备观测并检查通信路径…');const epoch=state?.epoch;
 try{const report=await api('/api/assistant',{before:lastReport?.id||null});if(state?.epoch!==report.epoch||epoch&&epoch!==report.epoch){m.replaceChildren(el('p','muted','实验已切换，请重新排查。'));return}
  m.replaceChildren(el('span','message-label','排障向导 · 基于本轮设备观测'));lastReport=report;state.probe=report.probe;renderState(state);$('#assistantStale').classList.add('hidden');
  const passedCount=report.probe.results.filter(r=>r.passed).length;
  if(report.passed){m.append(el('h3','success',report.recovered?'复检通过，业务已恢复。':'当前模拟业务正常。'),el('p','',`本地电脑、网关和服务器均为 3/3 成功，必要配置检查通过。`));}
  else{const task=report.task;m.append(el('h3',task.handoff?'warning':'',task.title),el('p','',task.reason));
   m.append(el('p','muted',`当前通信检查：${passedCount}/3 项通过。${task.handoff?'这次排查可以交接，但故障没有彻底解决。':'先处理这一处，执行后再次复检。'}`));
   m.append(el('p','',`打开 ${task.device} 终端，${task.handoff?'收集以下证据：':'依次输入：'}`));const pre=el('pre','',task.commands.join('\n'));m.append(pre);
   const actions=el('div','command-buttons');const copy=el('button','','复制命令');copy.onclick=async()=>{try{await navigator.clipboard.writeText(task.commands.join('\n'));toast('命令已复制。请到 '+task.device+' 终端粘贴，再按 Enter 执行。')}catch(e){const range=document.createRange();range.selectNodeContents(pre);const sel=getSelection();sel.removeAllRanges();sel.addRange(range);toast('请按 Ctrl+C 复制选中的命令。')}};
   const open=el('button','','打开 '+task.device+' 终端');open.onclick=()=>{if(location.pathname==='/assistant')window.open('/device?device='+encodeURIComponent(task.device),'fieldnote-device');else selectDevice(task.device,true)};actions.append(copy,open);m.append(actions);
   m.append(el('p','reference',`手册依据：${task.section} · PDF 第 ${task.page} 页。命令参数来自本实验网络规划。`));
  }
  const details=el('details'),summary=el('summary','','查看本轮命令观测与证据');details.append(summary);for(const c of report.checks){details.append(el('pre','',`${c.device}> ${c.command}\n${c.output}`))}m.append(details);
  m.append(el('p','muted','轻量规则向导；不调用大模型，不自动执行配置。'));
  $('#chat').scrollTop=m.offsetTop-$('#chat').offsetTop;
 }catch(e){m.append(el('p','warning','检查失败：'+e.message))}finally{setAssistantBusy(false)}
}
$('#diagnoseBtn').onclick=()=>diagnose('请检查当前网络，告诉我第一步怎么做。');$('#verifyBtn').onclick=()=>diagnose('我已完成操作，请重新检查，还有什么问题？');
$('#chatForm').onsubmit=e=>{e.preventDefault();const t=$('#chatInput').value.trim();if(!t||assistantBusy)return;$('#chatInput').value='';if(/检查|故障|网络|不通|服务|修|恢复|操作|怎么|路由|arp|vlan|端口|电脑|完成|好了/i.test(t))diagnose(t);else{message('你',t,true);message('排障向导','我现在是轻量规则演示助手，可以读取本实验设备状态、给出下一步命令并复检。请点击「开始排查」或「修改后复检」。')}};

$('#challenge').onchange=()=>{renderScenes();if(state)renderSources(state);toast($('#challenge').checked?'挑战模式：保留手册页码，隐藏章节标题与内容摘要。':'已切换为教学展示模式，完整出处已显示。')};$('#sourceBtn').onclick=showSources;$('#randomBtn').onclick=()=>changeScene('random');$('#resetBtn').onclick=()=>changeScene(null);$('#layoutBtn').onclick=()=>{positions=structuredClone(defaults);drawTopology()};
$('#planBtn').onclick=()=>{const box=el('div');box.append(el('p','','这些是健康网络的规划资料，排查时可以对照；不包含本次故障注入答案。'));const table=el('table');
 const rows=[['对象','正常配置'],['PC1 / PC2','192.168.10.10、192.168.10.11 /24；网关 192.168.10.1'],['SW1 接入口','GE0/0/1 → PC1；GE0/0/2 → PC2；均为 Access VLAN 10'],['SW1 ↔ SW2','SW1 GE0/0/24 ↔ SW2 GE0/0/1；Trunk 允许 VLAN 10、20'],['SW2 ↔ SW3','双方 GE0/0/24；Access VLAN 99；Vlanif99 分别为 192.168.99.1、192.168.99.2'],['服务器','192.168.30.10/24；网关 192.168.30.1；SW3 GE0/0/1 属于 VLAN 30'],['去程路由','SW2：192.168.30.0/24 → 192.168.99.2'],['回程路由','SW3：192.168.10.0/24 → 192.168.99.1'],['SW2 的 MAC','00e0-fc12-3456；互联地址绑定需保留'],['SW3 的 MAC','00e0-fc65-4321；互联地址绑定需保留']];for(const [i,row]of rows.entries()){const tr=el('tr');row.forEach(t=>tr.append(el(i?'td':'th','',t)));table.append(tr)}box.append(table);modal('正常网络规划',box)};
$('#guideBtn').onclick=()=>{const box=el('div');for(const t of ['1. 左边选一个场景；所有场景共用这张拓扑。','2. 右边点击「开始排查」，或者先双击 PC1，输入 ping 192.168.30.10。','3. 根据建议双击对应交换机，或点击「打开终端」。','4. 在终端逐条输入命令，也可以复制多行命令，粘贴后按 Enter 执行。','5. 点击「修改后复检」。修好一处不代表所有通信恢复。','6. 遇到物理链路持续异常，只能记录证据并交接，配置命令不能消除它。'])box.append(el('p','',t));box.append(el('pre','','?                 查看命令帮助\n↑ / ↓             浏览历史命令\nTab               补全或显示候选\nEnter             执行当前命令 / 多行命令\nShift + Enter     换行\nCtrl + L          清屏'));box.append(el('p','muted','这是自研行为模拟器，终端不会运行你电脑上的系统命令。规则向导为配套 Demo，不替代正在开发的离线助手。'));modal('两分钟上手',box)};
$('#exportBtn').onclick=()=>{if(!state)return;let text='# 驻点网络实验记录\n\n模式：自研行为模拟 / 规则助手 Demo\n实验编号：'+state.epoch+'\n配置版本：'+state.revision+'\n\n';if(state.sources?.length)text+='## 问题来源\n\n《华为 S 系列交换机维护宝典》第 25 版\n\n'+state.sources.map(s=>`- ${s.section}，PDF p.${s.pdf_pages}（正文 p.${s.printed_pages}）：${s.basis}`).join('\n')+'\n\n> 本实验按手册机制组合构造，不等同于手册中的单一原案例。\n\n';if(lastReport){text+='## 最近一次向导检查\n\n'+(lastReport.revision===state.revision?'当前检查':'旧配置检查，需复检')+'\n\n'+(lastReport.passed?'检查通过':lastReport.task.title+'\n'+lastReport.task.reason)+'\n\n'}text+='## 最近操作（最多 40 条）\n\n'+state.logs.map(l=>`${l.time} ${l.device} ${l.text}`).join('\n');const a=el('a');a.href=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));a.download='驻点-实验记录.md';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
async function poll(){try{const s=await api('/api/state');renderState(s)}catch(e){$('#labVersion').textContent='服务连接中断';$('#assistantStale').textContent='本地服务连接中断，当前结果不能代表最新状态。';$('#assistantStale').classList.remove('hidden')}}
async function init(){try{scenes=await api('/api/scenes');initDevices();await poll();const target=new URLSearchParams(location.search).get('device');if(names.includes(target))await selectDevice(target,false);setInterval(poll,1200)}catch(e){toast('无法连接本地实验服务：'+e.message)}}init();
