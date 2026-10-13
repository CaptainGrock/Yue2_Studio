'use strict';

// Audius's API key is a public OAuth client identifier. The private bearer
// token must never be placed in this file or returned by Studio's bootstrap.
let audiusClient=null;
let audiusRedirectHandled=false;
const AUDIUS_UPLOADS_KEY='yue2-studio-audius-uploads-v1';

// Local element lookup with a unique name: app.js already declares a global
// `const $`, and redeclaring it here would throw
// "Identifier '$' has already been declared" and kill the whole Studio UI
// (audius.js loads before app.js, both deferred in document order).
const audiusEl = id => document.getElementById(id);
// app.js owns `state`, `toast`, `button`, `artifactUrl` and `feedbackError`.
// This file must never throw when they are absent (app.js still loading, or
// failed to parse): the 500 ms interval below would otherwise spam the
// console with `ReferenceError: state is not defined` every tick.
function audiusState(){
  try{ return (typeof state!=='undefined'&&state)?state:null; }
  catch{ return null; }
}
function audiusToast(text,isErr){
  try{ if(typeof toast!=='undefined'&&toast) return toast(text,isErr); }catch{}
  if(isErr){ try{ console.error(text); }catch{} }
}
function audiusButton(text,fn,style){
  try{
    if(typeof button!=='undefined'&&button) return button(text,fn,style||'subtle small');
  }catch{}
  const b=document.createElement('button');
  b.className='button '+(style||'subtle small');
  b.textContent=text;
  if(fn) b.onclick=fn;
  return b;
}
function audiusArtifactUrl(jobId,path){
  try{
    if(typeof artifactUrl!=='undefined'&&artifactUrl) return artifactUrl(jobId,path);
  }catch{}
  return '/artifacts/'+jobId+'/'+String(path||'').split('/').map(encodeURIComponent).join('/');
}
function audiusError(error){
  try{
    if(typeof feedbackError!=='undefined'&&feedbackError) return feedbackError(error);
  }catch{}
  audiusToast((error&&error.message)||String(error),true);
}

function getAudiusClient(){
  const st=audiusState();
  if(!st||!st.boot||!st.boot.audius||!st.boot.audius.enabled)throw new Error('Audius publishing is not configured for this Studio installation.');
  if(!window.audiusSdk)throw new Error('The Audius SDK did not load. Check your internet connection and reload Studio.');
  if(!audiusClient)audiusClient=window.audiusSdk({
    apiKey:st.boot.audius.client_id,
    redirectUri:location.origin+'/'
  });
  return audiusClient;
}

function readAudiusUploads(){
  try{const value=JSON.parse(localStorage.getItem(AUDIUS_UPLOADS_KEY)||'{}');return value&&typeof value==='object'?value:{};}
  catch{return {};}
}

function writeAudiusUpload(jobId,value){
  const uploads=readAudiusUploads();uploads[jobId]=value;
  try{localStorage.setItem(AUDIUS_UPLOADS_KEY,JSON.stringify(uploads));}catch{}
}

function safeAudiusUrl(value){
  if(!value)return '';
  try{
    const url=new URL(value,'https://audius.co');
    return url.protocol==='https:'&&url.hostname==='audius.co'?url.href:'';
  }catch{return '';}
}

function openAudiusUrl(url){
  const safe=safeAudiusUrl(url);
  if(!safe)throw new Error('Audius did not return a safe public page URL.');
  window.open(safe,'_blank','noopener,noreferrer');
}

async function audiusProfile(){
  try{
    const sdk=getAudiusClient();
    if(!await sdk.oauth.isAuthenticated())return null;
    return await sdk.oauth.getUser();
  }catch{return null;}
}

async function updateAudiusStatus(){
  const st=audiusState();
  if(!st) return;
  const status=audiusEl('audiusStatus'),connect=audiusEl('connectAudius'),disconnect=audiusEl('disconnectAudius');
  if(!status||!connect||!disconnect) return;
  const hint=audiusEl('audiusCallbackHint');
  if(hint) hint.textContent='OAuth callback registered in Audius: '+location.origin+'/';
  if(!st.boot||!st.boot.audius||!st.boot.audius.enabled){
    status.textContent='Not configured. Set YUE2_AUDIUS_API_KEY before starting Studio.';
    connect.disabled=true;disconnect.hidden=true;return;
  }
  const user=await audiusProfile();
  status.textContent=user?'Connected as '+(user.name||user.handle||'Audius user')+'.':'Not connected.';
  connect.textContent=user?'Reconnect Audius':'Connect Audius';
  connect.disabled=false;disconnect.hidden=!user;
}

async function openAudiusSettings(){
  await updateAudiusStatus();
  const dialog=audiusEl('audiusDialog');
  if(dialog&&!dialog.open)dialog.showModal();
}

async function connectAudius(){
  try{
    await getAudiusClient().oauth.login({scope:'write'});
    await updateAudiusStatus();audiusToast('Audius connected.');
  }catch(error){audiusToast(error.message||'Audius connection failed.',true);}
}

async function disconnectAudius(){
  try{
    await getAudiusClient().oauth.logout();
    await updateAudiusStatus();audiusToast('Audius disconnected.');
  }catch(error){audiusToast(error.message||'Audius disconnect failed.',true);}
}

async function fetchAudiusTrack(sdk,trackId){
  let track=null;
  for(let attempt=0;attempt<8;attempt++){
    if(attempt)await new Promise(resolve=>setTimeout(resolve,1000));
    try{const result=await sdk.tracks.getTrack({trackId});track=result?.data||result;if(track)break;}catch{}
  }
  return track;
}

async function uploadJobToAudius(job){
  if(!job||job.kind!=='generation'||!['complete','needs_review'].includes(job.status))throw new Error('Only completed songs can be uploaded.');
  const profile=await audiusProfile();
  if(!profile){await openAudiusSettings();throw new Error('Connect Audius first.');}
  const rights=audiusEl('audiusRights');
  if(!rights||!rights.checked){await openAudiusSettings();throw new Error('Confirm that you have the rights to publish this music.');}

  const response=await fetch(audiusArtifactUrl(job.id,'result/audio.flac'));
  if(!response.ok)throw new Error('Could not read the rendered FLAC.');
  const file=new File([await response.blob()],(job.title||'yue2-song')+'.flac',{type:'audio/flac'});
  const sdk=getAudiusClient();
  const audio=await sdk.uploads.createAudioUpload({file}).start();
  const userId=profile.userId||profile.id;
  if(!userId)throw new Error('Audius did not return the connected user ID.');
  const genreEl=audiusEl('audiusGenre');
  const createdResult=await sdk.tracks.createTrack({
    userId,
    metadata:{
      title:job.title||'YuE2 song',
      genre:(genreEl&&genreEl.value)||'Electronic',
      description:'Created with YuE2 Studio. AI-assisted music; publication rights confirmed by the uploader.',
      ...audio,
      isDownloadable:true,
      noAiUse:true
    }
  });
  const created=createdResult?.data||createdResult;
  const trackId=created?.trackId||created?.id;
  if(!trackId)throw new Error('Audius accepted the audio but did not return a track ID.');

  const track=await fetchAudiusTrack(sdk,trackId);
  // Storage-node/CDN URLs are intentionally rejected. Only public audius.co pages may open.
  const trackUrl=safeAudiusUrl(track?.permalink);
  const handle=track?.user?.handle||profile.handle;
  const profileUrl=handle?safeAudiusUrl('https://audius.co/'+encodeURIComponent(handle)):'';
  const url=trackUrl||profileUrl;
  if(!url)throw new Error('Audius created the track, but its public page is still indexing. Check your Audius profile in a moment.');
  const published={trackId,url,kind:trackUrl?'track':'profile',created:new Date().toISOString()};
  writeAudiusUpload(job.id,published);
  audiusToast(trackUrl?'Uploaded to Audius.':'Uploaded. Audius is still indexing the track page.');
  return published;
}

function makeAudiusButton(job){
  const prior=readAudiusUploads()[job.id];
  const action=audiusButton(prior?(prior.kind==='track'?'Open on Audius':'Open Audius profile'):'Upload to Audius',()=>{});
  action.classList.add('audius-upload-button');action.dataset.jobId=job.id;
  if(prior){action.onclick=()=>openAudiusUrl(prior.url);return action;}
  action.onclick=async()=>{
    try{
      action.disabled=true;action.textContent='Uploading…';
      const published=await uploadJobToAudius(job);
      action.disabled=false;action.textContent=published.kind==='track'?'Open on Audius':'Open Audius profile';
      action.onclick=()=>openAudiusUrl(published.url);
    }catch(error){action.disabled=false;action.textContent='Upload to Audius';audiusError(error);}
  };
  return action;
}

function decorateAudiusButtons(){
  const st=audiusState();
  if(!st||!st.jobs) return;
  try{
    for(const card of document.querySelectorAll('#libraryList .run-card')){
      if(card.querySelector('.audius-upload-button'))continue;
      const source=card.querySelector('audio')?.getAttribute('src')||'';
      const match=source.match(/^\/artifacts\/([a-f0-9]{32})\/result\/audio\.flac$/);
      const job=match?st.jobs.find(item=>item.id===match[1]):null;
      if(job)card.querySelector('.run-state')?.parentElement?.append(makeAudiusButton(job));
    }
    const actions=audiusEl('runActions');
    if(actions&&st.runId&&!actions.querySelector('.audius-upload-button')){
      const job=st.jobs.find(item=>item.id===st.runId);
      if(job?.kind==='generation'&&['complete','needs_review'].includes(job.status))actions.append(makeAudiusButton(job));
    }
  }catch(error){ /* never let the background decorator throw into the console */ }
}

async function finishAudiusRedirect(){
  const st=audiusState();
  if(!st||!st.boot||!st.boot.audius||!st.boot.audius.enabled)return;
  if(audiusRedirectHandled||!location.hash.includes('code='))return;
  audiusRedirectHandled=true;
  try{
    await getAudiusClient().oauth.handleRedirect();
    history.replaceState(null,'',location.pathname+location.search);
    if(window.opener)window.close();
  }catch(error){audiusRedirectHandled=false;audiusToast(error.message||'Audius authorization failed.',true);}
}

function bindAudius(){
  try{
    const nav=audiusEl('audiusNav');
    if(nav)nav.onclick=openAudiusSettings;
    const connect=audiusEl('connectAudius');
    if(connect)connect.onclick=connectAudius;
    const disconnect=audiusEl('disconnectAudius');
    if(disconnect)disconnect.onclick=disconnectAudius;
    new MutationObserver(()=>{ try{decorateAudiusButtons();}catch{} }).observe(document.body,{childList:true,subtree:true});
    setInterval(()=>{
      try{ void finishAudiusRedirect(); }catch{}
      try{ decorateAudiusButtons(); }catch{}
    },500);
  }catch{}
}

window.addEventListener('DOMContentLoaded',bindAudius);
