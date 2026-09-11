'use strict';
let musicModels=null,modelStatusBusy=false,modelSettingsKey='',modelRefreshTimer;
const modelBytes=n=>(n/1e9).toFixed(2)+' GB';
function syncMusicEngine(){
  if(!state.boot)return;
  $('musicEngine').value=['torch','audio.cpp'].includes(state.settings.runtime.backend)?state.settings.runtime.backend:'';
  const key=JSON.stringify([state.settings.runtime.backend,state.settings.gguf]);
  if(key!==modelSettingsKey){modelSettingsKey=key;clearTimeout(modelRefreshTimer);if(state.settings.runtime.backend==='audio.cpp')$('musicEngineStatus').textContent='Checking GGUF setup…';modelRefreshTimer=setTimeout(refreshMusicModels,100);}
  if(state.settings.runtime.backend!=='audio.cpp')$('musicEngineStatus').textContent=state.settings.runtime.backend==='torch'?'Original engine · full score tools available':state.settings.runtime.backend+' · advanced engine';
}
async function refreshMusicModels(){
  if(modelStatusBusy||!state.boot)return;
  modelStatusBusy=true;
  try{
    musicModels=await api('/api/models');
    const snapshot=JSON.stringify(state.settings);
    const check=await api('/api/models/check',state.settings);
    if(snapshot===JSON.stringify(state.settings)&&state.settings.runtime.backend==='audio.cpp'){
      const short=state.settings.gguf.model_gguf.replace('yue2-3b-','').replace('.gguf','').toUpperCase();
      $('musicEngineStatus').textContent='GGUF · '+short+' · '+(check.ready?'Files ready · experimental':'Setup needed');
    }
    if($('modelsDialog').open)renderMusicModels(check);
  }catch(e){$('musicEngineStatus').textContent='Could not check model setup';if($('modelsDialog').open)$('modelSetupFeedback').textContent=e.message;}
  finally{modelStatusBusy=false;}
}
function renderMusicModels(check){
  const d=musicModels,t=d.transfer,active=['downloading','verifying','cancelling'].includes(t.status);
  $('modelEngineFound').textContent=d.executable?'Detected: '+d.executable:'No engine detected in the standard folders. Enter your installed executable or follow the setup guide.';
  $('modelFolder').textContent='Downloads: '+d.model_dir;
  $('modelGpu').textContent=(d.gpu?d.gpu.name+' · '+(d.gpu.memory_mib/1024).toFixed(1)+' GiB VRAM. Suggested starting point: '+d.suggested.toUpperCase()+'. ':'GPU memory could not be detected. Q8 is the balanced starting point. ')+'This is a suggestion, not a memory-fit guarantee. Longer songs and other apps change memory use.';
  const cards=$('modelCards');cards.replaceChildren();
  for(const model of d.variants){
    const card=document.createElement('article');card.className='model-card';
    const heading=document.createElement('h3');heading.textContent=model.label+(d.suggested===model.id?' · Suggested':'');
    const note=document.createElement('p');note.textContent=model.note;
    const size=document.createElement('p');size.className='hint';size.textContent=modelBytes(model.total_bytes)+' complete bundle · '+(model.installed?'Files present':modelBytes(model.missing_bytes)+' missing');
    const use=button('Use '+model.label,()=>busy(use.id,async()=>{
      const next=clone(state.settings);next.runtime.backend='audio.cpp';next.gguf.model_dir=d.model_dir;next.gguf.model_gguf=model.main;next.gguf.vae_gguf='yue2-vae-f16.gguf';
      if(!next.gguf.executable)next.gguf.executable=d.executable;
      const checked=await api('/api/models/check',next);if(!checked.ready)throw Error(checked.error);
      state.settings=(await api('/api/settings/validate',next)).settings;save();syncMusicEngine();await refreshMusicModels();toast(model.label+' selected. Your song is unchanged.');
    }),'primary small');use.id='useModel-'+model.id;use.disabled=!model.installed||active;
    const downloadButton=button(model.installed?'Verify files':'Download '+model.label,()=>busy(downloadButton.id,async()=>{await api('/api/models/download',{variant:model.id});await refreshMusicModels();}));downloadButton.id='downloadModel-'+model.id;downloadButton.disabled=active;
    card.append(heading,note,size,use,downloadButton);cards.append(card);
  }
  $('modelTransfer').hidden=t.status==='idle';
  $('modelTransferText').textContent=t.status==='complete'?'Download verified. Choose Use model to switch.':t.status+' · '+(t.file||'')+' · '+modelBytes(t.bytes)+' / '+modelBytes(t.total)+(t.error?' · '+t.error:'');
  $('modelProgress').value=t.total?100*t.bytes/t.total:0;
  $('cancelModelDownload').hidden=!active;$('cancelModelDownload').disabled=t.status==='cancelling';
  $('modelSetupFeedback').textContent=check.ready?'Selected GGUF files and executable are present. Backend compatibility is checked when you generate.':check.error;
}
async function openMusicModels(){
  $('modelExecutable').value=state.settings.gguf.executable||'';
  $('modelsDialog').showModal();await refreshMusicModels();
}
function bindMusicModels(){
  $('manageModels').onclick=openMusicModels;
  $('modelsNav').onclick=openMusicModels;
  $('doneModels').onclick=()=>$('modelsDialog').close();
  $('refreshModelStatus').onclick=refreshMusicModels;
  $('cancelModelDownload').onclick=()=>busy('cancelModelDownload',async()=>{await api('/api/models/cancel',{});await refreshMusicModels();});
  $('saveModelExecutable').onclick=()=>busy('saveModelExecutable',async()=>{
    const next=clone(state.settings);next.gguf.executable=$('modelExecutable').value.trim().replace(/^"(.*)"$/,'$1');
    state.settings=(await api('/api/settings/validate',next)).settings;$('modelExecutable').value=state.settings.gguf.executable;save();await refreshMusicModels();
  });
  $('musicEngine').onchange=async()=>{
    state.settings.runtime.backend=$('musicEngine').value;save();syncMusicEngine();await refreshMusicModels();
    if(state.settings.runtime.backend==='audio.cpp'){
      try{const check=await api('/api/models/check',state.settings);if(!check.ready)await openMusicModels();}catch(e){feedbackError(e);}
    }
  };
  syncMusicEngine();refreshMusicModels();
  setInterval(()=>{if($('modelsDialog').open)refreshMusicModels();},1500);
}
