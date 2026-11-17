"""Linux child entry: do not leave CUDA workers behind if their parent crashes."""
import ctypes,os,signal,sys
expected_parent=int(sys.argv[1])
if ctypes.CDLL('libc.so.6',use_errno=True).prctl(1,signal.SIGKILL,0,0,0)!=0:
    raise OSError(ctypes.get_errno(),'Cannot set worker parent-death signal')
if os.getppid()!=expected_parent:raise SystemExit(1)
os.execv(sys.executable,[sys.executable,'-m','uvicorn',*sys.argv[2:]])
