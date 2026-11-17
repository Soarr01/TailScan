"""Document display filters; all operate on original pixels, no text generation."""
import cv2
import numpy as np

def legacy_clean(image):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.divide(gray,cv2.GaussianBlur(gray,(0,0),25),scale=245),cv2.COLOR_GRAY2BGR)

def paper_color(image):
    h,w=image.shape[:2];scale=min(1,768/max(h,w))
    small=cv2.resize(image,(max(20,round(w*scale)),max(20,round(h*scale))))
    gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
    # Closing removes dark strokes before illumination estimation, avoiding text halos.
    background=cv2.morphologyEx(gray,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(31,31)))
    background=cv2.medianBlur(background,31)
    background=cv2.GaussianBlur(background,(0,0),5)
    background=cv2.resize(background,(w,h),interpolation=cv2.INTER_CUBIC).astype(np.float32)
    hsv=cv2.cvtColor(small,cv2.COLOR_BGR2HSV)
    whites=small[(gray>=np.percentile(gray,75))&(hsv[:,:,1]<70)]
    balance=np.ones(3,np.float32)
    if len(whites)>30:
        median=np.median(whites,axis=0);balance=np.clip(np.max(median)/np.maximum(median,1),.9,1.15)
    corrected=image.astype(np.float32)*balance[None,None,:]
    gain=np.clip(252/np.maximum(background,50),.8,3.2)
    corrected=np.clip(corrected*gain[:,:,None],0,255)
    # Gentle tone curve keeps faint gray marks while whitening flat paper.
    return np.clip((corrected-5)*255/247,0,255).astype(np.uint8)

def paper_gray(image):
    color=paper_color(image)
    gray=cv2.cvtColor(color,cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)

def paper_bw(image):
    gray=cv2.cvtColor(paper_color(image),cv2.COLOR_BGR2GRAY).astype(np.float32)
    window=41
    mean=cv2.boxFilter(gray,-1,(window,window),normalize=True,borderType=cv2.BORDER_REFLECT)
    std=np.sqrt(np.maximum(0,cv2.boxFilter(gray*gray,-1,(window,window),normalize=True)-mean*mean))
    threshold=mean*(1+.12*(std/128-1))
    return cv2.cvtColor(np.where(gray<threshold,0,255).astype(np.uint8),cv2.COLOR_GRAY2BGR)
