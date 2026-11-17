"""UVDoc backward-grid inference, retaining source pixels via OpenCV remap."""
import sys,time
from pathlib import Path
import cv2,numpy as np,torch

class UVDocEngine:
    def __init__(self, root):
        root=Path(root)/'uvdoc'
        sys.path.insert(0,str(root))
        from model import UVDocnet
        self.model=UVDocnet(num_filter=32,kernel_size=5)
        checkpoint=torch.load(root/'best_model.pkl',map_location='cpu',weights_only=True)
        self.model.load_state_dict(checkpoint['model_state'],strict=True)
        self.model=self.model.eval().cuda()

    @torch.inference_mode()
    def dewarp(self,image):
        h,w=image.shape[:2]
        rgb=cv2.cvtColor(cv2.resize(image,(488,712)),cv2.COLOR_BGR2RGB)
        tensor=torch.from_numpy(rgb.transpose(2,0,1).copy()).unsqueeze(0).float().cuda()/255
        grid,_=self.model(tensor)
        grid=grid[0].permute(1,2,0).cpu().numpy()
        if not np.isfinite(grid).all():raise ValueError('Invalid dewarping grid')
        # UVDoc uses bilinear align_corners=True. OpenCV resize uses a different
        # pixel-center convention, so construct the interpolation coordinates.
        gh,gw=grid.shape[:2]
        dense=torch.nn.functional.interpolate(torch.from_numpy(grid.transpose(2,0,1).copy())[None],
            size=(h,w),mode='bilinear',align_corners=True)[0].permute(1,2,0).numpy()
        mx=(dense[:,:,0]+1)*(w-1)/2;my=(dense[:,:,1]+1)*(h-1)/2
        dx=np.diff(grid,axis=1)[:-1];dy=np.diff(grid,axis=0)[:,:-1]
        jac=dx[:,:,0]*dy[:,:,1]-dx[:,:,1]*dy[:,:,0]
        if np.mean(jac<=0)>.01:raise ValueError('Folded dewarping grid')
        if np.mean(np.abs(grid)>1.15)>.03:raise ValueError('Dewarping grid outside image')
        output=cv2.remap(image,mx,my,cv2.INTER_CUBIC,borderMode=cv2.BORDER_REPLICATE)
        return output,{'grid':((grid+1)/2).round(5).tolist(),'grid_shape':[gh,gw],
                       'fold_fraction':float(np.mean(jac<=0)),'model':'UVDoc'}
