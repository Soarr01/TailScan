"""DocShadow SD7K, CPU only, with the evaluated original-resolution gain field."""
import os,threading
from pathlib import Path
import cv2,numpy as np

class DocShadowEngine:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(os.environ.get('TAILSCAN_IMAGE_LAB',str(Path(__file__).parent/'image_worker')))/'docshadow/docshadow_sd7k.onnx';self.session=None;self.lock=threading.Lock()
    def enhance(self,image):
        with self.lock:
            if self.session is None:
                import onnxruntime as ort
                options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
                self.session=ort.InferenceSession(str(self.path),sess_options=options,providers=['CPUExecutionProvider'])
            h,w=image.shape[:2];small=cv2.resize(image,(512,512))
            rgb=cv2.cvtColor(small,cv2.COLOR_BGR2RGB).astype(np.float32)/255
            result=self.session.run(None,{'image':rgb.transpose(2,0,1)[None]})[0][0].transpose(1,2,0)
            if not np.isfinite(result).all():raise RuntimeError('Nonfinite DocShadow output')
            result=cv2.cvtColor(np.clip(result,0,1),cv2.COLOR_RGB2BGR)*255
            gain=np.clip(result/np.maximum(small.astype(np.float32),1),.3,4)
            field=cv2.GaussianBlur(gain,(0,0),5)
            return np.clip(image.astype(np.float32)*cv2.resize(field,(w,h)),0,255).astype(np.uint8)
