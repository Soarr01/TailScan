"""Recompute the historical image metrics for a supplied reference/prediction."""
import argparse,json
import cv2,numpy as np
from skimage.metrics import structural_similarity

def measure(reference,prediction):
    if reference is None or prediction is None:raise ValueError('Cannot decode input image')
    if reference.shape!=prediction.shape:raise ValueError('Input dimensions must match; no implicit resizing')
    mse=np.mean((prediction.astype(float)-reference.astype(float))**2)
    foreground=cv2.cvtColor(reference,cv2.COLOR_BGR2GRAY)<200
    gray=cv2.cvtColor(prediction,cv2.COLOR_BGR2GRAY)
    return {'psnr':float(10*np.log10(255**2/max(mse,1e-10))),
        'ssim':float(structural_similarity(reference,prediction,channel_axis=2,data_range=255)),
        'dark_stroke_recall':float((gray[foreground]<200).mean()),
        'background_gray_std':float(gray[~foreground].std())}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('reference');parser.add_argument('prediction');args=parser.parse_args()
    print(json.dumps(measure(cv2.imread(args.reference),cv2.imread(args.prediction)),indent=2))
