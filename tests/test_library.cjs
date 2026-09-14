const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
process.env.TZ='America/Chicago';
const root=path.join(__dirname,'../src/yue2_studio/static');
let now='2026-03-08T12:00:00-05:00';
class FixedDate extends Date{constructor(...args){super(...(args.length?args:[now]));}}
const elements={libraryDate:{value:'',hidden:true},libraryDateFilter:{value:'custom'}};
let renders=0,errors=0,calls=0,resolve;
const state={jobs:[{id:'one',starred:false}]};
const context=vm.createContext({Date:FixedDate,state,$:id=>elements[id],renderLibrary:()=>renders++,toast:()=>{},feedbackError:()=>errors++,api:()=>{calls++;return new Promise(r=>resolve=r);}});
vm.runInContext(fs.readFileSync(path.join(root,'library.js'),'utf8'),context);
const matches=(created,filter,chosen)=>context.libraryDateMatches({created},filter,chosen);
assert(matches('2026-03-08T23:59:59-05:00','today'));
assert(!matches('2026-03-09T00:00:00-05:00','today'));
assert(matches('2026-03-08T05:59:59Z','yesterday')); // Still March 7 locally.
assert(matches('2026-03-08T06:00:00Z','today')); // DST day starts at UTC-6.
assert(matches('2026-03-02T00:00:00-06:00','last7'));
assert(!matches('2026-03-01T23:59:59-06:00','last7'));
assert(matches('2026-02-07T00:00:00-06:00','last30'));
assert(!matches('2026-02-06T23:59:59-06:00','last30'));
assert(matches('2026-03-08T05:59:59Z','custom','2026-03-07'));
assert(!matches('2026-03-08T05:59:59Z','custom',''));
assert(!matches('bad','today'));
assert(matches('bad','all'));
now='2026-11-01T12:00:00-06:00';
assert(matches('2026-11-01T00:00:00-05:00','today'));
assert(matches('2026-11-01T23:59:59-06:00','today'));
context.bindLibraryDates();
elements.libraryDateFilter.onchange();
assert.equal(elements.libraryDate.hidden,false);
assert.equal(elements.libraryDate.value,'2026-11-01');
elements.libraryDateFilter.value='all';elements.libraryDateFilter.onchange();
assert.equal(elements.libraryDate.hidden,true);
const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
vm.runInContext(app.split('\n').find(line=>line.startsWith('function libraryFilterMatches(')),context);
assert(context.libraryFilterMatches({starred:true},'starred'));
assert(!context.libraryFilterMatches({},'starred'));
assert(context.libraryFilterMatches({kind:'generation',stage:'audio',status:'complete'},'completed'));
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
assert(html.indexOf('src="/library.js"')<html.indexOf('src="/app.js"'));
for(const id of ['libraryDate','libraryDateFilter','i-star'])assert(html.includes(`id="${id}"`));
(async()=>{
  const pending=context.toggleStar('one');
  await context.toggleStar('one');
  assert.equal(calls,1);
  assert.equal(state.jobs[0].starred,false); // No optimistic success before persistence.
  state.jobs=[{id:'one',starred:false}]; // Polling replaced the object.
  resolve({starred:true});await pending;
  assert.equal(state.jobs[0].starred,true);
  context.api=async(url,data)=>{assert.equal(data.starred,false);return {starred:false};};
  await context.toggleStar('one');assert.equal(state.jobs[0].starred,false);
  context.api=async()=>{throw Error('save failed');};
  await context.toggleStar('one');assert.equal(state.jobs[0].starred,false);
  assert.equal(errors,1);assert(renders>=4);
  console.log('Library date boundaries, controls, filters, and star request tests passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
