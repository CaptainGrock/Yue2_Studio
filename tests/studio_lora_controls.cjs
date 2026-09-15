/* DOM contract checks without a browser, server, or rendering GPU. */
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:false,disabled:false,options:[],replaceChildren(...items){this.options=items;},add(item){this.options.push(item);}});return elements.get(id);}
const state={boot:{},settings:{runtime:{backend:'torch'},lora:{path:'',strength:1,auto_trigger:true}}};
const context=vm.createContext({state,$:element,Option:function(text,value){this.text=text;this.value=value;},save(){},toast(){},busy:async(id,fn)=>fn(),api:async(url,data)=>url==='/api/loras'?{folder:'E:/models/loras',loras:[{path:'E:/models/loras/test.safetensors',name:'Test style',trigger_word:'test_sound'}],rejected:[]}:{path:data.path,trigger_word:'test_sound'}});
vm.runInContext(fs.readFileSync('src/yue2_studio/static/loras.js','utf8'),context);
(async()=>{
  await vm.runInContext('refreshLoras()',context);
  assert.equal(element('loraSelect').options.length,2);
  assert.equal(element('loraOptions').hidden,true);
  vm.runInContext('bindLoras()',context);
  element('loraSelect').value='E:/models/loras/test.safetensors';element('loraSelect').onchange();
  assert.equal(state.settings.lora.path,'E:/models/loras/test.safetensors');
  assert.equal(element('loraTrigger').textContent,'test_sound');
  element('loraStrength').value='1.5';element('loraStrength').oninput();
  assert.equal(state.settings.lora.strength,1.5);
  element('loraAutoTrigger').checked=false;element('loraAutoTrigger').onchange();
  assert.equal(state.settings.lora.auto_trigger,false);
  state.settings.runtime.backend='audio.cpp';vm.runInContext('syncLoras()',context);
  assert.equal(element('loraStrength').disabled,true);
  assert.match(element('loraStatus').textContent,/requires Torch/);
  element('loraSelect').value='';element('loraSelect').onchange();
  assert.equal(state.settings.lora.path,'');assert.equal(element('loraOptions').hidden,true);
  state.settings.runtime.backend='torch';
  console.log('LoRA controls passed: selection, strength, trigger, GGUF notice, None.');
})().catch(error=>{console.error(error);process.exitCode=1;});
