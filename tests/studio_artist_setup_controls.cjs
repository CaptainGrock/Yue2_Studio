/* Real handlers with fake HTTP: never install, download, or train. */
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const elements=new Map(),calls=[];
function el(id){if(!elements.has(id))elements.set(id,{value:'',checked:false,textContent:'',append(){}});return elements.get(id);}
const context=vm.createContext({$:el,document:{createElement:()=>({})},busy:async(id,fn)=>fn(),confirmReplace:(a,b,fn)=>fn(),toast(){},openRun:async()=>{},api:async(url,data)=>{calls.push({url,data});return url.endsWith('/paths')?{paths:{}}:{id:'queued'};}});
vm.runInContext(fs.readFileSync('src/yue2_studio/static/artist.js','utf8'),context);
(async()=>{
 vm.runInContext('bindArtistSetup()',context);
 await new Promise(resolve=>setImmediate(resolve));
 el('artistPath_model').value='custom-model';
 await el('artistCheck').onclick();
 assert.equal(calls.at(-1).data.action,'check');assert.equal(calls.at(-1).data.confirmed,false);
 assert.equal(calls.at(-1).data.paths.model,'custom-model');
 const before=calls.length;el('artistDownload').onclick();assert.equal(calls.length,before,'Terms required');
 el('artistTerms').checked=true;await el('artistDownload').onclick();
 assert.equal(calls.at(-1).data.action,'download-models');assert.equal(calls.at(-1).data.terms_accepted,true);
 await el('artistInstall').onclick();assert.equal(calls.at(-1).data.action,'install-runtime');
 assert(calls.every(c=>!c.url.endsWith('/train')));
 const html=fs.readFileSync('src/yue2_studio/static/index.html','utf8');
 assert(/id="artistSteps"[^>]*value="500"/.test(html));
 assert(/id="artistCheckpoint"[^>]*value="250"/.test(html));
 const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
 assert.equal(ids.length,new Set(ids).size);
 const script=fs.readFileSync('src/yue2_studio/static/artist.js','utf8');
 for(const match of script.matchAll(/\$\('([^']+)'\)/g))if(match[1]!=='artistPath_')assert(ids.includes(match[1]),'Missing '+match[1]);
 assert(!html.includes('artistRecovered'));
 assert(html.indexOf('/artist.js')<html.indexOf('/app.js'));
 console.log('Artist setup UI passed: paths, confirmations, no implicit training, HTML contract.');
})().catch(error=>{console.error(error);process.exitCode=1;});
