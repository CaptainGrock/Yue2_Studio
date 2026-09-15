/* Real UI handlers with mocked HTTP: no server, LLM, or GPU jobs. */
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements=new Map(),sent=[];
function element(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',options:[],addEventListener(){},replaceChildren(...items){this.options=items;},add(item){this.options.push(item);}});return elements.get(id);}
const state={boot:{},connection:{model:'test'},settings:{runtime:{backend:'torch'},lora:{path:'',strength:1,auto_trigger:true}}};
const context=vm.createContext({state,$:element,Option:function(text,value){this.text=text;this.value=value;},save(){},toast(){},busy:async(id,fn)=>fn(),pollSurprises:async()=>{},openRunner(){throw Error('unexpected');},api:async(url,data)=>{
 if(url==='/api/loras')return {folder:'local',loras:[{path:'local/test.safetensors',name:'Test'}],rejected:[]};
 if(url==='/api/loras/inspect')return {path:data.path,trigger_word:'test_sound'};
 if(url==='/api/surprises'){sent.push(JSON.parse(JSON.stringify(data)));return {};}
 throw Error(url);
}});
vm.runInContext(fs.readFileSync('src/yue2_studio/static/loras.js','utf8'),context);
const app=fs.readFileSync('src/yue2_studio/static/app.js','utf8');
vm.runInContext(app.slice(app.indexOf('function bindSurprise()'),app.indexOf('async function pollSurprises()')),context);
(async()=>{
 vm.runInContext('bindLoras();bindSurprise()',context);
 await vm.runInContext('refreshLoras()',context);
 assert.equal(element('surpriseLoraSelect').options.length,2);
 element('surpriseLoraSelect').value='local/test.safetensors';element('surpriseLoraSelect').onchange();
 assert.equal(element('loraSelect').value,'local/test.safetensors');
 element('loraStrength').value='0.75';element('loraStrength').oninput();
 assert.match(element('surpriseLoraStatus').textContent,/0.75/);
 element('surpriseCount').value='2';
 await element('surpriseButton').onclick();
 assert.equal(sent[0].settings.lora.path,'local/test.safetensors');
 assert.equal(sent[0].settings.lora.strength,.75);
 assert.equal(sent[0].settings.lora.auto_trigger,true);
 element('surpriseLoraSelect').value='';element('surpriseLoraSelect').onchange();
 await element('surpriseButton').onclick();
 assert.equal(sent[1].settings.lora.path,'');
 assert.equal(sent[0].settings.lora.path,'local/test.safetensors','previous submission unchanged');
 element('loraSelect').value='local/test.safetensors';element('loraSelect').onchange();
 assert.equal(element('surpriseLoraSelect').value,'local/test.safetensors');
 state.settings.runtime.backend='audio.cpp';vm.runInContext('syncLoras()',context);
 assert.match(element('surpriseLoraStatus').textContent,/requires Torch/);
 const html=fs.readFileSync('src/yue2_studio/static/index.html','utf8');
 for(const id of ['surpriseLoraSelect','surpriseLoraHelp','surpriseLoraStatus','refreshSurpriseLoras'])assert(html.includes('id="'+id+'"'));
 assert.equal((html.match(/id="surpriseLoraSelect"/g)||[]).length,1);
 console.log('Surprise LoRA passed: catalogue, two-way sync, strength, request payload, None, GGUF notice.');
})().catch(error=>{console.error(error);process.exitCode=1;});
