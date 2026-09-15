/* DOM contract checks; no browser, models, GPU, or live Studio. */
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements=new Map(),calls=[];
function element(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,disabled:false,options:[],selectedOptions:[{textContent:'Saved project'}],replaceChildren(...items){this.options=items;},add(item){this.options.push(item);},append(...items){this.options.push(...items);}});return elements.get(id);}
const context=vm.createContext({state:{view:'trainer',settings:{runtime:{model:'local-model',vae:'local-vae'}}},$:element,Option:function(text,value){this.text=text;this.value=value;},statusText:{queued:'Queued'},setInterval(){},document:{createElement:()=>element(Math.random())},button:(label,fn)=>({label,onclick:fn}),toast(){},busy:async(id,fn)=>fn(),confirmReplace:(title,text,fn)=>fn(),refreshLoras:async()=>{},openRun(){},save(){},api:async(url,data)=>{
 calls.push({url,data});
 if(url==='/api/trainer/projects')return {projects:[],};
 if(url==='/api/jobs')return {jobs:[]};
 if(url==='/api/trainer/train')return {id:'run',title:'Saved project',status:'queued'};
 if(url==='/api/trainer/check')return {ready:false,issues:['Full weights required'],warnings:['No GPU allocation'],prepared:{model:'downloaded-model',vae:'downloaded-vae'}};
 if(url==='/api/trainer/download')return {id:'download',kind:'trainer_setup'};
 throw new Error(url);
}});
vm.runInContext(fs.readFileSync('src/yue2_studio/static/trainer.js','utf8'),context);
(async()=>{
 vm.runInContext('bindTrainer()',context);
 await new Promise(resolve=>setImmediate(resolve));
 element('trainerProjects').value='saved-id';
 for(const [id,value] of [['trainerSteps','20'],['trainerRate','0.0001'],['trainerRank','8'],['trainerCheckpoint','5']])element(id).value=value;
 element('trainerCaption').value='Unsaved changes must not be submitted';
 element('trainerTrain').onclick();
 await new Promise(resolve=>setImmediate(resolve));
 const sent=calls.find(c=>c.url==='/api/trainer/train').data;
 assert.equal(sent.project_id,'saved-id');assert.equal(sent.steps,20);assert.equal(sent.learning_rate,.0001);
 assert.equal(sent.model,'local-model');assert.equal(sent.vae,'local-vae');assert.equal(sent.default_caption,undefined);
 assert.match(element('trainerTrainStatus').textContent,/Queued/);
 await element('trainerCheck').onclick();
 assert.match(element('trainerSetupStatus').textContent,/Full weights required/);
 assert.equal(element('trainerUseModels').disabled,false);
 assert.equal(context.state.settings.runtime.model,'local-model');
 element('trainerUseModels').onclick();
 assert.equal(context.state.settings.runtime.model,'downloaded-model');
 element('trainerDownload').onclick();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.filter(c=>c.url==='/api/trainer/train').length,1);
 assert.equal(calls.find(c=>c.url==='/api/trainer/download').data.confirmed,true);
 const html=fs.readFileSync('src/yue2_studio/static/index.html','utf8');
 const mainNav=html.match(/<nav aria-label="Main navigation">([\s\S]*?)<\/nav>/)[1];
 assert.deepEqual([...mainNav.matchAll(/data-view="([^"]+)"/g)].map(match=>match[1]),['create','trainer','artist','library']);
 assert.equal((html.match(/data-view="trainer"/g)||[]).length,1,'Only one Style trainer navigation entry');
 assert(!html.includes('trainerGoal'),'Do not offer a cosmetic training-goal selector');
 assert.match(html,/id="trainerSteps"[^>]*value="2000"/);
 assert.match(html,/id="trainerCheckpoint"[^>]*value="500"/);
 assert.match(html,/id="trainerClip"[^>]*aria-describedby="trainerClipHint"/);
 assert.match(html,/3-minute song produces 18 ten-second clips/);
 for(const id of ['trainerTrain','trainerSteps','trainerRate','trainerRank','trainerCheckpoint','trainerRuns'])assert.ok(html.includes('id="'+id+'"'));
 const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]);
 assert.equal(ids.length,new Set(ids).size,'HTML IDs must be unique');
 for(const file of ['trainer.js','loras.js']){
   const script=fs.readFileSync('src/yue2_studio/static/'+file,'utf8');
   for(const match of script.matchAll(/\$\('([^']+)'\)/g))assert(ids.includes(match[1]),'Missing UI element '+match[1]);
   assert(html.indexOf('src="/'+file+'"')<html.indexOf('src="/app.js"'));
 }
 assert(html.includes('artistView'));assert(!html.includes('trainerRecovered'));
 console.log('Trainer controls passed: saved snapshot, numeric controls, model paths, queue status, HTML contract.');
})().catch(error=>{console.error(error);process.exitCode=1;});
