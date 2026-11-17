"""Download public, pinned model assets; no credentials or document uploads."""
import argparse,hashlib,json,os,shutil,time,urllib.error,urllib.parse,urllib.request
from pathlib import Path,PurePosixPath

ROOT=Path(__file__).resolve().parents[1]/'server'
LAB=Path(os.environ.get('TAILSCAN_IMAGE_LAB',str(ROOT/'image_worker')))
MANIFEST=[]

def sha256(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def download(url,destination,expected=None):
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists() and expected and sha256(destination)==expected:return
    temporary=destination.with_name(destination.name+'.part')
    for attempt in range(3):
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'TailScan-model-bootstrap'})
            with urllib.request.urlopen(request,timeout=120) as response,temporary.open('wb') as output:
                shutil.copyfileobj(response,output,1024*1024)
            actual=sha256(temporary)
            if expected and actual!=expected:raise ValueError(f'Checksum mismatch: {destination.name}')
            temporary.replace(destination)
            MANIFEST.append({'url':url,'file':str(destination),'sha256':actual})
            print('Downloaded',destination.name,flush=True);return
        except Exception:
            temporary.unlink(missing_ok=True)
            if attempt==2:raise
            time.sleep(2**attempt)

def license_file(repo,revision,name):
    for filename in ['LICENSE','LICENSE.md','LICENSE.txt']:
        try:
            download(f'https://raw.githubusercontent.com/{repo}/{revision}/{filename}',ROOT/'models/licenses'/name)
            return
        except urllib.error.HTTPError as error:
            if error.code!=404:raise
    print('Upstream license file not found automatically; see NOTICE.md for',repo)

def images():
    uv='4c9b82b537057aff2526e6dd118a847cdd072e82'
    docres='d3e3a18c7c7ad10e4615ca2eb6a10f83128d8560'
    assets=[
        (f'https://raw.githubusercontent.com/tanguymagne/UVDoc/{uv}/model.py',LAB/'uvdoc/model.py','320f460edc54cf830dfdd9788dfbc1b96a836429b64ed6078a30582be6f59e42'),
        (f'https://raw.githubusercontent.com/tanguymagne/UVDoc/{uv}/model/best_model.pkl',LAB/'uvdoc/best_model.pkl','7e90861b8a516eb4bc51f84bd889cb77275743d2d1d3ca8091951ec9f2b7da23'),
        (f'https://raw.githubusercontent.com/ZZZHANG-jx/DocRes/{docres}/models/restormer_arch.py',LAB/'docres/restormer_arch.py','4a6f50552cf21c016f3c38f0302ff9c9cea07a38111c219ef9e67279e60d6915'),
        ('https://huggingface.co/DaVinciCode/doctra-docres-main/resolve/1e63badacc1b20489c0c29b12437c98bda51b12e/docres.pkl',LAB/'models/docres.pkl','1d6a89d754fe1e58ffd1865eab0ef3f03344798d39197b2d9a77ce4fbc8c02fd'),
        ('https://github.com/fabio-sim/DocShadow-ONNX-TensorRT/releases/download/v1.0.0/docshadow_sd7k.onnx',LAB/'docshadow/docshadow_sd7k.onnx','8c09b9320a0fb3c53806cdf9cb8410b3706c77caed81f4ec1cb0bf2cbd14b049'),
        ('https://raw.githubusercontent.com/egdels/makeacopy/13b44236c79130153c7300451b113fc2febba860/app/src/main/assets/docquad/docquadnet256_trained_opset17.ort',ROOT/'models/docquad/docquadnet256.ort','f0f2f52d7d79ff02d346c8f9d0c9e903407366aeea1747cdcff160c401e3e72a')]
    for url,path,digest in assets:download(url,path,digest)
    for repo,revision,name in [('tanguymagne/UVDoc',uv,'UVDoc.txt'),('ZZZHANG-jx/DocRes',docres,'DocRes.txt'),('fabio-sim/DocShadow-ONNX-TensorRT','ec926bf36b4ac0778f836a2d34e27021447df27c','DocShadow-ONNX.txt'),('egdels/makeacopy','13b44236c79130153c7300451b113fc2febba860','DocQuadNet.txt')]:license_file(repo,revision,name)

def ocr():
    repo='PaddlePaddle/PaddleOCR-VL-1.6';revision='132c45f52c0a26ed5a6b2f6bd8e3985794cc27dd'
    with urllib.request.urlopen(f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true',timeout=60) as response:metadata=json.load(response)
    for item in metadata['siblings']:
        name=item['rfilename'];relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe upstream model path')
        if name.startswith('.') or name.lower().endswith(('.png','.jpg','.jpeg','.gif')):continue
        expected=item.get('lfs',{}).get('sha256')
        download(f'https://huggingface.co/{repo}/resolve/{revision}/{urllib.parse.quote(name,safe="/")}',ROOT/'models/paddleocr-vl16'/name,expected)

def font(path=None):
    candidates=[Path(path)] if path else [Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),Path('/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf')]
    source=next((p for p in candidates if p.is_file()),None)
    if source is None:raise FileNotFoundError('Install fonts-dejavu-core or pass --font-path /path/to/DejaVuSans.ttf')
    target=ROOT/'fonts/DejaVuSans.ttf';target.parent.mkdir(exist_ok=True);shutil.copyfile(source,target);print('Installed PDF font')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ['all','images','ocr','font']:parser.add_argument('--'+flag,action='store_true')
    parser.add_argument('--font-path');args=parser.parse_args()
    if not any([args.all,args.images,args.ocr,args.font,args.font_path]):parser.error('Select --all or --images / --ocr / --font')
    if args.all or args.images:images()
    if args.all or args.ocr:ocr()
    if args.all or args.font or args.font_path:font(args.font_path)
    folder=ROOT/'models';folder.mkdir(exist_ok=True)
    (folder/'download_manifest.json').write_text(json.dumps(MANIFEST,indent=2),encoding='utf-8')
