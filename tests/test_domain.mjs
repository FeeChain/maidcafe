import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const D=await import(pathToFileURL(process.cwd()+'/static/cafe-ui/domain.js'));
const bank=Array.from({length:305},(_,i)=>({id:'w'+i,word:'w'+i,rank:i,tier:Math.floor(i/100)+1,band:Math.min(4,Math.floor(i/65))}));
const words=[...Array.from({length:5},(_,i)=>({id:'t'+i,tutorial:true})),...bank];
const s=D.freshState();s.level=0;s.dueIds=bank.slice(0,45).map(w=>w.id);
let q=D.makeQueue(s,words);assert.deepEqual(q.slice(0,4).map(g=>[g.kind,g.ids.length]),[['old',20],['old',20],['old',5],['new',20]]);
const daily=D.freshState();daily.level=0;daily.mastery.w0={known:false,retryTomorrow:true};
assert(!D.makeQueue(daily,words).some(g=>g.ids.includes('w0')));
daily.mastery.w0.retryTomorrow=false;assert(D.makeQueue(daily,words).some(g=>g.ids.includes('w0')));
let g=D.createGroup(bank.slice(0,20).map(w=>w.id));for(let i=0;i<20;i++)D.judgeGroup(g,i<15);
assert(!D.canAdvance(g));D.retryGroup(g);assert.equal(g.ids.length,5);for(let i=0;i<5;i++)D.judgeGroup(g,i<4);D.retryGroup(g);assert.equal(g.ids.length,1);assert.equal(D.randomTargets(g,5).length,1);assert.equal(D.chosenTargets(g,['w0','w19']).join(), 'w19');D.judgeGroup(g,true);assert(D.canAdvance(g));
for(const method of ['binary','sample','full'])for(const known of [true,false]){
 const a=D.createAssessment(method,words,()=>.4);let n=0;while(!a.done&&n++<400){a.heard=known;D.answerAssessment(a,known);}assert(a.done);D.estimateLevel(a,words);assert.equal(a.frontier,known?305:0);
}
const a=D.createAssessment('binary',words,()=>.4);for(let i=0;i<3;i++){a.heard=i!==0;D.answerAssessment(a,true);}assert.equal(a.queue.length,6);for(let i=0;i<3;i++){a.heard=i===0;D.answerAssessment(a,true);}assert(a.done);D.estimateLevel(a,words);assert.equal(a.frontier,200);
console.log('Domain: old groups, 20→5→1 retries, target clamp, three assessment modes, sparse final block and ambiguous boundary passed.');
