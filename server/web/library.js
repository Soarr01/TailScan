'use strict';
document.body.classList.toggle('native-app',navigator.userAgent.includes('TailScan-iOS/'));
const ICONS={menu:'M4 6h16M4 12h16M4 18h16',grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',list:'M8 5h13M8 12h13M8 19h13M3 5h.01M3 12h.01M3 19h.01',search:'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',document:'M6 2h8l5 5v15H5V2zM14 2v6h5M8 12h8M8 16h8',image:'M3 3h18v18H3zM3 17l6-7 5 6 3-3 4 5M17 7h.01',camera:'M3 6h4l2-3h6l2 3h4v14H3zM16 13a4 4 0 1 1-8 0 4 4 0 0 1 8 0',plus:'M12 4v16M4 12h16',back:'M15 4l-8 8 8 8',right:'M9 5l7 7-7 7',edit:'M14 4l6 6M4 15L16 3l5 5L9 20H4z',crop:'M6 2v16h16M2 6h16v16',rotate:'M3 10a9 9 0 1 1 2 9M3 3v7h7',expand:'M9 3H3v6M15 3h6v6M3 15v6h6M21 15v6h-6',check:'M4 12l5 5L20 6',more:'M12 5h.01M12 12h.01M12 19h.01'};
function icon(name){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('class','icon');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',ICONS[name]||ICONS.document);svg.append(p);return svg}
document.querySelectorAll('[data-icon]').forEach(el=>el.replaceChildren(icon(el.dataset.icon)));
let documents=[],libraryLoading=false,gridMode=localStorage.getItem('tailscan-library-layout')==='grid';
const archiveTasks=new Map();
function updateShell(){
 $('resume-draft').classList.toggle('hidden',!pages.length);$('draft-description').textContent=($('title').value||'Tài liệu scan')+' · '+pages.length+' trang';
 $('connection').textContent=online?'Đã kết nối':'Chưa kết nối';$('connection').classList.toggle('offline',!online);
 for(const id of ['home','overview','editor-tab','home-new','home-import','home-camera','resume-draft'])$(id).disabled=busy;
 $('export').textContent=busy?'Đang xử lý…':`Lưu tài liệu${pages.length?' · '+pages.length+' trang':''}`;
 $('editor-tab').disabled=busy||!pages.length;
 document.querySelectorAll('#filter-presets button').forEach(b=>{b.classList.toggle('active',current()?.mode===b.dataset.mode);b.disabled=busy||(b.dataset.mode==='ai_clean'&&!aiReady)});
}
function workspace(edit=false){$('library-screen').classList.add('hidden');$('workspace-screen').classList.remove('hidden');document.body.classList.remove('screen-library');setEditing(edit);window.scrollTo(0,0)}
function setEditing(edit){document.body.classList.toggle('editing',edit);$('overview').classList.toggle('active',!edit);$('editor-tab').classList.toggle('active',edit);if(edit)setTimeout(drawCanvas,0)}
async function home(){if(busy)return;$('workspace-screen').classList.add('hidden');$('library-screen').classList.remove('hidden');document.body.classList.add('screen-library');updateShell();await loadLibrary();window.scrollTo(0,0)}
function ask({title,text='',value=null,accept='Đồng ý',choices=[]}){return new Promise(resolve=>{
 const dlg=$('app-dialog');if(dlg.open){resolve(null);return}
 $('dialog-title').textContent=title;$('dialog-description').textContent=text;$('dialog-input').classList.toggle('hidden',value===null);$('dialog-input').value=value??'';$('dialog-accept').textContent=accept;$('dialog-accept').classList.toggle('hidden',choices.length>0);
 const extra=document.createElement('div');extra.className='dialog-choices';for(const [id,label] of choices){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=()=>dlg.close(id);extra.append(b)}dlg.querySelector('form').insertBefore(extra,dlg.querySelector('.dialog-actions'));
 dlg.addEventListener('close',()=>{extra.remove();resolve(dlg.returnValue==='accept'?{value:$('dialog-input').value}:choices.some(c=>c[0]===dlg.returnValue)?{action:dlg.returnValue}:null)},{once:true});dlg.returnValue='cancel';dlg.showModal();
})}
async function canReplace(){return !pages.length||!!latestDocument||!!await ask({title:'Thay tài liệu đang soạn?',text:'Bản nháp hiện tại chưa được lưu vào thư viện. Hãy lưu trước nếu bạn muốn giữ các trang này.',accept:'Thay bản nháp'})}
function formatSize(n){return n>=1048576?(n/1048576).toFixed(1)+' MB':Math.max(1,Math.round(n/1024))+' KB'}
function renderLibrary(){
 const list=$('library-list');list.replaceChildren();list.classList.toggle('grid',gridMode);$('layout').replaceChildren(icon(gridMode?'list':'grid'));
 const query=$('search').value.trim().toLocaleLowerCase('vi');let rows=documents.filter(d=>d.title.toLocaleLowerCase('vi').includes(query));
 if($('sort').value==='name')rows.sort((a,b)=>a.title.localeCompare(b.title,'vi'));else rows.sort((a,b)=>$('sort').value==='oldest'?a.created-b.created:b.updated-a.updated);
 $('library-count').textContent=documents.length?documents.length+' tài liệu':'Thư viện của bạn';$('library-empty').classList.toggle('hidden',rows.length>0||!!query||libraryLoading);
 for(const d of rows){const card=document.createElement('article');card.className='document-card';const cover=document.createElement('img');cover.className='document-cover';cover.src=d.cover;cover.alt='';cover.loading='lazy';const link=document.createElement('a');link.className='document-main';link.href=d.pdf;link.target='_blank';link.rel='noopener';const title=document.createElement('strong');title.textContent=d.title;const meta=document.createElement('small');meta.textContent=d.page_count+' trang · '+new Date(d.updated*1000).toLocaleDateString('vi-VN')+' · '+formatSize(d.bytes);link.append(title,meta);if(d.ocr_pages){const badge=document.createElement('small');badge.className='document-badge';badge.textContent='Có văn bản tìm kiếm';link.append(badge)}const menu=document.createElement('button');menu.className='icon-button document-menu';menu.setAttribute('aria-label','Tùy chọn '+d.title);menu.append(icon('more'));menu.onclick=()=>documentMenu(d);card.append(cover,link,menu);list.append(card)}
 if(query&&!rows.length)$('library-status').textContent='Không tìm thấy tài liệu phù hợp.';
}
async function loadLibrary(){if(libraryLoading)return;libraryLoading=true;try{documents=await api('/api/library');$('library-status').textContent=''}catch(e){$('library-status').textContent='Chưa tải được thư viện. Kiểm tra Tailscale và kết nối máy xử lý.'}finally{libraryLoading=false;renderLibrary()}}
async function documentMenu(d){
 const choice=await ask({title:d.title,text:d.page_count+' trang · Đã lưu trên máy xử lý của bạn',choices:[['edit','Chỉnh sửa các trang'],['rename','Đổi tên'],['delete','Xóa tài liệu']]});if(!choice)return;
 try{if(choice.action==='rename'){const answer=await ask({title:'Đổi tên tài liệu',value:d.title,accept:'Lưu tên'});if(!answer)return;await api('/api/library/'+d.id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:answer.value.trim()})});await loadLibrary()}
 else if(choice.action==='delete'){if(!await ask({title:'Xóa tài liệu này?',text:'Tài liệu và các ảnh lưu trong thư viện sẽ bị xóa khỏi máy xử lý. Bản PDF bạn đã lưu vào Tệp không bị ảnh hưởng.',accept:'Xóa tài liệu'}))return;await api('/api/library/'+d.id,{method:'DELETE'});await loadLibrary()}
 else if(choice.action==='edit'){if(!await canReplace())return;busy=true;updateShell();const saved=await api('/api/library/'+d.id+'/edit',{method:'POST'});for(const p of pages){if(typeof releaseFilterCache==='function')releaseFilterCache(p);else if(p.filterPreview)URL.revokeObjectURL(p.filterPreview.url)}pages=saved.pages.map(p=>({...p,result:null}));selected=0;view='edit';$('title').value=saved.title;$('ocr').checked=!!saved.ocr;discardDocument();saveDraft();renderQueue();renderEditor();workspace(false)}}catch(e){await ask({title:'Chưa hoàn tất',text:e.message,accept:'Đóng'})}finally{busy=false;renderQueue();renderEditor()}
}
async function archiveDocument(doc){
 if(archiveTasks.has(doc.id))return archiveTasks.get(doc.id);
 const task=(async()=>{try{$('archive-status').textContent='Đang lưu vào thư viện…';const record=await api('/api/library',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({document_id:doc.id})});if(latestDocument?.id===doc.id){latestDocument={...doc,...record};$('pdf-link').href=record.pdf;$('text-link').href=record.txt;$('archive-status').textContent='Đã lưu trong thư viện. Có thể mở lại và chỉnh tiếp.'}await loadLibrary();return record}catch(e){if(latestDocument?.id===doc.id)$('archive-status').textContent='Chưa lưu được vào thư viện. Hãy tải PDF để giữ bản sao; bấm Lưu tài liệu để thử lại.';return null}finally{archiveTasks.delete(doc.id)}})();archiveTasks.set(doc.id,task);return task;
}
const oldStatus=status;status=function(message,error=false){oldStatus(message,error);$('editor-status').textContent=message;$('editor-status').classList.toggle('error',error)};
const oldUpdateControls=updateControls;updateControls=function(){oldUpdateControls();updateShell()};
const oldSelectPage=selectPage;selectPage=function(i){oldSelectPage(i);workspace(true)};
const oldAddFiles=addFiles;addFiles=async function(files){if(!files.length||busy)return;workspace(false);await oldAddFiles(files);if(pages.length)workspace(true)};
const oldShowDocument=showDocument;showDocument=function(doc){oldShowDocument(doc);archiveDocument(doc)};
const oldNew=$('new').onclick;$('new').onclick=async()=>{if(busy||!await canReplace())return;oldNew();workspace(false)};
for(const b of document.querySelectorAll('#filter-presets button'))b.onclick=()=>{$('mode').value=b.dataset.mode;$('mode').dispatchEvent(new Event('change'))};
$('home').onclick=home;$('back-library').onclick=async()=>{if(latestDocument&&archiveTasks.has(latestDocument.id))await archiveTasks.get(latestDocument.id);home()};$('resume-draft').onclick=()=>workspace(false);$('overview').onclick=()=>setEditing(false);$('editor-tab').onclick=()=>setEditing(true);
$('home-new').onclick=()=>$('new').click();$('home-import').onclick=()=>{if(latestDocument)oldNew();workspace(false);$('files').click()};$('home-camera').onclick=()=>{if(latestDocument)oldNew();workspace(false);$('camera').click()};
$('search').oninput=()=>{renderLibrary();if(!$('search').value)$('library-status').textContent=''};$('sort').onchange=renderLibrary;$('layout').onclick=()=>{gridMode=!gridMode;localStorage.setItem('tailscan-library-layout',gridMode?'grid':'list');renderLibrary()};
$('about').onclick=()=>ask({title:'TailScan',text:'Quét tài liệu riêng qua Tailscale. Thư viện lưu trên máy xử lý của bạn và chỉ bị xóa khi bạn chọn xóa. Các bản nháp chưa lưu có thể hết hạn sau 24 giờ. Hãy lưu thêm PDF quan trọng vào Tệp trên iPhone. Máy xử lý cần đang hoạt động. GPU tự ngủ sau 5 phút không xử lý ảnh; khi quét tiếp có thể phải đợi model tải lại.',accept:'Đã hiểu'});
updateShell();loadLibrary();if(latestDocument)archiveDocument(latestDocument);
