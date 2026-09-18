const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag='div') { this.tag=tag; this.children=[]; this.value=''; this.disabled=false; this.handlers={}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=items; }
  setAttribute(name,value) { this[name]=value; }
  addEventListener(name,fn) { (this.handlers[name] ||= []).push(fn); }
  showModal() { this.open=true; }
}
const elements = new Map();
const el = id => { if (!elements.has(id)) elements.set(id,new Element()); return elements.get(id); };
const calls=[];
const tracks = [
  {filename:'Band - Song.wav',artist:'Band',title:'Song',duration:100,exists:false},
  {filename:'Band - Missing.wav',artist:'Band',title:'Missing',duration:100,exists:false},
  {filename:'Band - Existing.wav',artist:'Band',title:'Existing',duration:100,exists:true}
];
const context = {
  document:{getElementById:el,createElement:tag=>new Element(tag)},
  setTimeout:()=>1, clearTimeout:()=>{},
  api:async(path,data)=>{
    calls.push([path,data]);
    if(path.endsWith('/scan'))return {folder:'E:/dataset',tracks:tracks.map(t=>({...t}))};
    if(path.endsWith('/search'))return {matches:data.title==='Missing'?[]:[{id:1,artist:'Band',title:data.title,album:'Album',duration:100,duration_difference:0,text:data.title==='Empty'?'':'Fixture lyric',instrumental:data.title==='Instrumental'}]};
    if(path.endsWith('/save')){
      if(data.filename==='Band - Failure.wav')throw new Error('Disk write failed');
      return {filename:data.filename.replace('.wav','.lyrics.txt'),saved:true};
    }
    throw new Error('Unexpected request '+path);
  }
};
vm.runInNewContext(fs.readFileSync('src/yue2_studio/static/dataset.js','utf8'),context);
(async()=>{
  el('datasetFolder').value='E:/dataset';
  el('datasetLyricsTab').onclick();
  assert.equal(el('datasetLyricsPanel').hidden,false);
  assert.equal(el('datasetAudioPanel').hidden,true);
  await el('datasetLyricsLoad').onclick();
  assert.equal(el('datasetLyricsTracks').children.length,3);
  await el('datasetLyricsSearchAll').onclick();
  assert.equal(calls.filter(([path])=>path.endsWith('/search')).length,2);
  assert.equal(calls.filter(([path])=>path.endsWith('/save')).length,0,'Search must never save automatically');
  const first=el('datasetLyricsTracks').children[0];
  const actions=first.children[3], save=actions.children[1];
  assert.equal(save.disabled,false);
  assert.equal(first.children[5].children[1].value,'Fixture lyric');
  assert.match(el('datasetLyricsTracks').children[1].children[2].textContent,/No matches/);
  await save.onclick();
  const saved=calls.find(([path])=>path.endsWith('/save'))[1];
  assert.equal(saved.filename,'Band - Song.wav');
  assert.equal(saved.text,'Fixture lyric');
  assert.equal(saved.folder,'E:/dataset');
  assert.equal(save.disabled,true);
  await el('datasetLyricsSearchAll').onclick();
  assert.equal(calls.filter(([path])=>path.endsWith('/search')).length,3,'Existing and just-saved files skipped');
  for(const title of ['Empty','Instrumental','Failure','Another']){
    tracks.push({filename:'Band - '+title+'.wav',artist:'Band',title,duration:100,exists:false});
  }
  await el('datasetLyricsLoad').onclick();
  await el('datasetLyricsSearchAll').onclick();
  assert.equal(el('datasetLyricsSaveAll').disabled,false);
  const start=calls.length;
  await el('datasetLyricsSaveAll').onclick();
  const writes=calls.slice(start).filter(([path])=>path.endsWith('/save')).map(([,data])=>data.filename);
  assert.deepEqual(writes,['Band - Song.wav','Band - Failure.wav','Band - Another.wav']);
  assert.match(el('datasetLyricsStatus').textContent,/2 saved · 1 failed/);
  assert.equal(el('datasetLyricsSaveAll').disabled,false,'Failed saves remain retryable');
  console.log('Lyrics tab scan/search/review/save and bulk failure/skip controls passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
