'use strict';

function localDateKey(value){
  const date=value instanceof Date?value:new Date(value);
  if(Number.isNaN(date.getTime()))return '';
  return [date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');
}

function libraryDateMatches(job,filter,chosen){
  if(filter==='all')return true;
  const created=new Date(job.created);
  if(Number.isNaN(created.getTime()))return false;
  if(filter==='custom')return Boolean(chosen)&&localDateKey(created)===chosen;
  const today=new Date();today.setHours(0,0,0,0);
  const tomorrow=new Date(today);tomorrow.setDate(today.getDate()+1);
  if(filter==='today')return created>=today&&created<tomorrow;
  const start=new Date(today);
  if(filter==='yesterday'){
    start.setDate(today.getDate()-1);return created>=start&&created<today;
  }
  if(!['last7','last30'].includes(filter))return false;
  start.setDate(today.getDate()-(filter==='last7'?6:29));
  return created>=start&&created<tomorrow;
}

const pendingStars=new Set();
async function toggleStar(id){
  const job=state.jobs.find(item=>item.id===id);
  if(!job||pendingStars.has(id))return;
  pendingStars.add(id);
  try{
    const starred=!job.starred;
    const updated=await api('/api/jobs/'+id+'/star',{starred});
    // Polling may have replaced the jobs array while the request was in flight.
    const current=state.jobs.find(item=>item.id===id);
    if(current)current.starred=updated.starred;
    renderLibrary();toast(starred?'Song starred.':'Star removed.');
  }catch(error){feedbackError(error);}
  finally{pendingStars.delete(id);}
}

function bindLibraryDates(){
  $('libraryDate').oninput=renderLibrary;
  $('libraryDateFilter').onchange=()=>{
    const custom=$('libraryDateFilter').value==='custom';
    $('libraryDate').hidden=!custom;
    if(custom&&!$('libraryDate').value)$('libraryDate').value=localDateKey(new Date());
    renderLibrary();
  };
}
