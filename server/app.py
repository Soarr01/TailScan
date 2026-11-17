"""Private, single-user document scanner served through Tailscale Serve."""
import asyncio
import io
import html
import json
import logging
import os
import re
import threading
import time
import uuid
import shutil
from filter_cache import ensure_variants, variant_urls, geometry_key, MODES as FILTER_MODES
from docshadow_engine import DocShadowEngine
DOCSHADOW = DocShadowEngine()
from gpu_runtime import GPURuntime, OCRProxy
import urllib.request
from typing import Literal
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
os.environ.setdefault('FLAGS_allocator_strategy', 'auto_growth')
import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pydantic import BaseModel, Field
from image_filters import paper_color, paper_gray, paper_bw

register_heif_opener()
Image.MAX_IMAGE_PIXELS = 32_000_000
ROOT = Path(__file__).parent
DATA = ROOT / 'data'
DATA.mkdir(exist_ok=True, mode=0o700)
MAX_BYTES = 25 * 1024 * 1024
JOBS = {}
LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=1)
GPU = GPURuntime(ROOT,busy=lambda:LOCK.locked())
MODEL = None
MODEL_ERROR = None
MODEL_NAME = 'PaddleOCR-VL-1.6'
PREPARE_LIMIT = asyncio.Semaphore(2)
CORNER_MODEL = None
CORNER_INIT_LOCK = threading.Lock()
CORNER_MODEL_PATH = ROOT/'models/docquad/docquadnet256.ort'
FILTER_URL = 'http://127.0.0.1:8791'
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
pdfmetrics.registerFont(TTFont('ScanSans', str(ROOT / 'fonts' / 'DejaVuSans.ttf')))


def init_model():
    global MODEL,MODEL_ERROR
    MODEL=OCRProxy(GPU);MODEL_ERROR=None


@asynccontextmanager
async def lifespan(app):
    # Only remove old generated documents belonging to this application.
    cutoff = time.time() - 86400
    for directory in DATA.iterdir():
        if directory.is_dir() and len(directory.name) == 32 and directory.stat().st_mtime < cutoff:
            for file in directory.iterdir():
                if file.is_file():
                    file.unlink()
            directory.rmdir()
    GPU.start()
    if os.environ.get('TAILSCAN_SKIP_MODEL_LOAD') != '1':init_model()
    try:yield
    finally:GPU.close()


app = FastAPI(title='TailScan', lifespan=lifespan)


def detect_corners_classic(image):
    h, w = image.shape[:2]
    scale = min(1.0, 1200 / max(h, w))
    small = cv2.resize(image, (round(w * scale), round(h * scale)))
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:8]:
        area = cv2.contourArea(contour) / (small.shape[0] * small.shape[1])
        if area < 0.35:
            continue
        points = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(points) != 4 or not cv2.isContourConvex(points):
            continue
        pts = points.reshape(4, 2).astype(np.float32) / scale
        ordered = np.zeros((4, 2), np.float32)
        sums = pts.sum(axis=1)
        diffs = np.diff(pts, axis=1).ravel()
        ordered[0], ordered[2] = pts[np.argmin(sums)], pts[np.argmax(sums)]
        ordered[1], ordered[3] = pts[np.argmin(diffs)], pts[np.argmax(diffs)]
        if len(np.unique(ordered, axis=0)) != 4:
            continue
        tl, tr, br, bl = ordered
        outw = round(max(np.linalg.norm(tr-tl), np.linalg.norm(br-bl)))
        outh = round(max(np.linalg.norm(bl-tl), np.linalg.norm(br-tr)))
        if min(outw, outh) < 100:
            continue
        return ordered
    return None


def suggest_corners(image):
    global CORNER_MODEL
    if CORNER_MODEL_PATH.is_file():
        try:
            if CORNER_MODEL is None:
                with CORNER_INIT_LOCK:
                    if CORNER_MODEL is None:
                        from corner_models import CornerModel
                        CORNER_MODEL = CornerModel(CORNER_MODEL_PATH,'docquad',protect_border=True)
            result = CORNER_MODEL.predict(image)
            if result['detected']:
                return np.float32(result['corners']), {'detector':'DocQuadNet-256',
                    'corner_tentative':result['tentative'], 'border_extended':result['border_extended']}
        except Exception:
            logging.exception('Corner model unavailable; falling back to contours')
    return detect_corners_classic(image), {'detector':'contours','corner_tentative':False,'border_extended':False}


def detect_corners(image):
    return suggest_corners(image)[0]


def validate_points(points):
    if points is None:
        return None
    try:
        if len(points) != 4 or any(len(p) != 2 for p in points):
            raise ValueError()
        pts = np.asarray(points, dtype=np.float32)
        if not np.isfinite(pts).all() or (pts < 0).any() or (pts > 1).any():
            raise ValueError()
        edges = np.roll(pts, -1, axis=0) - pts
        cross = edges[:, 0]*np.roll(edges[:, 1], -1)-edges[:, 1]*np.roll(edges[:, 0], -1)
        if not (cross > 0.0001).all() or cv2.contourArea(pts) < 0.005:
            raise ValueError()
        return pts.tolist()
    except (ValueError, TypeError):
        raise HTTPException(400, 'Bốn góc phải tạo thành một vùng giấy lồi, theo thứ tự quanh trang.')


def warp_corners(image, points):
    tl, tr, br, bl = points
    outw = round(max(np.linalg.norm(tr-tl), np.linalg.norm(br-bl)))
    outh = round(max(np.linalg.norm(bl-tl), np.linalg.norm(br-tr)))
    if min(outw, outh) < 20:
        raise ValueError('Crop region too small')
    target = np.float32([[0,0], [outw-1,0], [outw-1,outh-1], [0,outh-1]])
    return cv2.warpPerspective(image, cv2.getPerspectiveTransform(np.float32(points), target), (outw,outh))


def perspective(image):
    corners = detect_corners(image)
    return (warp_corners(image, corners), True) if corners is not None else (image, False)


def geometry(image, points=None, rotation=0, crop=False):
    if rotation:
        image=np.ascontiguousarray(np.rot90(image,k=-(rotation//90)))
    if points is not None:
        if not np.allclose(points,[[0,0],[1,0],[1,1],[0,1]],atol=.0001):
            h,w=image.shape[:2]
            return warp_corners(image,np.float32(points)*[w-1,h-1]),True
    elif crop:
        return perspective(image)
    return image,False


def ai_filter_ready():
    return (Path(os.environ.get('TAILSCAN_IMAGE_LAB',str(ROOT/'image_worker')))/'models/docres.pkl').is_file()


def dewarp_ready():
    return (Path(os.environ.get('TAILSCAN_IMAGE_LAB',str(ROOT/'image_worker')))/'uvdoc/best_model.pkl').is_file()


def flatten_page(image):
    if not dewarp_ready():raise RuntimeError('Dewarping is unavailable')
    ok,data=cv2.imencode('.png',image)
    if not ok:raise RuntimeError('Cannot encode dewarping input')
    request=urllib.request.Request(FILTER_URL+'/dewarp',data=data.tobytes(),headers={'Content-Type':'image/png'})
    with GPU.lease('images') as url:
        request.full_url=url+'/dewarp'
        with LOCAL_HTTP.open(request,timeout=30) as r:
            output=cv2.imdecode(np.frombuffer(r.read(),np.uint8),cv2.IMREAD_COLOR)
    if output is None or output.shape!=image.shape:raise RuntimeError('Invalid dewarping output')
    return output


def enhance(image, mode):
    if mode == 'original':
        return image
    if mode == 'docshadow':return DOCSHADOW.enhance(image)
    if mode == 'color':return paper_color(image)
    if mode == 'clean':return paper_gray(image)
    if mode == 'bw':return paper_bw(image)
    if mode == 'ai_clean':
        if not ai_filter_ready():raise RuntimeError('AI filter unavailable or GPU is still warming')
        ok,data=cv2.imencode('.png',image)
        if not ok:raise RuntimeError('Cannot encode image')
        request=urllib.request.Request(FILTER_URL+'/enhance',data=data.tobytes(),
                                        headers={'Content-Type':'image/png'})
        with GPU.lease('images') as url:
            request.full_url=url+'/enhance'
            with LOCAL_HTTP.open(request,timeout=30) as r:
                output=cv2.imdecode(np.frombuffer(r.read(),np.uint8),cv2.IMREAD_COLOR)
        if output is None or output.shape!=image.shape:raise RuntimeError('Invalid AI filter output')
        return output
    raise ValueError('Unknown display filter')


def draw_pdf_page(c, image, lines):
    h, w = image.shape[:2]
    width = 595.28
    height = width * h / w
    c.setPageSize((width, height))
    rgb = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    c.drawImage(ImageReader(rgb), 0, 0, width=width, height=height)
    for line in lines:
        box = np.asarray(line['box'])
        x, y = box.min(axis=0)
        x2, y2 = box.max(axis=0)
        if line.get('block'):
            # The document model returns paragraph boxes, not word coordinates.
            # Wrap all recognized text inside its region for a searchable layer.
            left, top = x * width / w, height - y * width / w
            available_w = max(5, (x2-x) * width/w)
            available_h = max(5, (y2-y) * width/w)
            font_size = max(3, min(9, available_h / 1.15))
            while True:
                wrapped = []
                for paragraph in line['text'].splitlines() or ['']:
                    current = ''
                    for word in paragraph.split():
                        candidate = (current+' '+word).strip()
                        if current and pdfmetrics.stringWidth(candidate,'ScanSans',font_size)>available_w:
                            wrapped.append(current)
                            current=word
                        else:
                            current=candidate
                    if current: wrapped.append(current)
                if len(wrapped)*font_size*1.15<=available_h or font_size<=2:
                    break
                font_size*=0.9
            text=c.beginText(left,top-font_size)
            text.setFont('ScanSans',font_size)
            text.setLeading(font_size*1.15)
            text.setTextRenderMode(3)
            for row in wrapped:
                text.textLine(row)
            c.drawText(text)
            continue
        font_size = max(2, (y2-y) * width / w * 0.85)
        text = c.beginText(x * width / w, height - y2 * width / w + font_size * 0.15)
        text.setFont('ScanSans', font_size)
        text.setTextRenderMode(3)
        natural = pdfmetrics.stringWidth(line['text'], 'ScanSans', font_size)
        if natural:
            text.setHorizScale(max(1, (x2-x)*width/w / natural * 100))
        text.textOut(line['text'])
        c.drawText(text)
    c.showPage()


def searchable_pdf(image, lines, output):
    c = canvas.Canvas(str(output))
    c.setTitle('TailScan document')
    draw_pdf_page(c, image, lines)
    c.save()


def run_job(job_id, raw, mode, crop, language, engine='fast', points=None, rotation=0, dewarp=False, source_id=None):
    job = JOBS[job_id]
    started = time.monotonic()
    directory = DATA / job_id
    try:
        if engine == 'fast':
            job.update(status='processing',phase='waking_gpu')
            MODEL.ensure_ready()
        job['phase']='processing'
        job['status'] = 'processing'
        with Image.open(io.BytesIO(raw)) as source:
            source = ImageOps.exif_transpose(source).convert('RGB')
            source.thumbnail((3600, 3600))
            image = cv2.cvtColor(np.asarray(source), cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(directory / 'original.jpg'), image)
        cache_directory=DATA/source_id if source_id else directory
        def load_geometry():
            output,_=geometry(image,points,rotation,crop)
            return flatten_page(output) if dewarp else output
        manifest=ensure_variants(cache_directory,load_geometry,points,rotation,dewarp,enhance,ai_filter_ready,mode)
        cache_key=manifest['key']
        ocr_image=cv2.imread(str(cache_directory/f'base-{cache_key}.png'))
        if cache_directory!=directory:
            for name in manifest['modes']:
                for prefix in ['filter','thumb']:
                    filename=f'{prefix}-{cache_key}-{name}.jpg'
                    shutil.copyfile(cache_directory/filename,directory/filename)
        if cache_directory!=directory:shutil.copyfile(cache_directory/f'base-{cache_key}.png',directory/f'base-{cache_key}.png')
        shutil.copyfile(directory/f'filter-{cache_key}-{mode}.jpg',directory/'scan.jpg')
        image=cv2.imread(str(directory/'scan.jpg'))
        cropped=bool(crop or (points is not None and not np.allclose(points,[[0,0],[1,0],[1,1],[0,1]])))
        lines = []
        markdown = []
        for result in (MODEL.predict(ocr_image, max_pixels=1003520, max_new_tokens=2048) if engine == 'fast' else []):
            payload = result.json
            if callable(payload):
                payload = payload()
            if isinstance(payload, str):
                payload = json.loads(payload)
            payload = payload.get('res', payload)
            for block in payload.get('parsing_res_list', []):
                raw_text = block.get('block_content','').strip()
                if not raw_text:
                    continue
                markdown.append(raw_text)
                if block.get('block_label')=='table':
                    from bs4 import BeautifulSoup
                    text=BeautifulSoup(raw_text,'html.parser').get_text(' ',strip=True)
                else:
                    text=html.unescape(raw_text.replace('**',''))
                x,y,x2,y2=block['block_bbox']
                lines.append({'text': text, 'confidence': None, 'block': True,
                              'label':block.get('block_label','text'),
                              'box': [[x,y],[x2,y],[x2,y2],[x,y2]]})
        plain = '\n\n'.join(line['text'] for line in lines)
        (directory / 'document.md').write_text('\n\n'.join(markdown),encoding='utf-8')
        (directory / 'text.txt').write_text(plain, encoding='utf-8')
        searchable_pdf(image, lines, directory / 'document.pdf')
        summary = {'id': job_id, 'status': 'done', 'text': plain, 'lines': lines,
                   'seconds': round(time.monotonic()-started, 2), 'cropped': cropped,
                   'width': image.shape[1], 'height': image.shape[0],
                   'model': MODEL_NAME if engine == 'fast' else None, 'engine':engine,
                   'rotation':rotation, 'crop_points':points, 'mode':mode,
                   'variants':variant_urls(job_id,manifest), 'filter_cache_key':cache_key,
                   'dewarp':dewarp, 'dewarp_model':'UVDoc' if dewarp else None,
                   'language': language,
                   'block_count':len(lines), 'ocr_input':'unfiltered',
                   'image': f'/api/jobs/{job_id}/scan.jpg',
                   'original': f'/api/jobs/{job_id}/original.jpg',
                   'pdf': f'/api/jobs/{job_id}/document.pdf',
                   'txt': f'/api/jobs/{job_id}/text.txt',
                   'markdown': f'/api/jobs/{job_id}/document.md'}
        (directory / 'result.json').write_text(json.dumps(summary, ensure_ascii=False), encoding='utf-8')
        job.update(summary)
    except Exception:
        logging.exception('Job %s failed', job_id)
        job.update(status='error', error=('Bộ lọc AI chưa khả dụng. Hãy chọn Giấy trắng hoặc Giữ màu gốc rồi thử lại.'
                   if mode=='ai_clean' else 'Không xử lý được trang. Hãy kiểm tra bốn góc cắt hoặc thử lại.'))
    finally:
        LOCK.release()


@app.get('/api/health')
def health():
    return {'status': 'error' if MODEL_ERROR else ('ready' if MODEL is not None else 'loading'),
            'model': MODEL_NAME, 'device': 'gpu:0', 'busy': LOCK.locked(),
            'quality_configured':False, 'scan_without_ocr':True, 'gpu':GPU.snapshot(),
            'docshadow_ready':DOCSHADOW.path.is_file(), 'ai_filter_ready':ai_filter_ready(), 'dewarp_ready':dewarp_ready(),
            'corner_detector':'DocQuadNet-256' if CORNER_MODEL_PATH.is_file() else 'contours',
            'error': 'Không tải được OCR; cần kiểm tra log máy chủ.' if MODEL_ERROR else None}


@app.get('/api/gpu')
def gpu_status():return GPU.snapshot()

@app.post('/api/gpu/sleep')
def gpu_sleep():
    if not GPU.sleep(force=True):raise HTTPException(409,'GPU đang xử lý. Hãy đợi tác vụ hoàn tất.')
    return GPU.snapshot()


@app.post('/api/scan', status_code=202)
async def scan(file: UploadFile = File(...), mode: str = Form('clean'), crop: bool = Form(True), language: str = Form('vi'), engine: str = Form('fast')):
    if engine == 'fast' and MODEL is None:
        raise HTTPException(503, 'OCR đang khởi động hoặc chưa sẵn sàng. Hãy thử lại sau.')
    if mode not in FILTER_MODES:
        raise HTTPException(400, 'Chế độ ảnh không hợp lệ.')
    if language not in {'vi', 'general'}:
        raise HTTPException(400, 'Ngôn ngữ không hợp lệ.')
    if engine not in {'fast','none'}:
        raise HTTPException(400, 'Chế độ OCR không hợp lệ.')
    raw = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, 'Ảnh tối đa 25 MB.')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > Image.MAX_IMAGE_PIXELS:
                raise HTTPException(413, 'Ảnh tối đa 32 megapixel.')
            image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, 'Hãy chọn ảnh JPG, PNG hoặc HEIC hợp lệ.')
    return enqueue(raw, mode, crop, language, engine)


def enqueue(raw, mode, crop, language, engine, points=None, rotation=0, dewarp=False, source_id=None):
    if engine == 'fast' and MODEL is None:
        raise HTTPException(503, 'OCR đang khởi động. Bạn vẫn có thể quét khi tắt OCR.')
    if not LOCK.acquire(blocking=False):
        raise HTTPException(429, 'Máy chủ đang xử lý một trang khác. Hãy thử lại sau.')
    job_id = uuid.uuid4().hex
    try:
        (DATA / job_id).mkdir(mode=0o700)
        JOBS[job_id] = {'id': job_id, 'status': 'queued'}
        POOL.submit(run_job, job_id, raw, mode, crop, language, engine, points, rotation, dewarp, source_id)
    except Exception:
        LOCK.release()
        raise
    return {'id': job_id, 'status': 'queued'}


class PageEdit(BaseModel):
    points: list[list[float]] | None = None
    rotation: Literal[0,90,180,270] = 0
    mode: Literal['original','clean','bw','color','ai_clean','docshadow'] = 'clean'
    ocr: bool = False
    dewarp: bool = False


class DocumentRequest(BaseModel):
    title: str = Field(default='Tài liệu scan', min_length=1, max_length=120)
    pages: list[str] = Field(min_length=1, max_length=30)


def prepare_page(raw):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height > Image.MAX_IMAGE_PIXELS:
                raise HTTPException(413, 'Ảnh tối đa 32 megapixel.')
            source = ImageOps.exif_transpose(source).convert('RGB')
            source.thumbnail((3600,3600))
            image = cv2.cvtColor(np.asarray(source), cv2.COLOR_RGB2BGR)
    except HTTPException:
        raise
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):
        raise HTTPException(400, 'Ảnh không hợp lệ. Hãy chọn JPG, PNG hoặc HEIC.')
    page_id = uuid.uuid4().hex
    directory = DATA/page_id
    directory.mkdir(mode=0o700)
    cv2.imwrite(str(directory/'original.jpg'), image, [cv2.IMWRITE_JPEG_QUALITY,98])
    # Suggest corners on the exact canonical pixels used for later edits/redetection.
    image=cv2.imread(str(directory/'original.jpg'))
    preview = Image.fromarray(cv2.cvtColor(image,cv2.COLOR_BGR2RGB))
    preview.thumbnail((1200,1200))
    preview.save(directory/'preview.jpg',quality=90)
    h,w = image.shape[:2]
    corners,detector_info = suggest_corners(image)
    normalized = (np.clip(corners/[w-1,h-1],0,1).tolist() if corners is not None
                  else [[0,0],[1,0],[1,1],[0,1]])
    result = {'id':page_id,'status':'prepared','width':w,'height':h,
              'corners':normalized,'detected':corners is not None,
              'preview':f'/api/jobs/{page_id}/preview.jpg', **detector_info}
    (directory/'result.json').write_text(json.dumps(result),encoding='utf-8')
    JOBS[page_id] = result
    return result


@app.post('/api/prepare', status_code=201)
async def prepare(file: UploadFile = File(...)):
    raw = await file.read(MAX_BYTES+1)
    await file.close()
    if len(raw)>MAX_BYTES:
        raise HTTPException(413,'Mỗi ảnh tối đa 25 MB.')
    async with PREPARE_LIMIT:
        return await asyncio.to_thread(prepare_page,raw)


@app.post('/api/pages/{page_id}/detect')
async def redetect(page_id: str):
    page=get_job(page_id)
    if page.get('status')!='prepared':raise HTTPException(400,'Hãy chọn một trang nguồn.')
    def run():
        image=cv2.imread(str(DATA/page_id/'original.jpg'))
        if image is None:raise HTTPException(404,'Ảnh nguồn không còn.')
        h,w=image.shape[:2];corners,info=suggest_corners(image)
        page.update(info,corners=np.clip(corners/[w-1,h-1],0,1).tolist() if corners is not None else [[0,0],[1,0],[1,1],[0,1]],detected=corners is not None)
        (DATA/page_id/'result.json').write_text(json.dumps(page),encoding='utf-8')
        return page
    async with PREPARE_LIMIT:return await asyncio.to_thread(run)



@app.post('/api/pages/{page_id}/variants')
async def page_variants(page_id:str,edit:PageEdit):
    page=get_job(page_id)
    if page.get('status')!='prepared':raise HTTPException(400,'Hãy chọn trang nguồn.')
    points=validate_points(edit.points)
    if not LOCK.acquire(blocking=False):raise HTTPException(429,'Máy đang xử lý trang khác. Hãy thử lại sau.')
    def run():
        try:
            def load():
                image=cv2.imread(str(DATA/page_id/'original.jpg'))
                if image is None:raise ValueError('Missing page')
                image,_=geometry(image,points,edit.rotation)
                return flatten_page(image) if edit.dewarp else image
            manifest=ensure_variants(DATA/page_id,load,points,edit.rotation,edit.dewarp,enhance,ai_filter_ready,edit.mode)
            return {'variants':variant_urls(page_id,manifest),'key':manifest['key']}
        finally:LOCK.release()
    return await asyncio.shield(asyncio.create_task(asyncio.to_thread(run)))

class VariantSource(BaseModel):
    source_id: str | None = Field(default=None,pattern=r'^[0-9a-f]{32}$')

@app.post('/api/jobs/{job_id}/variants')
async def backfill_variants(job_id:str,request:VariantSource):
    base=get_job(job_id)
    if base.get('status')!='done' or base.get('type')=='document':raise HTTPException(400,'Hãy chọn trang đã xử lý.')
    if base.get('variants') and all(mode in base['variants'] for mode in FILTER_MODES):return base
    source_id=request.source_id
    if source_id and get_job(source_id).get('status')!='prepared':raise HTTPException(400,'Trang nguồn không hợp lệ.')
    if not LOCK.acquire(blocking=False):raise HTTPException(429,'Máy đang bận. Hãy thử lại sau.')
    def run():
        try:
            source=DATA/(source_id or job_id);dest=DATA/job_id
            def load():
                image=cv2.imread(str(source/'original.jpg'))
                image,_=geometry(image,base.get('crop_points'),base.get('rotation',0),base.get('cropped',False) and base.get('crop_points') is None)
                return flatten_page(image) if base.get('dewarp') else image
            manifest=ensure_variants(source,load,base.get('crop_points'),base.get('rotation',0),bool(base.get('dewarp')),enhance,ai_filter_ready,base['mode'])
            key=manifest['key']
            if source!=dest:
                names=[f'base-{key}.png']+[f'{prefix}-{key}-{mode}.jpg' for mode in manifest['modes'] for prefix in ['filter','thumb']]
                for name in names:shutil.copyfile(source/name,dest/name)
            updated={**base,'variants':variant_urls(job_id,manifest),'filter_cache_key':key}
            (dest/'result.json').write_text(json.dumps(updated,ensure_ascii=False),encoding='utf-8');JOBS[job_id]=updated;return updated
        finally:LOCK.release()
    return await asyncio.shield(asyncio.create_task(asyncio.to_thread(run)))


class FilterChoice(BaseModel):
    mode: Literal['original','clean','color','bw','ai_clean','docshadow']

@app.post('/api/jobs/{job_id}/filter')
def choose_filter(job_id:str,choice:FilterChoice):
    base=get_job(job_id)
    if base.get('status')!='done' or not base.get('variants'):raise HTTPException(400,'Hãy xử lý trang trước.')
    if choice.mode not in base['variants']:raise HTTPException(409,'Bộ lọc này chưa sẵn sàng.')
    if base['mode']==choice.mode:return base
    key=base['filter_cache_key'];new_id=uuid.uuid4().hex;dest=DATA/new_id;dest.mkdir(mode=0o700)
    try:
        for mode in base['variants']:
            for prefix in ['filter','thumb']:
                name=f'{prefix}-{key}-{mode}.jpg';shutil.copyfile(DATA/job_id/name,dest/name)
        for name in ['original.jpg','text.txt','document.md']:shutil.copyfile(DATA/job_id/name,dest/name)
        if (DATA/job_id/f'base-{key}.png').exists():shutil.copyfile(DATA/job_id/f'base-{key}.png',dest/f'base-{key}.png')
        shutil.copyfile(dest/f'filter-{key}-{choice.mode}.jpg',dest/'scan.jpg')
        image=cv2.imread(str(dest/'scan.jpg'));searchable_pdf(image,base['lines'],dest/'document.pdf')
        result={**base,'id':new_id,'mode':choice.mode,'variants':variant_urls(new_id,{'key':key,'modes':list(base['variants'])}),
                'filter_reused':True,'image':f'/api/jobs/{new_id}/scan.jpg','original':f'/api/jobs/{new_id}/original.jpg',
                'pdf':f'/api/jobs/{new_id}/document.pdf','txt':f'/api/jobs/{new_id}/text.txt','markdown':f'/api/jobs/{new_id}/document.md'}
        (dest/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8');JOBS[new_id]=result;return result
    except Exception:
        shutil.rmtree(dest,ignore_errors=True);raise

@app.post('/api/pages/{page_id}/preview')
async def filter_preview(page_id: str, edit: PageEdit):
    page=get_job(page_id)
    if page.get('status')!='prepared':raise HTTPException(400,'Hãy chọn một trang nguồn.')
    points=validate_points(edit.points)
    needs_gpu=edit.mode=='ai_clean' or edit.dewarp
    if needs_gpu and not LOCK.acquire(blocking=False):
        raise HTTPException(429,'Máy đang xử lý OCR/bộ lọc AI. Hãy thử lại sau.')
    def run():
        try:
            image=cv2.imread(str(DATA/page_id/'original.jpg'))
            if image is None:raise HTTPException(404,'Ảnh nguồn không còn.')
            image,_=geometry(image,points,edit.rotation)
            if edit.dewarp:image=flatten_page(image)
            image=enhance(image,edit.mode)
            h,w=image.shape[:2];scale=min(1,1200/max(h,w))
            image=cv2.resize(image,(round(w*scale),round(h*scale)))
            ok,data=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,93])
            if not ok:raise ValueError('Cannot encode preview')
            return data.tobytes()
        except HTTPException:raise
        except Exception:
            logging.exception('Filter preview failed')
            raise HTTPException(503,'Không tạo được bản xem trước. Hãy thử bộ lọc khác hoặc thử lại.')
        finally:
            if needs_gpu:LOCK.release()
    future=asyncio.create_task(asyncio.to_thread(run))
    data=await asyncio.shield(future)
    return Response(data,media_type='image/jpeg')


@app.post('/api/pages/{page_id}/process', status_code=202)
def process_page(page_id: str, edit: PageEdit):
    page = get_job(page_id)
    if page.get('status') != 'prepared':
        raise HTTPException(400,'Đây không phải trang nguồn. Hãy thêm ảnh lại.')
    points = validate_points(edit.points)
    source = DATA/page_id/'original.jpg'
    if not source.is_file():
        raise HTTPException(404,'Ảnh nguồn không còn. Hãy thêm ảnh lại.')
    return enqueue(source.read_bytes(),edit.mode,False,'vi','fast' if edit.ocr else 'none',points,edit.rotation,edit.dewarp,page_id)


def assemble_document(request):
    pages = []
    for page_id in request.pages:
        page = get_job(page_id)
        if page.get('status')!='done' or not (DATA/page_id/'scan.jpg').is_file():
            raise HTTPException(400,'Chỉ có thể ghép những trang đã xử lý xong.')
        pages.append(page)
    document_id = uuid.uuid4().hex
    directory = DATA/document_id
    directory.mkdir(mode=0o700)
    title = request.title.strip() or 'Tài liệu scan'
    pdf = canvas.Canvas(str(directory/'document.pdf'))
    pdf.setTitle(title)
    text = []
    for page in pages:
        image = cv2.imread(str(DATA/page['id']/'scan.jpg'))
        if image is None:
            raise HTTPException(404,'Không còn bản scan. Hãy xử lý trang lại.')
        draw_pdf_page(pdf,image,page.get('lines',[]))
        text.append(page.get('text',''))
    pdf.save()
    plain = '\n\n\f\n\n'.join(text)
    (directory/'text.txt').write_text(plain,encoding='utf-8')
    result = {'id':document_id,'status':'done','type':'document','title':title,
              'page_count':len(pages),'pages':request.pages,'text':plain,
              'ocr_pages':sum(p.get('engine')=='fast' for p in pages),
              'pdf':f'/api/jobs/{document_id}/document.pdf',
              'txt':f'/api/jobs/{document_id}/text.txt'}
    (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    JOBS[document_id] = result
    return result


@app.post('/api/documents', status_code=201)
async def document(request: DocumentRequest):
    return await asyncio.to_thread(assemble_document,request)


@app.get('/api/jobs/{job_id}')
def get_job(job_id: str):
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise HTTPException(404)
    if job_id in JOBS:
        return JOBS[job_id]
    saved = DATA / job_id / 'result.json'
    if saved.is_file():
        return json.loads(saved.read_text(encoding='utf-8'))
    raise HTTPException(404, 'Không tìm thấy tài liệu.')


@app.get('/api/jobs/{job_id}/{filename}')
def download(job_id: str, filename: str):
    get_job(job_id)
    if filename not in {'scan.jpg', 'original.jpg', 'preview.jpg', 'document.pdf', 'text.txt','document.md'} and not re.fullmatch(r'(filter|thumb)-[0-9a-f]{16}-(original|clean|color|bw|ai_clean|docshadow)\.jpg',filename):
        raise HTTPException(404)
    path = DATA / job_id / filename
    if not path.is_file():
        raise HTTPException(404)
    types = {'jpg': 'image/jpeg', 'pdf': 'application/pdf', 'txt': 'text/plain; charset=utf-8', 'md':'text/markdown; charset=utf-8'}
    return FileResponse(path, media_type=types[path.suffix[1:]],
                        filename=f'tailscan-{job_id[:8]}{path.suffix}' if filename in {'document.pdf','text.txt'} else None)


from document_library import library_router
app.include_router(library_router(ROOT,DATA,get_job,prepare_page))

app.mount('/', StaticFiles(directory=ROOT / 'web', html=True), name='web')
