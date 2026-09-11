const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../src/yue2_studio/static/app.js'),'utf8');
const context={};vm.createContext(context);vm.runInContext(source.slice(source.indexOf('// Lyrics export:')),context);
for(const lyrics of ['', 'No tags\nCafé & words', '[Verse]\r\nFirst line\r\n\r\n[Chorus]\r\nRepeat\r\n[Chorus]\r\nRepeat', 'Opening\n[Verse 1] [Whispered]\nWords\n[Outro]']){
 const result=context.songDetails({lyrics,title:'Title',style:'Style',source:'generation_request',job_id:'test'});
 assert.equal(result.lyrics,lyrics);assert.equal(result.sections.map(s=>s.text).join(''),lyrics);assert.equal(result.timing,null);
}
const sections=context.lyricSections('[Verse]\nFirst\n[Chorus]\nAgain\n[Chorus]\nAgain');
assert.equal(sections.length,3);assert.equal(sections[2].tag,'[Chorus]');
console.log('Exact lyrics, CRLF, Unicode, repeated tags, untagged text and empty lyrics verified.');
