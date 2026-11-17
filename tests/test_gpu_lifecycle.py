import shutil,socket,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from gpu_runtime import GPURuntime

def free_port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

def test_idle_exit_and_wake_without_gpu(tmp_path):
    shutil.copyfile(Path(__file__).resolve().parents[1]/'server/gpu_worker_entry.py',tmp_path/'gpu_worker_entry.py')
    (tmp_path/'fake_service.py').write_text("from fastapi import FastAPI\napp=FastAPI()\n@app.get('/health')\ndef health():return {'status':'ready','dewarp_ready':True}\n")
    runtime=GPURuntime(tmp_path,idle_seconds=.8)
    runtime.spec={kind:(sys.executable,tmp_path,'fake_service:app',free_port()) for kind in ['ocr','images']}
    runtime.start()
    try:
        with runtime.lease('images'):
            first=runtime.snapshot()['pids']['images']
            assert runtime.sleep(force=True) is False
            assert runtime.snapshot()['state']=='awake'
        deadline=time.monotonic()+8
        while runtime.snapshot()['state']!='sleeping' and time.monotonic()<deadline:time.sleep(.1)
        assert runtime.snapshot()['state']=='sleeping' and not runtime.snapshot()['pids']
        with runtime.lease('images'):assert runtime.snapshot()['pids']['images']!=first
        assert runtime.sleep(force=True)
    finally:runtime.close()
