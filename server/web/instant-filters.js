'use strict';
function filterGeometry(p){return p?JSON.stringify(['instant-v1',p.id,p.points,p.rotation,!!p.dewarp]):null}
function filterBaseKey(p,ocr=$('ocr').checked){return filterGeometry(p)+'|ocr:'+ocr}
function releaseFilterCache(p){if(p.variantCache)Object.values(p.variantCache.urls).forEach(URL.revokeObjectURL);p.variantCache=null;if(p.filterPreview){URL.revokeObjectURL(p.filterPreview.url);p.filterPreview=null}}
async function warmFilters(p,sources,key=filterGeometry(p)){
 if(p.variantCache?.key===key&&Object.keys(sources).every(m=>p.variantCache.urls[m]))return;
 if(p.variantLoading?.key===key){await p.variantLoading.promise.catch(()=>{});if(p.variantCache?.key===key&&Object.keys(sources).every(m=>p.variantCache.urls[m]))return}
 const promise=(async()=>{
  const urls={};try{await Promise.all(Object.entries(sources).map(async([mode,source])=>{const r=await fetch(source.preview);if(!r.ok)throw Error('Không tải được bộ lọc đã lưu.');urls[mode]=URL.createObjectURL(await r.blob())}));
   if(!pages.includes(p)||filterGeometry(p)!==key){Object.values(urls).forEach(URL.revokeObjectURL);return}
   releaseFilterCache(p);p.variantCache={key,urls};p.variantSources=sources;p.variantGeometry=key;saveDraft();
  }catch(e){Object.values(urls).forEach(URL.revokeObjectURL);throw e}
 })();p.variantLoading={key,promise};try{await promise}finally{if(p.variantLoading?.promise===promise)p.variantLoading=null}
}
function showSavedFilter(p){
 const cache=p.variantCache;if(!cache||cache.key!==filterGeometry(p)||!cache.urls[p.mode])return false;
 p.filterPreview={url:cache.urls[p.mode],key:editKey(p,false)};
 if(current()===p){view='scan';renderEditor();$('scan-image').src=p.filterPreview.url;$('scan-info').textContent='Bộ lọc đã lưu · chuyển đổi ngay';$('scan-view').disabled=false;setView('scan')}
 renderQueue();return true;
}
const beforeInstantInvalidate=invalidate;invalidate=function(p){releaseFilterCache(p);p.variantSources=null;p.variantGeometry=null;p.baseResult=null;p.baseResultId=null;p.baseKey=null;beforeInstantInvalidate(p)};
const beforeInstantProcess=processPage;processPage=async function(p,number){
 const key=filterBaseKey(p),edit=editKey(p);let job;if(p.baseResult&&p.baseKey===key&&!p.baseResult.variants?.[p.mode])p.baseResult=await api('/api/jobs/'+p.baseResult.id+'/variants',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:p.id})});
 if(p.baseResult?.variants&&p.baseKey===key&&p.baseResult.variants[p.mode]){
  job=p.baseResult.mode===p.mode?p.baseResult:await api('/api/jobs/'+p.baseResult.id+'/filter',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:p.mode})});
  p.result=job;p.resultKey=edit;
 }else job=await beforeInstantProcess(p,number);
 if(job.variants){p.baseResult=job;p.baseResultId=job.id;p.baseKey=key;await warmFilters(p,job.variants);saveDraft()}
 return job;
};
scheduleFilterPreview=function(p){
 clearTimeout(previewTimer);if(showSavedFilter(p))return;
 const geometry=filterGeometry(p);
 previewTimer=setTimeout(()=>{
  const previous=previewTask||Promise.resolve();previewTask=previous.catch(()=>{}).then(async()=>{
   if(busy||!pages.includes(p)||filterGeometry(p)!==geometry)return;
   if(showSavedFilter(p))return;
   try{
    status('Đang chuẩn bị các bộ lọc một lần…');
    let sources=p.variantGeometry===geometry?p.variantSources:null;
    if(!sources?.[p.mode]&&p.baseResult&&p.baseKey?.startsWith(geometry+'|')){if(!p.baseResult.variants?.[p.mode])p.baseResult=await api('/api/jobs/'+p.baseResult.id+'/variants',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:p.id})});sources=p.baseResult.variants}
    if(!sources?.[p.mode]){const result=await api('/api/pages/'+p.id+'/variants',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({points:p.points,rotation:p.rotation,dewarp:!!p.dewarp,mode:p.mode})});sources=result.variants}
    await warmFilters(p,sources,geometry);
    if(filterGeometry(p)===geometry&&showSavedFilter(p))status('Đã lưu các bộ lọc. Chạm để xem ngay, không xử lý lại.');
   }catch(e){if(current()===p&&filterGeometry(p)===geometry)status(e.message,true)}
  });
 },120);
};
$('mode').onchange=()=>{
 const p=current();if(!p||busy)return;p.mode=$('mode').value;
 p.result=null;p.resultId=null;p.resultKey=null;p.filterPreview=null;discardDocument();saveDraft();renderQueue();
 if(showSavedFilter(p)){status('Đã đổi bộ lọc từ ảnh lưu sẵn.');return}
 view='edit';renderEditor();scheduleFilterPreview(p);
};
const beforeInstantEditor=renderEditor;renderEditor=function(){beforeInstantEditor();const p=current();if(p?.variantCache?.key===filterGeometry(p)&&p.variantCache.urls[p.mode]&&view==='scan'){$('scan-image').src=p.variantCache.urls[p.mode]}};
const beforeInstantControls=updateControls;updateControls=function(){
 beforeInstantControls();const p=current(),cached=p?.variantCache?.key===filterGeometry(p)&&p.variantCache.urls.ai_clean;
 const available=aiReady||!!cached;$('mode').querySelector('[value=ai_clean]').disabled=!available;
 const button=document.querySelector('[data-mode=ai_clean]');if(button)button.disabled=busy||!available;
 const ready=p?.variantCache?.key===filterGeometry(p);$('preview-page').textContent=ready?'Xác nhận trang':'Xử lý trang một lần';
 if(ready)$('page-state').textContent='Bộ lọc sẵn sàng';
};
const beforeInstantSelect=selectPage;selectPage=function(i){beforeInstantSelect(i);const p=current();if(p?.variants&&!p.variantSources){p.variantSources=p.variants;p.variantGeometry=filterGeometry(p)}if(p?.variantSources&&p.variantGeometry===filterGeometry(p))warmFilters(p,p.variantSources).catch(()=>{});else if(p?.result?.variants)warmFilters(p,p.result.variants).catch(()=>{})};
async function restoreInstantFilters(){for(const p of pages){if(!p.baseResult&&p.baseResultId){try{const job=await api('/api/jobs/'+p.baseResultId);if(job.status==='done'&&job.variants)p.baseResult=job}catch{}}if(p.result?.status==='done'){p.baseResult=p.result;p.baseResultId=p.result.id;p.baseKey=filterBaseKey(p,p.result.engine==='fast');if(p.result.variants){p.variantSources=p.result.variants;p.variantGeometry=filterGeometry(p)}}}const p=current();if(p?.baseResult&&!p.baseResult.variants?.docshadow){p.baseResult=await api('/api/jobs/'+p.baseResult.id+'/variants',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:p.id})});p.variantSources=p.baseResult.variants;p.variantGeometry=filterGeometry(p)}if(p?.variantSources&&p.variantGeometry===filterGeometry(p))await warmFilters(p,p.variantSources)}
(async()=>{while(busy)await sleep(100);await restoreInstantFilters().catch(()=>{});updateControls()})();
