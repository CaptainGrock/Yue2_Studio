const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(){this.children=[];this.value='';this.checked=false;this.handlers={};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(name,value){this[name]=value;}
  addEventListener(name,fn){(this.handlers[name] ||= []).push(fn);}
}
const elements=new Map();
const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const calls=[];
let runnerOpened=false, stopAfterFirst=false;
const context={
  document:{getElementById:el,createElement:()=>new Element()},
  setTimeout:()=>1,clearTimeout:()=>{},
  state:{connection:{provider:'test',model:'chosen-model',api_key:'request-only-secret'}},
  openRunner:()=>{runnerOpened=true;},
  api:async(path,data)=>{
    calls.push([path,data]);
    if(path.endsWith('/scan'))return {folder:'E:/dataset',tracks:[
      {filename:'Song.wav',artist:'Band',title:'Song',lyrics_name:'Song.txt',exists:true,has_structure:false},
      {filename:'Tagged.wav',artist:'Band',title:'Tagged',lyrics_name:'Tagged.lyrics.txt',exists:true,has_structure:true},
      {filename:'Missing.wav',artist:'Band',title:'Missing',exists:false,error:'Missing lyrics'},
      {filename:'Another.wav',artist:'Band',title:'Another',lyrics_name:'Another.txt',exists:true,has_structure:false}]};
    if(path.endsWith('/propose')){
      if(stopAfterFirst)el('datasetStructureStop').onclick();
      return {lyrics_name:data.filename.replace('.wav','.txt'),sha256:'hash',before:'Original words',after:'[Verse]\nOriginal words',sections:[{line:1,tag:'Verse'}],model:'chosen-model'};
    }
    if(path.endsWith('/apply'))return {filename:data.lyrics_name,backup:'E:/dataset/.lyrics-backups/original.bak'};
    throw new Error('Unexpected '+path);
  }
};
vm.runInNewContext(fs.readFileSync('src/yue2_studio/static/dataset.js','utf8'),context);
(async()=>{
  el('datasetFolder').value='E:/dataset';
  el('datasetStructureTab').onclick();
  assert.equal(el('datasetStructurePanel').hidden,false);
  assert.equal(el('datasetLyricsPanel').hidden,true);
  await el('datasetStructureLoad').onclick();
  assert.equal(el('datasetStructureAll').disabled,true,'Consent required');
  el('datasetStructureConsent').checked=true;el('datasetStructureConsent').onchange();
  assert.equal(el('datasetStructureAll').disabled,false);
  await el('datasetStructureAll').onclick();
  assert.equal(calls.filter(([p])=>p.endsWith('/propose')).length,2,'Tagged/missing files skipped');
  assert.equal(calls.filter(([p])=>p.endsWith('/apply')).length,0,'No auto apply');
  assert.equal(el('datasetStructureApplyAll').disabled,true,'Review required');
  const cards=el('datasetStructureTracks').children;
  assert.equal(cards[0].children[3].children[2].value,'Original words');
  cards[0].children[4].children[0].checked=true;
  cards[0].children[4].children[0].onchange();
  await el('datasetStructureApplyAll').onclick();
  const applied=calls.filter(([p])=>p.endsWith('/apply'));
  assert.equal(applied.length,1,'Only reviewed suggestions applied');
  assert.equal(applied[0][1].filename,'Song.wav');
  assert.equal(applied[0][1].sha256,'hash');
  assert.equal(applied[0][1].connection,undefined,'Credentials not sent to apply');
  assert.match(cards[0].children[1].textContent,/backup/);
  const beforeReview=calls.length;
  assert.equal(el('datasetStructureReviewAll').disabled,false);
  el('datasetStructureReviewAll').onclick();
  assert.equal(calls.length,beforeReview,'Mark reviewed must not write or contact the LLM');
  assert.equal(cards[0].children[4].children[0].checked,false,'Applied suggestion is not reselected');
  assert.equal(cards[1].children[4].children[0].checked,false,'Already-tagged file excluded');
  assert.equal(cards[2].children[4].children[0].checked,false,'Missing lyrics excluded');
  assert.equal(cards[3].children[4].children[0].checked,true,'Pending suggestion marked');
  assert.equal(el('datasetStructureReviewAll').disabled,true);
  await el('datasetStructureApplyAll').onclick();
  assert.equal(calls.filter(([p])=>p.endsWith('/apply')).length,2);
  await el('datasetStructureLoad').onclick();
  stopAfterFirst=true;
  const count=calls.length;
  await el('datasetStructureAll').onclick();
  assert.equal(calls.slice(count).filter(([p])=>p.endsWith('/propose')).length,1,'Stop prevents next song');
  el('datasetStructureRunner').onclick();assert.equal(runnerOpened,true);
  console.log('Structure tab consent, batching, review, apply and stop controls passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
