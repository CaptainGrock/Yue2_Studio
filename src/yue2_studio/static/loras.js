'use strict';
let loraCatalogue=[],loraFolder='',loraListError='',loraInspectEpoch=0;
const localLoras=new Map();
function loraName(path){return path.split(/[\\/]/).pop().replace(/\.safetensors$/i,'');}
function syncLoras(){
  if(!state.boot||!$('loraSelect'))return;
  const selection=state.settings.lora;
  if(!selection){$('loraStatus').textContent='LoRA controls will be available after Studio restarts. Let current renders finish first.';$('loraSelect').disabled=true;$('useLocalLora').disabled=true;if($('surpriseLoraSelect')){$('surpriseLoraSelect').disabled=true;$('surpriseLoraStatus').textContent=$('loraStatus').textContent;}return;}
  const current=selection.path,items=new Map(loraCatalogue.map(item=>[item.path,item]));
  for(const [path,item] of localLoras)items.set(path,item);
  if(current&&!items.has(current))items.set(current,{path:current,name:loraName(current)});
  const select=$('loraSelect');select.replaceChildren(new Option('None · original YuE2',''));
  for(const item of items.values())select.add(new Option((item.name||loraName(item.path)),item.path));
  select.value=current;select.disabled=false;
  if($('surpriseLoraSelect')){
    const surprise=$('surpriseLoraSelect');surprise.replaceChildren(...Array.from(select.options,option=>new Option(option.text,option.value)));
    surprise.value=current;surprise.disabled=false;
  }
  $('loraOptions').hidden=!current;
  $('loraStrength').value=selection.strength;$('loraStrengthValue').textContent=Number(selection.strength).toFixed(2);
  $('loraAutoTrigger').checked=selection.auto_trigger;
  const item=items.get(current);
  if($('surpriseTrainingStyleStatus'))$('surpriseTrainingStyleStatus').textContent=current?(item?.training_style?.trim()?'Training style saved in this LoRA. Selecting it fills both song-creation style boxes; you can edit either.':'No training style saved / not yet inspected. Your style descriptions are unchanged.'):'Selecting a LoRA can fill both song-creation style boxes from its saved training style.';
  if($('loraStrengthHelp'))$('loraStrengthHelp').textContent='0 applies no effect. Lower strengths give a subtler influence; 1 is the starting point. Above 1 can introduce distortion or reduce coherence. Style adapters affect acoustic rendering, not the composer.';
  $('loraTrigger').textContent=item?.trigger_word||'No phrase recorded / not yet inspected';
  const gguf=state.settings.runtime.backend==='audio.cpp';
  $('loraStrength').disabled=gguf;$('loraAutoTrigger').disabled=gguf;
  $('loraStatus').textContent=gguf?(current?'This selection requires Torch. Choose None to render with GGUF.':'Style LoRAs require the Torch engine.'):
    loraListError||(current?'Selected for future songs. Active renders keep their saved settings.':items.size?'Choose a Style adapter, or keep the original model.':'No YuE2 LoRAs found yet.');
  if($('surpriseLoraStatus'))$('surpriseLoraStatus').textContent=(current?'Strength '+Number(selection.strength).toFixed(2)+' · Automatic trigger '+(selection.auto_trigger?'on':'off')+'. ':'')+$('loraStatus').textContent;
  $('loraFolder').textContent=loraFolder?'Place YuE2 .safetensors files in '+loraFolder+' and refresh the list.':'Default folder: models/loras inside your YuE2 installation.';
}
function loraStyleSnapshot(){return Object.fromEntries(['style','surpriseStyle'].map(id=>[id,$(id)?.value]));}
function offerLoraTrainingStyle(info,previousStyles){
  const style=info.training_style;
  if(typeof style!=='string'||!style.trim()||style.length>12000)return;
  const candidates=Object.keys(previousStyles).filter(id=>$(id)&&$(id).value===previousStyles[id]&&$(id).value!==style);
  const apply=ids=>{
    if(state.settings.lora.path!==info.path)return;
    for(const id of ids)if($(id).value===previousStyles[id]){
      $(id).value=style;
      if(id==='surpriseStyle')$('surpriseLockStyle').checked=true;
    }
    if(typeof updateCounts==='function')updateCounts();
    save();
  };
  apply(candidates.filter(id=>!$(id).value.trim()));
  const conflicts=candidates.filter(id=>previousStyles[id].trim());
  if(conflicts.length)confirmReplace('Use this LoRA’s training style?','Replace existing text in '+conflicts.map(id=>id==='style'?'Style':'Surprise me Style direction').join(' and ')+' with the style saved in this LoRA? You can edit it afterward.',()=>apply(conflicts));
}
async function inspectSelectedLora(path,fillStyle=false){
  const previousStyle=loraStyleSnapshot();
  const epoch=++loraInspectEpoch;
  try{
    const info=await api('/api/loras/inspect',{path});
    localLoras.set(info.path,{...info,name:loraCatalogue.find(item=>item.path===info.path)?.name||loraName(info.path)});
    if(epoch===loraInspectEpoch&&state.settings.lora.path===path){state.settings.lora.path=info.path;loraListError='';syncLoras();save();if(fillStyle)offerLoraTrainingStyle(info,previousStyle);}
  }catch(error){if(epoch===loraInspectEpoch&&state.settings.lora.path===path){loraListError=error.message;syncLoras();}}
}
async function refreshLoras(){
  if(!state.settings.lora)return;
  try{const data=await api('/api/loras');loraCatalogue=data.loras;loraFolder=data.folder;loraListError=data.rejected.length?data.rejected.length+' incompatible or invalid file(s) excluded from the folder.':'';}
  catch(error){loraListError=error.status===404?'Restart Studio after current renders finish to enable LoRA selection.':error.message;}
  syncLoras();
  if(state.settings.lora.path)await inspectSelectedLora(state.settings.lora.path);
}
function bindLoras(){
  $('refreshLoras').onclick=()=>busy('refreshLoras',refreshLoras);
  for(const id of ['loraSelect','surpriseLoraSelect'])if($(id))$(id).onchange=()=>{loraInspectEpoch++;state.settings.lora.path=$(id).value;if(state.settings.lora.path&&$('surpriseLockStyle'))$('surpriseLockStyle').checked=true;loraListError='';syncLoras();save();if(state.settings.lora.path)return inspectSelectedLora(state.settings.lora.path,true);};
  if($('refreshSurpriseLoras'))$('refreshSurpriseLoras').onclick=()=>busy('refreshSurpriseLoras',refreshLoras);
  $('loraStrength').oninput=()=>{state.settings.lora.strength=Number($('loraStrength').value);syncLoras();save();};
  $('loraAutoTrigger').onchange=()=>{state.settings.lora.auto_trigger=$('loraAutoTrigger').checked;syncLoras();save();};
  $('useLocalLora').onclick=()=>busy('useLocalLora',async()=>{
    const previousStyle=loraStyleSnapshot();
    const path=$('loraLocalPath').value.trim().replace(/^"(.*)"$/,'$1');
    const info=await api('/api/loras/inspect',{path});
    localLoras.set(info.path,{...info,name:loraName(info.path)});
    state.settings.lora.path=info.path;if($('surpriseLockStyle'))$('surpriseLockStyle').checked=true;loraListError='';syncLoras();save();offerLoraTrainingStyle(info,previousStyle);toast('LoRA selected for future songs.');
  });
  refreshLoras();
}
