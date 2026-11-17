"""Pinned DocRes photometric enhancement at 512; preserve original resolution."""
import sys
from pathlib import Path
import cv2,numpy as np,torch

class DocResEngine:
    def __init__(self,root):
        self.root=Path(root)
        sys.path.insert(0,str(self.root/'docres'))
        from restormer_arch import Restormer
        torch.set_num_threads(4)
        model=Restormer(inp_channels=6,out_channels=3,dim=48,num_blocks=[2,3,3,4],num_refinement_blocks=4,
            heads=[1,2,4,8],ffn_expansion_factor=2.66,bias=False,LayerNorm_type='WithBias',dual_pixel_task=True)
        state=torch.load(self.root/'models/docres.pkl',map_location='cpu',weights_only=True)['model_state']
        model.load_state_dict({k.removeprefix('module.'):v for k,v in state.items()},strict=True)
        self.model=model.half().cuda().eval()
    def enhance(self,image):
        h,w=image.shape[:2];small=cv2.resize(image,(512,512))
        prompt_source=cv2.resize(image,(1024,1024));planes=[]
        for plane in cv2.split(prompt_source):
            bg=cv2.medianBlur(cv2.dilate(plane,np.ones((7,7),np.uint8)),21)
            diff=255-cv2.absdiff(plane,bg)
            planes.append(cv2.normalize(diff,None,0,255,cv2.NORM_MINMAX))
        prompt=cv2.resize(cv2.merge(planes),(512,512))
        tensor=np.concatenate((small,prompt),axis=2).transpose(2,0,1)[None]/255
        with torch.inference_mode():pred=self.model(torch.from_numpy(tensor).half().cuda()).clamp(0,1)
        pred=pred[0].float().cpu().numpy().transpose(1,2,0)*255
        if not np.isfinite(pred).all():raise RuntimeError('Nonfinite restoration')
        gain=np.clip(pred/np.maximum(small.astype(np.float32),1),.3,4)
        gain=cv2.resize(gain,(w,h),interpolation=cv2.INTER_LINEAR)
        return np.clip(image.astype(np.float32)*gain,0,255).astype(np.uint8)
