"""Durable document snapshots, separate from the disposable 24-hour job directory."""
import json,os,re,shutil,threading,time,uuid
from filter_cache import MODES as FILTER_MODES
from pathlib import Path
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from PIL import Image

class SaveDocument(BaseModel):
    document_id: str = Field(pattern=r'^[0-9a-f]{32}$')

class RenameDocument(BaseModel):
    title: str = Field(min_length=1,max_length=120)

def library_router(root,data,get_job,prepare_page):
    library=Path(root)/'library';library.mkdir(exist_ok=True,mode=0o700)
    lock=threading.RLock();router=APIRouter(prefix='/api/library')
    def directory(key):
        if not re.fullmatch('[0-9a-f]{32}',key):raise HTTPException(404)
        p=library/key
        if p.is_symlink() or p.resolve().parent!=library.resolve():raise HTTPException(404)
        return p
    def read(key):
        try:return json.loads((directory(key)/'record.json').read_text(encoding='utf-8'))
        except (FileNotFoundError,json.JSONDecodeError):raise HTTPException(404,'Tài liệu không còn trong thư viện.')
    def public(record):return {k:v for k,v in record.items() if k!='snapshots'}
    def write(p,record):
        temp=p/'record.tmp';temp.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8');os.replace(temp,p/'record.json')
    @router.get('')
    def listing():
        with lock:
            items=[]
            for p in library.iterdir():
                if re.fullmatch('[0-9a-f]{32}',p.name):
                    try:items.append(public(read(p.name)))
                    except HTTPException:pass
            return sorted(items,key=lambda r:r['updated'],reverse=True)
    @router.post('',status_code=201)
    def save(body:SaveDocument):
        with lock:
            key=body.document_id;dest=directory(key)
            if (dest/'record.json').exists():return public(read(key))
            doc=get_job(key)
            if doc.get('type')!='document' or doc.get('status')!='done':raise HTTPException(400,'Hãy tạo PDF trước khi lưu.')
            temp=library/('pending-'+uuid.uuid4().hex);temp.mkdir(mode=0o700)
            try:
                for name in ['document.pdf','text.txt']:shutil.copyfile(data/key/name,temp/name)
                snapshots=[]
                for index,page_id in enumerate(doc['pages']):
                    page=get_job(page_id);page_dir=temp/str(index);page_dir.mkdir(mode=0o700)
                    for name in ['original.jpg','scan.jpg']:shutil.copyfile(data/page_id/name,page_dir/name)
                    snapshot={k:page.get(k) for k in ['rotation','crop_points','mode','dewarp']}
                    cache_key=page.get('filter_cache_key')
                    if cache_key and re.fullmatch('[0-9a-f]{16}',cache_key) and (data/page_id/f'base-{cache_key}.png').exists():
                        modes=list(page.get('variants',{}));snapshot.update(filter_cache_key=cache_key,filter_modes=modes)
                        shutil.copyfile(data/page_id/f'base-{cache_key}.png',page_dir/f'base-{cache_key}.png')
                        for mode in modes:
                            if mode not in FILTER_MODES:raise ValueError('Invalid filter')
                            for prefix in ['filter','thumb']:
                                name=f'{prefix}-{cache_key}-{mode}.jpg';shutil.copyfile(data/page_id/name,page_dir/name)
                    snapshots.append(snapshot)
                with Image.open(temp/'0/scan.jpg') as im:
                    im.thumbnail((300,400));im.convert('RGB').save(temp/'cover.jpg',quality=85)
                record={'id':key,'title':doc['title'],'page_count':doc['page_count'],'ocr_pages':doc['ocr_pages'],
                    'created':time.time(),'updated':time.time(),'bytes':(temp/'document.pdf').stat().st_size,
                    'pdf':f'/api/library/{key}/document.pdf','txt':f'/api/library/{key}/text.txt',
                    'cover':f'/api/library/{key}/cover.jpg','snapshots':snapshots}
                write(temp,record);os.replace(temp,dest)
                return public(record)
            except Exception:
                shutil.rmtree(temp,ignore_errors=True);raise
    @router.patch('/{key}')
    def rename(key:str,body:RenameDocument):
        with lock:
            record=read(key);title=body.title.strip()
            if not title:raise HTTPException(400,'Tên tài liệu không được để trống.')
            record.update(title=title,updated=time.time());write(directory(key),record);return public(record)
    @router.delete('/{key}')
    def delete(key:str):
        with lock:
            read(key);shutil.rmtree(directory(key));return {'deleted':key}
    @router.post('/{key}/edit')
    def edit(key:str):
        with lock:
            record=read(key);pages=[]
            for index,snapshot in enumerate(record['snapshots']):
                page=prepare_page((directory(key)/str(index)/'original.jpg').read_bytes())
                page.update(name=f'Trang {index+1}',points=snapshot.get('crop_points') or [[0,0],[1,0],[1,1],[0,1]],
                    rotation=snapshot.get('rotation') or 0,mode=snapshot.get('mode') or 'clean',dewarp=bool(snapshot.get('dewarp')))
                cache_key=snapshot.get('filter_cache_key');modes=snapshot.get('filter_modes',[])
                if cache_key:
                    from filter_cache import variant_urls,geometry_key
                    expected=geometry_key(page['points'],page['rotation'],page['dewarp'])
                    if cache_key==expected:
                        names=[f'base-{cache_key}.png']+[f'{prefix}-{cache_key}-{mode}.jpg' for mode in modes for prefix in ['filter','thumb']]
                        for name in names:shutil.copyfile(directory(key=record['id'])/str(index)/name,data/page['id']/name)
                        manifest={'key':cache_key,'modes':modes}
                        (data/page['id']/f'filters-{cache_key}.json').write_text(json.dumps(manifest))
                        page['variants']=variant_urls(page['id'],manifest)
                pages.append(page)
            return {'title':record['title'],'pages':pages,'ocr':record['ocr_pages']>0}
    @router.get('/{key}/{filename}')
    def file(key:str,filename:str):
        read(key)
        types={'document.pdf':'application/pdf','text.txt':'text/plain; charset=utf-8','cover.jpg':'image/jpeg'}
        if filename not in types:raise HTTPException(404)
        return FileResponse(directory(key)/filename,media_type=types[filename],
            filename=f'TailScan-{key[:8]}.pdf' if filename=='document.pdf' else None)
    return router
