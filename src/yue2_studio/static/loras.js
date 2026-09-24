'use strict';
let loraCatalogue=[],loraFolder='',loraListError='',loraInspectEpoch=0;
const localLoras=new Map();
function loraName(path){return path.split(/[\\/]/).pop().replace(/\.safetensors$/i,'');}
function loraDisplayPath(path){const item=localLoras.get(path);return item?.relative?item.relative+' · '+item.parent:path;}
function syncLoras(){
  if(!state.boot||!$('loraSelect'))return;
  const selection=state.settings.lora;
  if(!selection){$('loraStatus').textContent='LoRA controls will be available after Studio restarts. Let current renders finish first.';$('loraSelect').disabled=true;$('useLocalLora').disabled=true;if($('surpriseLoraSelect')){$('surpriseLoraSelect').disabled=true;$('surpriseLoraStatus').textContent=$('loraStatus').textContent;}return;}
  if(!Array.isArray(selection.custom_folders))selection.custom_folders=[];
  const current=selection.path,items=new Map(loraCatalogue.map(item=>[item.path,item]));
  for(const [path,item] of localLoras)items.set(path,item);
  if(current&&!items.has(current))items.set(current,{path:current,name:loraName(current)});
  const select=$('loraSelect');select.replaceChildren(new Option('None · original YuE2',''));
  for(const item of items.values()){
    const kind=item.kind==='artist'?'Artist · ':item.kind==='unavailable'?'Folder unavailable · ':'Style · ';
    select.add(new Option(kind+(item.relative||item.name||loraName(item.path)),item.path));
  }
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
  const artist=item?.kind==='artist';
  if($('loraStrengthHelp'))$('loraStrengthHelp').textContent=artist?'Artist strength controls the song-generation adapter. 1 is the starting point; higher values may reduce coherence. While enabled, the required community acoustic companion stays at full strength. 0 disables both. This is not the same as an AR-only comparison with the companion kept on.':'0 applies no effect. Lower strengths give a subtler influence; 1 is the starting point. Above 1 can introduce distortion or reduce coherence. Style adapters affect acoustic rendering, not the composer.';
  $('loraTrigger').textContent=item?.trigger_word||'No phrase recorded / not yet inspected';
  const gguf=state.settings.runtime.backend==='audio.cpp';
  $('loraStrength').disabled=gguf;$('loraAutoTrigger').disabled=gguf;
  $('loraStatus').textContent=gguf?(current?'This selection requires Torch. Choose None to render with GGUF.':'LoRAs require the Torch engine.'):
    loraListError||(artist?'Artist LoRA + companion selected. Requires No score mode, Torch, quantization None, and AR offloading disabled. Keep your shared style in the style box; the trigger can be added automatically.':current?'Selected for future songs. Active renders keep their saved settings.':items.size?'Choose a Style or Artist adapter, or keep the original model.':'No YuE2 LoRAs found yet.');
  if($('surpriseLoraStatus'))$('surpriseLoraStatus').textContent=(current?'Strength '+Number(selection.strength).toFixed(2)+' · Automatic trigger '+(selection.auto_trigger?'on':'off')+'. ':'')+$('loraStatus').textContent;
  $('loraFolder').textContent=loraFolder?'The default folder '+loraFolder+' is always listed, plus any custom folders you add below.':'Default folder: models/loras inside your YuE2 installation. Add custom folders below.';
  renderLoraFolders(items);
}
function renderLoraFolders(items){
  const container=$('loraFolders');
  if(!container)return;
  const folders=state.settings.lora?.custom_folders||[];
  container.replaceChildren();
  if(!folders.length){const p=document.createElement('p');p.className='hint';p.textContent='No custom folders yet. Add one above; Studio scans it recursively, including style subfolders.';container.append(p);return;}
  for(const folder of folders){
    const card=document.createElement('div');card.className='lora-folder';
    const top=document.createElement('div');top.className='lora-folder-top';
    const name=document.createElement('strong');name.textContent=folder.split(/[\\/]/).filter(Boolean).pop()||folder;name.title=folder;
    const count=[...items.values()].filter(item=>item.kind!=='unavailable'&&item.path.startsWith(folder)&&item.path!==folder).length;
    const badge=document.createElement('span');badge.className='count-badge';badge.textContent=count?count+' found':'scanning…';
    const remove=document.createElement('button');remove.type='button';remove.className='button subtle small';remove.textContent='Remove';
    remove.onclick=()=>{
      const selection=state.settings.lora;
      const current=selection.path;
      const drop=()=>{selection.custom_folders=selection.custom_folders.filter(entry=>entry!==folder);if(current&&current.startsWith(folder))selection.path='';for(const path of [...localLoras.keys()])if(path.startsWith(folder))localLoras.delete(path);save();refreshLoras();};
      if(count)confirmReplace('Remove this LoRA folder?','Studio forgets '+folder+' and its '+count+' adapter file(s). If one is selected, it is deselected. Files on disk are not touched.',drop);
      else drop();
    };
    top.append(name,badge,remove);
    const pathLine=document.createElement('span');pathLine.className='lora-folder-path';pathLine.textContent=folder;pathLine.title=folder;
    card.append(top,pathLine);
    const children=[...items.values()].filter(item=>item.kind!=='unavailable'&&item.path.startsWith(folder)&&item.path!==folder).sort((a,b)=>(a.parent+a.name).localeCompare(b.parent+b.name));
    if(children.length){
      const files=document.createElement('div');files.className='lora-folder-files';
      for(const child of children){
        const file=document.createElement('button');file.type='button';file.className='lora-folder-file';
        const selected=state.settings.lora.path===child.path;
        if(selected)file.classList.add('selected');
        const label=document.createElement('span');
        label.textContent=(child.parent&&child.parent!=='.'?child.parent+' · ':'')+loraName(child.path)+(child.kind==='unavailable'?' (unavailable)':'');
        label.title=child.path;
        const use=document.createElement('small');use.textContent=selected?'Selected':'Use';use.className='lora-folder-use';
        file.append(label,use);
        file.onclick=()=>{
          loraInspectEpoch++;state.settings.lora.path=child.path;
          if($('surpriseLockStyle'))$('surpriseLockStyle').checked=true;
          loraListError='';syncLoras();save();
          inspectSelectedLora(child.path,true);
        };
        files.append(file);
      }
      card.append(files);
    }else{
      const empty=document.createElement('p');empty.className='hint';
      empty.textContent=items.get(folder)?.kind==='unavailable'?'Folder not found. Check the path, then remove and re-add it.':'No usable YuE2 adapters found yet. Refresh the list after adding files.';
      card.append(empty);
    }
    container.append(card);
  }
}
async function scanLoraFolder(entry){
  const result=await api('/api/loras/folders/scan',{folder:entry});
  for(const file of result.files||[]){
    localLoras.set(file.path,{...file,name:file.name||loraName(file.path)});
    if(!loraCatalogue.some(item=>item.path===file.path))loraCatalogue.push(file);
  }
  if(result.errors?.length)loraListError=result.errors.length+' incompatible file(s) skipped in '+entry+'.';
  syncLoras();
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
    const previous=localLoras.get(info.path);
    // File inspection responses carry no folder placement; keep the scanned one.
    localLoras.set(info.path,{...info,...(previous?.relative?{relative:previous.relative,parent:previous.parent}:{}),name:loraCatalogue.find(item=>item.path===info.path)?.name||loraName(info.path)});
    if(epoch===loraInspectEpoch&&state.settings.lora.path===path){state.settings.lora.path=info.path;loraListError='';syncLoras();save();if(fillStyle)offerLoraTrainingStyle(info,previousStyle);}
  }catch(error){if(epoch===loraInspectEpoch&&state.settings.lora.path===path){loraListError=error.message;syncLoras();}}
}
async function refreshLoras(){
  if(!state.settings.lora)return;
  try{const data=await api('/api/loras');loraCatalogue=data.loras;loraFolder=data.folder;loraListError=data.rejected.length?data.rejected.length+' incompatible or invalid file(s) excluded.':'';}
  catch(error){loraListError=error.status===404?'Restart Studio after current renders finish to enable LoRA selection.':error.message;}
  syncLoras();
  const folders=state.settings.lora.custom_folders||[];
  for(const folder of folders)await scanLoraFolder(folder).catch(()=>{});
  if(state.settings.lora.path)await inspectSelectedLora(state.settings.lora.path);
}
function bindLoras(){
  $('refreshLoras').onclick=()=>busy('refreshLoras',refreshLoras);
  for(const id of ['loraSelect','surpriseLoraSelect'])if($(id))$(id).onchange=()=>{loraInspectEpoch++;state.settings.lora.path=$(id).value;if(state.settings.lora.path&&$('surpriseLockStyle'))$('surpriseLockStyle').checked=true;loraListError='';syncLoras();save();if(state.settings.lora.path)return inspectSelectedLora(state.settings.lora.path,true);};
  if($('refreshSurpriseLoras'))$('refreshSurpriseLoras').onclick=()=>busy('refreshSurpriseLoras',refreshLoras);
  $('loraStrength').oninput=()=>{state.settings.lora.strength=Number($('loraStrength').value);syncLoras();save();};
  $('loraAutoTrigger').onchange=()=>{state.settings.lora.auto_trigger=$('loraAutoTrigger').checked;syncLoras();save();};
  $('addLoraFolder').onclick=()=>busy('addLoraFolder',async()=>{
    const entry=$('loraFolderPath').value.trim().replace(/^"(.*)"$/,'$1');
    if(!entry){toast('Paste or type a folder path first.',true);return;}
    const result=await api('/api/loras/folders/scan-all',{folders:[entry]});
    if(result.errors.length)throw new Error(result.errors[0].error+' Check the path and try again.');
    const stored=result.folders[0]?.path||entry;
    const data=await api('/api/settings/validate',{lora:{...state.settings.lora,custom_folders:[...(state.settings.lora.custom_folders||[]),stored]}});
    state.settings=data.settings;
    if(!state.settings.lora.custom_folders.includes(stored))state.settings.lora.custom_folders.push(stored);
    await scanLoraFolder(stored);
    $('loraFolderPath').value='';
    save();toast('Folder added. Its adapters are in the list below.');
  },'Scanning…');
  $('useLocalLora').onclick=()=>busy('useLocalLora',async()=>{
    const previousStyle=loraStyleSnapshot();
    const raw=$('loraLocalPath').value.trim().replace(/^"(.*)"$/,'$1');
    if(!raw)throw new Error('Paste a LoRA file path first.');
    // Try the path as a single file first; any valid adapter is selectable,
    // even when it lives outside the saved custom folders.
    let inspectError='';
    try{
      const info=await api('/api/loras/inspect',{path:raw});
      localLoras.set(info.path,{...info,name:loraName(info.path)});
      state.settings.lora.path=info.path;
      if($('surpriseLockStyle'))$('surpriseLockStyle').checked=true;
      loraListError='';syncLoras();save();
      offerLoraTrainingStyle(info,previousStyle);
      toast('LoRA selected for future songs.');
      return;
    }catch(error){inspectError=error.message;}
    // Not a usable file: treat the pasted string as a folder and scan it.
    const data=await api('/api/loras/folders/scan-all',{folders:[raw]});
    if(data.folders.length&&data.folders[0].files.length){
      const folder=data.folders[0];
    const first=folder.files[0];
    for(const file of folder.files){
      localLoras.set(file.path,{...file,name:file.name||loraName(file.path)});
      if(!loraCatalogue.some(item=>item.path===file.path))loraCatalogue.push(file);
    }
    const info=localLoras.get(first.path);
    state.settings.lora.path=first.path;
    if($('surpriseLockStyle'))$('surpriseLockStyle').checked=true;
    loraListError='';syncLoras();save();
    offerLoraTrainingStyle(info,previousStyle);
    toast((folder.files.length===1?'LoRA selected':'First of '+folder.files.length+' LoRAs selected')+' for future songs.');
    return;
    }
    // Neither a usable file nor a usable folder: classify from the scan result.
    // scan-all only reports the entry as an error when it is not a directory,
    // so an existing folder (empty or holding only invalid files) lands below.
    const normalize=p=>p.replace(/[\\/]+$/,'').toLowerCase();
    const missing=data.errors.length&&normalize(data.errors[0].folder)===normalize(raw)&&/No such file or directory|cannot find/i.test(inspectError);
    if(missing)throw new Error('That path doesn\'t exist. Paste an existing folder or .safetensors file path.');
    if(data.folders.length){
      const skipped=data.folders[0].errors.length;
      throw new Error('No usable YuE2 LoRA files were found in that folder.'+(skipped?' '+skipped+' invalid file(s) skipped.':''));
    }
    throw new Error('That file is not a usable YuE2 LoRA. Add its folder above, then pick it from the folder card. ('+inspectError+')');
  });
  refreshLoras();
}
