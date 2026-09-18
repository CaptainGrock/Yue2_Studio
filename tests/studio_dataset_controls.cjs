const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
const el = id => {
  if (!elements.has(id)) elements.set(id, {value:'', textContent:'', open:false,
    showModal(){this.open=true;}, addEventListener(){}, replaceChildren(...rows){this.rows=rows;}});
  return elements.get(id);
};
let response = {tools:{yt_dlp:true, ffmpeg:true, ffprobe:true, javascript:true},busy:false,default_folder:'E:/dataset',job:null};
const calls = [];
const context = {document:{getElementById:el,createElement:()=>({})},setTimeout:()=>1,clearTimeout:()=>{},
  api:async(path,data)=>{calls.push([path,data]);return response;}};
vm.runInNewContext(fs.readFileSync('src/yue2_studio/static/dataset.js','utf8'),context);
const tick = () => new Promise(resolve=>setImmediate(resolve));
(async()=>{
  el('datasetNav').onclick(); await tick();
  assert.equal(el('datasetDialog').open,true);
  assert.equal(el('datasetFolder').value,'E:/dataset');
  el('datasetUrl').value='https://youtube.com/playlist?list=PL1234567890';
  el('datasetArtist').value='My Band';
  response = {...response,busy:true,job:{status:'downloading',tracks:[{title:'<script>unsafe</script>',status:'saved',message:'Saved'}]}};
  await el('datasetStart').onclick(); await tick();
  assert.equal(calls[1][0],'/api/dataset-import/start');
  assert.equal(calls[1][1].folder,'E:/dataset');
  assert.equal(calls[1][1].fallback_artist,'My Band');
  assert.equal(el('datasetStart').disabled,true);
  assert.equal(el('datasetCancel').disabled,false);
  assert.equal(el('datasetTracks').rows[0].textContent,'saved: <script>unsafe</script> — Saved');
  await el('datasetCancel').onclick();
  assert.ok(calls.some(([path])=>path==='/api/dataset-import/cancel'));
  console.log('Dataset UI controls passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
