"""Pinned ONNX corner detectors. Pure CPU inference, no OCR/GPU dependency."""
from pathlib import Path
import cv2
import numpy as np
import onnxruntime as ort

def order_quad(points):
    p=np.asarray(points,dtype=np.float32)
    if p.shape!=(4,2) or not np.isfinite(p).all():return None
    center=p.mean(0)
    p=p[np.argsort(np.arctan2(p[:,1]-center[1],p[:,0]-center[0]))]
    p=np.roll(p,-int(np.argmin(p.sum(1))),axis=0)
    if not cv2.isContourConvex(p) or abs(cv2.contourArea(p))<1:return None
    return p

class CornerModel:
    def __init__(self,path,kind='docaligner',protect_border=False):
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        self.session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        self.kind=kind;self.name=self.session.get_inputs()[0].name
        self.minus_one_one='fastvit' in Path(path).name.lower()
        self.protect_border=protect_border
    def predict(self,image):
        h,w=image.shape[:2]
        if self.kind=='docquad':
            scale=min(256/w,256/h);nw,nh=round(w*scale),round(h*scale)
            ox,oy=(256-nw)//2,(256-nh)//2
            small=np.zeros((256,256,3),np.uint8)
            small[oy:oy+nh,ox:ox+nw]=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2RGB),(nw,nh))
        else:
            small=cv2.resize(cv2.cvtColor(image,cv2.COLOR_BGR2RGB),(256,256));scale=None
        tensor=np.ascontiguousarray(small.transpose(2,0,1)[None],dtype=np.float32)/255
        if self.minus_one_one:tensor=tensor*2-1
        outputs=self.session.run(None,{self.name:tensor})
        heat=outputs[0][0]
        if self.kind=='docquad':heat=1/(1+np.exp(-np.clip(heat,-60,60)))
        points=[];peaks=[]
        for channel in heat:
            peak=float(channel.max());peaks.append(peak)
            y,x=np.unravel_index(np.argmax(channel),channel.shape)
            # Local weighted centroid avoids fusing distinct heatmap peaks.
            x0,x1=max(0,x-4),min(channel.shape[1],x+5)
            y0,y1=max(0,y-4),min(channel.shape[0],y+5)
            patch=channel[y0:y1,x0:x1].copy();patch[patch<peak*.3]=0
            yy,xx=np.mgrid[y0:y1,x0:x1];total=patch.sum()
            cx=float((patch*xx).sum()/total) if total else x
            cy=float((patch*yy).sum()/total) if total else y
            if scale is None:points.append([cx*w/channel.shape[1],cy*h/channel.shape[0]])
            else:points.append([(cx*256/channel.shape[1]-ox)/scale,(cy*256/channel.shape[0]-oy)/scale])
        points=order_quad(points)
        valid=points is not None and min(peaks)>=.3
        mask_iou=None
        if self.kind=='docquad' and points is not None:
            probability=1/(1+np.exp(-np.clip(outputs[1][0,0],-60,60)))
            predicted=(probability>.5).astype(np.uint8)
            quad_mask=np.zeros_like(predicted)
            mapped=(points*scale+[ox,oy])*(predicted.shape[1]/256)
            cv2.fillConvexPoly(quad_mask,np.rint(mapped).astype(np.int32),1)
            union=np.logical_or(predicted,quad_mask).sum()
            mask_iou=float(np.logical_and(predicted,quad_mask).sum()/max(1,union))
            # Accept a plausible suggestion when segmentation supports an obscured corner.
            valid=min(peaks)>=.02 and np.mean(peaks)>=.4 and mask_iou>=.5
        if points is not None:
            points[:,0]=np.clip(points[:,0],0,w-1);points[:,1]=np.clip(points[:,1],0,h-1)
            valid=valid and cv2.isContourConvex(points) and cv2.contourArea(points)/(w*h)>=.08
        extended=False
        if valid and self.protect_border:
            points,extended=extend_visible_paper(image,points)
        return {'corners':points.tolist() if points is not None else None,'peaks':peaks,
                'mask_iou':mask_iou,'detected':bool(valid),'tentative':min(peaks)<.3,
                'border_extended':extended}


def extend_visible_paper(image,points):
    """Conservative continuation when a predicted edge cuts across visible paper.

    A clipped photograph has no observable page corner at that side. Prefer
    retaining paper to the photo boundary over silently trimming content.
    """
    h,w=image.shape[:2];scale=min(1,640/max(h,w))
    small=cv2.resize(image,(round(w*scale),round(h*scale)))
    lab=cv2.cvtColor(small,cv2.COLOR_BGR2LAB).astype(np.float32)
    p=np.float32(points)*scale;sh,sw=small.shape[:2]
    inside=np.zeros((sh,sw),np.uint8);cv2.fillConvexPoly(inside,np.rint(p).astype(np.int32),1)
    colors=lab[inside>0]
    if len(colors)<100:return points,False
    bright=colors[colors[:,0]>=np.percentile(colors[:,0],70)]
    prototype=np.median(bright,axis=0)
    matches=(lab[:,:,0]>=max(100,prototype[0]-40))&(np.linalg.norm(lab[:,:,1:]-prototype[1:],axis=2)<16)
    changed=False
    def intersect(a,b,axis,value):
        delta=b[axis]-a[axis]
        if abs(delta)<1e-5:return b.copy()
        return a+(b-a)*((value-a[axis])/delta)
    for side in ['bottom','top','left','right']:
        q=p.copy()
        if side=='bottom':q[3]=intersect(p[0],p[3],1,sh-1);q[2]=intersect(p[1],p[2],1,sh-1)
        if side=='top':q[0]=intersect(p[3],p[0],1,0);q[1]=intersect(p[2],p[1],1,0)
        if side=='left':q[0]=intersect(p[1],p[0],0,0);q[3]=intersect(p[2],p[3],0,0)
        if side=='right':q[1]=intersect(p[0],p[1],0,sw-1);q[2]=intersect(p[3],p[2],0,sw-1)
        q[:,0]=np.clip(q[:,0],0,sw-1);q[:,1]=np.clip(q[:,1],0,sh-1)
        if not cv2.isContourConvex(q) or cv2.contourArea(q)<cv2.contourArea(p)*1.02:continue
        old=np.zeros((sh,sw),np.uint8);new=old.copy()
        cv2.fillConvexPoly(old,np.rint(p).astype(np.int32),1);cv2.fillConvexPoly(new,np.rint(q).astype(np.int32),1)
        extra=(new>0)&(old==0)
        if extra.sum()<sw*sh*.008:continue
        if float(matches[extra].mean())>=.82:
            p=q;changed=True
    result=p/scale;result[:,0]=np.clip(result[:,0],0,w-1);result[:,1]=np.clip(result[:,1],0,h-1)
    return np.float32(result),changed
