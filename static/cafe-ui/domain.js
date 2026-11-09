export const VERSION=1;
export const LEVELS=[
 {name:'CET4 之前',next:'CET4',detail:'先把日常英语的基础慢慢补齐。'},
 {name:'CET4',next:'CET6',detail:'四级词汇已经熟练，接下来学习六级。'},
 {name:'CET6',next:'TOEFL',detail:'六级词汇已经熟练，接下来学习托福。'},
 {name:'TOEFL',next:'GRE',detail:'托福词汇已经熟练，接下来学习 GRE。'},
 {name:'GRE',next:'进阶词汇',detail:'继续学习词库里还没有掌握的进阶词汇。'}
];
export function freshState(){return {version:VERSION,page:'welcome',seated:false,level:null,tutorialComplete:false,tutorialStarted:false,welcomeComplete:false,tutorialStep:0,tutorial:null,learning:null,queue:[],queueIndex:0,mastery:{},recent:[],dueIds:[],dialogues:[],customWords:[],assessment:null,assessmentArchive:[],settings:{size:20,art:'rotate',model:'standard',ready:false},returnPage:'learn',historyDay:null,exam:null,examSelection:[],examRange:'recent',errorReturn:null,serial:0};}
export function chunks(items,size){const out=[];for(let i=0;i<items.length;i+=size)out.push(items.slice(i,i+size));return out;}
export function createGroup(ids,kind='new',id='group-1'){return {id,kind,rootIds:[...ids],ids:[...ids],passed:[],index:0,revealed:false,round:1,done:ids.length===0};}
export function judgeGroup(group,pass){
 if(group.done) return null;
 const id=group.ids[group.index];if(!id) return null;
 group.passed=group.passed.filter(x=>x!==id);if(pass)group.passed.push(id);
 group.index++;group.revealed=false;group.done=group.index>=group.ids.length;return id;
}
export function pending(group){return group.rootIds.filter(id=>!group.passed.includes(id));}
export function retryGroup(group){const ids=pending(group);if(!ids.length)return false;group.ids=ids;group.index=0;group.revealed=false;group.done=false;group.round++;return true;}
export function canAdvance(group){return !!group&&group.done&&pending(group).length===0;}
export function randomTargets(group,count,random=Math.random){const pool=[...group.ids];for(let i=pool.length-1;i>0;i--){const j=Math.floor(random()*(i+1));[pool[i],pool[j]]=[pool[j],pool[i]];}return pool.slice(0,Math.min(count,5,pool.length));}
export function chosenTargets(group,selected){return [...new Set(selected)].filter(id=>group.ids.includes(id)).slice(0,5);}
export function makeQueue(state,words){
 const bank=[...new Map(words.filter(w=>!w.tutorial).map(w=>[w.id,w])).values()];
 const allowed=bank.filter(w=>state.learningFrontier!=null?w.rank>=state.learningFrontier:w.band>=(state.level??0));
 const due=state.dueIds.filter(id=>bank.some(w=>w.id===id));
 const explicit=bank.filter(w=>state.mastery[w.id]&&!state.mastery[w.id].known);
 const eligible=new Set([...explicit,...allowed].map(w=>w.id));
 const fresh=bank.filter(w=>eligible.has(w.id)&&!due.includes(w.id)&&!state.mastery[w.id]?.known).map(w=>w.id);
 const queue=[];for(const [kind,ids] of [['old',due],['new',fresh]])for(const g of chunks(ids,state.settings.size))queue.push({kind,ids:g});return queue;
}
export function startQueue(state,words){state.queue=makeQueue(state,words);state.queueIndex=0;state.learning=state.queue.length?createGroup(state.queue[0].ids,state.queue[0].kind,`batch-${++state.serial}`):null;}
export function recordStudy(state,pass,now=Date.now()){
 const id=judgeGroup(state.learning,pass);if(!id)return;
 state.mastery[id]={known:!!pass,seen:now};state.recent=[id,...state.recent.filter(x=>x!==id)].slice(0,100);
}
export function advanceQueue(state){
 if(!canAdvance(state.learning))return false;
 state.dueIds=state.dueIds.filter(id=>!state.learning.rootIds.includes(id));
 state.queueIndex++;const next=state.queue[state.queueIndex];state.learning=next?createGroup(next.ids,next.kind,`batch-${++state.serial}`):null;return true;
}
export function createExam(ids){return {ids:[...new Set(ids)],index:0,revealed:false,answers:[],done:false};}
export function answerExam(exam,known){if(exam.done)return;const id=exam.ids[exam.index];if(!id)return;exam.answers.push({id,known:!!known});exam.index++;exam.revealed=false;exam.done=exam.index>=exam.ids.length;}
export function examResult(exam){return {known:exam.answers.filter(x=>x.known).length,unknown:exam.answers.filter(x=>!x.known).length,unanswered:exam.ids.length-exam.answers.length};}
export function createAssessment(method,words,random=Math.random){
 const bank=words.filter(w=>!w.tutorial&&w.tier>0),by=new Map();
 for(const w of bank){if(!by.has(w.tier))by.set(w.tier,[]);by.get(w.tier).push(w.id);}
 const groups=[...by.entries()].sort((a,b)=>a[0]-b[0]).map(([,ids])=>{for(let i=ids.length-1;i>0;i--){const j=Math.floor(random()*(i+1));[ids[i],ids[j]]=[ids[j],ids[i]];}return ids;});
 const mid=Math.floor((groups.length-1)/2);
 const a={method,index:0,answers:[],phase:'hear',heard:null,done:!bank.length,groups,lo:-1,hi:groups.length,mid,batchStart:0,extra:false};
 a.queue=method==='full'?groups.flat():method==='sample'?groups.flatMap(g=>g.slice(0,3)):groups[mid]?.slice(0,3)||[];return a;
}
export function answerAssessment(a,known){
 if(a.done)return;
 a.answers.push({id:a.queue[a.index],heard:!!a.heard,known:!!known});a.index++;a.phase='hear';a.heard=null;
 if(a.method!=='binary'){a.done=a.index>=a.queue.length;return;}
 if(a.index<a.queue.length)return;
 const batch=a.answers.slice(a.batchStart),correct=batch.filter(x=>x.heard).length;
 if(batch.length===3&&correct===2&&!a.extra&&a.groups[a.mid].length>3){a.extra=true;a.queue.push(...a.groups[a.mid].slice(3,6));return;}
 const high=batch.length<=3?correct===batch.length:correct>=5;
 const low=batch.length<=3?correct<=1:correct<=2;
 if(high)a.lo=a.mid;else if(low)a.hi=a.mid;else{a.lo=a.mid;a.hi=a.mid+1;}
 if(a.hi-a.lo<=1){a.done=true;return;}
 a.mid=Math.floor((a.lo+a.hi)/2);a.batchStart=a.answers.length;a.extra=false;a.queue.push(...a.groups[a.mid].slice(0,3));
}
export function estimateLevel(a,words){
 const byId=new Map(words.map(w=>[w.id,w]));let boundary=0;
 if(a.method==='binary')boundary=a.hi;
 else{for(const group of a.groups){const tested=a.answers.filter(x=>group.includes(x.id));if(tested.length&&tested.filter(x=>x.heard).length/tested.length>=0.85)boundary++;else break;}}
 const next=a.groups[boundary];a.frontier=next?Math.min(...next.map(id=>byId.get(id).rank)):Math.max(...words.filter(w=>!w.tutorial).map(w=>w.rank))+1;
 return next?Math.min(...next.map(id=>byId.get(id).band)):4;
}
export function safeResume(s){if(!s.seated)return'welcome';if(s.level===null)return'start';if(!s.tutorialStarted)return'result';if(!s.tutorialComplete)return s.tutorial?.done?'group':'learn';if(!s.welcomeComplete)return'welcome-end';return s.learning?(s.learning.done?'group':'learn'):'complete';}

// Browser history is a request to navigate, not a second copy of study state.
export function resolvePage(s,page){
 if(page==='error')return page;
 if(s.previewReturn&&page==='welcome')return page;
 if(s.recalibrating&&['methods','assessment'].includes(page))return s.assessment?.done&&page==='assessment'?'settings':page;
 if(s.replayTutorial)return s.tutorial?.done?'group':'learn';
 if(!s.seated)return'welcome';
 if(s.level===null)return ['start','methods','level'].includes(page)?page:page==='assessment'&&s.assessment&&!s.assessment.done?page:'start';
 if(!s.tutorialStarted)return'result';
 if(!s.tutorialComplete||!s.welcomeComplete)return safeResume(s);
 if(['welcome','start','methods','level','assessment','result','welcome-end','learn','group','complete'].includes(page))return safeResume(s);
 if(page==='player'&&!s.dialogues.some(d=>d.id===s.historyId))return'history';
 if(['exam','exam-result'].includes(page))return !s.exam?'exam-select':s.exam.done?'exam-result':'exam';
 return ['history','player','library','settings','exam-select'].includes(page)?page:safeResume(s);
}

