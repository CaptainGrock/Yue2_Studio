/* Preset handlers only: no network, model loading or GPU work. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('src/yue2_studio/static/app.js','utf8');
const elements=new Map();
function el(id){if(!elements.has(id))elements.set(id,{value:'',disabled:false,textContent:'',attributes:{},
 setAttribute(k,v){this.attributes[k]=v;},closest(){return {classList:{toggle(){}}};},
 addEventListener(type,fn){this[type]=fn;}});return elements.get(id);}
const initial={abc:{temperature:.7,top_p:.9,top_k:30,max_tokens:4096},semantic:{temperature:1,top_p:.95,top_k:100,max_tokens:9000},generation:{cfg_scale:null,ode_steps:32},runtime:{backend:'torch',offload_ar:false},lora:{path:'kept',strength:1}};
const state={boot:{},settings:structuredClone(initial)};
let saves=0;
const context=vm.createContext({state,$:el,updateCounts(){},save(){saves++;},toast(){}});
vm.runInContext(app.slice(app.indexOf('const EXPERIMENTS='),app.indexOf('function stylePreset')),context);
const run=code=>vm.runInContext(code,context);
el('planMode').value='full';run('bindExperimentalSliders()');
assert.deepEqual(state.settings,initial,'Binding must not rewrite restored settings');
for(const id of ['compositionSlider','performanceSlider','influenceSlider'])assert.equal(Number(el(id).value),2);
run("applyExperiment('performance',4)");assert.equal(state.settings.semantic.temperature,1.2);
assert.equal(state.settings.semantic.max_tokens,9000);assert.equal(state.settings.generation.ode_steps,32);
assert.deepEqual(state.settings.lora,initial.lora);
run("applyExperiment('influence',0)");assert.equal(state.settings.generation.cfg_scale,.85);
state.settings.abc.temperature=.731;run('updateExperimentalSliders()');assert.equal(el('compositionValue').textContent,'Custom advanced values');
assert.equal(state.settings.abc.temperature,.731);
el('planMode').value='off';run('updateExperimentalSliders()');assert(el('compositionSlider').disabled);
run("applyExperiment('composition',0)");assert.equal(state.settings.abc.temperature,.731);
el('planMode').value='full';el('abc').value='supplied score';run('updateExperimentalSliders()');assert(el('compositionSlider').disabled);
el('abc').value='';state.settings.runtime.backend='audio.cpp';run('updateExperimentalSliders()');
for(const id of ['compositionSlider','performanceSlider','influenceSlider'])assert(el(id).disabled);
const before=JSON.stringify(state.settings);run("applyExperiment('performance',0);resetExperiments()");assert.equal(JSON.stringify(state.settings),before);
state.settings.runtime.backend='torch';run('updateExperimentalSliders();resetExperiments()');assert.deepEqual(state.settings,initial);
run("applyExperiment('missing',0);applyExperiment('performance',99)");assert.deepEqual(state.settings,initial);
assert(saves>0);
const html=fs.readFileSync('src/yue2_studio/static/index.html','utf8');
for(const id of elements.keys())if(!['planMode','abc'].includes(id))assert(html.includes('id="'+id+'"'),id);
assert(html.includes('same seed does not guarantee identical music'));
assert(html.includes('aria-label="About the Composition slider"'));
assert(app.includes('bindExperimentalSliders();'));
console.log('Experimental sliders passed: defaults, custom values, bypasses, reset and preserved unrelated settings.');
