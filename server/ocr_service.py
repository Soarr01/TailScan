"""Private Paddle worker. Its process lifetime owns every Paddle CUDA allocation."""
import os
os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK','True')
os.environ.setdefault('FLAGS_allocator_strategy','auto_growth')
import asyncio,json,logging,threading,faulthandler,signal
from pathlib import Path
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import cv2,numpy as np
from fastapi import FastAPI,HTTPException,Request
MODEL=None;ERROR=None;LOCK=threading.Lock();POOL=ThreadPoolExecutor(max_workers=1)
PHASE='loading'
faulthandler.register(signal.SIGUSR1,all_threads=True)
def initialize():
    global MODEL,ERROR,PHASE
    try:
        import paddle
        from paddleocr import PaddleOCRVL
        paddle.disable_static();paddle.set_device('gpu:0')
        model=PaddleOCRVL(pipeline_version='v1.6',vl_rec_model_dir=os.environ.get('TAILSCAN_OCR_MODEL_DIR',str(Path(__file__).parent/'models/paddleocr-vl16')),device='gpu:0',
            use_doc_orientation_classify=False,use_doc_unwarping=False,use_chart_recognition=False,use_seal_recognition=False,use_queues=False)
        paddle.device.cuda.empty_cache();MODEL=model;PHASE='idle'
    except Exception:
        ERROR=True;logging.exception('Paddle worker initialization failed')
@asynccontextmanager
async def lifespan(app):
    POOL.submit(initialize);yield
app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
@app.get('/health')
def health():return {'status':'error' if ERROR else 'ready' if MODEL is not None else 'loading','busy':LOCK.locked(),'phase':PHASE}
def predict(raw):
    global PHASE
    import paddle
    try:
        PHASE='decoding'
        paddle.disable_static();paddle.set_device('gpu:0')
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        if image is None or image.shape[0]*image.shape[1]>32_000_000:raise ValueError('Invalid OCR image')
        results=[];PHASE='predicting'
        for result in MODEL.predict(image,max_pixels=1003520,max_new_tokens=2048):
            payload=result.json
            if callable(payload):payload=payload()
            if isinstance(payload,str):payload=json.loads(payload)
            results.append(payload)
        PHASE='serializing';return results
    finally:paddle.device.cuda.empty_cache();PHASE='idle';LOCK.release()
@app.post('/predict')
async def process(request:Request):
    if MODEL is None:raise HTTPException(503,'OCR is loading')
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>100*1024*1024:raise HTTPException(413)
    if not LOCK.acquire(blocking=False):raise HTTPException(429,'OCR busy')
    return await asyncio.shield(asyncio.wrap_future(POOL.submit(predict,bytes(raw))))
