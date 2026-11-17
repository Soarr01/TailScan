import os
os.environ.setdefault('CUDA_VISIBLE_DEVICES','0')
os.environ['USE_TF']='0'
import asyncio,io,logging,threading,json,time,urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
import cv2,numpy as np,torch
from PIL import Image
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import Response
from docres_engine import DocResEngine
from uvdoc_engine import UVDocEngine
ROOT=Path(os.environ.get('TAILSCAN_IMAGE_LAB',str(Path(__file__).parent))).resolve();MODEL=None;ERROR=None
DEWARP=None;DEWARP_ERROR=None
LOCK=threading.Lock();POOL=ThreadPoolExecutor(max_workers=1)
Image.MAX_IMAGE_PIXELS=32_000_000
def initialize():
    global MODEL,ERROR,DEWARP,DEWARP_ERROR
    try:
        if os.environ.get('TAILSCAN_WAIT_PADDLE')=='1':
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(360):
                try:
                    with opener.open('http://127.0.0.1:8787/api/health',timeout=2) as r:
                        if json.load(r)['status'] in {'ready','error'}:break
                except Exception:pass
                time.sleep(1)
            else:raise RuntimeError('Main scanner did not finish warming')
        MODEL=DocResEngine(ROOT)
    except Exception:
        ERROR=True;logging.exception('DocRes initialization failed')
    try:
        DEWARP=UVDocEngine(ROOT)
    except Exception:
        DEWARP_ERROR=True;logging.exception('UVDoc initialization failed')
@asynccontextmanager
async def lifespan(app):
    threading.Thread(target=initialize,daemon=True).start()
    yield
app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
@app.get('/health')
def health():return {'status':'error' if ERROR else 'ready' if MODEL else 'loading','busy':LOCK.locked(),'model':'DocRes-appearance-512','dewarp_ready':DEWARP is not None,'dewarp_error':DEWARP_ERROR}
def process(raw,dewarp=False):
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.width*source.height>32_000_000:raise ValueError('Image too large')
            image=cv2.cvtColor(np.asarray(source.convert('RGB')),cv2.COLOR_RGB2BGR)
        output=DEWARP.dewarp(image)[0] if dewarp else MODEL.enhance(image)
        ok,data=cv2.imencode('.png',output)
        if not ok:raise RuntimeError('Encoding failed')
        return data.tobytes()
    finally:
        torch.cuda.empty_cache();LOCK.release()
@app.post('/enhance')
async def enhance(request:Request):return await transform(request,False)

@app.post('/dewarp')
async def dewarp(request:Request):return await transform(request,True)

async def transform(request:Request,dewarp:bool):
    if (DEWARP if dewarp else MODEL) is None:raise HTTPException(503,'Image model is loading')
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>100*1024*1024:raise HTTPException(413)
    if not LOCK.acquire(blocking=False):raise HTTPException(429,'AI filter busy')
    try:
        result=await asyncio.shield(asyncio.wrap_future(POOL.submit(process,bytes(raw),dewarp)))
        return Response(result,media_type='image/png')
    except Exception:
        logging.exception('AI filtering failed');raise HTTPException(500,'AI filter failed')
