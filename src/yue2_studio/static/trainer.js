'use strict';
let trainerData=null;
function trainerOptions(){return {folder:$('trainerFolder').value.trim().replace(/^"(.*)"$/,'$1'),clip_seconds:Number($('trainerClip').value)};}
function trainerSummary(){
  if(!trainerData)return;
  const selected=trainerData.tracks.filter(row=>row.enabled),seconds=selected.reduce((n,row)=>n+row.seconds,0),clips=selected.reduce((n,row)=>n+row.clips,0);
  $('trainerSummary').textContent=selected.length+' of '+trainerData.tracks.length+' songs selected · '+(seconds/60).toFixed(1)+' minutes · '+clips+' complete '+trainerData.clip_seconds+'-second clips';
}
function renderTrainer(){
  $('trainerReview').hidden=!trainerData;if(!trainerData)return;
  const container=$('trainerTracks');container.replaceChildren();
  for(const row of trainerData.tracks){
    const card=document.createElement('article');card.className='trainer-track';
    const label=document.createElement('label');label.className='check-label';
    const check=document.createElement('input');check.type='checkbox';check.checked=row.enabled;check.disabled=Boolean(row.error)||!row.clips;
    check.onchange=()=>{row.enabled=check.checked;trainerSummary();$('trainerSaveStatus').textContent='Unsaved selection changes';};
    label.append(check,document.createTextNode(row.name));card.append(label);
    const meta=document.createElement('p');meta.className='hint';meta.textContent=row.error||row.seconds.toFixed(1)+' s · '+row.sample_rate+' Hz · '+row.channels+' channels · '+row.clips+' clips';card.append(meta);
    if(row.warnings.length){const warning=document.createElement('p');warning.className='hint';warning.textContent=row.warnings.join(' ');card.append(warning);}
    container.append(card);
  }
  trainerSummary();
}
async function scanTrainer(){
  await busy('trainerScan',async()=>{
    const result=await api('/api/trainer/scan',trainerOptions());trainerData=result;
    $('trainerFolder').value=result.folder;$('trainerStatus').textContent=result.note;
    if(!$('trainerName').value)$('trainerName').value=result.metadata.singer_name?result.metadata.singer_name+' · first experiment':'My style experiment';
    if(!$('trainerTrigger').value)$('trainerTrigger').value=result.metadata.style_trigger||'';
    if(!$('trainerCaption').value)$('trainerCaption').value=result.metadata.style_prompt||'';
    $('trainerSaveStatus').textContent='Review your shared style and song selection, then save.';renderTrainer();
  },'Scanning audio headers…');
}
async function refreshTrainer(){
  try{
    const data=await api('/api/trainer/projects');
    const select=$('trainerProjects'),previous=select.value;select.replaceChildren(new Option(data.projects.length?'Choose a saved setup':'No saved projects',''));
    for(const project of data.projects)select.add(new Option(project.name+' · '+new Date(project.created).toLocaleString(),project.id));
    if(data.projects.some(p=>p.id===previous))select.value=previous;
  }catch(error){$('trainerStatus').textContent=error.status===404?'Restart Studio after current renders finish to enable dataset preparation.':error.message;}
}
function bindTrainer(){
  $('trainerCheck').onclick=()=>busy('trainerCheck',checkTrainerSetup);
  $('trainerUseModels').onclick=()=>{
    if(!trainerPrepared.model||!trainerPrepared.vae)return;
    state.settings.runtime.model=trainerPrepared.model;state.settings.runtime.vae=trainerPrepared.vae;save();
    $('trainerSetupStatus').textContent='Downloaded model paths selected for future training and generation. Active and queued runs are unchanged. Check setup again.';
  };
  $('trainerDownload').onclick=()=>confirmReplace('Download full training models?',
    'Downloads approximately 7.8 GB of official YuE2 + VAE weights to a separate local cache, unless already cached. Model license terms apply (CC BY-NC 4.0). Requires internet and disk space. This queues a CPU-only download after existing Studio jobs, not training, and does not enable GGUF LoRAs.',()=>busy('trainerDownload',async()=>{
      const job=await api('/api/trainer/download',{confirmed:true});
      await openRun(job.id);await refreshTrainerRuns();
    }));
  $('trainerTrain').onclick=()=>{
    const select=$('trainerProjects'),id=select.value;
    if(!id){toast('Choose a saved training project first.',true);return;}
    const payload={project_id:id,steps:Number($('trainerSteps').value),learning_rate:Number($('trainerRate').value),rank:Number($('trainerRank').value),checkpoint_every:Number($('trainerCheckpoint').value),model:state.settings.runtime.model,vae:state.settings.runtime.vae};
    confirmReplace('Queue this saved training setup?',(select.selectedOptions[0]?.textContent||id)+'. Unsaved dataset/style edits are not included. Existing Studio jobs finish first.',()=>busy('trainerTrain',async()=>{
      const job=await api('/api/trainer/train',payload);
      $('trainerTrainStatus').textContent='Queued '+job.title+'. Open its run for progress, logs, checkpoints, and Cancel.';
      await refreshTrainerRuns();toast('Training added to the GPU queue.');
    }));
  };
  $('trainerScan').onclick=()=>trainerData?confirmReplace('Rescan the dataset?','This replaces the current song selections. Your shared style stays in the form.',scanTrainer):scanTrainer();
  $('trainerSelectAll').onclick=()=>{for(const row of trainerData.tracks)row.enabled=!row.error&&row.clips>0;renderTrainer();};
  $('trainerSelectNone').onclick=()=>{for(const row of trainerData.tracks)row.enabled=false;renderTrainer();};
  $('trainerSave').onclick=()=>busy('trainerSave',async()=>{
    if(!trainerData)throw new Error('Scan a dataset first.');
    const options=trainerOptions();if(options.folder!==trainerData.folder||options.clip_seconds!==trainerData.clip_seconds)throw new Error('Folder or scan options changed. Scan again before saving.');
    const saved=await api('/api/trainer/projects',{...options,name:$('trainerName').value,goal:$('trainerGoal').value,trigger:$('trainerTrigger').value,default_caption:$('trainerCaption').value,
      tracks:trainerData.tracks.map(({name,bytes,mtime_ns,enabled})=>({name,bytes,mtime_ns,enabled}))});
    $('trainerSaveStatus').textContent='Saved setup: '+saved.name+' · '+saved.id.slice(0,8)+'. Training has not started.';await refreshTrainer();$('trainerProjects').value=saved.id;toast('Training setup saved.');
  });
  $('trainerOpen').onclick=()=>{
    const id=$('trainerProjects').value;if(!id)return;
    const open=()=>busy('trainerOpen',async()=>{
      const data=await api('/api/trainer/projects/'+id);trainerData=data;
      $('trainerName').value=data.name;$('trainerGoal').value=data.goal;$('trainerFolder').value=data.folder;$('trainerClip').value=data.clip_seconds;$('trainerTrigger').value=data.trigger;$('trainerCaption').value=data.default_caption;
      $('trainerStatus').textContent=data.note;$('trainerSaveStatus').textContent='Loaded saved setup. Saving rechecks source files and creates a new version.';renderTrainer();
    });
    if(trainerData)confirmReplace('Open this training setup?','This replaces the current training form. Save it first if you want to keep your edits.',open);else open();
  };
  $('trainerRefresh').onclick=()=>{refreshTrainer();refreshTrainerRuns();};refreshTrainer();refreshTrainerRuns();
  setInterval(()=>{if(state.view==='trainer')refreshTrainerRuns();},4000);
}

let trainerRunsBusy=false,trainerRunsSignature='';
async function refreshTrainerRuns(){
  if(trainerRunsBusy)return;
  trainerRunsBusy=true;
  try{
    const {jobs}=await api('/api/jobs'),runs=jobs.filter(job=>['training','trainer_setup'].includes(job.kind));
    const signature=JSON.stringify(runs);
    if(signature===trainerRunsSignature)return;
    trainerRunsSignature=signature;
    const container=$('trainerRuns');container.replaceChildren();
    if(!runs.length){container.textContent='No training runs yet.';return;}
    for(const job of runs){
      const row=document.createElement('div');row.className='row wrap';
      const text=document.createElement('p');text.className='hint';text.textContent=job.title+' · '+(statusText[job.status]||job.status)+(job.error?' · '+job.error:'');
      row.append(text,button('Progress / checkpoints',()=>openRun(job.id)));container.append(row);
    }
    if(runs.some(job=>job.status==='complete'))await refreshLoras();
  }catch(error){$('trainerTrainStatus').textContent=error.message;}
  finally{trainerRunsBusy=false;}
}

let trainerPrepared={};
async function checkTrainerSetup(){
  const result=await api('/api/trainer/check',{model:state.settings.runtime.model,vae:state.settings.runtime.vae,
    ...($('trainerProjects').value?{project_id:$('trainerProjects').value}:{})});
  trainerPrepared=result.prepared;
  $('trainerUseModels').disabled=!trainerPrepared.model||!trainerPrepared.vae;
  $('trainerSetupStatus').textContent=(result.ready?'Setup checks passed. GPU memory sufficiency is not guaranteed.':'Setup needs attention:')+'\n'+[...result.issues,...result.warnings].join('\n');
}
