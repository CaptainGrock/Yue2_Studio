'use strict';
const sheetZoom={get run(){return window.zoomRun;},set run(v){window.zoomRun=v;},get abc(){return window.zoomAbc;},set abc(v){window.zoomAbc=v;}};
const ZOOM_STEPS=[1,1.5,2,3];
window.zoomRun=window.zoomRun||1;
window.zoomAbc=window.zoomAbc||1;
const $ = id => document.getElementById(id);
const clone = value => JSON.parse(JSON.stringify(value));
const state = {
zoomRun:1,zoomAbc:1,boot:null,settings:{},mode:'create',upload:null,sourceJob:'',jobs:[],view:'create',activeId:null,runId:null,connection:{provider:'openai',model:'',max_tokens:4096,timeout:360,context_length:32768,temperature:null},connections:{},draft:null,settingsSnapshot:null};
let saveTimer,toastTimer,polling=false,modelEpoch=0,restoreCallback=null;
const oomNotified=new Set();
const ICON = name => {const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');const use=document.createElementNS(svg.namespaceURI,'use');use.setAttribute('href','#i-'+name);svg.append(use);return svg;};
const THEME_KEY='yue2-studio-theme-v1';
const THEMES={
  midnight:{background:'#111614',accent:'#b8efcd'},
  ocean:{background:'#0d1720',accent:'#7bdff2'},
  violet:{background:'#17121f',accent:'#d2a8ff'},
  ember:{background:'#1c1512',accent:'#ffb38a'},
  daylight:{background:'#f4f5f2',accent:'#202421'}
};
let currentTheme={name:'midnight',...THEMES.midnight};
function hexRgb(hex){const n=parseInt(hex.slice(1),16);return {r:n>>16,g:n>>8&255,b:n&255};}
function rgbHex({r,g,b}){return '#'+[r,g,b].map(v=>Math.round(Math.max(0,Math.min(255,v))).toString(16).padStart(2,'0')).join('');}
function mix(a,b,amount){const x=hexRgb(a),y=hexRgb(b);return rgbHex({r:x.r+(y.r-x.r)*amount,g:x.g+(y.g-x.g)*amount,b:x.b+(y.b-x.b)*amount});}
function readableInk(hex){const {r,g,b}=hexRgb(hex);return (r*299+g*587+b*114)/1000>155?'#111714':'#f7f8f5';}
function applyTheme(theme,persist=true){
  const background=theme.background,accent=theme.accent;
  currentTheme={name:theme.name,background,accent};
  const root=document.documentElement,{r,g,b}=hexRgb(background),dark=(r*299+g*587+b*114)/1000<150,contrast=dark?'#ffffff':'#000000';
  const surface=mix(background,contrast,dark?.045:.035),surface2=mix(background,contrast,dark?.075:.065),border=mix(background,contrast,dark?.14:.16);
  const values={'--bg':background,'--panel':surface,'--panel2':surface2,'--border':border,'--text':mix(background,contrast,dark?.9:.84),'--muted':mix(background,contrast,dark?.6:.57),'--soft':mix(background,contrast,dark?.43:.44),'--accent':accent,'--accent-ink':readableInk(accent),'--sidebar':mix(background,'#000000',dark?.1:.055),'--hover':mix(background,accent,dark?.12:.1),'--active':mix(background,accent,dark?.2:.17),'--top-border':mix(background,contrast,dark?.11:.13)};
  for(const [key,value] of Object.entries(values))root.style.setProperty(key,value);
  root.style.colorScheme=dark?'dark':'light';root.dataset.theme=currentTheme.name;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',background);
  if(persist)try{localStorage.setItem(THEME_KEY,JSON.stringify(currentTheme));}catch{}
  syncThemeDialog();
}
function syncThemeDialog(){if(!$('appearanceDialog'))return;document.querySelectorAll('#appearanceDialog .theme-card[data-theme]').forEach(card=>{const selected=card.dataset.theme===currentTheme.name;card.classList.toggle('selected',selected);card.setAttribute('aria-pressed',String(selected));});}
function loadTheme(){try{const saved=JSON.parse(localStorage.getItem(THEME_KEY));const name=THEMES[saved?.name]?saved.name:'midnight';applyTheme({name,...THEMES[name]},false);}catch{applyTheme({name:'midnight',...THEMES.midnight},false);}}
function bindAppearance(){$('appearanceNav').onclick=()=>{syncThemeDialog();$('appearanceDialog').showModal();};document.querySelectorAll('#appearanceDialog .theme-card[data-theme]').forEach(card=>card.onclick=()=>{const name=card.dataset.theme;applyTheme({name,...THEMES[name]});toast(`${card.querySelector('strong').textContent} theme applied.`);});$('resetTheme').onclick=()=>applyTheme({name:'midnight',...THEMES.midnight});$('doneAppearance').onclick=()=>$('appearanceDialog').close();}
loadTheme();
function button(text,fn,style='subtle small'){const b=document.createElement('button');b.className='button '+style;b.textContent=text;b.onclick=fn;return b;}
function message(id,text,error=false){const box=$(id);box.hidden=!text;box.className='feedback'+(error?' error':'');box.textContent=text;}
function toast(text,error=false){clearTimeout(toastTimer);$('toast').hidden=false;$('toast').className='toast'+(error?' error':'');$('toast').textContent=text;toastTimer=setTimeout(()=>{$('toast').hidden=true;},error?10000:4500);}
async function api(path,data,options={}){const response=await fetch(path,{...options,method:data===undefined?'GET':'POST',headers:data===undefined?{}:{'Content-Type':'application/json','X-Studio-Token':state.boot?.token||''},body:data===undefined?undefined:JSON.stringify(data)});const body=await response.json();if(!response.ok)throw new Error(body.error||'Request failed.');return body;}
async function busy(id,fn,label='Working…'){const el=$(id),original=[...el.childNodes];el.disabled=true;el.textContent=label;try{return await fn();}catch(error){toast(error.message,true);return null;}finally{el.disabled=false;el.replaceChildren(...original);}}
function feedbackError(error){toast(error.message,true);}
function showOomFailure(job){
  if(!job||oomNotified.has(job.id)||$('oomDialog').open)return;
  oomNotified.add(job.id);
  $('oomText').textContent=job.auto_retry?.artist_lora
    ?'The automatic retry also ran out of GPU memory. Artist LoRA must keep AR offloading disabled. The song may be too long for the available VRAM. Close other applications using the GPU and try again.'
    :'The automatic retry also ran out of GPU memory. The song may be too long for the available VRAM. Check for background applications using the GPU, close them, and try again.';
  $('oomOpenRun').onclick=()=>{$('oomDialog').close();openRun(job.id);};
  $('oomDialog').showModal();
}
function checkOomFailures(){showOomFailure(state.jobs.find(job=>job.status==='failed'&&job.failure_kind==='cuda_oom'&&job.auto_retry?.exhausted&&!oomNotified.has(job.id)));}
window.addEventListener('load',()=>{$('oomClose').onclick=()=>$('oomDialog').close();setInterval(checkOomFailures,1000);});
function download(name,data,type='application/json'){const url=URL.createObjectURL(new Blob([data],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function projectData(){if(state.settings.lora&&!Array.isArray(state.settings.lora.custom_folders))state.settings.lora.custom_folders=[];return {version:1,surprise:{lock_style:$('surpriseLockStyle').checked,profanity:$('surpriseProfanity').value,count:$('surpriseCount').value,voice:$('surpriseVoice').value,style:$('surpriseStyle').value,language:$('surpriseLanguage').value},title:$('songTitle').value,style:$('style').value,lyrics:$('lyrics').value,abc:$('abc').value,mode:state.mode,cot:$('planMode').value,seed:$('seed').value,settings:clone(state.settings),brief:$('brief').value,action:$('assistAction').value,instructions:$('writingInstructions').value,upload:state.upload,source_job:state.sourceJob,connection:publicConnection(state.connection)};}
function publicConnection(value){return Object.fromEntries(['provider','model','base_url','max_tokens','timeout','context_length','temperature'].filter(k=>value[k]!==undefined).map(k=>[k,value[k]]));}
function save(){if(!state.boot)return;clearTimeout(saveTimer);$('saveStatus').textContent='Saving…';saveTimer=setTimeout(()=>{try{localStorage.setItem('yue2-studio-draft-v1',JSON.stringify(projectData()));$('saveStatus').textContent='Draft saved locally';}catch(error){$('saveStatus').textContent='Save project to keep this draft';}},350);updateCounts();}
function updateCounts(){syncLoras();if(typeof syncMusicEngine==='function')syncMusicEngine();$('ggufNote').hidden=state.settings.runtime?.backend!=='audio.cpp';$('planButton').disabled=$('planMode').value==='off'||state.settings.runtime?.backend==='audio.cpp';const lyrics=$('lyrics').value.trim();$('wordCount').textContent=(lyrics.replace(/\[[^\]]*\]/g,'').match(/\S+/g)||[]).length+' words';let count=0;if(state.boot)for(const group of state.boot.groups)for(const f of group.fields)if(state.settings[group.id][f.key]!==f.default)count++;$('changedCount').textContent=count?count+' changed':'Default';$('renderSummary').textContent=(state.settings.runtime?.backend==='audio.cpp'?'audio.cpp GGUF · ':'')+(state.settings.generation?.ode_steps||32)+' synthesis steps · Lossless FLAC';$('scoreBadge').textContent=$('abc').value.trim()?'Score supplied':state.mode==='cover'?'Required for cover':'Optional';if(typeof updateExperimentalSliders==='function')updateExperimentalSliders();}
function hasSong(){return Boolean($('style').value.trim()||$('lyrics').value.trim()||$('abc').value.trim());}
function confirmReplace(title,text,fn){$('confirmTitle').textContent=title;$('confirmText').textContent=text;restoreCallback=fn;$('confirmDialog').showModal();}
function maybeReplace(title,text,fn){if(hasSong())confirmReplace(title,text,fn);else fn();}
function switchView(view){$('artistView').hidden=view!=='artist';state.view=view;$('createView').hidden=view!=='create';$('libraryView').hidden=view!=='library';$('trainerView').hidden=view!=='trainer';$('pageCrumb').textContent=({create:'Create music',library:'Song library',trainer:'Style trainer',artist:'Artist trainer'}[view]||'Studio');document.querySelectorAll('[data-view]').forEach(el=>el.classList.toggle('active',el.dataset.view===view));if(view==='library'){renderLibrary();refreshLibraryJobs();}}
function setMode(mode,changePlan=true){state.mode=mode;const cover=mode==='cover';$('coverSection').hidden=!cover;$('createTab').classList.toggle('active',!cover);$('coverTab').classList.toggle('active',cover);$('createTab').setAttribute('aria-selected',String(!cover));$('coverTab').setAttribute('aria-selected',String(cover));$('generateButton').textContent=cover?'Create cover':'Create song';$('generateButton').append(ICON('arrow'));if(cover){$('scoreDetails').open=true;if(changePlan)$('planMode').value='melody';}updateMode();}
function updateMode(){const mode=$('planMode').value;$('modeHint').textContent={full:'Plans a melody with chords, then renders the song.',melody:'Uses a melody plan while generating new accompaniment.',off:'Generates audio directly. No ABC input or editable plan.'}[mode];$('planButton').disabled=mode==='off';updateCounts();}
function restoreProject(data){$('surpriseLockStyle').checked=data.surprise?.lock_style??Boolean(data.settings?.lora?.path);$('surpriseProfanity').value=data.surprise?.profanity==='required'?'required':'prompt';$('surpriseCount').value=data.surprise?.count??1;$('surpriseVoice').value=['any','female','male','duet','instrumental'].includes(data.surprise?.voice)?data.surprise.voice:'any';$('surpriseStyle').value=String(data.surprise?.style||'');$('surpriseLanguage').value=String(data.surprise?.language??'English');updateSurpriseLabel();for(const [id,key] of [['songTitle','title'],['style','style'],['lyrics','lyrics'],['abc','abc'],['brief','brief'],['writingInstructions','instructions']])$(id).value=typeof data[key]==='string'?data[key]:'';state.settings=clone(state.boot.defaults);for(const g of state.boot.groups)for(const f of g.fields)if(data.settings?.[g.id]?.[f.key]!==undefined)state.settings[g.id][f.key]=data.settings[g.id][f.key];$('planMode').value=['full','melody','off'].includes(data.cot)?data.cot:'full';$('seed').value=data.seed??831001;$('assistAction').value=['song','lyrics','style','review','adapt'].includes(data.action)?data.action:'song';state.upload=data.upload&&/^[a-f0-9]{32}\.[a-z0-9]+$/.test(data.upload.upload_id)?{upload_id:data.upload.upload_id,name:String(data.upload.name||'Source recording'),url:'/uploads/'+data.upload.upload_id}:null;state.sourceJob=String(data.source_job||'');state.connection.api_key='';state.connections={};if(data.connection&&state.boot.providers.some(p=>p.id===data.connection.provider)){state.connection={...state.connection,...publicConnection(data.connection),api_key:''};state.connections={};}setMode(data.mode==='cover'?'cover':'create',false);updateUpload();updateRunnerBadge();message('scoreResult','');save();}
function newSong(){maybeReplace('Start a new song?','Your current draft will be replaced. Use Save project first if you want to keep a portable copy.',()=>{const connection=state.connection,instructions=$('writingInstructions').value;restoreProject({settings:state.settings,instructions});state.connection=connection;state.draft=null;$('draftPreview').hidden=true;$('rawResponse').hidden=true;message('assistantProgress','');updateRunnerBadge();switchView('create');save();});}
function insertAtCursor(text){const el=$('lyrics'),start=el.selectionStart,end=el.selectionEnd;const before=el.value.slice(0,start),after=el.value.slice(end);const prefix=before&&!before.endsWith('\n')?'\n\n':'';el.value=before+prefix+text+after;el.focus();el.setSelectionRange(start+prefix.length+text.length,start+prefix.length+text.length);save();}
const STYLES={soul:'English, indie soul, intimate expressive vocal, warm electric piano, rounded bass, brushed drums, relaxed pocket, 92 BPM, spacious arrangement',pop:'English, warm piano pop, expressive female vocal, acoustic piano, rounded bass, restrained drums, memorable melodic chorus, unhurried phrasing, 88 BPM',cinematic:'English, cinematic folk, warm textured male vocal, fingerpicked acoustic guitar, cello, upright bass, gentle percussion, intimate verses building to a wide chorus, 80 BPM',synth:'English, atmospheric synth-pop, soft close vocal, analog synth pads, pulsing bass, crisp electronic drums, bittersweet late-night mood, 108 BPM'};
const EXPERIMENTS={
  composition:{group:'abc',slider:'compositionSlider',output:'compositionValue',summary:'compositionSettings',levels:[
    {label:'Very familiar',values:{temperature:.55,top_p:.82,top_k:16}},
    {label:'Familiar',values:{temperature:.6,top_p:.86,top_k:24}},
    {label:'Default',values:{temperature:.7,top_p:.9,top_k:30}},
    {label:'Unexpected',values:{temperature:.85,top_p:.94,top_k:45}},
    {label:'Very unexpected',values:{temperature:1,top_p:.97,top_k:64}}]},
  performance:{group:'semantic',slider:'performanceSlider',output:'performanceValue',summary:'performanceSettings',levels:[
    {label:'Very controlled',values:{temperature:.8,top_p:.88,top_k:50}},
    {label:'Controlled',values:{temperature:.9,top_p:.92,top_k:75}},
    {label:'Default',values:{temperature:1,top_p:.95,top_k:100}},
    {label:'Adventurous',values:{temperature:1.1,top_p:.97,top_k:140}},
    {label:'Very adventurous',values:{temperature:1.2,top_p:.99,top_k:200}}]},
  influence:{group:'generation',slider:'influenceSlider',output:'influenceValue',summary:'influenceSettings',levels:[
    {label:'Very loose',values:{cfg_scale:.85}},
    {label:'Loose',values:{cfg_scale:.95}},
    {label:'Default',values:{cfg_scale:null}},
    {label:'Focused',values:{cfg_scale:1.05}},
    {label:'Very focused',values:{cfg_scale:1.15}}]}
};
function matchingExperimentLevel(experiment){return experiment.levels.findIndex(level=>Object.entries(level.values).every(([key,value])=>state.settings[experiment.group]?.[key]===value));}
function experimentSummary(name,level){const v=level.values;if(name==='influence')return 'CFG: '+(v.cfg_scale===null?'Automatic (1.0, or 1.01 in Direct audio)':v.cfg_scale);return (name==='composition'?'Planner':'Audio tokens')+': temp '+v.temperature+' · top-p '+v.top_p+' · top-k '+v.top_k;}
function updateExperimentalSliders(){if(!state.boot)return;for(const [name,experiment] of Object.entries(EXPERIMENTS)){const slider=$(experiment.slider);if(!slider)continue;const match=matchingExperimentLevel(experiment),level=experiment.levels[match<0?2:match],control=slider.closest('.experiment-control');if(match>=0)slider.value=match;$(experiment.output).textContent=match<0?'Custom advanced values':level.label;$(experiment.summary).textContent=match<0?'Open Advanced settings to review the custom values.':experimentSummary(name,level);control.classList.toggle('custom',match<0);const unused=name==='composition'&&($('planMode').value==='off'||Boolean($('abc').value.trim()));const disabled=state.settings.runtime?.backend==='audio.cpp';slider.disabled=disabled;control.classList.toggle('bypassed',disabled||unused);if(unused)$(experiment.output).textContent='Not used for this song';slider.setAttribute('aria-valuetext',$(experiment.output).textContent);}}
function applyExperiment(name,index){const experiment=EXPERIMENTS[name];if(!experiment||!Number.isInteger(index)||!experiment.levels[index]||$(experiment.slider).disabled)return;const level=experiment.levels[index];Object.assign(state.settings[experiment.group],level.values);updateCounts();save();}
function resetExperiments(){if(state.settings.runtime?.backend==='audio.cpp')return;for(const experiment of Object.values(EXPERIMENTS))Object.assign(state.settings[experiment.group],experiment.levels[2].values);updateCounts();save();toast('Experimental sliders reset to engine defaults.');}
function bindExperimentalSliders(){for(const [name,experiment] of Object.entries(EXPERIMENTS))$(experiment.slider).addEventListener('input',event=>applyExperiment(name,Number(event.target.value)));$('resetExperimental').onclick=resetExperiments;updateExperimentalSliders();}
function stylePreset(key){const apply=()=>{$('style').value=STYLES[key];save();};if($('style').value.trim())confirmReplace('Replace the current style?','This starting point will replace the Style field. Your lyrics and score stay available.',apply);else apply();}
function openSettings(group){state.settingsSnapshot=clone(state.settings);$('settingsSearch').value='';$('changedOnly').checked=false;message('settingsFeedback','');renderSettings();$('advancedDialog').showModal();if(group)setTimeout(()=>document.getElementById('settings-'+group)?.scrollIntoView({block:'start'}),0);}
function readField(input,f){if(f.kind==='bool')return input.checked;if(f.kind==='integer'||f.kind==='number'){if(input.value.trim()===''&&f.default===null)return null;const n=Number(input.value);return input.value.trim()===''?NaN:n;}return input.value;}
function settingControl(group,f){let input;if(f.choices){input=document.createElement('select');for(const v of f.choices)input.add(new Option(v,v));}else{input=document.createElement('input');input.type=f.kind==='bool'?'checkbox':['integer','number'].includes(f.kind)?'number':'text';if(f.min!==null)input.min=f.min;if(f.max!==null)input.max=f.max;if(input.type==='number')input.step=f.kind==='integer'?'1':String(f.step||'any');if(f.default===null)input.placeholder='Automatic';}input.id='setting-'+group+'-'+f.key;const v=state.settings[group][f.key];if(f.kind==='bool')input.checked=v;else input.value=v??'';input.addEventListener('input',()=>{state.settings[group][f.key]=readField(input,f);input.closest('.setting-field').classList.toggle('changed',state.settings[group][f.key]!==f.default);updateCounts();});return input;}
function renderSettings(){const query=$('settingsSearch').value.toLowerCase(),changedOnly=$('changedOnly').checked,container=$('settingsFields'),nav=$('settingsNav');container.replaceChildren();nav.replaceChildren();for(const group of state.boot.groups){const fields=group.fields.filter(f=>(!query||[group.title,f.label,f.key,f.note].join(' ').toLowerCase().includes(query))&&(!changedOnly||state.settings[group.id][f.key]!==f.default));if(!fields.length)continue;const section=document.createElement('section');section.className='settings-group';section.id='settings-'+group.id;const h=document.createElement('h3');h.textContent=group.title;const subtitle=document.createElement('p');subtitle.textContent=group.subtitle;section.append(h,subtitle);for(const f of fields){const row=document.createElement('div');row.className='setting-field'+(state.settings[group.id][f.key]!==f.default?' changed':'');const label=document.createElement('label');label.htmlFor='setting-'+group.id+'-'+f.key;label.textContent=f.label;const key=document.createElement('span');key.className='setting-key';key.textContent=group.id+'.'+f.key;label.append(key);const note=document.createElement('p');note.className='setting-note';note.textContent=f.note;const defaultNote=document.createElement('span');defaultNote.className='setting-default';defaultNote.textContent='Default: '+(f.default===null?'Automatic':String(f.default));note.append(defaultNote);row.append(label,settingControl(group.id,f),note);if(f.key==='custom_folders')row.hidden=true;else section.append(row);}container.append(section);const link=button(group.title,()=>{section.scrollIntoView({block:'start'});nav.querySelectorAll('button').forEach(b=>b.classList.remove('active'));link.classList.add('active');});nav.append(link);}if(!changedOnly){const section=document.createElement('section');section.className='settings-group';section.id='settings-fixed';const h=document.createElement('h3');h.textContent='Fixed engine values';section.append(h);for(const f of state.boot.fixed){if(query&&![f.label,f.value,f.note].join(' ').toLowerCase().includes(query))continue;const row=document.createElement('div');row.className='setting-field fixed';const label=document.createElement('label');label.textContent=f.label;const value=document.createElement('strong');value.textContent=f.value;const note=document.createElement('p');note.className='setting-note';note.textContent=f.note;row.append(label,value,note);section.append(row);}container.append(section);nav.append(button('Fixed engine values',()=>section.scrollIntoView({block:'start'})));}if(!container.children.length){const p=document.createElement('p');p.className='hint';p.textContent='No settings match this filter.';container.append(p);}}
async function applySettings(){await busy('doneSettings',async()=>{const result=await api('/api/settings/validate',state.settings);state.settings=result.settings;state.settingsSnapshot=null;$('advancedDialog').close();save();toast('Engine settings applied.');},'Validating…');}
function cancelSettings(){if(state.settingsSnapshot){state.settings=state.settingsSnapshot;state.settingsSnapshot=null;updateCounts();}}
function provider(){return state.boot.providers.find(p=>p.id===$('provider').value);}
function readConnection(){const p=provider();return {provider:p.id,model:$('modelSelect').value==='__custom__'?$('customModel').value.trim():$('modelSelect').value,api_key:$('apiKey').value.trim(),base_url:$('baseUrl').value.trim()||p.url,temperature:$('llmTemperature').value===''?null:Number($('llmTemperature').value),max_tokens:Number($('llmMaxTokens').value),timeout:Number($('llmTimeout').value),context_length:Number($('llmContext').value)};}
function selectModels(list,selected=''){const select=$('modelSelect');select.replaceChildren();for(const id of list)select.add(new Option(id,id));select.add(new Option('Custom model ID…','__custom__'));select.value=list.includes(selected)?selected:selected?'__custom__':list[0]||'__custom__';$('customModel').value=list.includes(selected)?'':selected;$('customModelField').hidden=select.value!=='__custom__';}
function loadProvider(connection){const p=provider(),local=['lm_studio','ollama','own_server'].includes(p.id);$('baseUrlField').hidden=!local;$('baseUrl').value=connection.base_url||p.url;$('apiKeyLabel').textContent=p.key?'API key':'API key (optional)';$('apiKey').value=connection.api_key||'';$('apiKey').type='password';$('showKey').textContent='Show';$('localContextField').hidden=!['lm_studio','ollama'].includes(p.id);$('llmTemperature').value=connection.temperature??'';$('llmMaxTokens').value=connection.max_tokens||4096;$('llmTimeout').value=connection.timeout||360;$('llmContext').value=connection.context_length||32768;selectModels(p.models,connection.model||'');$('modelSource').textContent=p.liveSource||(p.models.length?'Starter choices from your video builder. Refresh to get the provider’s live model list.':'Refresh models to discover your server’s models, or enter an exact model ID.');$('runnerNote').textContent={openai:'Uses the OpenAI Responses API. Model access depends on your API account. Leave temperature automatic for reasoning models that do not support it.',lm_studio:'Start LM Studio’s local server and load a text model. Uses its native /api/v1/chat interface, including input context and output limits. Unload its model before music generation if GPU memory is tight.',ollama:'Start Ollama and install a text model. Discovers installed models dynamically and releases the model after writing with keep_alive=0.',own_server:'OpenAI Chat Completions server. Accepts a server root, /v1 URL, or full /v1/chat/completions URL. Model loading and context allocation are managed by your server.',apifreellm:'Uses the video builder’s APIFreeLLM message interface. This provider does not expose temperature or output-token controls; leave them at their defaults.'}[p.id]||'Choose a text-generation model. API keys are sent only to this provider’s configured endpoint.';message('connectionResult','');}
function openRunner(){modelEpoch++;$('provider').replaceChildren();for(const p of state.boot.providers)$('provider').add(new Option(p.label,p.id));$('provider').value=state.connection.provider;loadProvider(state.connection);$('runnerDialog').showModal();}
function updateRunnerBadge(){const p=state.boot.providers.find(p=>p.id===state.connection.provider);$('llmLabel').textContent=state.connection.model?p.label:'Connect a writing assistant';$('llmModelLabel').textContent=state.connection.model||'Choose a provider & model';$('llmDot').classList.toggle('neutral',!state.connection.model);}
async function refreshModels(){const epoch=++modelEpoch,cfg=readConnection();await busy('refreshModels',async()=>{message('connectionResult','Loading available models…');const result=await api('/api/llm/models',cfg);if(epoch!==modelEpoch)return;provider().models=result.models;provider().liveSource=result.source;selectModels(result.models,cfg.model);$('modelSource').textContent=result.source;message('connectionResult',result.models.length+' models found.');},'Refreshing…');}
function saveRunner(){const cfg=readConnection();if(!cfg.model){message('connectionResult','Select a model or enter its exact ID.',true);return;}if(provider().key&&!cfg.api_key){message('connectionResult','Enter an API key for this provider.',true);return;}state.connection=cfg;state.connections[cfg.provider]=cfg;updateRunnerBadge();$('runnerDialog').close();save();toast('Writing runner selected.');}
async function testConnection(){await busy('testConnection',async()=>{message('connectionResult','Contacting the selected model…');try{const result=await api('/api/llm/test',readConnection());message('connectionResult',result.model+'\n'+result.text+(result.truncated?'\nResponse reached the output limit.':''));}catch(error){message('connectionResult',error.message,true);throw error;}},'Testing…');}
async function assist(){if(!state.connection.model){openRunner();return;}await busy('assistButton',async()=>{message('assistantProgress','Writing with '+state.connection.model+'… You can keep editing your song while it works.');try{const result=await api('/api/llm/assist',{connection:state.connection,action:$('assistAction').value,brief:$('brief').value,title:$('songTitle').value,style:$('style').value,lyrics:$('lyrics').value,abc:$('abc').value,instructions:$('writingInstructions').value});state.draft=result.draft;$('rawResponse').hidden=false;$('rawResponseText').textContent=result.text;$('draftPreview').hidden=!result.draft;if(result.draft){$('draftTitle').value=result.draft.title;$('draftLyrics').value=result.draft.lyrics;$('draftStyle').value=result.draft.style;$('draftNotes').textContent=result.draft.notes;$('draftModel').textContent=result.model;}message('assistantProgress',result.truncated?'The response reached its output limit. Review carefully or increase maximum output tokens and try again.':result.warning||'Your draft is ready. Review and edit it below, then apply what you like.');}catch(error){message('assistantProgress',error.message,true);throw error;}},'Writing your draft…');}
function applyDraft(part){const apply=()=>{if(part==='all')$('songTitle').value=$('draftTitle').value;if(part==='all'||part==='lyrics')$('lyrics').value=$('draftLyrics').value;if(part==='all'||part==='style')$('style').value=$('draftStyle').value;save();toast('Draft applied to your song.');};maybeReplace('Apply this '+(part==='all'?'draft':part)+'?','This replaces the corresponding editor fields with the draft you reviewed. Save your project first to keep the current version.',apply);}
function updateUpload(){const source=state.upload;$('sourceName').textContent=source?source.name:'Drop your source recording here';$('sourcePlayer').hidden=!source;if(source)$('sourcePlayer').src='/uploads/'+source.upload_id;else{$('sourcePlayer').pause();$('sourcePlayer').removeAttribute('src');}$('transcribeButton').disabled=!source;}
async function uploadAudio(file){if(!file)return;await busy('chooseAudio',async()=>{if(file.size>300*1024*1024)throw new Error('Source audio must be under 300 MB.');toast('Uploading source audio…');const response=await fetch('/api/upload',{method:'POST',headers:{'X-Studio-Token':state.boot.token,'X-Filename':encodeURIComponent(file.name),'Content-Type':'application/octet-stream'},body:file});const result=await response.json();if(!response.ok)throw new Error(result.error);state.upload=result;state.sourceJob='';updateUpload();save();toast('Source audio ready for transcription.');},'Uploading…');}
async function transcribe(){await busy('transcribeButton',async()=>{const job=await api('/api/transcribe',{upload_id:state.upload?.upload_id,settings:state.settings,title:state.upload?.name||'Source transcription'});state.activeId=job.id;await poll();openRun(job.id);toast('Transcription added to the GPU queue.');},'Adding to queue…');}
async function checkScore(strip=false){await busy(strip?'prepareAbc':'checkAbc',async()=>{const result=await api('/api/score',{abc:$('abc').value,strip,keep_voice:$('keepVoice').value});if(strip){$('abc').value=result.abc;$('planMode').value='melody';updateMode();save();renderAbcSheet();}const voices=Object.entries(result.report.voices).map(([name,v])=>name+': '+v.sounding_notes+' notes').join(' · ');message('scoreResult',(strip?'Melody prepared; retained notes and timing checked.\n':'Native score structure checked.\n')+result.report.bpm+' BPM · '+result.report.nominal_duration_seconds.toFixed(1)+' seconds in the score\n'+voices+'\nListen to the rendered audio to verify musical accuracy.');},'Checking…');}
function requestData(){const seed=$('seed').value.trim();if(!/^[0-9]{1,19}$/.test(seed)||BigInt(seed)>=2n**63n)throw new Error('Seed must be a whole number from 0 to 9223372036854775807.');const request={style:$('style').value,lyrics:$('lyrics').value,cot:$('planMode').value,seed,id:'song'};if($('abc').value.trim())request.abc=$('abc').value;return {title:$('songTitle').value,mode:state.mode,stage:'audio',request,settings:state.settings,source_job:state.sourceJob};}
async function generate(stage){await busy(stage==='plan'?'planButton':'generateButton',async()=>{const payload=requestData();payload.stage=stage;const job=await api('/api/generate',payload);state.activeId=job.id;save();await poll();toast((stage==='plan'?'Plan':'Song')+' added to the GPU queue.');},'Adding to queue…');}
const statusText={queued:'Queued',running:'Rendering',cancelling:'Stopping…',complete:'Complete',cancelled:'Cancelled',failed:'Failed',needs_review:'Review ending',interrupted:'Interrupted'};
function libraryFilterMatches(job,filter){if(filter==='all')return true;if(filter==='starred')return job.starred===true;const song=job.kind==='generation'&&job.stage==='audio';if(!song)return false;const gguf=job.backend==='audio.cpp';if(filter==='completed')return ['complete','needs_review'].includes(job.status);if(filter==='gguf')return gguf;if(filter==='torch')return !gguf;if(filter==='failed')return job.status==='failed';if(filter==='active')return ['running','queued','cancelling'].includes(job.status);return false;}
function renderLibrary(){const query=$('librarySearch').value.toLowerCase(),filter=$('libraryFilter').value,dateFilter=$('libraryDateFilter').value,chosen=$('libraryDate').value;const jobs=state.jobs.filter(j=>(!query||j.title.toLowerCase().includes(query))&&libraryFilterMatches(j,filter)&&libraryDateMatches(j,dateFilter,chosen));const list=$('libraryList');list.replaceChildren();$('libraryEmpty').hidden=jobs.length>0;if(!jobs.length){$('libraryEmpty').querySelector('h2').textContent=state.jobs.length?'No runs match this view.':'Your first song belongs here.';$('libraryEmpty').querySelector('p').textContent=state.jobs.length?'Try a different search or filter.':'Create a song or transcribe a recording. Its audio, score, settings, and progress will appear here.';}for(const j of jobs){const card=document.createElement('article');card.className='run-card';const art=document.createElement('div');art.className='run-art';art.append(ICON(j.kind==='transcription'?'cover':j.stage==='plan'?'file':'music'));const text=document.createElement('div'),title=document.createElement('h3'),meta=document.createElement('small');title.textContent=j.title;const titleRow=document.createElement('div'),star=document.createElement('button');titleRow.className='run-title-row';star.type='button';star.className='star-button'+(j.starred?' starred':'');star.append(ICON('star'));star.title=j.starred?'Remove star':'Star this song';star.setAttribute('aria-label',(j.starred?'Remove star from ':'Star ')+j.title);star.setAttribute('aria-pressed',String(Boolean(j.starred)));star.onclick=()=>toggleStar(j.id);const rename=document.createElement('button');rename.type='button';rename.className='rename-button';rename.append(ICON('pencil'));rename.title='Edit song name';rename.setAttribute('aria-label','Edit song name: '+j.title);rename.onclick=()=>renameSong(j.id);titleRow.append(star,title,rename);meta.textContent=(j.kind==='trainer_setup'?'Training-model download':j.kind==='training'?'LoRA training':j.kind==='transcription'?'Transcription':j.stage==='plan'?'Symbolic plan':j.mode==='cover'?'Cover':'Original song')+' · '+new Date(j.created).toLocaleString();text.append(titleRow,meta);const actions=document.createElement('div');const status=document.createElement('span');status.className='run-state '+j.status;status.textContent=j.kind==='transcription'&&j.status==='running'?'Transcribing':statusText[j.status]||j.status;actions.append(status);if(j.mastered){const pill=document.createElement('span');pill.className='pill mint mastered-pill';pill.textContent='Mastered';pill.title='This song has a mastered version; open the run to switch between original and master.';actions.append(pill);}actions.append(button('Open run',()=>openRun(j.id)),button('Remove',()=>removeRun(j.id),'danger small'));if(j.kind==='generation'&&['complete','needs_review'].includes(j.status)){const masterBtn=button(j.mastered?'Re-master':'Master',async()=>{try{masterBtn.disabled=true;const result=await api('/api/jobs/'+j.id+'/master',{});const current=state.jobs.find(item=>item.id===j.id);if(current)current.mastered=true;toast('Mastered · glue '+result.metrics.glue_compression_db+' dB, peak '+result.metrics.mastered_peak_dbfs+' dBFS.');if(state.view==='library')renderLibrary();}catch(error){feedbackError(error);}finally{masterBtn.disabled=false;}},'small');masterBtn.title='Creates a mastered copy: gentle harshness taming, low warmth, glue compression, -1 dBFS peak. The original render stays untouched.';actions.append(masterBtn);}card.append(art,text,actions);if(j.kind==='generation'&&j.stage==='audio'&&['complete','needs_review'].includes(j.status)){const player=document.createElement('audio');player.controls=true;player.preload='none';player.src='/artifacts/'+j.id+'/result/audio.flac';player.setAttribute('aria-label','Listen to '+j.title);card.append(player);}list.append(card);}}
async function refreshLibraryJobs(){try{const result=await api('/api/jobs');state.jobs=result.jobs;$('libraryCount').textContent=state.jobs.length;renderLibrary();}catch(error){const empty=$('libraryEmpty');empty.hidden=false;empty.querySelector('h2').textContent='Could not load your library.';empty.querySelector('p').textContent=error.message;}}
function artifactUrl(id,path){return '/artifacts/'+id+'/'+path.split('/').map(encodeURIComponent).join('/');}
let runScoreState={jobId:'',abc:'',lyrics:'',editing:false,previewOn:false,previewCtl:null,dragLink:null,userEdited:false,previewCursor:{els:null,key:null}};;
function lyricsOf(job){return (job.input&&job.input.request&&job.input.request.lyrics)||'';}
/* Build the note span -> SVG element map from abcjs timing events.
   abcjs merges simultaneous notes across staves into ONE event (e.g. a vocal
   rest "Dm"z24 sounding alongside an accompaniment d'4). The event's flat
   startChar/endChar points at the rest token, so per-voice spans come from
   startCharArray/endCharArray, matched to element groups by index. Note-free
   groups (rests, decoratived) are dropped so every mapped element is a note. */
function buildNoteMap(text,tms){
  const out=[];
  for(const t of (tms||[])){
    if(!t||t.type!=='event'||typeof t.startChar!=='number'||typeof t.endChar!=='number'||t.endChar<=t.startChar||t.endChar>text.length)continue;
    const groups=(t.elements||[]).map(g=>(Array.isArray(g)?g:[g]).filter(Boolean));
    for(let i=0;i<groups.length;i++){
      const g=groups[i];
      const hasHead=g.some(e=>(e.classList&&e.classList.contains('abcjs-notehead'))||(e.querySelector&&e.querySelector('.abcjs-notehead')));
      if(!hasHead)continue;
      const sc=(t.startCharArray&&typeof t.startCharArray[i]==='number')?t.startCharArray[i]:t.startChar;
      const ec=(t.endCharArray&&typeof t.endCharArray[i]==='number')?t.endCharArray[i]:t.endChar;
      const sp=noteSpanOnly(text,sc,ec)||noteSpanOnly(text,t.startChar,t.endChar);
      if(!sp)continue;
      out.push({startChar:sp.start,endChar:sp.end,els:g.filter(Boolean)});
    }
  }
  return out.filter(n=>n.els.length);
}
function renderRunScore(){const box=$('runScoreSheet');if(!box||!runScoreState.jobId)return;const textPre=runScoreState.editing?$('runScoreTa').value:runScoreState.abc;const rkey=runScoreState.editing+'|'+textPre;if(runScoreState.renderKey===rkey&&box.querySelector('svg')){syncRunCursor();return;}runScoreState.renderKey=rkey;const __sy=box?box.scrollTop:0,__sx=box?box.scrollLeft:0;runScoreState.timings=null;runScoreState.cursorEls=null;runScoreState.cursorKey=null;runScoreState.noteMap=null;runScoreState.msByEl=null;runScoreState.totalMs=0;box.innerHTML='';const hint=$('runScoreHint');hint.hidden=true;hint.textContent='';const text=runScoreState.editing?$('runScoreTa').value:runScoreState.abc;if(!text){box.innerHTML='<p class="hint">This run has no score to display.</p>';return;}if(!window.ABCJS){box.textContent=text;hint.hidden=false;hint.textContent='abcjs failed to load - showing ABC text instead.';return;}try{const width=Math.max(320,Math.min(880,(box.clientWidth||800)-16));const visual=ABCJS.renderAbc(box,text,{staffwidth:width,paddingtop:8,paddingbottom:8,add_classes:true,scrollVertical:true});try{if(visual&&visual[0]){let tms=visual[0].setTiming(0,0);if(!tms||!tms.length)tms=visual[0].setTiming(120,0);if(tms)runScoreState.timings=tms.filter(t=>t&&isFinite(t.milliseconds)&&t.elements&&t.elements.length).map(t=>({ms:t.milliseconds,elements:t.elements})).sort((a,b)=>a.ms-b.ms);try{runScoreState.noteMap=buildNoteMap(text,tms);runScoreState.msByEl=(function(){const m=new Map();for(const t of runScoreState.timings||[]){for(const g of (t.elements||[])){for(const e of (Array.isArray(g)?g:[g]))if(e)m.set(e,t.ms);}}return m;})();runScoreState.totalMs=runScoreState.timings&&runScoreState.timings.length?runScoreState.timings[runScoreState.timings.length-1].ms:0;}catch(e2){runScoreState.noteMap=null;runScoreState.msByEl=null;runScoreState.totalMs=0;}}}catch(err){}syncRunCursor();const svg=box.querySelector('svg');if(svg){const w=parseFloat(svg.getAttribute('width'))||svg.clientWidth||width;const h=parseFloat(svg.getAttribute('height'))||svg.clientHeight||0;if(w&&h){svg.setAttribute('viewBox','0 0 '+w+' '+h);}svg.removeAttribute('width');svg.removeAttribute('height');svg.style.width=((sheetZoom.run||1)*100)+'%';ensureZoomBar('run');ensureTransport('run');box.scrollTop=__sy;box.scrollLeft=__sx;}const first=box.querySelector('svg');if(first&&first.warnings&&first.warnings.length){hint.hidden=false;hint.textContent='abcjs notes: '+first.warnings.join(' | ');}}catch(err){box.innerHTML='';const fb=document.createElement('pre');fb.textContent=text;box.append(fb);hint.hidden=false;hint.textContent='Score could not be drawn: '+err.message;}}
function timemapScoreMs(audioSec){
  const m=runScoreState.timemap;
  if(!m||!m.anchors||m.anchors.length<2)return null;
  const a=m.anchors;
  if(audioSec<=a[0][0])return a[0][1]*1000;
  for(let i=0;i<a.length-1;i++){
    if(audioSec<=a[i+1][0]){
      const [a0,s0]=a[i],[a1,s1]=a[i+1];
      const f=(audioSec-a0)/Math.max(1e-6,a1-a0);
      return (s0+f*(s1-s0))*1000;
    }
  }
  const [a0,s0]=a[a.length-2],[a1,s1]=a[a.length-1];
  const f=(audioSec-a0)/Math.max(1e-6,a1-a0);
  return (s0+f*(s1-s0))*1000;
}
function timemapAudioMs(scoreMs){
  const m=runScoreState.timemap;
  if(!m||!m.anchors||m.anchors.length<2)return null;
  const a=m.anchors, sSec=scoreMs/1000;
  if(sSec<=a[0][1])return a[0][0]*1000;
  for(let i=0;i<a.length-1;i++){
    if(sSec<=a[i+1][1]){
      const [a0,s0]=a[i],[a1,s1]=a[i+1];
      const f=(sSec-s0)/Math.max(1e-6,s1-s0);
      return (a0+f*(a1-a0))*1000;
    }
  }
  const [a0,s0]=a[a.length-2],[a1,s1]=a[a.length-1];
  const f=(sSec-s0)/Math.max(1e-6,s1-s0);
  return (a0+f*(a1-a0))*1000;
}
async function loadRunTimemap(jobId){
  try{
    const m=await api('/api/jobs/'+jobId+'/timemap');
    if(state.runId===jobId&&m&&m.anchors&&m.anchors.length>=2)runScoreState.timemap=m;
  }catch(e){/* no map: linear fallback stays */}
}
function syncRunCursor(){const player=$('runPlayer');
/* timeupdate fires only ~4Hz, which can skip short notes; drive the cursor at display rate while playing. */
if(player&&!player.paused){if(runScoreState._cursorRaf)cancelAnimationFrame(runScoreState._cursorRaf);runScoreState._cursorRaf=requestAnimationFrame(()=>{const p=$('runPlayer');if(p&&!p.paused)syncRunCursor();});}
const timings=runScoreState.timings;if(!timings||!timings.length)return;const dur=player.duration;if(!dur||!isFinite(dur))return;const last=timings[timings.length-1].ms;if(!(last>0))return;const mapped=timemapScoreMs(player.currentTime);const scoreMs=mapped!=null?mapped:player.currentTime/dur*last;let lo=0,hi=timings.length-1,idx=0;while(lo<=hi){const mid=(lo+hi)>>1;if(timings[mid].ms<=scoreMs+0.5){idx=mid;lo=mid+1;}else hi=mid-1;}const t=timings[idx];const els=(t.elements||[]).reduce((a,g)=>a.concat(Array.isArray(g)?g.filter(e=>e&&e.classList):[]),[]);const key=t.ms+'#'+els.length;if(runScoreState.cursorKey===key&&runScoreState.cursorEls)return;if(runScoreState.cursorEls)runScoreState.cursorEls.forEach(e=>e.classList.remove('abc-playing'));runScoreState.cursorEls=els;runScoreState.cursorKey=key;els.forEach(e=>e.classList.add('abc-playing'));const box=$('runScoreSheet');const el=els[0];if(el&&el.getBoundingClientRect){const b=box.getBoundingClientRect(),r=el.getBoundingClientRect();const inView=r.top>=b.top&&r.bottom<=b.bottom;if(!inView){if(r.bottom>b.bottom-24)box.scrollTop+=r.bottom-b.bottom-64;else if(r.top<b.top+24)box.scrollTop+=r.top-b.top+64;}}}function seekSheet(event){const timings=runScoreState.timings;if(!timings||!timings.length)return;const player=$('runPlayer');if(!player.duration||!isFinite(player.duration))return;const last=timings[timings.length-1].ms;if(!(last>0))return;let best=null,bd=Infinity;for(const t of timings){const el=t.elements&&t.elements[0]&&t.elements[0][0];if(!el||!el.getBoundingClientRect)continue;const r=el.getBoundingClientRect();const d=(r.left+r.width/2-event.clientX)**2+((r.top+r.height/2-event.clientY)**2)/4;if(d<bd){bd=d;best=t;}}if(best){const inv=timemapAudioMs(best.ms);player.currentTime=inv!=null?Math.min(player.duration-0.05,inv/1000):best.ms/last*player.duration;runScoreState.cursorKey=null;syncRunCursor();}}function syncRunEditor(){const editing=runScoreState.editing;const ed=$('runScoreEditor');if(ed)ed.classList.toggle('open',editing);const ew=$('runLyricsEditWrap');if(ew)ew.style.display=editing?'block':'none';const lt=$('runLyricsText');if(lt)lt.style.display=editing?'none':'block';setScoreDragging(true);}
function setRunEditing(on){stopScorePreview();detachScoreDrag();runScoreState.editing=on;$('runEditBtn').textContent=on?'Close editor':'Edit score & lyrics';if(on){$('runScoreTa').value=runScoreState.abc;$('runLyricsEdit').value=runScoreState.lyrics;}else{runScoreState.lyrics=$('runLyricsEdit').value;if(runScoreState.overlay){runScoreState.baseAbc=stripLyricsFromAbc($('runScoreTa').value);applyRunOverlay();}else{runScoreState.abc=$('runScoreTa').value;renderRunScore();}}syncRunEditor();}
async function startRerender(id){const abc=runScoreState.editing?$('runScoreTa').value:runScoreState.abc;const lyrics=runScoreState.editing&&$('runLyricsEdit').value.trim()?$('runLyricsEdit').value:'';if(!abc&&!lyrics)throw new Error('Edit the score or lyrics first.');const next=await api('/api/jobs/'+id+'/rerender',{abc,lyrics});state.activeId=next.id;runScoreState.editing=false;syncRunEditor();await openRun(next.id);await poll();toast('Re-render queued with your edits.');}
function runSectionKey(id,part){return 'yue2-run-ui-v1:'+id+':'+part;}
function runSectionOpen(id,part,fallback){
  try{const v=localStorage.getItem(runSectionKey(id,part));if(v!==null)return v==='1';}catch(e){}
  return fallback;
}
function rememberRunSection(id,part,open){
  try{localStorage.setItem(runSectionKey(id,part),open?'1':'0');}catch(e){}
}
function closeMenu(m){if(m)m.hidden=true;}
function closeRunMenus(){closeMenu($('runDownloadMenu'));closeMenu($('runEditMenu'));}

const RUN_SECTIONS=[['runLyricsSection','lyrics',false],['runLogSection','log',false],['runScoreSection','score',true]];

function bindRunMenus(){
  const dlBtn=$('runDownloadMenuBtn'),dlMenu=$('runDownloadMenu');
  const edBtn=$('runEditMenuBtn'),edMenu=$('runEditMenu');
  const showMenu=(btn,menu)=>{const showing=menu.hidden;closeRunMenus();if(!showing)return;menu.hidden=false;const r=btn.getBoundingClientRect();menu.style.top=Math.round(r.bottom+6)+'px';menu.style.right=Math.round(Math.max(8,innerWidth-r.right))+'px';};
  dlBtn.onclick=e=>{e.stopPropagation();showMenu(dlBtn,dlMenu);};
  edBtn.onclick=e=>{e.stopPropagation();showMenu(edBtn,edMenu);};
  document.addEventListener('click',closeRunMenus);
  dlMenu.addEventListener('click',async e=>{
    const b=e.target.closest('button[data-dl]');if(!b)return;
    dlMenu.hidden=true;await runDownload(b.dataset.dl);
  });
  edMenu.addEventListener('click',async e=>{
    const b=e.target.closest('button[data-edit]');if(!b)return;
    edMenu.hidden=true;const id=state.runId;if(!id)return;
    if(b.dataset.edit==='editor')$('runEditBtn').click();
    else if(b.dataset.edit==='rerender'){try{await startRerender(id);}catch(error){feedbackError(error);}}
    else if(b.dataset.edit==='load'){const job=state.jobs.find(j=>j.id===id);if(job)useRun(job,false);}
    else if(b.dataset.edit==='export'){const job=await api('/api/jobs/'+id);download('yue2-run-'+id.slice(0,8)+'.json',JSON.stringify(job.input,null,2));}
  });
  // Log download beside the live log
  const logA=$('runLogDownload');
  if(logA)logA.onclick=e=>{
    e.preventDefault();
    const id=state.runId;if(!id)return;
    const a=document.createElement('a');a.href=artifactUrl(id,'run.log');a.download='run.log';a.click();
  };
  // Section memory
  for(const [elId,part] of RUN_SECTIONS){
    const el=$(elId);if(!el)continue;
    el.addEventListener('toggle',()=>{if(state.runId&&!el.hidden)rememberRunSection(state.runId,part,el.open);});
  }
  // Stage details: collapse/expand only via the summary; clicking marks user intent.
  const prog=$('runProgress');
  if(prog){
    prog.addEventListener('click',()=>{
      prog.dataset.userToggled='1';
      if(prog.dataset.collapsed==='1')delete prog.dataset.collapsed;
      else prog.dataset.collapsed='1';
    });
  }
}
async function runDownload(kind){
  const id=state.runId;if(!id)return;
  const job=await api('/api/jobs/'+id);
  const base=(job.title||'song').replace(/[<>:"/\\|?*\x00-\x1f]/g,'-').slice(0,90)||'song';
  if(kind==='master'){
    const src='result/audio_mastered.flac';
    if(!job.mastered){toast('Master this song first (Master button below).',true);return;}
    const a=document.createElement('a');a.href=artifactUrl(id,src);a.download=base+'-master.flac';a.click();return;
  }
  if(kind==='flac'){
    const a=document.createElement('a');a.href=artifactUrl(id,'result/audio.flac');a.download=base+'.flac';a.click();return;
  }
  if(kind==='wav'){
    const result=await api('/api/jobs/'+id+'/wav',{});const a=document.createElement('a');a.href=result.url;a.download=base+'.wav';a.click();return;
  }
  if(kind==='mp3'){
    await busy('runDownloadMenuBtn',async()=>{
      const result=await api('/api/jobs/'+id+'/mp3',{});
      const a=document.createElement('a');a.href=result.url;a.download=base+'.mp3';a.click();
    },'Preparing MP3…');
  }
}
async function openRun(id){
  state.runId=id;await updateRun();
  // Per-song section memory (defaults: lyrics+log collapsed, score open)
  for(const [elId,part,def] of RUN_SECTIONS){const el=$(elId);if(el&&!el.hidden)el.open=runSectionOpen(id,part,def);}
  // Stage details auto-collapse when the run is complete (user can expand).
  try{
    const job=state.jobs.find(j=>j.id===id)||await api('/api/jobs/'+id);
    const done=!['queued','running','cancelling'].includes(job.status);
    const prog=$('runProgress');
    if(done&&prog&&!prog.dataset.userToggled)prog.dataset.collapsed='1';
    if(!done&&prog)prog.dataset.collapsed='';
  }catch(e){}
  if(!$('runDialog').open)$('runDialog').showModal();
}
function removeRun(id){const job=state.jobs.find(j=>j.id===id);if(!job)return;if(['queued','running','cancelling'].includes(job.status)){toast('Cancel this run before removing it.',true);return;}confirmReplace('Remove this run?','This permanently deletes "'+job.title+'" and its audio, score, and settings from the library.',async()=>{try{// Release the browser's own handle on this run's audio before deleting on disk.
for(const audio of document.querySelectorAll('audio'))if(audio.src.includes(id)){audio.pause();audio.removeAttribute('src');audio.load();}
await api('/api/jobs/'+id+'/delete',{});state.jobs=state.jobs.filter(j=>j.id!==id);$('libraryCount').textContent=state.jobs.length;if(state.view==='library')renderLibrary();toast('Run removed.');}catch(error){feedbackError(error);}});}
async function updateRun(){if(!state.runId)return;const id=state.runId;const job=await api('/api/jobs/'+id);if(state.runId!==id)return;renderProgress('runProgress',job);$('runTitle').textContent=job.title;$('runType').textContent=job.kind==='trainer_setup'?'TRAINING-MODEL DOWNLOAD':job.kind==='training'?'LORA TRAINING':job.kind==='transcription'?'SOURCE TRANSCRIPTION':job.stage==='plan'?'SYMBOLIC PLAN':'STUDIO RUN';$('runMeta').textContent=(statusText[job.status]||job.status)+' · '+new Date(job.created).toLocaleString();if(job.error||job.warning){message('runFeedback',job.error||job.warning,Boolean(job.error));}$('runCompatInfo').hidden=!job.runtime_adjustments;if(job.runtime_adjustments){$('runCompatInfo').title='';$('runCompatInfo').dataset.tip=job.runtime_adjustments.reason;$('runCompatText').textContent='';}$('runLogPath').textContent=job.log_path||'';$('runLog').textContent=job.log;$('runRequest').textContent=JSON.stringify(job.input,null,2);$('runReceipts').textContent=JSON.stringify(job.receipts||{},null,2);$('runScoreSection').hidden=!job.abc;const scoreOpen=$('runScoreSection').open;if(runScoreState.jobId!==id){stopScorePreview();detachScoreDrag();runScoreState={jobId:id,abc:job.abc||'',lyrics:lyricsOf(job),editing:false,userEdited:false,baseAbc:null,overlay:false,overlayOffsets:[],overlayWords:null,autoOverlay:false,previewCursor:{els:null,key:null}};$('runEditBtn').textContent='Edit score & lyrics';loadRunTimemap(id);}else{if(!runScoreState.editing&&!runScoreState.userEdited&&!runScoreState.overlay)runScoreState.abc=job.abc||'';runScoreState.lyrics=lyricsOf(job);}$('runLyricsEdit').value=runScoreState.lyrics;syncRunEditor();const ovBtn=$('runLyricsOverlayBtn');if(ovBtn){if(ovBtn.dataset.bound!=='1'){ovBtn.onclick=toggleRunLyricsOverlay;ovBtn.dataset.bound='1';}ovBtn.hidden=!(job.abc&&(runScoreState.lyrics||'').trim());if(ovBtn.hidden)runScoreState.autoOverlay=false;if(job.abc&&(runScoreState.lyrics||'').trim()&&!runScoreState.overlay&&!runScoreState.autoOverlay){runScoreState.autoOverlay=true;runScoreState.baseAbc=stripLyricsFromAbc(runScoreState.abc);runScoreState.overlay=true;applyRunOverlay();}updateRunOverlayButton();}if(scoreOpen)renderRunScore();$('runScore').textContent=runScoreState.abc||'';const hasAudio=job.artifacts.includes('result/audio.flac');$('runPlayer').hidden=!hasAudio;if(state.runSourceJob!==id){state.runSourceJob=id;state.runSource=job.mastered?'master':'original';}
if(!job.mastered)state.runSource='original';
const audioUrl=artifactUrl(id,state.runSource==='master'?'result/audio_mastered.flac':'result/audio.flac');if(hasAudio&&$('runPlayer').getAttribute('src')!==audioUrl){$('runPlayer').playbackRate=1;$('runSpeed').value='1';$('runPlayer').src=audioUrl;}const speedRow=$('runSpeedRow');speedRow.hidden=!hasAudio;if(hasAudio&&$('runSpeed').value)$('runPlayer').playbackRate=parseFloat($('runSpeed').value);if(!hasAudio){$('runPlayer').pause();$('runPlayer').removeAttribute('src');}const actions=$('runActions');actions.replaceChildren();if(job.kind==='generation'&&['failed','cancelled','interrupted'].includes(job.status)){const retry=button('Retry saved song',async()=>{try{retry.disabled=true;const next=await api('/api/jobs/'+id+'/retry',{});state.activeId=next.id;await openRun(next.id);await poll();}catch(e){feedbackError(e);}finally{retry.disabled=false;}},'primary small');retry.title='Reuses saved lyrics, style and settings. No LLM call.';actions.append(retry);}if(['queued','running','cancelling'].includes(job.status)){const b=button(job.status==='cancelling'?'Stopping…':'Cancel run',async()=>{try{b.disabled=true;await api('/api/jobs/'+id+'/cancel',{});await poll();}catch(e){feedbackError(e);}finally{b.disabled=false;}},'danger small');b.disabled=job.status==='cancelling';actions.append(b);}if(hasAudio&&job.kind==='generation'&&['complete','needs_review'].includes(job.status)){
if(job.mastered){
actions.append(button(state.runSource==='master'?'Play original':'Play master',()=>{state.runSource=state.runSource==='master'?'original':'master';updateRun();},'small'));
const remaster=button('Re-master',async()=>{try{remaster.disabled=true;const result=await api('/api/jobs/'+id+'/master',{});toast('Re-mastered · glue '+result.metrics.glue_compression_db+' dB, peak '+result.metrics.mastered_peak_dbfs+' dBFS.');await updateRun();}catch(e){feedbackError(e);}finally{remaster.disabled=false;}},'small');remaster.title='Recreates the mastered copy from the original render.';actions.append(remaster);
const masterLink=document.createElement('a');masterLink.href=artifactUrl(id,'result/audio_mastered.flac');masterLink.download='audio_mastered.flac';masterLink.className='button small';masterLink.textContent='Download master';actions.append(masterLink);
}else{
const masterBtn=button('Master',async()=>{try{masterBtn.disabled=true;const result=await api('/api/jobs/'+id+'/master',{});toast('Mastered · glue '+result.metrics.glue_compression_db+' dB, peak '+result.metrics.mastered_peak_dbfs+' dBFS.');state.runSource='master';await updateRun();}catch(e){feedbackError(e);}finally{masterBtn.disabled=false;}},'primary small');masterBtn.title='Creates a mastered copy: gentle harshness taming, low warmth, glue compression, -1 dBFS peak. The original render stays untouched.';actions.append(masterBtn);}}
if(hasAudio)$('runDownloadMenuBtn').hidden=false;if(job.abc){actions.append(button(job.kind==='transcription'?'Review melody in editor':'Use score in editor',()=>useRun(job,true),'primary small'));if($('runEditBtn').dataset.bound!=='1'){$('runEditBtn').onclick=()=>setRunEditing(!runScoreState.editing);$('runEditBtn').dataset.bound='1';}}if(job.kind==='generation'&&job.status!=='complete'&&job.status!=='needs_review')$('runEditMenuBtn').hidden=true;else if(job.kind==='generation')$('runEditMenuBtn').hidden=false;if(job.kind==='generation')actions.append(button('Load request & settings',()=>useRun(job,false)));actions.append(button('Export run input',()=>download('yue2-run-'+id.slice(0,8)+'.json',JSON.stringify(job.input,null,2))));if(job.kind==='generation'){const song={title:job.title,style:job.input.request.style,lyrics:job.input.request.lyrics,source:'generation_request',job_id:id};addLyricExports(actions,()=>song);$('runLyricsSection').hidden=false;$('runLyricsText').textContent=song.lyrics;if(runScoreState.editing)runScoreState.lyrics=song.lyrics||runScoreState.lyrics;else runScoreState.lyrics=song.lyrics;$('runLyricsEdit').value=runScoreState.lyrics;}else $('runLyricsSection').hidden=true;const links=$('artifactLinks');links.replaceChildren();for(const artifact of ['input.json','run.log',...(job.runtime_adjustments?['runtime_adjustments.json']:[]),...job.artifacts]){const link=document.createElement('a');link.href=artifactUrl(id,artifact);link.textContent=artifact.replace('result/','');link.download=artifact.split('/').at(-1);links.append(link);}}
function useRun(job,withScore){const apply=()=>{if(job.kind==='transcription'){$('abc').value=job.abc;state.sourceJob=job.id;setMode('cover');$('scoreDetails').open=true;$('planMode').value=job.input.settings.transcription.task==='full'?'full':'melody';state.upload={upload_id:job.input.upload_id,name:job.title};updateUpload();}else{const input=job.input,request=input.request;restoreProject({title:input.title,...request,settings:input.settings,mode:input.mode,connection:undefined,instructions:$('writingInstructions').value});if(withScore)$('abc').value=job.abc;state.sourceJob=job.id;$('scoreDetails').open=Boolean($('abc').value);}updateMode();renderAbcSheet();message('scoreResult','Score copied into the editor. Check it before rendering; original artifacts are preserved.');$('runDialog').close();setRunEditing(false);switchView('create');save();toast('Run loaded into the editor.');};maybeReplace('Load this run into the editor?','This copies the selected run into your current draft. Save your project first if you want to keep the current version.',apply);}
async function poll(){if(polling||!state.boot)return;polling=true;try{const result=await api('/api/jobs');const changed=JSON.stringify(result.jobs)!==JSON.stringify(state.jobs);state.jobs=result.jobs;$('libraryCount').textContent=state.jobs.length;const running=state.jobs.find(j=>['running','cancelling'].includes(j.status));const pending=state.jobs.filter(j=>j.status==='queued');$('engineStatus').textContent=running?(running.kind==='trainer_setup'?'Model download active':'GPU job active'):pending.length?'Jobs queued':Object.values(state.boot.installed).every(Boolean)?'Local engine ready':'Check model paths';$('engineSub').textContent=running?(running.kind==='trainer_setup'?'Downloading full model weights':running.kind==='training'?'Training style LoRA':running.kind==='transcription'?'Transcribing source melody':'Rendering music')+' · '+pending.length+' queued':'YuE2 + SheetSage2';if(changed&&state.view==='library')renderLibrary();const active=state.jobs.find(j=>j.id===state.activeId)||running||pending[0];if(active){$('activeRun').hidden=false;$('activeTitle').textContent=active.title;$('activeStatus').textContent=(statusText[active.status]||active.status)+(active.error?' · '+active.error:'');const detail=await api('/api/jobs/'+active.id);renderProgress('activeProgress',detail);$('activeLog').textContent=detail.log.split('\n').slice(-6).join('\n');$('activeOpen').onclick=()=>openRun(active.id);}else $('activeRun').hidden=true;if($('runDialog').open&&state.runId)await updateRun();await pollSurprises();}catch(error){$('engineStatus').textContent='Studio disconnected';$('engineSub').textContent='Check the launcher window';}finally{polling=false;}}
function bindShell(){bindLibraryDates();bindAppearance();document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>switchView(el.dataset.view));$('librarySearch').oninput=renderLibrary;$('libraryFilter').onchange=renderLibrary;$('refreshLibrary').onclick=()=>busy('refreshLibrary',refreshLibraryJobs);if($('runnerNav'))$('runnerNav').onclick=()=>state.boot?openRunner():toast('Studio is still starting.',true);if($('advancedNav'))$('advancedNav').onclick=()=>state.boot?openSettings():toast('Studio is still starting.',true);if($('modelsNav'))$('modelsNav').onclick=()=>state.boot&&typeof openMusicModels==='function'?openMusicModels():toast('Music models are still starting.',true);if($('guideNav'))$('guideNav').onclick=()=>$('guideDialog').showModal();}
async function init(){bindShell();try{state.boot=await api('/api/bootstrap');state.settings=clone(state.boot.defaults);bind();connectBrowserLifetime();if(!state.boot.profanity_check){const note=document.createElement('p');note.className='hint';note.textContent='Restart Studio after your current batch finishes to enable Require strong profanity.';$('surpriseProfanity').after(note);}$('compatibilityNote').textContent=state.boot.compatibility?.note||'';$('compatibilityNote').hidden=!state.boot.compatibility?.note;$('systemPrompt').textContent=state.boot.songwriter_prompt;const installed=Object.values(state.boot.installed).every(Boolean);$('engineStatus').textContent=installed?'Local engine ready':'Check model paths';$('engineSub').textContent=installed?'YuE2 + SheetSage2':'Open advanced settings';$('engineDot').classList.toggle('warning',!installed);try{const saved=localStorage.getItem('yue2-studio-draft-v1');if(saved){const data=JSON.parse(saved);const validated=await api('/api/settings/validate',data.settings||{});data.settings=validated.settings;restoreProject(data);}}catch(error){toast('The saved draft could not be restored: '+error.message,true);}updateCounts();updateRunnerBadge();try{if(typeof bindMusicModels==='function')bindMusicModels();}catch(error){toast('Music model controls could not start: '+error.message,true);}await poll();setInterval(poll,2500);}catch(error){$('engineStatus').textContent='Could not connect';$('engineSub').textContent='Start the Studio launcher';toast('Studio could not start: '+error.message,true);$('generateButton').disabled=true;$('planButton').disabled=true;$('assistButton').disabled=true;}}
function bind(){bindExperimentalSliders();bindArtistTrainer();bindLoras();bindTrainer();bindSurprise();bindLyricExports();document.querySelectorAll('[data-view]').forEach(el=>el.onclick=()=>switchView(el.dataset.view));$('createTab').onclick=()=>{setMode('create');save();};$('coverTab').onclick=()=>{setMode('cover');save();};for(const id of ['runnerNav','runnerCard'])$(id).onclick=openRunner;for(const id of ['advancedNav','advancedButton'])$(id).onclick=()=>openSettings();$('guideNav').onclick=()=>$('guideDialog').showModal();$('transcriptionSettings').onclick=()=>openSettings('transcription');$('newProject').onclick=newSong;$('libraryCreate').onclick=()=>switchView('create');$('refreshLibrary').onclick=()=>busy('refreshLibrary',poll);$('librarySearch').oninput=renderLibrary;$('libraryFilter').onchange=renderLibrary;for(const id of ['songTitle','style','lyrics','abc','seed','brief','assistAction','writingInstructions'])$(id).addEventListener('input',save);$('abc').addEventListener('input',()=>message('scoreResult',''));$('planMode').onchange=()=>{updateMode();save();};$('randomSeed').onclick=()=>{const bytes=new Uint32Array(1);crypto.getRandomValues(bytes);$('seed').value=bytes[0];save();};document.querySelectorAll('[data-tag]').forEach(el=>el.onclick=()=>insertAtCursor('['+el.dataset.tag+']\n'));$('moreTags').onclick=()=>{const toolbar=$('moreTags').parentElement;$('moreTags').remove();for(const name of ['Intro','Interlude','Outro','Instrumental']){const b=document.createElement('button');b.textContent='+ '+name;b.onclick=()=>insertAtCursor('['+name+']\n');toolbar.append(b);}};$('lyricTemplate').onclick=()=>insertAtCursor('[Verse]\n\n[Pre-Chorus]\n\n[Chorus]\n\n[Verse]\n\n[Chorus]\n\n[Bridge]\n\n[Chorus]\n\n[Outro]\n');document.querySelectorAll('[data-style]').forEach(el=>el.onclick=()=>stylePreset(el.dataset.style));document.querySelectorAll('[data-brief]').forEach(el=>el.onclick=()=>{$('brief').value=el.dataset.brief;save();});$('styleInspire').onclick=()=>{$('assistAction').value='style';$('brief').focus();$('brief').scrollIntoView({behavior:'smooth',block:'center'});if(!$('brief').value)$('brief').value='Create a coherent musical style for this song. ';save();};$('lyricsImport').onclick=()=>$('textFile').click();$('textFile').onchange=async e=>{const file=e.target.files[0];if(!file)return;if(file.size>500000){toast('Lyrics file is too large.',true);return;}const text=await file.text();const apply=()=>{$('lyrics').value=text;save();};if($('lyrics').value.trim())confirmReplace('Replace the current lyrics?','The imported file replaces the Lyrics field.',apply);else apply();e.target.value='';};$('importAbc').onclick=()=>$('abcFile').click();$('abcFile').onchange=async e=>{const file=e.target.files[0];if(!file)return;if(file.size>500000){toast('ABC file is too large.',true);return;}const text=await file.text();const apply=()=>{$('abc').value=text;$('scoreDetails').open=true;message('scoreResult','Imported score. Check its native structure before rendering.');save();};if($('abc').value.trim())confirmReplace('Replace the current score?','This replaces the editable score with your imported ABC.',apply);else apply();e.target.value='';};$('checkAbc').onclick=()=>checkScore();$('prepareAbc').onclick=()=>checkScore(true);$('chooseAudio').onclick=()=>$('audioFile').click();$('audioFile').onchange=e=>{uploadAudio(e.target.files[0]);e.target.value='';};$('dropZone').ondragover=e=>{e.preventDefault();$('dropZone').classList.add('dragging');};$('dropZone').ondragleave=()=>$('dropZone').classList.remove('dragging');$('dropZone').ondrop=e=>{e.preventDefault();$('dropZone').classList.remove('dragging');uploadAudio(e.dataTransfer.files[0]);};$('transcribeButton').onclick=transcribe;$('generateButton').onclick=()=>generate('audio');$('planButton').onclick=()=>generate('plan');$('settingsSearch').oninput=renderSettings;$('changedOnly').onchange=renderSettings;$('resetSettings').onclick=()=>{state.settings=clone(state.boot.defaults);renderSettings();updateCounts();};$('doneSettings').onclick=applySettings;$('advancedDialog').addEventListener('close',cancelSettings);document.querySelectorAll('.close-dialog').forEach(el=>el.onclick=()=>el.closest('dialog').close());$('runDialog').addEventListener('close',()=>{$('runPlayer').pause();state.runId=null;});$('runScoreSection').addEventListener('toggle',()=>{if($('runScoreSection').open)renderRunScore();});$('runScoreTa').addEventListener('input',()=>renderRunScore());$('runPlayer').addEventListener('timeupdate',syncRunCursor);$('runSpeed').addEventListener('change',()=>{$('runPlayer').playbackRate=parseFloat($('runSpeed').value)||1;});$('runPlayer').addEventListener('seeked',syncRunCursor);$('runScoreSheet').addEventListener('click',event=>{if(runScoreState.previewOn)return;if(runScoreState.timings&&runScoreState.timings.length)seekSheet(event);});bindRunMenus();$('confirmNo').onclick=()=>{$('confirmDialog').close();restoreCallback=null;};$('confirmYes').onclick=()=>{const fn=restoreCallback;restoreCallback=null;$('confirmDialog').close();fn?.();};$('exportProject').onclick=()=>{const name=($('songTitle').value||'untitled-song').replace(/[^\p{L}\p{N}_-]/gu,'-');download(name+'.yue2.json',JSON.stringify(projectData(),null,2));toast('Project exported. API keys are excluded.');};$('importProject').onclick=()=>$('projectFile').click();$('projectFile').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>2*1024*1024)throw new Error('Project must be under 2 MB.');const data=JSON.parse(await file.text());if(data.version!==1||typeof data.lyrics!=='string'||typeof data.style!=='string')throw new Error('Choose a YuE2 Studio project JSON.');const validated=await api('/api/settings/validate',data.settings||{});data.settings=validated.settings;maybeReplace('Open this project?','This replaces the current local draft. API keys are cleared when opening a project.',()=>{restoreProject(data);switchView('create');toast('Project opened. Enter your API key again if using a cloud LLM.');});}catch(error){feedbackError(error);}e.target.value='';};$('provider').onchange=()=>{modelEpoch++;const previous=state.runnerEditingProvider||state.connection.provider;const current=$('provider').value;$('provider').value=previous;state.connections[previous]=readConnection();$('provider').value=current;state.runnerEditingProvider=current;loadProvider(state.connections[current]||{});};$('runnerDialog').addEventListener('close',()=>{state.runnerEditingProvider=null;modelEpoch++;});$('modelSelect').onchange=()=>{$('customModelField').hidden=$('modelSelect').value!=='__custom__';};$('refreshModels').onclick=refreshModels;$('showKey').onclick=()=>{const show=$('apiKey').type==='password';$('apiKey').type=show?'text':'password';$('showKey').textContent=show?'Hide':'Show';};$('testConnection').onclick=testConnection;$('saveConnection').onclick=saveRunner;$('assistButton').onclick=assist;$('applyDraft').onclick=()=>applyDraft('all');$('applyLyrics').onclick=()=>applyDraft('lyrics');$('applyStyle').onclick=()=>applyDraft('style');window.addEventListener('beforeunload',()=>{try{localStorage.setItem('yue2-studio-draft-v1',JSON.stringify(projectData()));}catch{}});}
function updateSurpriseLabel() {
  const count = Number($('surpriseCount').value) || 1;
  $('surpriseButton').replaceChildren(ICON('spark'), document.createTextNode(`Surprise me · create ${count} ${count === 1 ? 'song' : 'songs'}`));
}
function bindSurprise() {
  $('surpriseLockStyle').addEventListener('change',save);
  for (const id of ['surpriseCount','surpriseVoice','surpriseStyle','surpriseLanguage','surpriseProfanity']) {
    $(id).addEventListener('input', () => { updateSurpriseLabel(); save(); });
  }
  $('surpriseButton').onclick = async () => {
    if (!state.connection.model) { openRunner(); return; }
    await busy('surpriseButton', async () => {
      if($('surpriseProfanity').value==='required'&&!state.boot.profanity_check)throw new Error('Restart Studio after the current batch finishes to enable the profanity check.');
      const count = Number($('surpriseCount').value);
      if (!Number.isInteger(count) || count < 1 || count > 50) throw new Error('Choose 1–50 songs.');
      if(hasSong()&&!window.confirm('Surprise me ignores the song in the editor and invents its own lyrics, style and title. Start anyway?'))return;
      if($('surpriseLockStyle').checked&&!state.boot.surprise_style_lock)throw new Error('Restart Studio after current jobs finish to enable locked-style Surprise batches.');
      if($('surpriseLockStyle').checked&&!$('surpriseStyle').value.trim())throw new Error('Enter a style direction before locking it.');
      await api('/api/surprises', {
        ...(state.boot.surprise_style_lock?{lock_style:$('surpriseLockStyle').checked}:{}),
        count, ...(state.boot.profanity_check?{profanity:$('surpriseProfanity').value}:{}), voice: $('surpriseVoice').value, style: $('surpriseStyle').value,
        language: $('surpriseLanguage').value, length: $('surpriseLength').value, brief: $('brief').value,
        instructions: $('writingInstructions').value, cot: $('planMode').value,
        settings: state.settings, connection: state.connection
      });
      save();
      await pollSurprises();
      toast(`Surprise batch started: ${count} ${count === 1 ? 'song' : 'songs'}.`);
    }, 'Starting batch…');
    await pollSurprises();
  };
}
async function pollSurprises() {
  const {batches} = await api('/api/surprises');
  const batch = batches[0];
  if (!batch) return;
  const active = ['queued','writing','rendering','cancelling'].includes(batch.status);
  $('surpriseButton').disabled = active;
  $('stopSurprise').hidden = !active;
  $('stopSurprise').disabled = batch.status === 'cancelling';
  const completed = batch.songs.filter(s => ['complete','needs_review'].includes(s.status)).length;
  const detail = {
    queued:'Waiting for the studio queue.', writing:`Writing song ${batch.current} of ${batch.count}…`,
    rendering:`Rendering song ${batch.current} of ${batch.count}…`,
    cancelling:'Stopping. An in-flight LLM request may finish, but its draft will not be rendered.',
    complete:'Batch finished. Your songs are ready in the library.',
    cancelled:'Batch stopped. Finished songs are kept in the library.',
    interrupted:'Studio restarted. Start a new batch to continue creating.', failed:'Batch stopped after an error.'
  }[batch.status] || batch.status;
  message('surpriseProgress', `${completed} of ${batch.count} songs rendered\n${detail}${batch.error ? '\n'+batch.error : ''}`, batch.status === 'failed');
  const list = $('surpriseSongs');
  list.replaceChildren();
  for (const song of batch.songs) {
    const item = button(song.title, () => openRun(song.id));
    const status = document.createElement('small');
    status.textContent = statusText[state.jobs.find(j => j.id === song.id)?.status || song.status] || song.status;
    item.append(status); list.append(item);
  }
  $('stopSurprise').onclick = () => busy('stopSurprise', async () => {
    await api('/api/surprises/'+batch.id+'/cancel', {});
    await pollSurprises();
  }, 'Stopping…');
}
init();

function renderProgress(id,job){
  const root=$(id),data=job.progress||progressFromLog(job.log||'',job.status),current=data.current;
  const signature=JSON.stringify(data);
  if(root.dataset.signature===signature)return;
  root.dataset.signature=signature;root.replaceChildren();
  const live=['running','cancelling'].includes(job.status);
  const title=document.createElement('div');title.className='progress-heading';
  const label=document.createElement('strong');
  label.textContent=job.status==='queued'?'Waiting for the GPU':job.status==='cancelling'?'Stopping run…':live?(current?.label||'Starting engine…'):(statusText[job.status]||job.status);
  title.append(label);root.append(title);
  const bar=document.createElement('progress');bar.setAttribute('aria-label',current?.label||label.textContent);
  if(live&&current?.status==='running'){
    if(current.total>0){bar.max=current.total;bar.value=current.completed;const percent=document.createElement('span');percent.textContent=Math.min(100,Math.round(100*current.completed/current.total))+'%';title.append(percent);}
  }else if(live){bar.removeAttribute('value');}
  else {bar.max=1;bar.value=['completed','needs_review'].includes(job.status)?1:0;}
  root.append(bar);
  const metrics=document.createElement('p');metrics.className='hint';
  metrics.textContent=current?[current.completed!==null?`${current.completed.toLocaleString()}${current.total!==null?' / '+current.total.toLocaleString():''} ${current.unit}`:null,current.tokens_per_second!==null?`${current.tokens_per_second.toFixed(1)} tokens/sec`:null,current.elapsed!==null?`${current.elapsed.toFixed(1)}s in this stage`:null].filter(Boolean).join(' · '):'Progress appears when the engine starts reporting. Logs remain available below.';
  root.append(metrics);
  if(live&&current?.unit==='tokens'&&current.total===null){const note=document.createElement('p');note.className='hint';note.textContent='The model decides when the song or score ends. Token count is live; total length is not known yet.';root.append(note);}
  const stages=document.createElement('ol');stages.className='progress-stages';
  for(const stage of data.stages||[]){const item=document.createElement('li');item.dataset.status=stage.status;const name=document.createElement('span');name.textContent=stage.label;const detail=document.createElement('span');detail.textContent=({completed:'Done',running:'In progress',truncated:'Limit reached',failed:'Failed',cancelled:'Cancelled',interrupted:'Interrupted'}[stage.status]||stage.status)+(stage.elapsed!==null?' · '+stage.elapsed.toFixed(1)+'s':'');item.append(name,detail);stages.append(item);}
  root.append(stages);
}

// Read existing console output as well, so a running server needs no restart.
function progressFromLog(log,status){
  const stages=new Map();
  for(const line of log.replace(/\r/g,'\n').split('\n')){
    const match=line.match(/^\[YuE2\] (Starting|Running|Completed|Failed|Cancelled|Finished \(generation limit reached\)) (.+?): (.+)$/);
    if(!match)continue;
    const [,action,label,detail]=match,count=detail.match(/^(\d+)(?:\/(\d+))? (tokens|steps|items)\b/),elapsed=detail.match(/elapsed ([\d.]+)s/),speed=detail.match(/([\d.]+) tokens\/s/);
    stages.set(label,{label,detail,status:{Starting:'running',Running:'running',Completed:'completed',Failed:'failed',Cancelled:'cancelled','Finished (generation limit reached)':'truncated'}[action],completed:count?Number(count[1]):null,total:count?.[2]?Number(count[2]):null,unit:count?.[3]||null,elapsed:elapsed?Number(elapsed[1]):null,tokens_per_second:speed?Number(speed[1]):null});
  }
  const items=[...stages.values()],current=items.at(-1)||null;
  if(current?.status==='running'&&['failed','cancelled','interrupted'].includes(status))current.status=status;
  return {stages:items,current,status};
}

let browserSessionController=null,browserSessionTimer=null,browserPageHidden=false;
async function connectBrowserLifetime(){
  if(!state.boot?.browser_autoclose||browserSessionController||browserPageHidden)return;
  clearTimeout(browserSessionTimer);
  const controller=new AbortController();browserSessionController=controller;
  try{
    const response=await fetch('/api/browser-session',{headers:{'X-Studio-Token':state.boot.token},signal:controller.signal});
    if(!response.ok)throw new Error('Browser session disconnected');
    const reader=response.body.getReader();
    while(!(await reader.read()).done){}
  }catch(error){/* Reconnect after transient network failures. */}
  finally{
    if(browserSessionController===controller)browserSessionController=null;
    if(!browserPageHidden)browserSessionTimer=setTimeout(connectBrowserLifetime,2000);
  }
}
window.addEventListener('pagehide',()=>{browserPageHidden=true;clearTimeout(browserSessionTimer);browserSessionController?.abort();});
window.addEventListener('pageshow',()=>{browserPageHidden=false;connectBrowserLifetime();});

// Lyrics export: preserve source text; section tags describe structure, not timing.
function lyricSections(lyrics){
  const matches=[...lyrics.matchAll(/^[ \t]*(\[[^\]\r\n]+\](?:[ \t]*\[[^\]\r\n]+\])*)[ \t]*(?:\r?\n|$)/gm)];
  if(!matches.length)return lyrics?[{index:1,tag:null,text:lyrics,lyrics}]:[];
  const sections=[];
  if(matches[0].index>0){const text=lyrics.slice(0,matches[0].index);sections.push({index:1,tag:null,text,lyrics:text});}
  matches.forEach((match,index)=>{const end=matches[index+1]?.index??lyrics.length;sections.push({index:sections.length+1,tag:match[1],text:lyrics.slice(match.index,end),lyrics:lyrics.slice(match.index+match[0].length,end)});});
  return sections;
}
function songDetails(song){
  return {schema:'yue2-studio-song-v1',source:song.source||'editor',job_id:song.job_id||null,title:song.title||'',style:song.style||'',lyrics:song.lyrics||'',sections:lyricSections(song.lyrics||''),timing:null,note:'Exact text from the indicated source. Section tags are writing cues, not verified audio boundaries. No transcription or word timestamps are included.'};
}
function exportSong(song,format){
  const title=(song.title||'song').replace(/[<>:"/\\|?*\x00-\x1f]/g,'-').replace(/[. ]+$/g,'').slice(0,90)||'song';
  if(format==='txt')download('yue2-'+title+'-lyrics.txt',song.lyrics||'','text/plain;charset=utf-8');
  else download('yue2-'+title+'-song.json',JSON.stringify(songDetails(song),null,2));
}
function addLyricExports(container,readSong){
  container.append(button('Copy lyrics',async()=>{try{await navigator.clipboard.writeText(readSong().lyrics||'');toast('Lyrics copied with section tags.');}catch{toast('Clipboard unavailable. Use Download lyrics TXT instead.',true);}}),button('Download lyrics TXT',()=>exportSong(readSong(),'txt')),button('Song details JSON',()=>exportSong(readSong(),'json')));
}
function bindLyricExports(){
  addLyricExports($('editorLyricExports'),()=>({title:$('songTitle').value,style:$('style').value,lyrics:$('lyrics').value,source:'editor'}));
  addLyricExports($('draftLyricExports'),()=>({title:$('draftTitle').value,style:$('draftStyle').value,lyrics:$('draftLyrics').value,source:'reviewed_llm_draft'}));
}
/* == lyrics aligned under the vocal notes (display-only overlay) == */
/* YuE2 ABC scores carry no lyric line: the words live in a separate field.
   This overlay invents an ABC w: line from the song's lyrics - one word (or
   hyphenated syllable) per Vocal note - and renders THAT copy, while the
   original score stays untouched in baseAbc. Insertion offsets map rendered
   note spans back to original coordinates, so hover-pluck and drag-to-edit
   keep addressing the real score and the server never sees w: lines. */
function lyricWords(raw){
  return (raw||'').replace(/\[[^\]]*\]/g,' ').split(/\n+/)
    .flatMap(line=>line.trim()?line.trim().split(/\s+/):[])
    .map(w=>w.replace(/\s+/g,'')).filter(Boolean);
}
function stripLyricsFromAbc(text){
  return (text||'').split('\n').filter(l=>!/^[ \t]*w:/.test(l)).join('\n');
}
function abcWithLyrics(text,lyrics){
  const clean=stripLyricsFromAbc(text);
  const words=lyricWords(lyrics);
  if(!words.length)return{text:clean,insertions:[],words:0,used:0};
  // Flatten words into a syllable stream: a word of N hyphen parts consumes N
  // notes; the last syllable of each word is marked with a hyphen suffix on
  // the previous syllable, matching ABC's w: hyphenation convention. This
  // can never deadlock: every note simply takes the next syllable or *.
  const syls=[];
  for(const w of words){
    const parts=w.split('-').filter(Boolean);
    if(!parts.length)continue;
    parts.forEach((p,i)=>syls.push(i<parts.length-1?p+'-':p));
  }
  const lines=clean.split('\n');
  const out=[];const insertions=[];let pos=0,si=0,inVocal=false;
  const NOTE_RE=/(?:[=^_]){0,2}[A-Ga-g](?![A-Za-z])[#b]?[,']*/g;
  for(const line of lines){
    const vm=/^[ \t]*V:[ \t]*(\S+)/.exec(line);
    if(vm){inVocal=/^(Vocal|V)$/i.test(vm[1])&&!/inst/i.test(vm[1]);
      out.push(line);pos+=line.length+1;continue;}
    if(!inVocal||/^[ \t]*([A-Za-z]:|%)/.test(line)){out.push(line);pos+=line.length+1;continue;}
    const body=line;
    out.push(line);pos+=line.length+1;
    // w: tokens map 1:1 to EVERY slot in order - notes AND rests. Walk the
    // raw line left-to-right: chord names and grace notes take no slot, a
    // rest slot gets '*', a note slot gets the next syllable.
    const TOK=/"[^"]*"|\{[^}]*\}|\[[^\]]*\]|[xXzZ](?![A-Za-z])\d*|(?:[=^_]){0,2}[A-Ga-g](?![A-Za-z])[#b]?[,']*(?:\d+\/?\d*|\/\d*)?[>-]*/g;
    const toks=[];let m,done=false;
    while(!done&&(m=TOK.exec(body))){
      const t=m[0];
      if(t[0]=='"'||t[0]=='{')continue;      // chord symbol / grace notes: no slot
      if(/^[xXzZ]/.test(t)){toks.push('*');continue;}  // rest: keep the slot
      if(si<syls.length)toks.push(syls[si++]);          // note: next syllable
      else done=true;
    }
    if(toks.length){
      const wl='w: '+toks.join(' ');
      insertions.push({pos,len:wl.length+1});
      out.push(wl);pos+=wl.length+1;
    }
    if(si>=syls.length)break;
  }
  return{text:out.join('\n'),insertions,words:words.length,used:si};
}
function applyRunOverlay(){
  const st=runScoreState;
  const r=abcWithLyrics(st.baseAbc,st.lyrics||'');
  st.abc=r.text;st.overlayOffsets=r.insertions;st.overlayWords={used:r.used,total:r.words};
  st.renderKey=null;
  if(st.editing)$('runScoreTa').value=st.abc;
  renderRunScore();
  const hint=$('runScoreHint');
  if(hint&&r.used<r.words){
    hint.hidden=false;
    hint.textContent='Aligned '+r.used+' of '+r.words+' lyric words: the melody has '+(r.used<r.words?'fewer notes than words.':'more notes; the rest were left blank.');
  }
}
function toggleRunLyricsOverlay(){
  const st=runScoreState;
  if(!st.jobId)return;
  if(!st.overlay){
    st.baseAbc=stripLyricsFromAbc(st.editing?$('runScoreTa').value:st.abc);
    st.overlay=true;
    applyRunOverlay();
  }else{
    st.overlay=false;st.overlayOffsets=[];st.overlayWords=null;
    if(st.editing)$('runScoreTa').value=st.baseAbc;
    st.abc=st.baseAbc;st.renderKey=null;
    renderRunScore();
  }
  updateRunOverlayButton();
}
function updateRunOverlayButton(){
  const btn=$('runLyricsOverlayBtn');
  if(!btn)return;
  btn.textContent=runScoreState.overlay?'Hide lyrics on score':'Show lyrics on score';
}
/* == score drag & piano preview (appended) == */
/* == score drag & piano preview (appended) == */
function currentScoreText(){if(runScoreState.overlay)return runScoreState.baseAbc??runScoreState.abc;return runScoreState.editing?$('runScoreTa').value:runScoreState.abc;}
function setCurrentScoreText(v){if(runScoreState.overlay){runScoreState.baseAbc=v;applyRunOverlay();}else if(runScoreState.editing){$('runScoreTa').value=v;}else{runScoreState.abc=v;}}
/* Collect every rendered note group: abcjs augments the real SVG <g> with an
   abcelem expando carrying the source-text span (startChar/endChar) and pitches. */
function noteSpanOnly(text,start,end){
  const slice=text.slice(start,end);
  const m=/^(?:"[^"]*")?((?:[=^_]){0,2}[A-Ga-g](?![A-Za-z])[#b]?[,']*[0-9/>|-]*)$/.exec(slice);
  if(!m)return null;
  return {start:start+slice.length-m[1].length,end:end};
}
function scoreNoteSpans(){
  const map=runScoreState.noteMap;
  if(!map)return[];
  const ins=runScoreState.overlay?runScoreState.overlayOffsets:null;
  const text=(runScoreState.overlay?runScoreState.abc:currentScoreText())||'';
  const conv=ch=>{if(!ins)return ch;let c=ch;for(const o of ins){if(o.pos<=c)c-=o.len;}return c;};
  return map.filter(n=>n.endChar<=text.length&&noteSpanOnly(text,n.startChar,n.endChar))
            .map(n=>{const sp=noteSpanOnly(text,n.startChar,n.endChar);return {els:n.els,startChar:conv(sp.start),endChar:conv(sp.end)};});
}
function setDragHint(msg){
  const h=$('runDragHint');
  if(!h)return;
  h.hidden=!msg;
  h.textContent=msg||'';
}
async function scorePitchStep(startChar,endChar,semitones){
  try{
    const out=await api('/api/score/pitch',{abc:currentScoreText(),pitch:{start_char:startChar,end_char:endChar,semitones:semitones}});
    setCurrentScoreText(out.abc);
    runScoreState.renderKey=null;
    renderRunScore();
    return true;
  }catch(err){toast(err&&err.message||String(err));return false;}
}
function setScoreDragging(on){
  const btn=$('runPreviewBtn');
  if(btn)btn.hidden=!runScoreState.editing;
  if(!on){detachScoreDrag();return;}
  if(runScoreState.dragLink)return;
  const sheet=$('runScoreSheet');
  let drag=null,suppressClick=false;
  sheet.addEventListener('click',evt=>{if(suppressClick){suppressClick=false;evt.stopImmediatePropagation();evt.preventDefault();}},true);
  sheet.addEventListener('mousemove',hoverMove);
  sheet.addEventListener('mouseleave',()=>{clearHover();sheet.classList.remove('score-can-grab');});
  sheet.addEventListener('scroll',clearHover,{passive:true});
  sheet.addEventListener('contextmenu',runSheetMenu);
  bindSheetWheel('run');
  function spanAt(evt){return pickNote(scoreNoteSpans(),evt);}
  function clearHover(){sheet.querySelectorAll('.score-note-hover').forEach(e=>e.remove());}
  let hoverPending=false,hoverLast=null;
  function hoverMove(evt){
    if(hoverPending)return;
    hoverPending=true;
    requestAnimationFrame(()=>{hoverPending=false;
      const s=pickNote(scoreNoteSpans(),evt);
      clearHover();
      sheet.classList.toggle('score-can-grab',!!s);
      if(s){const k=s.startChar+':'+s.endChar;if(hoverLast!==k){hoverLast=k;const m=noteMidiFromSpan(currentScoreText(),s.startChar,s.endChar);if(m!=null)pluckMidi(m,0.12);}}else hoverLast=null;
      if(!s)return;
      const b=noteBox(s);
      if(!b)return;
      const h=document.createElement('div');
      h.className='score-note-hover';
      const sb=sheet.getBoundingClientRect();
      h.style.left=(b.x-sb.left+sheet.scrollLeft-7)+'px';
      h.style.top=(b.y-sb.top+sheet.scrollTop-7)+'px';
      h.style.width=(b.w+14)+'px';
      h.style.height=(b.h+14)+'px';
      sheet.appendChild(h);
    });
  }
  function onDown(evt){
    if(evt.button!==0)return;
    const span=spanAt(evt);
    if(!span)return;
    drag={span,startY:evt.clientY,last:0,moved:false};
    drag.base=noteMidiFromSpan(currentScoreText(),span.startChar,span.endChar);
    evt.preventDefault();
  }
  function onMove(evt){
    if(!drag){hoverMove(evt);return;}
    const dy=drag.startY-evt.clientY;
    if(!drag.moved&&Math.abs(dy)<8)return;
    if(!drag.moved){drag.moved=true;suppressClick=true;sheet.classList.add('score-dragging');clearHover();}
    const step=evt.ctrlKey?12:1;
    const semis=Math.max(-24,Math.min(24,Math.round(dy/9)*step));
    if(semis!==drag.last){
      drag.last=semis;
      if(drag.base!=null)pluckMidi(drag.base+semis,0.16);
      setDragHint(semis>0?('\u25b2 '+semis+' semitone'+(Math.abs(semis)===1?'':'s')+' \u2014 release to apply'):('\u25bc '+Math.abs(semis)+' semitone'+(Math.abs(semis)===1?'':'s')+' \u2014 release to apply'));
    }
    evt.preventDefault();
  }
  async function onUp(){
    if(!drag)return;
    const info=drag;
    drag=null;
    sheet.classList.remove('score-dragging');
    setDragHint('');
    if(!info.moved)return;
    if(!info.last){suppressClick=false;return;}
    const ok=await scorePitchStep(info.span.startChar,info.span.endChar,info.last);
    if(ok&&!runScoreState.editing)runScoreState.userEdited=true;
    if(ok)toast('Note moved '+Math.abs(info.last)+' semitone'+(Math.abs(info.last)===1?'':'s')+(info.last>0?' up.':' down.'));
    setTimeout(()=>{suppressClick=false;},80);
  }
  sheet.addEventListener('mousedown',onDown);
  window.addEventListener('mousemove',onMove);
  window.addEventListener('mouseup',onUp);
  runScoreState.dragLink={detach(){
    sheet.removeEventListener('mousedown',onDown);
    window.removeEventListener('mousemove',onMove);
    window.removeEventListener('mouseup',onUp);
  }};
}
function detachScoreDrag(){
  if(runScoreState.dragLink){try{runScoreState.dragLink.detach();}catch(e){}runScoreState.dragLink=null;}
  const sheet=$('runScoreSheet');
  if(sheet)sheet.classList.remove('score-dragging');
  setDragHint('');
}
function stopScorePreview(){
  runScoreState.previewOn=false;
  if(runScoreState.previewCtl){
    try{runScoreState.previewCtl.stop();}catch(e){}
    runScoreState.previewCtl=null;
  }
  previewCursorClear(runScoreState.previewCursor);
  const ctlBox=$('runPreviewCtl');
  if(ctlBox){ctlBox.hidden=true;ctlBox.innerHTML='';}
  const st=$('runPreviewStatus');
  if(st){st.hidden=true;st.textContent='';}
  const btn=$('runStopPreviewBtn');
  if(btn)btn.hidden=true;
}
async function startScorePreview(){
  if(!runScoreState.editing)return;
  if(runScoreState.previewOn){stopScorePreview();return;}
  const st=$('runPreviewStatus');
  const show=(msg,warn)=>{st.hidden=!msg;st.textContent=msg||'';st.style.color=warn?'var(--danger,#e06c75)':'';};
  if(!window.ABCJS||!ABCJS.synth||!ABCJS.synth.SynthController){show('abcjs synth is not available in this build.',true);return;}
  if(ABCJS.synth.supportsAudio&&!ABCJS.synth.supportsAudio()){show('Web Audio is not available in this browser.',true);return;}
  const abc=$('runScoreTa').value;
  if(!abc){show('There is no score to preview.',true);return;}
  const holder=document.createElement('div');
  holder.style.display='none';
  document.body.appendChild(holder);
  let visual=null;
  try{visual=ABCJS.renderAbc(holder,abc,{scrollVertical:true});}catch(err){visual=null;}
  holder.remove();
  if(!visual||!visual[0]){show('Could not parse the current score for preview.',true);return;}
  const ctlBox=$('runPreviewCtl');
  ctlBox.hidden=false;ctlBox.innerHTML='';
  let ctl=null;
  try{
    ctl=new ABCJS.synth.SynthController();
    ctl.load('#runPreviewCtl',{onEvent:runPreviewOnEvent},{displayPlayButton:true,displayRestart:true,displayProgress:true});
    await ctl.setTune(visual[0],false,{soundFontUrl:window.location.origin+'/soundfont/',chordsOff:true,drumOff:true});
    ctl.play();
    runScoreState.previewCtl=ctl;
    runScoreState.previewOn=true;
    $('runStopPreviewBtn').hidden=false;
    show('Piano preview of your edits \u2014 this is not the real render. Stop preview or close the editor to end it.');
  }catch(err){
    show('Preview failed: '+((err&&err.message)||err),true);
    try{ctl&&ctl.stop();}catch(e){}
    if(ctlBox){ctlBox.hidden=true;ctlBox.innerHTML='';}
  }
}
if($('runPreviewBtn'))$('runPreviewBtn').onclick=()=>{startScorePreview();};
if($('runStopPreviewBtn'))$('runStopPreviewBtn').onclick=()=>{stopScorePreview();};
/* == main editor sheet (appended) == */
/* == main editor sheet (appended) == */
function renderAbcSheet(){
  const box=$('abcSheet');
  if(!box)return;
  const text=$('abc').value.trim();
  const pbtn=$('abcPreviewBtn');
  if(pbtn)pbtn.hidden=!text;
  const wrap=$('abcWrap');const tgl=$('abcToggle');
  if(tgl&&!tgl.dataset.bound){tgl.dataset.bound='1';tgl.addEventListener('click',()=>{state.abcSheetOpen=state.abcSheetOpen===false?true:false;tgl.textContent=(state.abcSheetOpen?'\u25be ':'\u25b8 ')+'ABC notation';if(wrap)wrap.hidden=!state.abcSheetOpen;});}
  if(!text){box.hidden=true;box.innerHTML='';state.abcNoteMap=null;if(wrap)wrap.hidden=true;return;}
  const abcOpen=state.abcSheetOpen!==false;
  if(tgl)tgl.textContent=(abcOpen?'\u25be ':'\u25b8 ')+'ABC notation';
  if(wrap)wrap.hidden=!abcOpen;
  if(!abcOpen){box.hidden=true;return;}
  box.hidden=false;
  const key='abc|'+text;
  if(box.dataset.renderKey===key&&box.querySelector('svg'))return;
  box.dataset.renderKey=key;
  const __sy=box.scrollTop,__sx=box.scrollLeft;
  box.innerHTML='';
  if(!window.ABCJS)return;
  try{
    const width=Math.max(320,Math.min(880,(box.clientWidth||800)-16));
    const visual=ABCJS.renderAbc(box,text,{staffwidth:width,paddingtop:8,paddingbottom:8,add_classes:true,scrollVertical:true});
    let tms=visual&&visual[0]?visual[0].setTiming(0,0):null;
    if(!tms||!tms.length)tms=visual&&visual[0]?visual[0].setTiming(120,0):null;
    try{state.abcNoteMap=buildNoteMap(text,tms);state.abcTimings=(tms||[]).filter(t=>t&&t.type==='event'&&isFinite(t.milliseconds)&&t.elements&&t.elements.length).map(t=>({ms:t.milliseconds,elements:t.elements})).sort((a,b)=>a.ms-b.ms);state.abcMsByEl=(function(){const m=new Map();for(const t of state.abcTimings){for(const g of (t.elements||[])){for(const e of (Array.isArray(g)?g:[g]))if(e)m.set(e,t.ms);}}return m;})();state.abcTotalMs=state.abcTimings.length?state.abcTimings[state.abcTimings.length-1].ms:0;}catch(e2){state.abcNoteMap=null;state.abcTimings=null;state.abcMsByEl=null;state.abcTotalMs=0;}
    const svg=box.querySelector('svg');
    if(svg){
      const w=parseFloat(svg.getAttribute('width'))||svg.clientWidth||width;
      const h=parseFloat(svg.getAttribute('height'))||svg.clientHeight||0;
      if(w&&h)svg.setAttribute('viewBox','0 0 '+w+' '+h);
      svg.removeAttribute('width');svg.removeAttribute('height');
      svg.style.width=((sheetZoom.abc||1)*100)+'%';
      ensureZoomBar('abc');
      ensureTransport('abc');
      box.scrollTop=__sy;box.scrollLeft=__sx;
    }
  }catch(err){
    box.innerHTML='';
    const p=document.createElement('p');p.className='hint';p.textContent='Score could not be drawn: '+err.message;box.append(p);
    state.abcNoteMap=null;
  }
}
function setAbcDragHint(msg){
  const h=$('abcDragHint');
  if(!h)return;
  h.hidden=!msg;
  h.textContent=msg||'';
}
async function commitAbcPitch(startChar,endChar,semitones){
  try{
    const out=await api('/api/score/pitch',{abc:$('abc').value,pitch:{start_char:startChar,end_char:endChar,semitones:semitones}});
    $('abc').value=out.abc;
    renderAbcSheet();
    return true;
  }catch(err){toast(err&&err.message||String(err));return false;}
}
function setupAbcSheetDrag(){
  const sheet=$('abcSheet');
  if(!sheet||sheet.dataset.dragBound==='1')return;
  sheet.dataset.dragBound='1';
  let drag=null;
  function spansNow(){
    const map=state.abcNoteMap;
    const text=$('abc').value;
    if(!map)return[];
    return map.filter(n=>n.endChar<=text.length&&/^[=_^]?[A-Ga-g][#b]?[,']*[0-9/>|-]*$/.test(text.slice(n.startChar,n.endChar))).map(n=>({els:n.els,startChar:n.startChar,endChar:n.endChar}));
  }
  function clearAbcHover(){sheet.querySelectorAll('.score-note-hover').forEach(e=>e.remove());}
  let abcHoverPending=false,abcHoverLast=null;
  function hoverAbcMove(evt){
    if(abcHoverPending)return;
    abcHoverPending=true;
    requestAnimationFrame(()=>{abcHoverPending=false;
      const s=pickNote(spansNow(),evt);
      clearAbcHover();
      sheet.classList.toggle('score-can-grab',!!s);
      if(s){const k=s.startChar+':'+s.endChar;if(abcHoverLast!==k){abcHoverLast=k;const m=noteMidiFromSpan($('abc')?$('abc').value:'',s.startChar,s.endChar);if(m!=null)pluckMidi(m,0.12);}}else abcHoverLast=null;
      if(!s)return;
      const b=noteBox(s);
      if(!b)return;
      const h=document.createElement('div');
      h.className='score-note-hover';
      const sb=sheet.getBoundingClientRect();
      h.style.left=(b.x-sb.left+sheet.scrollLeft-7)+'px';
      h.style.top=(b.y-sb.top+sheet.scrollTop-7)+'px';
      h.style.width=(b.w+14)+'px';
      h.style.height=(b.h+14)+'px';
      sheet.appendChild(h);
    });
  }
  function onDown(evt){
    if(evt.button!==0)return;
    const best=pickNote(spansNow(),evt);
    if(!best)return;
    drag={span:best,startY:evt.clientY,last:0,moved:false};
    drag.base=noteMidiFromSpan($('abc')?$('abc').value:'',best.startChar,best.endChar);
    evt.preventDefault();
  }
  function onMove(evt){
    if(!drag){hoverAbcMove(evt);return;}
    const dy=drag.startY-evt.clientY;
    if(!drag.moved&&Math.abs(dy)<8)return;
    if(!drag.moved){drag.moved=true;sheet.classList.add('score-dragging');clearAbcHover();}
    drag.moved=true;
    const step=evt.ctrlKey?12:1;
    const semis=Math.max(-24,Math.min(24,Math.round(dy/9)*step));
    if(semis!==drag.last){
      drag.last=semis;
      if(drag.base!=null)pluckMidi(drag.base+semis,0.16);
      setAbcDragHint(semis>0?('\u25b2 '+semis+' semitone'+(Math.abs(semis)===1?'':'s')+' \u2014 release to apply'):('\u25bc '+Math.abs(semis)+' semitone'+(Math.abs(semis)===1?'':'s')+' \u2014 release to apply'));
    }
    evt.preventDefault();
  }
  async function onUp(){
    if(!drag)return;
    const info=drag;
    drag=null;
    setAbcDragHint('');
    if(!info.moved){return;}
    if(!info.last)return;
    const ok=await commitAbcPitch(info.span.startChar,info.span.endChar,info.last);
    if(ok)toast('Note moved '+Math.abs(info.last)+' semitone'+(Math.abs(info.last)===1?'':'s')+(info.last>0?' up.':' down.'));
  }
  sheet.addEventListener('mousemove',hoverAbcMove);
  sheet.addEventListener('mouseleave',()=>{clearAbcHover();sheet.classList.remove('score-can-grab');});
  sheet.addEventListener('scroll',clearAbcHover,{passive:true});
  sheet.addEventListener('contextmenu',abcSheetMenu);
  bindSheetWheel('abc');
  sheet.addEventListener('mousedown',onDown);
  window.addEventListener('mousemove',onMove);
  window.addEventListener('mouseup',onUp);
}
function stopAbcPreview(){
  if(state.abcPreviewCtl){
    try{state.abcPreviewCtl.stop();}catch(e){}
    state.abcPreviewCtl=null;
  }
  previewCursorClear(state.abcPreviewCursor);
  const ctlBox=$('abcPreviewCtl');
  if(ctlBox){ctlBox.hidden=true;ctlBox.innerHTML='';}
  const st=$('abcPreviewStatus');
  if(st){st.hidden=true;st.textContent='';}
  const btn=$('abcStopPreviewBtn');
  if(btn)btn.hidden=true;
}
async function startAbcPreview(){
  if(state.abcPreviewCtl){stopAbcPreview();return;}
  const st=$('abcPreviewStatus');
  const show=(msg,warn)=>{st.hidden=!msg;st.textContent=msg||'';st.style.color=warn?'var(--danger,#e06c75)':'';};
  if(!window.ABCJS||!ABCJS.synth||!ABCJS.synth.SynthController){show('abcjs synth is not available in this build.',true);return;}
  if(ABCJS.synth.supportsAudio&&!ABCJS.synth.supportsAudio()){show('Web Audio is not available in this browser.',true);return;}
  const abc=$('abc').value;
  if(!abc){show('There is no score to preview.',true);return;}
  const holder=document.createElement('div');
  holder.style.display='none';
  document.body.appendChild(holder);
  let visual=null;
  try{visual=ABCJS.renderAbc(holder,abc,{scrollVertical:true});}catch(err){visual=null;}
  holder.remove();
  if(!visual||!visual[0]){show('Could not parse the score for preview.',true);return;}
  const ctlBox=$('abcPreviewCtl');
  ctlBox.hidden=false;ctlBox.innerHTML='';
  let ctl=null;
  try{
    ctl=new ABCJS.synth.SynthController();
    ctl.load('#abcPreviewCtl',{onEvent:abcPreviewOnEvent},{displayPlayButton:true,displayRestart:true,displayProgress:true});
    await ctl.setTune(visual[0],false,{soundFontUrl:window.location.origin+'/soundfont/',chordsOff:true,drumOff:true});
    ctl.play();
    state.abcPreviewCtl=ctl;
    $('abcStopPreviewBtn').hidden=false;
    show('Piano preview of the score in the editor \u2014 not the real render.');
  }catch(err){
    show('Preview failed: '+((err&&err.message)||err),true);
    try{ctl&&ctl.stop();}catch(e){}
    if(ctlBox){ctlBox.hidden=true;ctlBox.innerHTML='';}
  }
}
if($('abc'))$('abc').addEventListener('input',()=>{clearTimeout(state.abcRenderTimer);state.abcRenderTimer=setTimeout(renderAbcSheet,350);});
if($('scoreDetails'))$('scoreDetails').addEventListener('toggle',()=>{if($('scoreDetails').open)renderAbcSheet();});
if($('abcPreviewBtn'))$('abcPreviewBtn').onclick=()=>{startAbcPreview();};
if($('abcStopPreviewBtn'))$('abcStopPreviewBtn').onclick=()=>{stopAbcPreview();};
setupAbcSheetDrag();
/* == note hit-testing & hover highlight (appended) == */
function noteBox(s){
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity,ok=false;
  let fb=null,fba=Infinity;
  for(const el of s.els){
    if(!el||!el.getBoundingClientRect)continue;
    const r=el.getBoundingClientRect();
    if(!r.width&&!r.height)continue;
    /* Skip wide/flat tie-slur and beam curves: their boxes are huge and would
       swallow the pointer, stealing the pick from the note you aim at. */
    if(r.width>Math.max(14,2.2*r.height)||r.height>Math.max(14,2.2*r.width)){
      const a=r.width*r.height;
      if(a<fba){fba=a;fb=r;}
      continue;
    }
    ok=true;
    if(r.left<x0)x0=r.left;
    if(r.top<y0)y0=r.top;
    if(r.right>x1)x1=r.right;
    if(r.bottom>y1)y1=r.bottom;
  }
  if(!ok){
    /* every element was a curve: fall back to the smallest one */
    if(!fb)return null;
    return{x:fb.left,y:fb.top,w:fb.width,h:fb.height,cx:fb.left+fb.width/2,cy:fb.top+fb.height/2};
  }
  return{x:x0,y:y0,w:x1-x0,h:y1-y0,cx:(x0+x1)/2,cy:(y0+y1)/2};
}
function noteEdgeDist(b,x,y){
  if(!b)return Infinity;
  const dx=Math.max(b.x-x,0,x-(b.x+b.w));
  const dy=Math.max(b.y-y,0,y-(b.y+b.h));
  return Math.sqrt(dx*dx+dy*dy);
}
function pickNote(spans,evt){
  let best=null,bd=28,bt=1e9;
  for(const s of spans){
    const b=noteBox(s);
    if(!b)continue;
    const d=noteEdgeDist(b,evt.clientX,evt.clientY);
    if(d>=bd)continue;
    const t=Math.abs(b.cx-evt.clientX)+Math.abs(b.cy-evt.clientY);
    if(d<bd||t<bt){bd=d;bt=t;best=s;}
  }
  return best;
}
/* == preview cursor & seek helpers (appended) == */
/* == preview cursor & seek helpers (appended) == */
function previewCursorApply(bag,entry,boxId){
  if(!bag)return;
  const els=((entry&&entry.elements)||[]).reduce((a,g)=>a.concat(Array.isArray(g)?g.filter(Boolean):[g]),[]).filter(e=>e&&e.classList);
  if(bag.key===(entry&&entry.ms)&&bag.els)return;
  if(bag.els)bag.els.forEach(e=>e.classList.remove('abc-preview'));
  bag.els=els;
  bag.key=(entry&&entry.ms);
  els.forEach(e=>e.classList.add('abc-preview'));
  const box=$(boxId);
  const el=els[0];
  if(box&&el&&el.getBoundingClientRect){
    const b=box.getBoundingClientRect(),r=el.getBoundingClientRect();
    if(r.top<b.top+8)box.scrollTop+=r.top-b.top+48;
    else if(r.bottom>b.bottom-8)box.scrollTop+=r.bottom-b.bottom-48;
  }
}
function previewCursorClear(bag){
  if(bag&&bag.els){try{bag.els.forEach(e=>e.classList.remove('abc-preview'));}catch(e){}}
  if(bag){bag.els=null;bag.key=null;}
}
function previewNearestEntry(timings,ms){
  if(!timings||!timings.length)return null;
  let lo=0,hi=timings.length-1,idx=0;
  while(lo<=hi){const mid=(lo+hi)>>1;if(timings[mid].ms<=ms){idx=mid;lo=mid+1;}else hi=mid-1;}
  return timings[idx];
}
function runPreviewOnEvent(entry){
  if(!entry||typeof entry.milliseconds!=='number'){previewCursorClear(runScoreState.previewCursor);return;}
  const t=previewNearestEntry(runScoreState.timings,entry.milliseconds);
  if(t)previewCursorApply(runScoreState.previewCursor,t,'runScoreSheet');
}
function abcPreviewOnEvent(entry){
  if(!entry||typeof entry.milliseconds!=='number'){previewCursorClear(state.abcPreviewCursor);return;}
  const t=previewNearestEntry(state.abcTimings,entry.milliseconds);
  if(t)previewCursorApply(state.abcPreviewCursor,t,'abcSheet');
}
function previewSeekRun(span){
  const ms=runScoreState.msByEl&&span&&span.els&&span.els[0]?runScoreState.msByEl.get(span.els[0]):null;
  if(ms!=null&&runScoreState.previewCtl&&runScoreState.totalMs>0){
    runScoreState.previewCtl.seek(Math.max(0,Math.min(1,ms/runScoreState.totalMs)));
  }
}
function previewSeekAbc(span){
  const ms=state.abcMsByEl&&span&&span.els&&span.els[0]?state.abcMsByEl.get(span.els[0]):null;
  if(ms!=null&&state.abcPreviewCtl&&state.abcTotalMs>0){
    state.abcPreviewCtl.seek(Math.max(0,Math.min(1,ms/state.abcTotalMs)));
  }
}
if(!runScoreState.previewCursor)runScoreState.previewCursor={els:null,key:null};
/* == zoom bar, Ctrl+wheel, zoom-aware hit-testing (appended) == */

function zoomLabelId(which){return which==='run'?'runZoomLabel':'abcZoomLabel';}
function ensureZoomBar(which){
  const sheet=$(which==='run'?'runScoreSheet':'abcSheet');
  if(!sheet)return;
  let bar=sheet.querySelector('.score-zoombar');
  if(!bar){
    bar=document.createElement('div');
    bar.className='score-zoombar';
    const mk=(lbl,fn,title)=>{const b=document.createElement('button');b.type='button';b.textContent=lbl;b.title=title;b.addEventListener('click',fn);return b;};
    bar.appendChild(mk('\u2212',()=>setSheetZoom(which,prevZoom(sheetZoom[which]),null),'Zoom out'));
    const lab=document.createElement('button');lab.type='button';lab.id=zoomLabelId(which);lab.title='Zoom level';bar.appendChild(lab);
    bar.appendChild(mk('+',()=>setSheetZoom(which,nextZoom(sheetZoom[which]),null),'Zoom in (or Ctrl+scroll)'));
    bar.appendChild(mk('\u2922',()=>setSheetZoom(which,1,null),'Fit width'));
    sheet.appendChild(bar);
  }
  const lab=bar.querySelector('#'+zoomLabelId(which));
  if(lab)lab.textContent=Math.round((sheetZoom[which]||1)*100)+'%';
}
function bindSheetWheel(which){
  const sheet=$(which==='run'?'runScoreSheet':'abcSheet');
  if(!sheet||sheet.dataset.wheelBound)return;
  sheet.dataset.wheelBound='1';
  ensureTransport(which);
  sheet.addEventListener('wheel',evt=>{
    if(!evt.ctrlKey)return;
    evt.preventDefault();
    const before=svgPointFromEvt(sheet,evt);
    setSheetZoom(which,evt.deltaY<0?nextZoom(sheetZoom[which]):prevZoom(sheetZoom[which]),null);
    keepPoint(sheet,which,before);
  },{passive:false});
  ensureZoomBar(which);
}
function svgPointFromEvt(sheet,evt){
  const svg=sheet.querySelector('svg');
  if(!svg)return null;
  const r=svg.getBoundingClientRect();
  return{x:(evt.clientX-r.left)/Math.max(r.width,1),y:(evt.clientY-r.top)/Math.max(r.height,1)};
}
function keepPoint(sheet,which,p){
  if(!p)return;
  const svg=sheet.querySelector('svg');
  if(!svg||!sheet.clientWidth)return;
  const sb=sheet.getBoundingClientRect();
  const r=svg.getBoundingClientRect();
  const tx=p.x*r.width+sb.left,ty=p.y*r.height+sb.top;
  sheet.scrollLeft+=tx-(sb.left+sb.width/2);
  sheet.scrollTop+=ty-(sb.top+sb.height/2);
}
/* == right-click zoom & pitch-preview sounds (appended) == */
/* sheetZoom lives at the top of the file (TDZ: it is used before this line executes) */
function nextZoom(z){for(const s of ZOOM_STEPS){if(s>z+0.01)return s;}return ZOOM_STEPS[ZOOM_STEPS.length-1];}
function prevZoom(z){let p=1;for(const s of ZOOM_STEPS){if(s<z-0.01)p=s;}return p;}
function applySheetZoom(which){
  const sheet=$(which==='run'?'runScoreSheet':'abcSheet');
  const svg=sheet&&sheet.querySelector('svg');
  if(svg)svg.style.width=((sheetZoom[which]||1)*100)+'%';
}
function centerSheetOn(sheet,ms,timings){
  if(!sheet||ms==null||!timings||!timings.length)return;
  let best=null,bd=1e18;
  for(const t of timings){const d=Math.abs(t.ms-ms);if(d<bd){bd=d;best=t;}}
  if(!best)return;
  const el=(best.elements||[]).reduce((a,g)=>a.concat(Array.isArray(g)?g:[g]),[]).find(e=>e&&e.getBoundingClientRect);
  if(!el)return;
  const r=el.getBoundingClientRect(),sb=sheet.getBoundingClientRect();
  sheet.scrollLeft+=(r.left+r.width/2)-(sb.left+sb.width/2);
  sheet.scrollTop+=(r.top+r.height/2)-(sb.top+sb.height/2);
}
function msAtViewCenter(sheet,timings){
  const sb=sheet.getBoundingClientRect();
  if(!sb.width)return null;
  const cx=sb.left+sb.width/2,cy=sb.top+sb.height/2;
  let best=null,bd=1e18;
  for(const t of timings||[]){
    for(const g of (t.elements||[])){for(const e of (Array.isArray(g)?g:[g])){
      if(!e||!e.getBoundingClientRect)continue;
      const r=e.getBoundingClientRect();
      const d=Math.pow(r.left+r.width/2-cx,2)+Math.pow(r.top+r.height/2-cy,2);
      if(d<bd){bd=d;best=t;}
    }}
  }
  return best?best.ms:null;
}
function setSheetZoom(which,z,anchorMs){
  sheetZoom[which]=z;
  applySheetZoom(which);
  ensureZoomBar(which);
  centerSheetOn($(which==='run'?'runScoreSheet':'abcSheet'),anchorMs,which==='run'?runScoreState.timings:state.abcTimings);
}
function closeScoreMenu(){const m=document.getElementById('scoreCtxMenu');if(m)m.remove();}
function showScoreMenu(evt,items){
  closeScoreMenu();
  const m=document.createElement('div');m.className='score-ctx-menu';m.id='scoreCtxMenu';
  for(const it of items){
    const b=document.createElement('button');b.type='button';b.textContent=it.label;
    b.addEventListener('click',e=>{e.stopPropagation();closeScoreMenu();it.fn();});
    m.appendChild(b);
  }
  document.body.appendChild(m);
  const r=m.getBoundingClientRect();
  let x=evt.clientX,y=evt.clientY;
  if(x+r.width>window.innerWidth-8)x=window.innerWidth-8-r.width;
  if(y+r.height>window.innerHeight-8)y=window.innerHeight-8-r.height;
  m.style.left=x+'px';m.style.top=y+'px';
  setTimeout(()=>{document.addEventListener('click',e=>{if(!m.contains(e.target))closeScoreMenu();},true);document.addEventListener('keydown',closeScoreMenu,{once:true,capture:true});},0);
}
function runSheetMenu(evt){
  const sheet=$('runScoreSheet');if(!sheet)return;
  const om=document.getElementById('scoreCtxMenu');
  if(om&&om.contains(evt.target))return;
  if(om){om.remove();return;}
  evt.preventDefault();
  const span=pickNote(scoreNoteSpans(),evt);
  const z=sheetZoom.run||1;
  const items=[];
  if(span)items.push({label:'Zoom into this measure',fn:()=>{const ms=(runScoreState.msByEl&&span.els&&span.els[0])?runScoreState.msByEl.get(span.els[0]):null;setSheetZoom('run',z>=2?3:2,ms);}});
  items.push({label:'Zoom in',fn:()=>setSheetZoom('run',nextZoom(z),msAtViewCenter(sheet,runScoreState.timings))});
  items.push({label:'Zoom out',fn:()=>setSheetZoom('run',prevZoom(z),msAtViewCenter(sheet,runScoreState.timings))});
  if(z>1)items.push({label:'Fit width (100%)',fn:()=>setSheetZoom('run',1,null)});
  showScoreMenu(evt,items);
}
function abcScoreSpans(){
  const map=state.abcNoteMap;const ta=$('abc');const text=ta?ta.value:'';
  if(!map)return[];
  return map.filter(n=>n.endChar<=text.length&&/^[=_^]?[A-Ga-g][#b]?[,']*[0-9/>|-]*$/.test(text.slice(n.startChar,n.endChar))).map(n=>({els:n.els,startChar:n.startChar,endChar:n.endChar})).filter(n=>n.els.length);
}
function abcSheetMenu(evt){
  const sheet=$('abcSheet');if(!sheet)return;
  const om=document.getElementById('scoreCtxMenu');
  if(om&&om.contains(evt.target))return;
  if(om){om.remove();return;}
  evt.preventDefault();
  const span=pickNote(abcScoreSpans(),evt);
  const z=sheetZoom.abc||1;
  const items=[];
  if(span)items.push({label:'Zoom into this measure',fn:()=>{const ms=(state.abcMsByEl&&span.els&&span.els[0])?state.abcMsByEl.get(span.els[0]):null;setSheetZoom('abc',z>=2?3:2,ms);}});
  items.push({label:'Zoom in',fn:()=>setSheetZoom('abc',nextZoom(z),msAtViewCenter(sheet,state.abcTimings))});
  items.push({label:'Zoom out',fn:()=>setSheetZoom('abc',prevZoom(z),msAtViewCenter(sheet,state.abcTimings))});
  if(z>1)items.push({label:'Fit width (100%)',fn:()=>setSheetZoom('abc',1,null)});
  showScoreMenu(evt,items);
}
const KEY_SIGS={C:{},G:{F:1},D:{F:1,C:1},A:{F:1,C:1,G:1},E:{F:1,C:1,G:1,D:1},B:{F:1,C:1,G:1,D:1,A:1},'F#':{F:1,C:1,G:1,D:1,A:1,E:1},'C#':{F:1,C:1,G:1,D:1,A:1,E:1,B:1},F:{B:-1},'Bb':{B:-1,E:-1},'Eb':{B:-1,E:-1,A:-1},'Ab':{B:-1,E:-1,A:-1,D:-1},'Db':{B:-1,E:-1,A:-1,D:-1,G:-1},'Gb':{B:-1,E:-1,A:-1,D:-1,G:-1,C:-1},'Cb':{B:-1,E:-1,A:-1,D:-1,G:-1,C:-1,F:-1}};
const MINOR_REL={A:'C',B:'D',C:'Eb',D:'F',E:'G',F:'Ab',G:'Bb'};
function scoreKeySig(abc){
  const m=/^\s*K:\s*([A-G])([#b]?)\s*(\S*)/m.exec(abc||'');
  if(!m)return{};
  let k=m[1]+m[2];
  if(/^m/i.test(m[3]||''))k=MINOR_REL[m[1]]||k;
  return KEY_SIGS[k]||{};
}
function noteMidiFromSpan(abc,startChar,endChar){
  const tok=(abc||'').slice(startChar,endChar);
  const m=/^([=_^]?)([A-Ga-g])([',]*)/.exec(tok);
  if(!m)return null;
  const up=m[2]===m[2].toUpperCase();
  const L=m[2].toUpperCase();
  let midi=(up?60:72)+[0,2,4,5,7,9,11]['CDEFGAB'.indexOf(L)];
  for(const ch of m[3])midi+=(ch===','?-12:12);
  const acc=m[1];
  if(acc==='^')midi+=1;
  else if(acc==='_')midi-=1;
  else if(!acc)midi+=(scoreKeySig(abc)[L]||0);
  return midi;
}
let plinkAC=null;
function plinkCtx(){
  if(!plinkAC){try{plinkAC=new (window.AudioContext||window.webkitAudioContext)();}catch(e){return null;}}
  if(plinkAC.state==='suspended'){try{plinkAC.resume().catch(()=>{});}catch(e){}}
  return plinkAC;
}
function pluckMidi(midi,vol){
  const ac=plinkCtx();if(!ac)return;
  try{
    const t=ac.currentTime;const f=440*Math.pow(2,(midi-69)/12);
    const g=ac.createGain();
    g.gain.setValueAtTime(0.0001,t);
    g.gain.exponentialRampToValueAtTime(vol||0.14,t+0.012);
    g.gain.exponentialRampToValueAtTime(0.0001,t+0.5);
    g.connect(ac.destination);
    [[1,1],[2,0.22]].forEach(pair=>{
      const o=ac.createOscillator();o.type='triangle';o.frequency.value=f*pair[0];
      const og=ac.createGain();og.gain.value=pair[1];
      o.connect(og);og.connect(g);o.start(t);o.stop(t+0.55);
    });
  }catch(e){}
}
document.addEventListener('mousedown',()=>{try{plinkCtx();}catch(e){}},true);
/* == per-sheet floating transport + space shortcut (appended) == */
function togglePlayback(){
  const p=$('runPlayer');
  if(!p||!p.src||p.readyState===0)return;
  if(p.paused){try{p.play().catch(()=>{});}catch(e){}}else p.pause();
}
document.addEventListener('keydown',evt=>{
  if(evt.code!=='Space')return;
  const t=evt.target;
  if(t&&(t.tagName==='TEXTAREA'||t.tagName==='INPUT'||t.tagName==='SELECT'||t.isContentEditable))return;
  const dlg=$('runDialog');
  const dlgOpen=!!dlg&&(dlg.open===true||(!dlg.hidden&&dlg.offsetParent!==null)||(!dlg.hidden&&dlg.style.display!=='none'&&dlg.getBoundingClientRect().height>0));
  if(!dlgOpen)return;
  evt.preventDefault();
  togglePlayback();
});
function ensureTransport(which){
  const sheet=$(which==='run'?'runScoreSheet':'abcSheet');
  if(!sheet)return;
  if(sheet.querySelector('.score-transport'))return;
  const b=document.createElement('button');
  b.type='button';
  b.className='score-transport';
  b.title='Play / pause (Space)';
  b.textContent='\u25b6';
  b.addEventListener('click',e=>{
    e.stopPropagation();
    const p=$('runPlayer');
    if(!p||!p.src){toast('No audio yet - render the song first.');return;}
    togglePlayback();
  });
  const sync=()=>{b.textContent=p.paused?'\u25b6':'\u2759\u2759';};
  const p=$('runPlayer');
  if(p){p.addEventListener('play',sync);p.addEventListener('pause',sync);}
  // Sticky row pinned to the top-right of the sheet while it scrolls.
  const row=document.createElement('div');
  row.className='score-transport-row';
  row.append(b);
  sheet.insertBefore(row,sheet.firstChild);
}

if(!state.abcPreviewCursor)state.abcPreviewCursor={els:null,key:null};
