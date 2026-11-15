/* No browser dependency: exercises the actual progress client with server responses. */
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Element {
 constructor(){this.innerHTML='';this.dataset={};this.disabled=false;this.attributes={};this.textContent='';}
 querySelector(s){return this.innerHTML.includes('connection-notice')&&s==='.connection-notice'?{}:null;}
 setAttribute(k,v){this.attributes[k]=v;}
 insertAdjacentHTML(_,v){this.innerHTML+=v;}
 click(){}
}
const elements={},storage=new Map(),handlers={},html=[];
let sequence=[],calls=0,rendered;
const context={URL,Map,Promise,FormData,console,crypto:require('crypto').webcrypto,location:{href:'http://localhost:5000/'},
 persianLabel:value=>String(value ?? ''),
 escapeHtml:s=>String(s??'').replaceAll('<','&lt;'),
 setTimeout:fn=>{queueMicrotask(fn);},
 sessionStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 document:{getElementById:k=>elements[k]??=(new Element())},
 window:{addEventListener:(k,fn)=>handlers[k]=fn},
 fetch:async()=>{calls++;let next=sequence.shift();if(next instanceof Error)throw next;if(!next)throw new Error('Unexpected fetch');return {ok:next.status<400,status:next.status,json:async()=>next.data};},
 setError:()=>assert.fail('unexpected error'),
 renderResults:d=>{rendered=d},renderCIResults:()=>{},renderTSResults:()=>{},renderDSResults:()=>{},renderClusterResults:()=>{}}
vm.createContext(context);vm.runInContext(fs.readFileSync(__dirname+'/../loyalty/static/js/progress.js','utf8'),context);
const live={operation_id:'real-id',path:'/analyze',status:'running',stage:'Clean data',elapsed_seconds:2,percentage:null,events:[{label:'Clean data',status:'running',elapsed_seconds:2,completed_units:7,total_units:null,unit:'rows'}]};
const done={...live,status:'succeeded',stage:null,percentage:100,result:{score:42},events:[{...live.events[0],status:'completed',elapsed_seconds:3}]};
(async()=>{
 // Actual server completion is the only condition that writes a 100% value.
 context.testLive=live;vm.runInContext("paintJob(testLive,'/analyze')",context);
 assert(!elements.statusArea.innerHTML.includes('value="100"'));
 assert(elements.statusArea.innerHTML.includes('Clean data'));
 assert(elements.statusArea.innerHTML.includes('زمان سپری‌شده کل'));
 assert(!elements.statusArea.innerHTML.toLowerCase().includes('remaining'));
 sequence=[{status:202,data:{operation_id:'real-id'}},{status:200,data:live},new Error('offline'),{status:200,data:done}];
 const result=await vm.runInContext("runTracked('/analyze',{})",context);
 assert.equal(result.score,42);assert.equal(calls,4);
 assert(elements.statusArea.innerHTML.includes('value="100"'));
 assert.equal(storage.size,0);
 // Recover after a reload, including an ambiguous initial submission.
 storage.set('loyalty-operation',JSON.stringify({base:'http://localhost:5000/',key:'request-key',path:'/analyze'}));
 sequence=[{status:200,data:{operation_id:'real-id'}},{status:200,data:done}];
 await handlers.DOMContentLoaded();assert.equal(rendered.score,42);
 assert.equal(elements.runBtn.disabled,false);assert.equal(storage.size,0);
 // Failure never gets completion and remains associated with its own operation.
 sequence=[{status:202,data:{operation_id:'failed-id'}},{status:200,data:{...live,operation_id:'failed-id',status:'failed',result:{error:'actual failure'}}}];
 let failed=false;try{await vm.runInContext("runTracked('/analyze',{})",context);}catch(e){failed=true;assert.equal(e.message,'actual failure')}
 assert(failed);assert(!elements.statusArea.innerHTML.includes('value="100"'));
 // A lost initial response retries with the same idempotency key (same options object).
 sequence=[new Error('lost start response'),{status:202,data:{operation_id:'real-id'}},{status:200,data:done}];
 await vm.runInContext("runTracked('/analyze',{})",context);
 console.log('PASS: live telemetry, reconnect, reload recovery, failure, start retry; no timer-generated progress');
})().catch(e=>{console.error(e);process.exit(1)});
