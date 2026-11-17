"""Own GPU workers as child processes; exiting them releases CUDA contexts."""
import contextlib,json,logging,os,signal,socket,subprocess,sys,threading,time,urllib.request
from pathlib import Path
from types import SimpleNamespace
import cv2

HTTP=urllib.request.build_opener(urllib.request.ProxyHandler({}))
class GPURuntime:
    def __init__(self,root,busy=lambda:False,idle_seconds=None):
        self.root=Path(root);self.busy=busy;self.idle_seconds=float(idle_seconds or os.environ.get('TAILSCAN_GPU_IDLE_SECONDS','300'))
        self.lock=threading.RLock();self.start_lock=threading.RLock();self.active={'ocr':0,'images':0};self.processes={};self.states={};self.last_used=time.monotonic();self.closed=False
        self.spec={
            'ocr':(os.environ.get('TAILSCAN_OCR_PYTHON',sys.executable),self.root,'ocr_service:app',int(os.environ.get('TAILSCAN_OCR_PORT','8790'))),
            'images':(os.environ.get('TAILSCAN_IMAGE_PYTHON',str(self.root.parent/'.venv-images/bin/python')),Path(os.environ.get('TAILSCAN_IMAGE_LAB',str(self.root/'image_worker'))).resolve(),'docres_service:app',int(os.environ.get('TAILSCAN_IMAGES_PORT','8791')))}
    def start(self):threading.Thread(target=self._watch,daemon=True,name='gpu-idle-watch').start()
    def url(self,kind):return f'http://127.0.0.1:{self.spec[kind][3]}'
    def _stop(self,kind,grace=8):
        process=self.processes.pop(kind,None)
        if process and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
        self.states[kind]='sleeping'
    def _ensure(self,kind):
        with self.start_lock:
            process=self.processes.get(kind)
            if process is None or process.poll() is not None:
                # Paddle startup has a larger memory peak than steady inference.
                # Free the small image context before a cold OCR initialization.
                if kind=='ocr':
                    with self.lock:
                        if not self.active['images']:self._stop('images')
                python,cwd,module,port=self.spec[kind]
                try:
                    connection=socket.create_connection(('127.0.0.1',port),timeout=.3)
                except OSError:pass
                else:
                    connection.close();raise RuntimeError(f'Unmanaged service occupies GPU worker port {port}')
                env={**os.environ,'TAILSCAN_WAIT_PADDLE':'0','USE_TF':'0'}
                with (self.root/f'gpu-{kind}.log').open('ab') as log:
                    process=subprocess.Popen([python,str(self.root/'gpu_worker_entry.py'),str(os.getpid()),module,'--host','127.0.0.1','--port',str(port)],cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
                self.processes[kind]=process;self.states[kind]='waking'
            for _ in range(300):
                if process.poll() is not None:
                    self.states[kind]='error';raise RuntimeError(f'{kind} worker stopped; check GPU log')
                try:
                    with HTTP.open(self.url(kind)+'/health',timeout=1) as r:health=json.load(r)
                    if health['status']=='ready' and (kind!='images' or health.get('dewarp_ready') or health.get('dewarp_error')):
                        self.states[kind]='awake';return
                    if health['status']=='error':
                        self.states[kind]='error';raise RuntimeError(f'{kind} model initialization failed')
                except (OSError,ValueError):pass
                time.sleep(1)
            self.states[kind]='error';raise TimeoutError(f'{kind} model did not finish loading')
    def abort(self,kind):
        with self.start_lock,self.lock:
            process=self.processes.get(kind)
            if kind=='ocr' and process and process.poll() is None:
                os.kill(process.pid,signal.SIGUSR1)
                time.sleep(.1)
            self._stop(kind,grace=3)
    @contextlib.contextmanager
    def lease(self,kind):
        with self.lock:self.active[kind]+=1;self.last_used=time.monotonic()
        try:
            self._ensure(kind);yield self.url(kind)
        finally:
            with self.lock:self.active[kind]-=1;self.last_used=time.monotonic()
    def sleep(self,force=False):
        with self.start_lock,self.lock:
            if any(self.active.values()) or self.busy():return False
            if not force and time.monotonic()-self.last_used<self.idle_seconds:return False
            for kind in self.spec:self._stop(kind)
            return True
    def _watch(self):
        while not self.closed:
            time.sleep(min(5,self.idle_seconds/4))
            try:self.sleep()
            except Exception:logging.exception('GPU sleep check failed')
    def snapshot(self):
        with self.lock:
            states={k:self.states.get(k,'sleeping') if self.processes.get(k) and self.processes[k].poll() is None else 'sleeping' for k in self.spec}
            state='waking' if 'waking' in states.values() else 'awake' if 'awake' in states.values() else 'error' if 'error' in states.values() else 'sleeping'
            return {'state':state,'workers':states,'pids':{k:p.pid for k,p in self.processes.items() if p.poll() is None},'active':sum(self.active.values()),'idle_seconds':round(time.monotonic()-self.last_used,1),'sleep_after_seconds':self.idle_seconds}
    def close(self):
        self.closed=True
        with self.start_lock,self.lock:
            for kind in self.spec:self._stop(kind)

class OCRProxy:
    def __init__(self,runtime):self.runtime=runtime
    def ensure_ready(self):
        with self.runtime.lease('ocr'):pass
    def predict(self,image,**options):
        ok,data=cv2.imencode('.png',image)
        if not ok:raise RuntimeError('Cannot encode OCR input')
        with self.runtime.lease('ocr') as url:
            request=urllib.request.Request(url+'/predict',data=data.tobytes(),headers={'Content-Type':'image/png'})
            try:
                with HTTP.open(request,timeout=180) as r:results=json.load(r)
            except Exception:
                self.runtime.abort('ocr');raise
        return [SimpleNamespace(json=result) for result in results]
