import sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from filter_cache import ensure_variants,geometry_key,MODES

def test_reuses_geometry_and_only_adds_missing_filters(tmp_path):
    image=np.full((60,80,3),240,np.uint8);image[12:45,20:50]=25
    loads=[];calls=[]
    def load():loads.append(1);return image
    def enhance(pixels,mode):calls.append(mode);return pixels
    points=[[0,0],[1,0],[1,1],[0,1]]
    first=ensure_variants(tmp_path,load,points,0,False,enhance,lambda:False)
    assert set(first['modes'])==set(MODES)-{'ai_clean'}
    second=ensure_variants(tmp_path,load,points,0,False,enhance,lambda:True)
    assert set(second['modes'])==set(MODES) and len(loads)==1
    assert calls.count('ai_clean')==1
    total=len(calls)
    ensure_variants(tmp_path,load,points,0,False,enhance,lambda:True,required='docshadow')
    assert len(calls)==total and len(loads)==1
    ensure_variants(tmp_path,load,points,90,False,enhance,lambda:True)
    assert len(loads)==2
    assert geometry_key(points,0,False)!=geometry_key(points,0,True)
