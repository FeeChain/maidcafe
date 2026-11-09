import {LEVELS,freshState,chunks,createGroup,judgeGroup,pending,retryGroup,canAdvance,randomTargets,chosenTargets,startQueue,recordStudy,advanceQueue,createExam,answerExam,examResult,createAssessment,answerAssessment,estimateLevel,safeResume,resolvePage} from './domain.js';
import {cafeMenu} from './menu-design.js';
import {ART,POOLS,pickArt,PAGE_LABELS,CAFE_LINES} from './presentation.js';

const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const query=new URLSearchParams(location.search);
const scenario=null,previewMode=false;
const STORAGE='maidcafe-ui-v1';
let revision=0, saving=false, transaction=false, dirty=false, pendingAudio=null, pendingLocation=null, setupInfo=null, generationTimer=null;
let WORDS=[],S=freshState(),ui={menu:false,method:'binary',level:1,genMode:'3',selected:[],expanded:null,libraryTab:'all',search:'',busy:null,historyPos:0},audio=null,playback=null,toastTimer=null,modalReturn=null;
function loadArtCache(){try{return new Map(Object.entries(JSON.parse(sessionStorage.getItem(STORAGE+':art:v4')||'{}')).filter(([,art])=>Object.hasOwn(ART,art)));}catch{return new Map();}}
const artCache=loadArtCache(),lastArtByPage=new Map();let previousArt=null;
const dialogCodes={'单词手帖':'D01','认识一个新词':'D02','把词收进手帖':'D03','故事助手':'D04','恢复学习记录':'D05','测试完成':'D06','已经收进手帖':'D07'};
const iconPaths={cup:'M4 8h12v7a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V8Zm12 2h2a3 3 0 0 1 0 6h-2M3 22h16M8 2v3m5-3v3',back:'m14 5-7 7 7 7M7 12h13',play:'m8 5 11 7-11 7V5Z',pause:'M8 5v14M16 5v14',sound:'m11 5-6 5H2v4h3l6 5V5Zm4 3a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14',menu:'M4 6h16M4 12h16M4 18h16',book:'M3 4h6a4 4 0 0 1 3 2 4 4 0 0 1 3-2h6v15h-6a4 4 0 0 0-3 2 4 4 0 0 0-3-2H3V4Zm9 2v15',history:'M4 6V2M4 6h4M4 6a9 9 0 1 1-1 8M12 7v5l3 2',settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-6v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',check:'m5 12 4 4L20 5',close:'m6 6 12 12M6 18 18 6',arrow:'m9 5 7 7-7 7',spark:'m12 2 2.7 7.3L22 12l-7.3 2.7L12 22l-2.7-7.3L2 12l7.3-2.7L12 2Z',test:'M8 3h8v4H8V3Zm-3 2H3v17h18V5h-2M7 12h10M7 17h7',warning:'M12 8v5m0 3v1M12 2 1 21h22L12 2Z',download:'M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4',plus:'M12 4v16M4 12h16',leaf:'M20 3C8 2 1 8 5 16s15 3 15-13ZM5 20l9-10'};
const ico=(name='cup')=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${iconPaths[name]||iconPaths.cup}"/></svg>`;
const btn=(label,action,cls='',extra='')=>`<button class="btn ${cls}" data-action="${action}" ${extra}>${label}</button>`;
const textBtn=(label,action,extra='')=>`<button class="text-btn" data-action="${action}" ${extra}>${label}</button>`;
const back=(label='返回学习',action='return-study')=>`<button class="back" data-action="${action}">${ico('back')}${label}</button>`;
const wordById=id=>S.customWords.find(w=>w.id===id)||WORDS.find(w=>w.id===id);
const allWords=()=>[...new Map([...WORDS,...S.customWords].map(w=>[w.id,w])).values()];
const currentGroup=()=>S.replayTutorial||!S.welcomeComplete?S.tutorial:S.learning;
const tutorialMode=()=>!!S.replayTutorial||(!S.welcomeComplete&&S.tutorialStarted&&!S.tutorialComplete);
const brand=`<div class="brand"><span class="brand-seal" aria-hidden="true">${ico('cup')}</span><span class="brand-copy">MaidCafe<small>咖啡 · 姐姐们的故事</small></span></div>`;
function pageIdentity(page=S.page){let [code,label]=PAGE_LABELS[page]||['P00','进店准备'];if(['learn','group'].includes(page)&&tutorialMode()){code=page==='learn'?'P07-A':'P07-B';label=page==='learn'?'教学词卡':'教学对话';}if(page==='learn')label+=' · '+(currentGroup()?.revealed?'揭晓':'听词');if(page==='assessment')label+=' · '+(S.assessment?.phase==='know'?'看词':'听词');return{code,label};}
const protoMark=(page=S.page)=>{const {code,label}=pageIdentity(page);return `<div class="page-watermark" data-page-id="${code}" aria-label="页面 ${code}，${label}"><b>${code}</b><span>${label}</span></div>`;};
function cafeLine(g){if(!Number.isInteger(g.lineIndex)||!CAFE_LINES[g.lineIndex]){const choices=CAFE_LINES.map((_,i)=>i).filter(i=>i!==S.lastGroupLine);g.lineIndex=choices[Math.floor(Math.random()*choices.length)];S.lastGroupLine=g.lineIndex;dirty=true;}return CAFE_LINES[g.lineIndex];}

const artStyle=art=>`--room-width:${ART[art]?.roomWidth||'100%'};--room-left:${ART[art]?.roomLeft||'0px'};--room-position:${ART[art]?.room||'right center'};--art-position:${ART[art]?.position||'50% 40%'};--mobile-position:${ART[art]?.mobile||'50% 30%'}`;
function sceneArt(){
 if(S.settings.art==='fixed')return'momo-room-v4.png';
 const g=currentGroup();
 if(g&&['learn','group'].includes(S.page)){
  cafeLine(g);
  if(!g.art||!ART[g.art]){g.art=tutorialMode()?'momo-room-v4.png':pickArt(POOLS.learn,S.lastGroupArt);S.lastGroupArt=g.art;dirty=true;}
  return g.art;
 }
 const key=S.page,pool=POOLS[key]||['momo-room-v4.png'];
 if(!artCache.has(key)||!pool.includes(artCache.get(key)))artCache.set(key,pickArt(pool,previousArt));
 return previousArt=artCache.get(key);
}
function workHero(kicker,title,description,art){if(S.settings.art==='fixed')art='momo-room-v4.png';return`<div class="work-hero"><div class="work-hero-copy"><div class="eyebrow">${kicker}</div><h1>${title}</h1>${description?`<p class="lead">${description}</p>`:''}</div><figure class="work-hero-art" style="${artStyle(art)}"><img src="assets/${art}" alt="${ART[art]?.name||'女仆'} 在咖啡馆陪你坐一会儿"><figcaption>${ART[art]?.name||'maidcafe'} · 一杯咖啡的时间</figcaption></figure></div>`;}
function shell(content,{scene=true,title='咖啡的香气，今天也准时到了。',subtitle='',top=false}={}){
 const art=sceneArt(),character=ART[art];const quiet=S.settings.art==='quiet';
 const layout=document.documentElement.dataset.layout,person=['Momo','Suzu','Aoi','Haruka','Shizuku'].includes(character?.name)?character.name.toLowerCase():'momo';
 const conceptArt=layout==='g'?`<div class="manga-panel manga-person"><img src="assets/${art}" alt="${character.name} 在咖啡馆"><span aria-hidden="true">01 / COFFEE</span></div><div class="manga-panel manga-room"><img src="assets/rainy-table.webp" alt="窗边的咖啡桌"><span aria-hidden="true">02 / A LITTLE CHAT</span></div>`:layout==='h'?`<figure class="table-photo"><img src="assets/${art}" alt="${character.name} 的咖啡馆照片"><figcaption>${character.name} · at maidcafe</figcaption></figure>`:layout==='i'?`<img class="novel-character" src="assets/${person==='suzu'?'suzu-full-v4.png':person+'-full-v3.webp'}" alt="${character.name} 站在咖啡馆里">`:'';
 // Word cards use the scene; larger tools and conversations use the full sheet.
 const backdrop=layout==='b'&&!scene?'rainy-table.webp':art;
 const props=layout==='h'?'<div class="table-props" aria-hidden="true"><div class="linen"></div><div class="coffee-cup"><span></span></div><div class="coffee-spoon"></div></div>':'';
 return `<div class="app-shell ${scene?'scene-room':'wide-room'} ${quiet?'quiet':''}" data-screen="${esc(S.page)}" style="--scene-art:url(assets/${backdrop});${artStyle(backdrop)}">${!quiet?`<img class="shell-background" src="assets/${backdrop}" style="${artStyle(backdrop)}" alt="咖啡馆的完整背景插画">`:''}<header class="masthead">${brand}<span class="mast-note">喫茶と、ことば。</span></header>${props}${scene?`<main class="layout" ${quiet?'style="grid-template-columns:1fr;max-width:760px"':''}>${!quiet?`<aside class="scene" style="${artStyle(art)}">${conceptArt}<div class="scene-copy"><span class="scene-name"><strong>${character?.name||'maidcafe'}</strong><small>${character?.role||'窗边的位置'}</small></span><h2>${title}</h2>${subtitle?`<div class="line"></div><p>${subtitle}</p>`:''}</div></aside>`:''}<section class="content ${top?'top':''}">${layout==='i'?`<div class="novel-name" aria-hidden="true">${character.name}</div>`:''}${content}</section></main>`:`<main class="workroom">${content}</main>`}${menuMarkup()}${protoMark()}</div>`;
}
function menuMarkup(){if(!S.welcomeComplete||S.replayTutorial||['welcome','start','methods','level','assessment','result','welcome-end','error','boot'].includes(S.page))return'';return cafeMenu(ui.menu,ico);}

function persist(){dirty=true;}
function toast(msg){const el=$('#toast');el.textContent=msg;el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),3500);}
function stopAudio(){if(audio){audio.pause();audio=null;}if(playback)playback.playing=false;}
function go(page,{replace=false,keepAudio=false}={}){if(!keepAudio)stopAudio();ui.menu=false;S.page=page;persist();pendingLocation={page,replace};if(!transaction){applyLocation();render();}}
function applyLocation(){if(!pendingLocation)return;const {page,replace}=pendingLocation;pendingLocation=null;const url=new URL(location.href);url.hash='/'+page;history[replace?'replaceState':'pushState']({page},'',url);window.scrollTo({top:0,behavior:'instant'});}
function goTool(page){if(['learn','group','complete'].includes(S.page))S.returnPage=S.page;go(page);}
function returnStudy(){go(S.returnPage==='group'&&S.learning?.done?'group':S.learning?(S.learning.done?'group':'learn'):'complete');}
function soundMarkup(){return`<div class="sound-mark" aria-hidden="true">${'<i></i>'.repeat(11)}</div>`;}
function coach(text,detail=''){return`<div class="coach"><img src="assets/momo-avatar-v3.webp" alt=""><div><b>Momo</b> ${text}${detail?`<small>${detail}</small>`:''}</div></div>`;}
function welcomeView(){return`<main class="welcome" data-screen="welcome"><img src="assets/welcome-suzu-v4.png" alt="Suzu 在咖啡馆门口，端着咖啡迎接你"><div class="welcome-brand">${brand}</div><div class="welcome-note">喫茶と、ことば。</div><section class="invitation"><div class="host-tag"><strong>Suzu</strong><span>欢迎光临 MaidCafe</span></div><h1>咖啡刚煮好，<br>进来坐坐吧。</h1><p class="lead">让我们喝着咖啡来偷听姐姐们的叽叽喳喳吧</p>${btn('入座 '+ico('arrow'),'seat','primary')}<p class="welcome-signoff">窗边还有座位哦。</p></section>${protoMark()}</main>`;}
function startView(){return shell(`<div class="eyebrow">找到适合你的位置</div><h1>让我来看看你的水平。</h1><p class="lead">选择已经熟练掌握的词汇档位，<br>或者我们来做个小测试重新认识下你自己。</p><div class="choice-list"><button class="choice" data-action="go" data-page="methods"><span>${ico('test')}</span><span><strong>测试一下</strong><small>还不确定自己的水平？用几个词试试看。</small></span><span class="arrow">${ico('arrow')}</span></button><button class="choice" data-action="go" data-page="level"><span>${ico('book')}</span><span><strong>选择已掌握档位</strong><small>知道自己熟练掌握到哪里，就直接选择。</small></span><span class="arrow">${ico('arrow')}</span></button></div>${S.assessment&&!S.assessment.done?`<div class="rule"></div><div class="row spread"><span class="tiny">上次${methodName(S.assessment.method)}已完成 ${S.assessment.index} 词</span>${textBtn('继续上次测试 '+ico('arrow'),'resume-assessment')}</div>`:''}`,{title:'让我们先认识一下吧，<br>我叫 Momo。'});}
function methodName(m){return({binary:'二分测试',sample:'抽取测试',full:'疯狂测试'})[m];}
function methodsView(){const options=[['binary','二分测试','用较少的词，逐步找出掌握边界。','适合快速找到起点；可能漏掉零散的薄弱词。','逐段折半寻找边界；通常几十个词'],['sample','抽取测试','每个难度都抽几个词，看看整体情况。','覆盖更均衡；花的时间稍多，仍可能漏掉个别词。','每个 100 词段抽 3 词'],['full','疯狂测试','词库里的词，一个个确认。','覆盖最完整，也最花时间；随时可以保存，下次继续。',`${WORDS.length-5} 个词`]];return shell(`${back('返回选择方式','go-start')}<h1>选一种你喜欢的测试。</h1><div class="choice-list">${options.map(([id,name,short,long,time])=>`<button class="choice ${ui.method===id?'active':''}" data-action="method" data-id="${id}" aria-pressed="${ui.method===id}"><span class="dot"></span><span><strong>${name}</strong><small>${short}</small><small>${long}</small>${ui.method===id?`<small>${time}</small>`:''}</span></button>`).join('')}</div><div class="action-row">${btn('开始','start-assessment','primary')}</div><p class="footer-note">测试进度会自动保存。下次回来，可以从上次的位置继续。</p>`,{top:true,title:'选一种舒服的方式。'});}
function levelView(){return shell(`${back('返回选择方式','go-start')}<div class="eyebrow">已掌握的词汇</div><h1>你已经熟练掌握到哪里？</h1><p class="lead">这里选择的是你已经熟练掌握的词汇。<br>确认后，我们会从下一阶段开始。</p><div class="level-list" role="group" aria-label="已经熟练掌握的档位">${LEVELS.map((l,i)=>`<button data-action="level" data-index="${i}" class="${ui.level===i?'active':''}" aria-pressed="${ui.level===i}">${l.name}</button>`).join('')}</div><div class="level-explainer">当前已熟练掌握：${LEVELS[ui.level].name}<b>接下来学习 ${LEVELS[ui.level].next}</b></div><div class="action-row">${btn('确认学习起点','confirm-level','primary')}</div>`,{title:'熟悉的词，就像常走的街道。'});}
function assessmentView(){const a=S.assessment;if(!a||a.done)return startView();const w=wordById(a.queue[a.index]);const phase=a.phase==='hear';const progress=a.method==='binary'?Math.min(90,a.answers.length*6):(a.index/a.queue.length)*100;return shell(`<div class="card-top"><span>${methodName(a.method)}</span><span>已完成 ${a.index} 词${a.method!=='binary'?` / ${a.queue.length}`:''}</span></div><div class="progress-line"><span style="width:${progress}%"></span></div><div class="eyebrow">${phase?'先听声音':'再看看这个词'}</div><div class="word-stage">${phase?soundMarkup()+'<div class="word veiled">· · ·</div><p class="tiny" style="margin-top:20px">不看拼写，能想起它的意思吗？</p>':`<div class="word">${esc(w.word)}</div><p class="tiny" style="margin-top:25px">看到拼写，认识这个词吗？</p>`}</div><div class="word-actions">${btn(phase?'听出来了':'认识','assessment-answer','primary',`data-known="yes"`)}${btn(phase?'没听出来':'不认识','assessment-answer','',`data-known="no"`)}</div><div class="assist-row">${textBtn(ico('sound')+' 重听','replay-word',`data-id="${w.id}"`)}</div><div class="rule"></div><div class="row spread"><span class="tiny">不用猜，按真实感觉选择就好。</span>${textBtn('下次继续','pause-assessment')}</div>`,{title:'咖啡的香气，今天也准时到了。'});}
function resultView(){const l=LEVELS[S.level??0];return shell(`<h1>我感觉我们已经彼此很熟悉了呢</h1><p class="lead">你当前熟练掌握的词汇档位</p><p class="serif" style="font-size:30px;margin:12px 0">${l.name}</p><div class="level-explainer">为你准备的下一阶段<b>${l.next}</b></div><p class="lead">使用 5 个简单的词，我来帮你熟悉一下吧。</p><div class="action-row">${btn('开始体验','start-tutorial','primary')}</div>`,{title:'原来，我们已经认识这么多了。'});}
function teachingMessage(g){
 if(g.round>1)return'这一轮只留下点过「再学一次」的词，按钮和刚才一样。';
 if(g.index===0)return g.revealed?'认识这个意思，点「学会了」；没记住，就点「再学一次」。':'先听发音，再点「翻开看看」。点「重听」可以再放一遍。';
 if(g.index===1)return g.revealed?'试试「再学一次」。这个词会留到下一轮再出现。':'每张卡都是同样的操作。先听，再翻开。';
 if(g.index===2){const hasStory=S.dialogues.some(d=>d.groupId===g.id&&d.single===g.ids[g.index]);return !g.revealed?'翻开以后，试试「生成对话」，看看这个词怎么用。':hasStory?'对话就在下面。听完，或直接用「学会了／再学一次」继续。':'点「生成对话」，只用眼前这一个生词；也可以直接继续翻卡。';}
 return'接着用相同的按钮学词。每轮结束后，还能为这一组生成对话。';
}
function learningControls(g,w){return `<div class="learning-controls" role="group" aria-label="词卡操作">${g.revealed?btn('学会了 <span class="key">1</span>','judge','primary','data-known="yes"'):btn('翻开看看 <span class="key">Space</span>','reveal','primary')}${btn(ico('sound')+' 重听','replay-word','tool-btn',`data-id="${w.id}"`)}${btn('再学一次 <span class="key">2</span>','judge','',`data-known="no" ${g.revealed?'':'disabled aria-label="再学一次，翻开词卡后可用"'}`)}${btn(ico('spark')+' 生成对话','single-story','tool-btn',!g.revealed||ui.busy?'disabled title="翻开词卡后可以生成对话"':'')}</div>`;}

function learnView(){
 const isTut=tutorialMode(),g=currentGroup();if(!g)return completeView();if(g.done)return groupView();const w=wordById(g.ids[g.index]);
 const stories=S.dialogues.filter(d=>d.groupId===g.id&&d.single===w.id),busy=ui.busy?.single===w.id;
 return shell(`<div class="card-top"><span>${isTut?'初次体验':g.kind==='old'?'背过的词':'新单词'} · ${g.round>1?'再学一轮':isTut?'五词小练习':'第 '+(S.queueIndex+1)+' 组'}</span><span>${g.index+1} / ${g.ids.length}</span></div><div class="progress-line"><span style="width:${g.index/g.ids.length*100}%"></span></div>${isTut?coach(teachingMessage(g)):''}<div class="word-stage">${g.revealed?`<div class="word">${esc(w.word)}</div><div class="word-meaning">${esc(w.meaning)}</div>`:soundMarkup()+'<div class="word veiled">· · ·</div><p class="tiny" style="margin-top:18px">先听发音，想想它的意思。</p>'}</div>${learningControls(g,w)}${busy||stories.length?`<div class="word-story">${busy?'<div class="loading-row"><span class="spinner"></span>正在准备这个词的对话…</div>':''}${stories.map(d=>dialogueCard(d)).join('')}</div>`:''}${isTut?'<p class="card-foot">这 5 个词只用于熟悉操作，不改变正式学习记录。</p>':''}`,{top:true,title:isTut?'让我用这几个词，陪你走一遍。':cafeLine(g)});
}
function groupView(){const g=currentGroup();if(!g)return completeView();const isTut=tutorialMode();const left=pending(g).length;const stories=S.dialogues.filter(d=>d.groupId===g.id);const count=ui.genMode==='custom'?ui.selected.length:Math.min(+ui.genMode,g.ids.length);const action=left?btn(`再学剩下的 ${left} 个词`,'retry-group','primary'):btn(isTut?'完成体验':S.queueIndex+1<S.queue.length?'下一组 '+ico('arrow'):'这一轮，先到这里','next-group','primary');return shell(`<div class="work-head"><div><div class="eyebrow">${isTut?'初次体验':'窗边的小对话'} · 当前词组 ${g.ids.length} 词</div><h1>大家是怎么使用这些词的呢？</h1></div></div>${isTut?coach(g.round>1?`这一轮的选词范围只有剩下的 ${g.ids.length} 个词。不足 3／5 个时，按实际数量生成；全部学会就可以完成体验。`:'随机挑几个词，或自己选最多 5 个。生成的对话会留在下面，不听也可以继续。'):''}<div class="group-layout"><section><p class="muted" style="margin-bottom:20px">从当前这组词里挑几个，听听大家怎么说</p><div class="segmented" role="group" aria-label="对话选词方式">${[['3','随机 3 词'],['5','随机 5 词'],['custom','自己选']].map(([v,l])=>`<button data-action="gen-mode" data-value="${v}" class="${ui.genMode===v?'active':''}" aria-pressed="${ui.genMode===v}">${l}</button>`).join('')}</div>${ui.genMode==='custom'?`<div class="select-area"><div class="row spread"><span class="tiny">点一下选中，再点一下取消</span><span class="tiny">已选 <b>${ui.selected.length}</b> / ${Math.min(5,g.ids.length)}</span></div><div class="word-chips">${g.ids.map(id=>`<button class="word-chip ${ui.selected.includes(id)?'selected':''}" data-action="select-word" data-id="${id}" aria-pressed="${ui.selected.includes(id)}" ${!ui.selected.includes(id)&&ui.selected.length>=5?'disabled':''}><span class="mark">${ui.selected.includes(id)?'✓':'+'}</span>${esc(wordById(id).word)}</button>`).join('')}</div></div>`:''}<div class="action-row">${btn(ui.busy?'<span class="spinner"></span> 故事正在准备…':ico('spark')+` 生成对话${count?' · '+count+' 词':''}`,'group-story','primary',ui.busy||!count?'disabled':'')}</div><p class="footer-note">${g.ids.length<3?'当前只有 '+g.ids.length+' 个词，按实际数量生成。':'每次生成都保留在下面，可以随时再听。'}</p><div class="story-list">${stories.length?stories.map(d=>dialogueCard(d)).join(''):`<div class="empty">${ico('cup')}<strong>这桌的故事，还没开始。</strong>选几个词，第一段对话就从这里开始。</div>`}</div></section><aside class="group-aside"><figure class="group-art-frame" style="${artStyle(sceneArt())}"><img class="group-art" src="assets/${sceneArt()}" alt="女仆在咖啡馆陪你听一会儿对话"></figure><h3>${left?'还有 '+left+' 个词，再练一轮。':'这一组，已经熟悉了。'}</h3><p class="tiny">${left?'学会的词已经记下了。下一轮，只练剩下的词。':'可以直接继续下一组，也可以留在这里再听一会儿。'}</p>${action}<p class="tiny" style="margin-top:12px;text-align:center">想听就听，也可以直接继续。</p></aside></div>`,{scene:false,title:'有些故事，要等咖啡喝到一半才开始。'});}
function welcomeEndView(){return shell(`<div class="eyebrow">欢迎体验完成</div><h1>欢迎体验结束，<br>现在正式开始。</h1><p class="lead">先听，再翻卡，选择「学会了」或「再学一次」。<br>想听怎么用，随时可以生成对话。</p><div class="rule"></div><p class="muted">接下来，从适合你的 <b>${LEVELS[S.level??0].next}</b> 开始。</p><div class="action-row">${btn('正式开始','begin-learning','primary')}</div>`,{title:'我会一直记得，你喜欢坐的地方的，常来哦。'});}
function completeView(){return shell(`<div class="eyebrow">这一段，先到这里</div><h1>这一轮的词，<br>已经学完了。</h1><p class="lead">学过的词和生成的对话都已保存。<br>可以再听一会儿，也可以下次再来。</p><div class="action-row">${btn('看看对话历史','tool','primary','data-page="history"')}</div><p class="footer-note">可以从菜单添加单词或导入词包；下次回来，会先安排到期复习。</p>`,{title:'杯底还留着一点咖啡的香气。'});}

function dialogueCard(d){if(d.status&&d.status!=='done')return `<article class="dialogue-card"><div class="dialogue-body"><h3>${d.status==='error'?'这段故事暂时没有准备好':d.status==='tts'?'姐姐们正在录音…':'姐姐们正在编故事…'}</h3><p class="tiny">${esc(d.report?.error||'可以继续学词，故事会留在这里。')}</p></div></article>`;const open=ui.expanded===d.id;return`<article class="dialogue-card" data-dialogue="${d.id}"><button class="dialogue-head" data-action="open-dialogue" data-id="${d.id}" aria-expanded="${open}"><span class="dialogue-icon">${ico('cup')}</span><span class="dialogue-title"><strong>${esc(d.title)}</strong><small>${d.turns.length} 句 · ${d.targets.length} 个词 · ${d.single?'单词小对话':'窗边对话'}</small></span><span class="arrow">${ico(open?'close':'arrow')}</span></button>${open?playerBody(d):''}</article>`;}
function tokenMarkup(text,d){const targets=d.targets.flatMap(id=>wordById(id)?.word.toLowerCase().split(' ')||[]);return text.split(/([A-Za-z]+(?:'[A-Za-z]+)?)/g).map(t=>/^[A-Za-z]/.test(t)?`<button class="token ${targets.includes(t.toLowerCase())?'target':''}" data-action="lookup-token" data-word="${esc(t)}">${esc(t)}</button>`:esc(t)).join('');}
function playerBody(d){const p=playback?.id===d.id?playback:null;return`<div class="dialogue-body"><div class="player-bar">${btn(ico(p?.playing?'pause':'play')+(p?.playing?' 暂停':' 播放'),'play-dialogue','small primary',`data-id="${d.id}"`)}${textBtn('上一句','previous-turn',`data-id="${d.id}" aria-label="上一句"`)}${textBtn('下一句','next-turn',`data-id="${d.id}" aria-label="下一句"`)}<span class="time">${p?Math.max(0,p.index+1):0} / ${d.turns.length}</span></div><div class="transcript">${d.turns.map((t,i)=>`<div class="turn ${p?.index===i?'current':''}" data-turn="${i}">${['momo','haruka','shizuku','suzu','aoi'].includes(t.speaker?.toLowerCase())?`<img class="avatar" src="assets/${t.speaker.toLowerCase()}-avatar-v3.webp" alt="">`:`<span class="avatar guest-avatar" aria-hidden="true">${esc((t.speaker||'?').slice(0,1))}</span>`}<div><span class="turn-speaker">${esc(t.speaker||'Momo')}</span><div class="turn-text ${p?.played.includes(i)?'':'veil'}">${p?.played.includes(i)?tokenMarkup(t.text,d):'● ● ●'}</div></div></div>`).join('')}</div><div class="dialogue-foot">英文随播放显示 · 点词可查看释义</div></div>`;}
function historyView(){const days={};for(const d of [...S.dialogues].sort((a,b)=>b.ts-a.ts)){if(d.tutorial)continue;const day=new Date(d.ts).toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric'});(days[day]??=[]).push(d);}return shell(`${back()}${workHero('对话历史','留在店里的故事','每一天的对话都收在这里。想起哪一段，就再听一遍。','reading-haruka-v3.webp')}${Object.entries(days).length?Object.entries(days).map(([day,ds])=>`<h2 class="history-day">${day}</h2><div class="stack">${ds.map(d=>`<button class="choice" data-action="history-dialogue" data-id="${d.id}"><span>${ico('cup')}</span><span><strong>${esc(d.title)}</strong><small>${new Date(d.ts).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} · ${d.turns.length} 句 · ${d.targets.length} 个词</small></span><span class="arrow">${ico('arrow')}</span></button>`).join('')}</div>`).join(''):`<div class="empty">${ico('history')}<strong>这里还很安静</strong>学习时生成的对话，会按天留在这里。</div>`}`,{scene:false,title:'书签夹住的那一页，还藏着昨天的故事。'});}
function historyPlayerView(){const d=S.dialogues.find(d=>d.id===ui.historyId||d.id===S.historyId);if(!d)return historyView();ui.expanded=d.id;return shell(`${back('返回对话历史','back-history')}${workHero(new Date(d.ts).toLocaleDateString('zh-CN')+' · 对话历史',esc(d.title),'英文随播放显示。遇到想查的词，点一下就好。','momo-room-v4.png')}${dialogueCard(d)}`,{scene:false,title:'熟悉的声音，又在桌边响起来了。'});}
function libraryView(){const data=allWords();const q=ui.search.trim().toLowerCase();const own=new Set([...S.recent,...S.customWords.map(w=>w.id),...Object.keys(S.mastery)]);const filtered=data.filter(w=>(ui.libraryTab==='all'||own.has(w.id))&&(!q||w.word.toLowerCase().includes(q)||w.meaning.includes(q)));return shell(`${back()}${workHero('词库与生词本','你的单词手帖','查一个词，记下一个新词，或把熟悉的词再学一遍。','study-aoi-v3.webp')}<div class="library-tools">${btn(ico('plus')+' 添加词','add-word','small')}${btn(ico('download')+' 导入','import','small')}</div><div class="segmented" role="group" aria-label="词库范围">${[['all','全部词库'],['mine','我的单词']].map(([v,l])=>`<button class="${ui.libraryTab===v?'active':''}" data-action="library-tab" data-value="${v}">${l}</button>`).join('')}</div><div class="searchbox"><input id="word-search" type="search" placeholder="查一个单词，或搜索中文意思" value="${esc(ui.search)}" aria-label="查词"><span class="tiny">${filtered.length} 词</span></div>${filtered.length?`<div class="word-list" tabindex="0" role="region" aria-label="词库列表，可滚动查看">${filtered.slice(0,300).map(w=>`<div class="word-row"><button class="row-action" data-action="replay-word" data-id="${w.id}" aria-label="听 ${esc(w.word)} 的发音">${ico('sound')}</button><button class="word-main text-btn" style="display:block;text-align:left;color:var(--ink)" data-action="lookup" data-id="${w.id}"><strong>${esc(w.word)}</strong><small>${esc(w.meaning)}</small></button><span class="pill ${S.mastery[w.id]?.known?'green':''}">${S.mastery[w.id]?.known?'已学过':own.has(w.id)?'学习中':'词库'}</span></div>`).join('')}</div>`:`<div class="empty"><strong>${q?'没有找到这个词':'这里还没有单词'}</strong>${q?'可以手动添加这个词，或导入词表。':'学过的词和你添加的词，都会收在这里。'}</div>`}<p class="footer-note">词库与学习记录保存在这台电脑上。</p>`,{scene:false,title:'有些词，见过以后就成了老朋友。'});}
function settingsView(){return shell(`${back()}${workHero('设置','让这里更合你的习惯。','学多少、看什么风景，都按你喜欢的来。','shizuku-room-v5.png')}<section class="settings-section"><h3>学习与店里的风景</h3><div class="setting-row"><div>每组词数<p>从下一组开始生效，这一组照原来的数量学完。</p></div><input class="field" id="group-size" aria-label="每组词数" type="number" min="1" max="100" value="${S.settings.size}"></div><div class="setting-row"><div>配图方式<p>换组时换个风景；同一组学习及剩余词重学时，画面保持不变。</p></div><select class="field" id="art-mode" aria-label="配图方式">${[['rotate','换组时换个风景'],['fixed','固定配图'],['quiet','安静阅读 · 减少配图']].map(([v,l])=>`<option value="${v}" ${S.settings.art===v?'selected':''}>${l}</option>`).join('')}</select></div></section><section class="settings-section"><h3>故事助手与配音</h3><div class="setting-row"><div>${S.settings.ready?'故事助手已准备好':'随时可以准备'}<p>本地 AI 生成对话，Kokoro 使用英音／美音配音。</p></div>${btn('查看助手','assistant','small')}</div></section><section class="settings-section"><h3>词库与学习记录</h3><div class="setting-actions">${btn('导入词包','import','small')}${btn('导出学习记录','backup','small')}${btn('从备份恢复','restore','small')}</div><p class="footer-note" style="margin-top:12px">备份包含学习进度、设置和对话文本；词包与配音文件保留在本机。</p></section><section class="settings-section"><h3>再看一遍</h3><div class="setting-actions">${textBtn('重看迎宾','revisit-welcome')}${textBtn('重看五词教学','revisit-tutorial')}${textBtn('打开校准工具','recalibrate')}${textBtn('下载入门词包','download-starter')}</div></section><p class="footer-note">调整会自动保存。</p>`,{scene:false,title:'那本菜单的角落，藏着一颗小星星。'});}
function examSelectView(){const words=allWords();const recent=[...new Set(S.recent)].slice(0,30);const blocks=chunks(words.slice(5),100);const items=S.examRange==='recent'?recent.map(id=>({id,title:wordById(id).word,desc:wordById(id).meaning})):blocks.map((g,i)=>({id:'block-'+i,title:'词段 '+(i+1),desc:`${g.length} 个词 · 第 ${i*100+1}–${i*100+g.length} 词`}));const n=S.examRange==='recent'?S.examSelection.length:S.examSelection.reduce((sum,b)=>sum+(blocks[+b.split('-')[1]]?.length||0),0);return shell(`${back()}${workHero('主动考试','看看现在，记住了多少。','选一些学过的词，轻轻检查一下。只统计这次回答，不改变学习记录。','welcome-suzu-v4.png')}<div class="segmented" style="margin-top:25px" role="group" aria-label="考试范围"><button class="${S.examRange==='recent'?'active':''}" data-action="exam-range" data-value="recent">最近学习的词 · 最多 10 个</button><button class="${S.examRange==='blocks'?'active':''}" data-action="exam-range" data-value="blocks">按词段选择</button></div><div class="checklist">${items.map(item=>`<label class="check-item"><input type="checkbox" data-exam-id="${item.id}" ${S.examSelection.includes(item.id)?'checked':''} ${S.examRange==='recent'&&!S.examSelection.includes(item.id)&&S.examSelection.length>=10?'disabled':''}><span><strong>${esc(item.title)}</strong><small>${esc(item.desc)}</small></span></label>`).join('')}</div>${!items.length?'<div class="empty">先认识几个词，再回来试试。也可以选择词段。</div>':''}<div class="action-row">${btn(`开始测试${n?' · '+n+' 词':''}`,'start-exam','primary',n?'':'disabled')}</div>`,{scene:false,title:'书里的一个词，今天又见面了。'});}
function examView(){const ex=S.exam;if(!ex)return examSelectView();if(ex.done)return examResultView();const w=wordById(ex.ids[ex.index]);return shell(`${back('返回学习','quit-exam')}<div class="card-top"><span>主动考试</span><span>${ex.index+1} / ${ex.ids.length}</span></div><div class="progress-line"><span style="width:${ex.index/ex.ids.length*100}%"></span></div><div class="word-stage">${ex.revealed?`<div class="word">${esc(w.word)}</div><div class="word-meaning">${esc(w.meaning)}</div>`:soundMarkup()+'<div class="word veiled">· · ·</div><p class="tiny" style="margin-top:20px">先听声音，在心里想想它的意思。</p>'}</div><div class="exam-controls" role="group" aria-label="考试词卡操作">${ex.revealed?btn('认识','exam-answer','primary','data-known="yes"'):btn('翻开看看','exam-reveal','primary')}${btn(ico('sound')+' 重听','replay-word','',`data-id="${w.id}"`)}${btn('还不熟','exam-answer','',`data-known="no" ${ex.revealed?'':'disabled aria-label="还不熟，翻开词卡后可用"'}`)}</div><p class="card-foot">只统计本次回答，不改变学习记录。</p>`,{title:'书里的一个词，今天又见面了。'});}
function examResultView(){const ex=S.exam;if(!ex)return examSelectView();const r=examResult(ex);return shell(`<div class="eyebrow">本次测试 · ${ex.ids.length} 个词</div><h1>现在的掌握情况，<br>在这里。</h1><div class="stats"><div class="stat"><b>${r.known}</b><small>已经掌握</small></div><div class="stat"><b>${r.unknown}</b><small>尚需掌握</small></div></div><p class="tiny center">学习记录和原来的进度保持不变。</p><div class="action-row">${btn('返回学习','return-study','primary')}</div>`,{title:'原来，这些词已经住进记忆里了。'});}
function errorView(){return shell(`<div class="error-icon">${ico('warning')}</div><div class="eyebrow">这里需要重新准备一下</div><h1>刚才卡住了一下。</h1><p class="lead">${esc(S.errorMessage||'这段对话暂时没有准备好。')}<br>重新准备一下，就可以接着来。</p><p class="tiny" style="margin-top:18px">已经保存的进度、词库和设置都会保留。</p><div class="action-row">${btn('返回开始','recover','primary')}</div>`,{title:'我去看看，是哪儿出了点小状况。'});}

function render(){
 if(transaction)return;
 const focus=document.activeElement?.id,sel=document.activeElement?.selectionStart;
 const views={welcome:welcomeView,start:startView,methods:methodsView,level:levelView,assessment:assessmentView,result:resultView,learn:learnView,group:groupView,'welcome-end':welcomeEndView,complete:completeView,history:historyView,player:historyPlayerView,library:libraryView,settings:settingsView,'exam-select':examSelectView,exam:examView,'exam-result':examResultView,error:errorView};
 $('#app').innerHTML=(views[S.page]||welcomeView)();
 if(previewMode&&parent!==window)parent.postMessage({type:'maidcafe-preview-page',page:S.page,scene:S.page==='learn'&&tutorialMode()?'tutorial':S.page},location.origin);
 if(focus&&document.getElementById(focus)){const input=document.getElementById(focus);input.focus({preventScroll:true});try{input.setSelectionRange(sel,sel);}catch{}}
}

async function playWord(id){
 if(transaction){pendingAudio=id;return;}
 const w=wordById(id);if(!w)return;stopAudio();
 const clip=new Audio('/api/cafe/word-audio?word='+encodeURIComponent(w.word));audio=clip;
 document.querySelector('.sound-mark')?.classList.add('playing');
 clip.onended=()=>document.querySelector('.sound-mark')?.classList.remove('playing');
 clip.onerror=()=>{if(audio===clip){document.querySelector('.sound-mark')?.classList.remove('playing');toast('词汇配音暂时无法读取，请在设置中检查配音资源后重听。');}};
 try{await clip.play();}catch(error){if(audio===clip&&error.name!=='AbortError'&&error.name!=='NotAllowedError')toast('词汇配音正在准备，请稍后重听。');}
}
function refreshPlayers(){const d=S.dialogues.find(x=>x.id===playback?.id);if(!d)return;document.querySelectorAll(`[data-dialogue="${d.id}"] .dialogue-body`).forEach(el=>{el.outerHTML=playerBody(d);});document.querySelector(`[data-dialogue="${d.id}"] .turn.current`)?.scrollIntoView({block:'nearest',behavior:'smooth'});}
function playTurn(d,index){if(index<0||index>=d.turns.length)return;if(audio)audio.pause();const played=playback?.id===d.id?playback.played:[];if(!played.includes(index))played.push(index);playback={id:d.id,index,playing:true,played};const clip=new Audio(d.turns[index].audio);audio=clip;clip.onended=()=>{if(audio!==clip||!playback?.playing||playback.id!==d.id)return;if(index+1<d.turns.length)playTurn(d,index+1);else{playback.playing=false;refreshPlayers();}};clip.play().catch(error=>{if(audio!==clip||error.name==='AbortError')return;if(playback)playback.playing=false;refreshPlayers();toast('音频暂时没有播放，请再点一次播放。');});refreshPlayers();}
function togglePlay(id){const d=S.dialogues.find(x=>x.id===id);if(!d)return;if(playback?.id===id&&playback.playing){audio?.pause();playback.playing=false;refreshPlayers();return;}if(playback?.id===id&&audio&&audio.currentTime>0&&!audio.ended){playback.playing=true;audio.play().catch(()=>{playback.playing=false;refreshPlayers();});refreshPlayers();}else playTurn(d,playback?.id===id&&playback.index<d.turns.length-1?playback.index:0);}
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw Error(value.error||'操作未完成，请重试。');return value;}
async function save(intent={}){if(!dirty)return;const result=await api('/api/cafe/state',{revision,state:{...S,dialogues:[]},intent});revision=result.revision;S.revision=revision;dirty=false;}
async function perform(fn,intent={}){
 if(saving)return;
 const before=structuredClone(S);saving=true;transaction=true;dirty=false;pendingAudio=null;
 try{
  await fn();sceneArt();
  await save(intent);
  transaction=false;applyLocation();render();
  if(pendingAudio){const id=pendingAudio;pendingAudio=null;playWord(id);}
 }catch(error){S=before;pendingAudio=null;pendingLocation=null;transaction=false;closeModal();S.errorMessage=error.message;S.errorReturn=S.page;S.page='error';render();}
 finally{transaction=false;saving=false;}
}
async function refreshDialogues(){S.dialogues=await api('/api/cafe/dialogues');const pending=S.dialogues.find(d=>['writing','tts'].includes(d.status));ui.busy=pending?{id:pending.id,groupId:pending.groupId}:null;if(!saving)render();if(pending){clearTimeout(generationTimer);generationTimer=setTimeout(()=>refreshDialogues().catch(e=>toast(e.message)),1800);}}
async function generateStory(single=false){
 if(ui.busy)return;const g=currentGroup();if(!g)return;
 const ids=single?[g.ids[g.index]]:ui.genMode==='custom'?chosenTargets(g,ui.selected):randomTargets(g,+ui.genMode);
 if(!ids.length){toast('先选 1–5 个词，就可以生成。');return;}
 setupInfo=await api('/api/setup');S.settings.ready=setupInfo.ready;
 if(!setupInfo.ready){await assistantModal();return;}
 const result=await api('/api/cafe/generate',{ids,groupId:g.id,single:single?ids[0]:null,tutorial:tutorialMode()});
 ui.busy={id:result.id,groupId:g.id};ui.expanded=result.id;
 await refreshDialogues();
}
function openModal(title,html){modalReturn=document.activeElement;$('#modal').innerHTML=`<div class="modal-overlay"><section class="modal-card" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="modal-head"><h2><small class="dialog-watermark">${dialogCodes[title]||'D00'}</small>${title}</h2><button class="close-btn" data-action="modal-close" aria-label="关闭">${ico('close')}</button></div>${html}</section></div>`;setTimeout(()=>$('#modal input:not([type=file]), #modal textarea, #modal button')?.focus(),0);}
function closeModal(){const wasLookup=!!$('#modal [data-lookup-card]'),resume=ui.resumeAudio;ui.resumeAudio=null;$('#modal').innerHTML='';modalReturn?.focus?.({preventScroll:true});if(wasLookup&&resume){audio?.pause();audio=resume.audio;playback=resume.playback;playback.playing=true;const clip=audio;clip.play().catch(error=>{if(audio!==clip||error.name==='AbortError')return;playback.playing=false;refreshPlayers();});refreshPlayers();}}
function lookup(w){if(!w)return;ui.resumeAudio=playback?.playing&&audio?{audio,playback}:null;if(audio)audio.pause();if(playback)playback.playing=false;refreshPlayers();const known=S.mastery[w.id]?.known;const mine=S.recent.includes(w.id)||!!S.mastery[w.id]||S.customWords.some(x=>x.id===w.id);openModal('单词手帖',`<div data-lookup-card><div class="word">${esc(w.word)}</div><div class="definition">${esc(w.meaning)}</div>${textBtn(ico('sound')+' 听发音','replay-word',`data-id="${w.id}"`)}${w.example?`<p class="example">${esc(w.example)}</p>`:''}<div class="action-row">${known?btn('再学一遍','readd','primary',`data-id="${w.id}"`):mine?'<span class="pill green">已经在你的单词手帖里</span>':btn('加入生词本','add-existing','primary',`data-id="${w.id}"`)}</div><p class="tiny" style="margin-top:18px">${ui.resumeAudio?'已为你暂停，关闭后继续。':'添加与重学会保留当前正在学习的词组。'}</p></div>`);}
function addWordModal(){openModal('认识一个新词',`<label class="tiny" for="new-word">英文单词或短语</label><input class="field" id="new-word" autocomplete="off" placeholder="例如 gentle"><label class="tiny" for="new-meaning" style="display:block;margin:15px 0 5px">释义（可选）</label><input class="field" id="new-meaning" placeholder="写下方便你记住的意思"><p class="tiny" style="margin-top:14px">可填写自己的释义，也可以使用词库中的解释。</p><div class="action-row">${btn('加入生词本','save-word','primary')}</div><p id="new-word-error" class="tiny" role="status"></p>`);}
function importModal(){openModal('把词收进手帖',`<p class="muted">粘贴词表，或从文件里带过来。</p><textarea id="import-text" class="field" rows="5" placeholder="一行一个词\ngentle 轻柔的\nborrow 借用" style="margin-top:15px"></textarea><div class="row" style="margin-top:15px">${btn('选择 .txt 文件','choose-text','small')}${btn('选择 Anki 词包','choose-deck','small')}</div><input class="native-file" id="txt-file" type="file" accept=".txt,text/plain"><input class="native-file" id="apkg-file" type="file" accept=".apkg"><div class="action-row">${btn('导入词表','import-text','primary')}</div><p class="tiny" style="margin-top:16px">支持文字词表与 Anki .apkg 词包。已有学习记录会保留。</p><p id="import-status" class="tiny" role="status"></p>`);}
async function assistantModal(){
 setupInfo=await api('/api/setup');const info=setupInfo,job=info.install||{};S.settings.ready=info.ready;
 openModal('故事助手',`<p class="muted">对话在这台电脑生成。选一个方案，一键下载并配置好。</p><div class="readiness"><span class="pill ${info.ready?'green':''}">${info.ready?'故事助手已就绪':'尚未准备'}</span><p class="tiny" style="margin-top:10px">配音：Kokoro · 英音／美音</p></div><label class="tiny" for="model-profile">助手方案</label><select class="field" id="model-profile"><option value="standard" ${S.settings.model==='standard'?'selected':''}>标准助手 · 约 2.5 GB</option><option value="light" ${S.settings.model==='light'?'selected':''}>轻量助手 · 约 1.4 GB</option></select><div id="assistant-progress" class="tiny" role="status" style="margin-top:15px">${esc(job.message||info.message)}</div><div class="action-row">${btn(job.active?'正在准备…':info.ready?'重新检测':'一键准备','prepare-assistant','primary',job.active?'disabled':'')}${job.active?btn('暂停下载','cancel-assistant'):''}</div>${info.models.length?`<details style="margin-top:18px"><summary class="tiny">使用电脑中已有的模型</summary><select class="field" id="existing-model">${info.models.map(m=>`<option value="${esc(m)}" ${m===info.model?'selected':''}>${esc(m)}</option>`).join('')}</select>${textBtn('使用这个助手','use-assistant')}</details>`:''}`);
 if(job.active)pollSetup();
}
async function pollSetup(){
 if(!$('#assistant-progress'))return;
 try{const info=await api('/api/setup'),job=info.install||{};const out=$('#assistant-progress');if(!out)return;
 out.innerHTML=esc(job.message||info.message)+(job.total>0?`<progress max="${job.total}" value="${job.completed}" aria-label="下载进度"></progress><p>${Math.floor(job.completed/job.total*100)}%</p>`:'');
 if(job.active)setTimeout(pollSetup,1200);else{S.settings.ready=info.ready;await assistantModal();}
 }catch(e){const out=$('#assistant-progress');if(out)out.textContent=e.message;}
}
function downloadJSON(data,name){const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
function addExisting(id){S.recent=[id,...S.recent.filter(x=>x!==id)];S.mastery[id]??={known:false,seen:Date.now()};queueAddedWord(id);persist();}
function queueAddedWord(id,force=false){if(!S.welcomeComplete)return;if(S.learning?.rootIds.includes(id)&&!force)return;if(S.queue.slice(S.queueIndex+1).some(g=>g.ids.includes(id)))return;S.queue.push({kind:'new',ids:[id]});if(!S.learning){S.queueIndex=S.queue.length-1;S.learning=createGroup([id],'new','batch-'+(++S.serial));S.returnPage='learn';}}
function saveNewWord(){const word=$('#new-word').value.trim().toLowerCase();if(!/^[a-z]+(?:[ '-][a-z]+){0,3}$/.test(word)){$('#new-word-error').textContent='请输入英文单词或短语。';return;}let w=allWords().find(x=>x.word.toLowerCase()===word);if(!w){w={id:word,word,meaning:$('#new-meaning').value.trim()||'我的单词',example:'',band:S.level??0};S.customWords.push(w);}if(S.mastery[w.id]?.known){lookup(w);toast('这个词已经学过，可点「再学一遍」。');return;}addExisting(w.id);closeModal();render();toast('已加入生词本，当前词组保持不变。');}
function parseImport(text){const rows=text.split(/[\n,，;；]+/).map(s=>s.trim()).filter(Boolean).slice(0,500);let added=0,skipped=0;for(const row of rows){const m=row.replace(/^\d+[.)、\s]+/,'').match(/^([a-zA-Z]+(?:[ '-][a-zA-Z]+){0,3})(.*)$/);if(!m)continue;const word=m[1].trim().toLowerCase();let w=allWords().find(x=>x.word===word);if(w&&(S.mastery[w.id]||S.recent.includes(w.id))){skipped++;continue;}if(!w){w={id:word,word,meaning:m[2].trim()||'导入的词',example:'',band:S.level??0};S.customWords.push(w);}addExisting(w.id);added++;}persist();return{added,skipped};}
function beginTutorial(replay=false){S.replayTutorial=replay;S.tutorialStarted=true;if(!replay)S.tutorialComplete=false;S.tutorialStep=0;S.tutorial=createGroup(WORDS.slice(0,5).map(w=>w.id),'new','tutorial-'+(++S.serial));ui.expanded=null;go('learn');playWord(S.tutorial.ids[0]);}
function prepareStudy(){startQueue(S,allWords());S.returnPage=S.learning?'learn':'complete';go(S.returnPage);if(S.learning)playWord(S.learning.ids[0]);}
function startAssessment(){if(S.assessment)S.assessmentArchive.push(S.assessment);S.assessment=createAssessment(ui.method,WORDS);go('assessment');playWord(S.assessment.queue[0]);}
function finishAssessment(){const lv=estimateLevel(S.assessment,WORDS);if(!S.recalibrating)S.learningFrontier=S.assessment.frontier;if(S.recalibrating){S.calibrationResult=lv;openModal('测试完成',`<p class="lead">本次词汇档位：${LEVELS[lv].name}</p><p class="tiny" style="margin-top:15px">本次结果单独保留，不覆盖已有学习进度。</p><div class="action-row">${btn('返回设置','finish-recalibration','primary')}</div>`);}else{S.level=lv;go('result');}}

async function action(el){
 const a=el.dataset.action,id=el.dataset.id;
 if(a==='go'){go(el.dataset.page);return;}
 if(a==='seat'){if(S.previewReturn){const p=S.previewReturn;S.previewReturn=null;go(p);}else{S.seated=true;go('start');}return;}
 if(a==='go-start'){if(S.recalibrating){S.recalibrating=false;go('settings');}else go('start');return;}
 if(a==='method'){ui.method=id;render();return;}
 if(a==='level'){ui.level=+el.dataset.index;render();return;}
 if(a==='confirm-level'){S.learningFrontier=null;S.level=ui.level;go('result');return;}
 if(a==='start-assessment'){startAssessment();return;}
 if(a==='resume-assessment'){go('assessment');if(S.assessment.phase==='hear')playWord(S.assessment.queue[S.assessment.index]);return;}
 if(a==='pause-assessment'){go(S.recalibrating?'settings':'start');return;}
 if(a==='assessment-answer'){
  const yes=el.dataset.known==='yes';const assess=S.assessment;
  if(assess.phase==='hear'){assess.heard=yes;assess.phase='know';persist();render();}
  else{answerAssessment(assess,yes);persist();if(assess.done)finishAssessment();else{render();playWord(assess.queue[assess.index]);}}return;
 }
 if(a==='start-tutorial'){beginTutorial();return;}
 if(a==='reveal'){const g=currentGroup();g.revealed=true;persist();render();return;}
 if(a==='judge'){
  const g=currentGroup();if(!g?.revealed)return;const pass=el.dataset.known==='yes';
  if(tutorialMode()){judgeGroup(g,pass);S.tutorialStep=g.index;}
  else recordStudy(S,pass);
  ui.expanded=null;persist();if(g.done){ui.selected=[];ui.genMode='3';go('group');}else{render();playWord(g.ids[g.index]);}return;
 }
 if(a==='replay-word'){playWord(id);return;}
 if(a==='single-story'){await generateStory(true);return;}
 if(a==='gen-mode'){ui.genMode=el.dataset.value;render();return;}
 if(a==='select-word'){if(ui.selected.includes(id))ui.selected=ui.selected.filter(x=>x!==id);else if(ui.selected.length<5)ui.selected.push(id);render();return;}
 if(a==='group-story'){await generateStory(false);return;}
 if(a==='retry-group'){if(retryGroup(currentGroup())){ui.selected=[];ui.expanded=null;go('learn');playWord(currentGroup().ids[0]);}return;}
 if(a==='next-group'){
  const g=currentGroup();if(!canAdvance(g)){toast('先把本组剩下的词再过一遍。');return;}
  if(tutorialMode()){if(S.replayTutorial){S.replayTutorial=false;go('settings');}else{S.tutorialComplete=true;go('welcome-end');}}
  else{advanceQueue(S);ui.selected=[];ui.expanded=null;go(S.learning?'learn':'complete');if(S.learning)playWord(S.learning.ids[0]);}return;
 }
 if(a==='begin-learning'){S.welcomeComplete=true;prepareStudy();return;}
 if(a==='menu'){ui.menu=!ui.menu;render();return;}
 if(a==='menu-close'){ui.menu=false;render();return;}
 if(a==='tool'){goTool(el.dataset.page);return;}
 if(a==='return-study'){returnStudy();return;}
 if(a==='open-dialogue'){stopAudio();ui.expanded=ui.expanded===id?null:id;render();return;}
 if(a==='play-dialogue'){togglePlay(id);return;}
 if(a==='previous-turn'||a==='next-turn'){const d=S.dialogues.find(x=>x.id===id);if(d)playTurn(d,Math.max(0,Math.min(d.turns.length-1,(playback?.id===id?playback.index:0)+(a==='next-turn'?1:-1))));return;}
 if(a==='history-dialogue'){ui.historyPos=window.scrollY;ui.historyId=id;S.historyId=id;go('player');return;}
 if(a==='back-history'){go('history');requestAnimationFrame(()=>window.scrollTo(0,ui.historyPos));return;}
 if(a==='lookup'){lookup(wordById(id));return;}
 if(a==='lookup-token'){const word=el.dataset.word.toLowerCase(),w=allWords().find(w=>w.word.toLowerCase()===word);if(w)lookup(w);else{const d=await api('/api/lookup?word='+encodeURIComponent(word));openModal(esc(word),`<p class="definition">${esc(d.definition||'词库暂未收录，可以写下自己的释义。')}</p>${textBtn('添加到我的单词','add-token',`data-word="${esc(word)}"`)}`);}return;}
 if(a==='modal-close'){closeModal();return;}
 if(a==='add-token'){const w=el.dataset.word;addWordModal();$('#new-word').value=w;return;}
 if(a==='add-existing'){addExisting(id);closeModal();render();toast('已加入生词本。');return;}
 if(a==='readd'){S.mastery[id]={known:false,seen:Date.now()};S.recent=[id,...S.recent.filter(x=>x!==id)];queueAddedWord(id,true);persist();closeModal();render();toast('已重新加入后续学习，当前词组保持不变。');return;}
 if(a==='library-tab'){ui.libraryTab=el.dataset.value;render();return;}
 if(a==='add-word'){addWordModal();return;}
 if(a==='save-word'){saveNewWord();return;}
 if(a==='import'){importModal();return;}
 if(a==='choose-text'){document.getElementById('txt-file').click();return;}
 if(a==='choose-deck'){document.getElementById('apkg-file').click();return;}
 if(a==='import-text'){const txt=$('#import-text').value.trim();if(!txt){$('#import-status').textContent='先粘贴一些词，或选择词表文件。';return;}const r=parseImport(txt);openModal('已经收进手帖',`<div class="stats"><div class="stat"><b>${r.added}</b><small>新增词</small></div><div class="stat"><b>${r.skipped}</b><small>已存在，保留原记录</small></div></div><div class="action-row">${btn('查看单词手帖','import-done','primary')}</div>`);return;}
 if(a==='import-done'){closeModal();ui.libraryTab='mine';ui.search='';go('library');return;}
 if(a==='assistant'){await assistantModal();return;}
 if(a==='prepare-assistant'){if(setupInfo?.ready&&$('#model-profile').value===S.settings.model){await assistantModal();return;}S.settings.model=$('#model-profile').value;await api('/api/setup/prepare',{profile:S.settings.model});await assistantModal();persist();return;}
 if(a==='cancel-assistant'){await api('/api/setup/cancel',{});await assistantModal();return;}
 if(a==='use-assistant'){await api('/api/setup',{model:$('#existing-model').value});await assistantModal();persist();return;}
 if(a==='backup'){const link=document.createElement('a');link.href='/api/backup';link.download='MaidCafe-records.json';link.click();return;}
 if(a==='restore'){openModal('恢复学习记录',`<p class="muted">选择 MaidCafe 导出的 JSON 备份。</p><p class="tiny" style="margin:15px 0">仅可在没有学习记录的安装中恢复，避免覆盖已有进度。</p><input class="field" id="restore-file" type="file" accept=".json"><p id="restore-status" class="tiny" role="status" style="margin-top:15px"></p>`);return;}
 if(a==='revisit-welcome'){S.previewReturn='settings';go('welcome');return;}
 if(a==='revisit-tutorial'){beginTutorial(true);return;}
 if(a==='recalibrate'){S.recalibrating=true;go('methods');return;}
 if(a==='finish-recalibration'){S.recalibrating=false;closeModal();go('settings');return;}
 if(a==='download-starter'){const link=document.createElement('a');link.href='/window-seat.apkg';link.download='maidcafe-window-seat.apkg';link.click();return;}
 if(a==='exam-range'){S.examRange=el.dataset.value;S.examSelection=[];persist();render();return;}
 if(a==='start-exam'){
  const blocks=chunks(allWords().slice(5),100);const ids=S.examRange==='recent'?S.examSelection:S.examSelection.flatMap(b=>blocks[+b.split('-')[1]]?.map(w=>w.id)||[]);if(!ids.length)return;
  S.exam=createExam(ids);go('exam');playWord(ids[0]);return;
 }
 if(a==='exam-reveal'){S.exam.revealed=true;persist();render();return;}
 if(a==='exam-answer'){if(!S.exam?.revealed)return;answerExam(S.exam,el.dataset.known==='yes');persist();if(S.exam.done)go('exam-result');else{render();playWord(S.exam.ids[S.exam.index]);}return;}
 if(a==='quit-exam'){S.exam=null;returnStudy();return;}
 if(a==='recover'){ui.busy=null;ui.menu=false;closeModal();await boot();return;}
}
function SafeReturn(){if(S.welcomeComplete&&['settings','library','history'].includes(S.errorReturn))return S.errorReturn;return safeResume(S);}
document.addEventListener('click',e=>{const el=e.target.closest('[data-action]');if(el&&!el.disabled){e.preventDefault();(el.dataset.action==='recover'?action(el):perform(()=>action(el),{action:el.dataset.action,id:el.dataset.id,known:el.dataset.known}));}});
document.addEventListener('input',e=>{if(e.target.id==='word-search'){ui.search=e.target.value;render();}});
document.addEventListener('change',e=>perform(async()=>{
 const t=e.target;
 if(t.id==='model-profile'){const button=$('#modal [data-action=prepare-assistant]');if(button)button.textContent=t.value===S.settings.model&&setupInfo?.ready?'重新检测':'准备所选方案';}
 if(t.id==='group-size'){const value=Number(t.value);if(!Number.isInteger(value)||value<1||value>100){toast('每组词数可以设置为 1–100。');t.value=S.settings.size;return;}S.settings.size=value;const rest=S.queue.slice(S.queueIndex+1);const groups=[];for(const kind of ['old','new'])for(const ids of chunks(rest.filter(g=>g.kind===kind).flatMap(g=>g.ids),value))groups.push({kind,ids});S.queue=S.queue.slice(0,S.queueIndex+1).concat(groups);persist();toast('已保存，从下一组开始生效。');}
 if(t.id==='art-mode'){S.settings.art=t.value;persist();render();toast('已保存配图方式。');}
 if(t.dataset.examId){const id=t.dataset.examId;if(t.checked){if(S.examRange==='recent'&&S.examSelection.length>=10){t.checked=false;return;}S.examSelection.push(id);}else S.examSelection=S.examSelection.filter(x=>x!==id);persist();render();}
 if(t.id==='txt-file'&&t.files[0]){if(t.files[0].size>1024*1024){$('#import-status').textContent='支持 1 MB 以内的文字词表。';return;}$('#import-text').value=await t.files[0].text();}
 if(t.id==='apkg-file'&&t.files[0]){const f=t.files[0];const out=$('#import-status');out.textContent='正在读取词包…';const r=await fetch('/api/decks/import?name='+encodeURIComponent(f.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:f});const data=await r.json();if(!r.ok)throw Error(data.error||'导入失败');const previousIds=new Set(WORDS.map(w=>w.id));const snap=await api('/api/cafe/bootstrap');WORDS=snap.words;const added=WORDS.filter(w=>!w.tutorial&&!previousIds.has(w.id)).map(w=>w.id);for(const ids of chunks(added,S.settings.size))S.queue.push({kind:'new',ids});if(!S.learning&&S.welcomeComplete&&added.length){S.queueIndex=S.queue.length-Math.ceil(added.length/S.settings.size);S.learning=createGroup(S.queue[S.queueIndex].ids,'new','batch-'+(++S.serial));S.returnPage='learn';}persist();out.textContent=`已导入 ${data.words} 个词。`;toast('词包已导入，完成当前学习后会安排新增词。');}
 if(t.id==='restore-file'&&t.files[0]){if(t.files[0].size>32*1024*1024)throw Error('请选择 32 MB 以内的备份。');await api('/api/restore',JSON.parse(await t.files[0].text()));closeModal();await boot();toast('学习记录已恢复。');}
}));
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'){if($('#modal').innerHTML){closeModal();return;}if(ui.menu){ui.menu=false;render();return;}}
 if($('#modal').innerHTML){if(e.key==='Tab'){const nodes=[...document.querySelectorAll('#modal button:not(:disabled),#modal input,#modal select,#modal textarea,#modal a')];const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}return;}
 if(e.target.closest('input,textarea,select,button,a'))return;
 if(S.page==='learn'){const g=currentGroup();if(e.code==='Space'&&!g.revealed){e.preventDefault();document.querySelector('[data-action="reveal"]')?.click();}if(g.revealed&&['1','2'].includes(e.key)){e.preventDefault();document.querySelector(`[data-action="judge"][data-known="${e.key==='1'?'yes':'no'}"]`)?.click();}if(e.key.toLowerCase()==='r')playWord(g.ids[g.index]);}
});
window.addEventListener('maidcafe-design-change',e=>{if(previewMode&&window.__maidcafePrototype){if(e.detail?.showMenu&&S.welcomeComplete&&!S.replayTutorial)ui.menu=true;render();}});
window.addEventListener('popstate',()=>perform(()=>{closeModal();go(resolvePage(S,location.hash.replace('#/','')),{replace:true});}));

async function bootScreen(){stopAudio();$('#app').innerHTML=`<main class="welcome" data-screen="boot"><img src="assets/arrival-morning-v3.webp" alt="清晨的咖啡馆"><div class="welcome-brand">${brand}</div><div class="loading-card"><div class="eyebrow">店里正在准备</div><h2>正在收拾你的窗边座位。</h2><progress id="boot-progress" value="0" max="3" aria-label="读取页面素材"></progress><p class="tiny" id="boot-status">咖啡已经备好，正在取来你的单词…</p></div>${protoMark('boot')}</main>`;let done=0;await Promise.all(['welcome-suzu-v4.png','aoi-room-v5.png','momo-room-v4.png'].map(src=>new Promise(resolve=>{const img=new Image();const finish=()=>{done++;if($('#boot-progress'))$('#boot-progress').value=done;resolve();};img.onload=finish;img.onerror=finish;img.src='assets/'+src;})));}
async function boot(){
 try{
  await bootScreen();const data=await api('/api/cafe/bootstrap');WORDS=data.words;revision=data.revision;
  S={...freshState(),...(data.state||{})};S.dialogues=data.dialogues;
  S.mastery={...S.mastery,...data.mastery};S.dueIds=data.dueIds;
  S.recent=[...new Set([...S.recent,...data.recent])].filter(id=>allWords().some(w=>w.id===id)).slice(0,100);
  ui.method=S.assessment?.method||'binary';ui.bootFailed=false;
  // A completed visit builds a fresh queue on the next launch, with due words first.
  if(S.welcomeComplete){
   if(!S.learning)startQueue(S,allWords());
   else{const current=new Set(S.learning.rootIds),future=S.queue.slice(S.queueIndex+1),due=data.dueIds.filter(id=>!current.has(id)),dueSet=new Set(due);
    const rest=future.flatMap(g=>g.ids).filter(id=>!dueSet.has(id)&&!S.mastery[id]?.known);
    const groups=[...chunks(due,S.settings.size).map(ids=>({kind:'old',ids})),...chunks([...new Set(rest)],S.settings.size).map(ids=>({kind:'new',ids}))];
    S.queue=S.queue.slice(0,S.queueIndex+1).concat(groups);
   }
  }
  go(resolvePage(S,S.page||safeResume(S)),{replace:true});sceneArt();await save();
  window.__maidcafe={snapshot:()=>structuredClone(S),audioState:()=>({time:audio?.currentTime||0,paused:audio?.paused,ready:audio?.readyState,src:audio?.src}),version:data.version};
  if(data.dialogues.some(d=>['writing','tts'].includes(d.status)))refreshDialogues();
 }catch(error){ui.bootFailed=true;S.errorMessage=error.message;S.errorReturn='welcome';S.page='error';render();}
}
boot();
