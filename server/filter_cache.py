"""Immutable full-resolution filters and small previews for one page geometry."""
import hashlib,json,logging
from pathlib import Path
import cv2

MODES=('original','clean','color','bw','docshadow','ai_clean')
def geometry_key(points,rotation,dewarp):
    return hashlib.sha256(json.dumps(['instant-v1',points,rotation,dewarp],sort_keys=True).encode()).hexdigest()[:16]

def ensure_variants(directory,image_loader,points,rotation,dewarp,enhance,ai_ready,required='original'):
    directory=Path(directory);key=geometry_key(points,rotation,dewarp)
    base=directory/f'base-{key}.png';manifest=directory/f'filters-{key}.json'
    saved=json.loads(manifest.read_text()) if manifest.exists() else {'key':key,'modes':[]}
    wanted=list(MODES if ai_ready() else MODES[:-1])
    if required=='ai_clean' and required not in wanted:wanted.append(required)
    if all(m in saved['modes'] for m in wanted) and base.exists():return saved
    image=cv2.imread(str(base)) if base.exists() else image_loader()
    if image is None:raise RuntimeError('Missing page pixels')
    if not base.exists() and not cv2.imwrite(str(base),image):raise RuntimeError('Cannot cache page geometry')
    for mode in wanted:
        if mode in saved['modes']:continue
        try:output=enhance(image,mode)
        except Exception:
            if mode==required:raise
            logging.exception('Optional filter unavailable: %s',mode);continue
        full=directory/f'filter-{key}-{mode}.jpg';thumb=directory/f'thumb-{key}-{mode}.jpg'
        h,w=output.shape[:2];scale=min(1,1200/max(h,w));small=cv2.resize(output,(round(w*scale),round(h*scale)))
        if not cv2.imwrite(str(full),output,[cv2.IMWRITE_JPEG_QUALITY,95]):raise RuntimeError('Cannot cache filter')
        if not cv2.imwrite(str(thumb),small,[cv2.IMWRITE_JPEG_QUALITY,93]):raise RuntimeError('Cannot cache preview')
        saved['modes'].append(mode)
    saved.update(width=image.shape[1],height=image.shape[0])
    temporary=manifest.with_suffix('.tmp');temporary.write_text(json.dumps(saved));temporary.replace(manifest)
    return saved

def variant_urls(page_id,manifest):
    key=manifest['key']
    return {m:{'image':f'/api/jobs/{page_id}/filter-{key}-{m}.jpg',
               'preview':f'/api/jobs/{page_id}/thumb-{key}-{m}.jpg'} for m in manifest['modes']}
