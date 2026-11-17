"""Source-only release checks. Findings print filenames, never matched contents."""
import re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
try:
    result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,check=True,capture_output=True)
    files=[ROOT/p for p in result.stdout.decode().split('\0') if p]
except (OSError,subprocess.CalledProcessError):
    files=[p for p in ROOT.rglob('*') if p.is_file() and not any(s in p.relative_to(ROOT).parts for s in ['.git','__pycache__','.pytest_cache'])]
patterns={
    'private-key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-token':re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})'),
    'embedded-secret':re.compile(r'''(?i)(?:api_key|access_token|password)\s*[:=]\s*["'][A-Za-z0-9_\-]{20,}["']''')}
findings=[]
for file in files:
    rel=file.relative_to(ROOT).as_posix()
    if file.suffix.lower() in {'.ipa','.onnx','.ort','.safetensors','.pkl','.pth','.pdf','.jpg','.jpeg','.heic','.ttf'}:findings.append((rel,'non-source asset'))
    if file.name=='.env' or file.name=='worker.json' or any(s in file.relative_to(ROOT).parts for s in ['test-output','data','library']):findings.append((rel,'private runtime data'))
    if file.suffix.lower() not in {'.py','.md','.txt','.swift','.html','.js','.css','.yml','.yaml','.json','.plist','.sh'}:continue
    text=file.read_text(encoding='utf-8')
    for label,pattern in patterns.items():
        if pattern.search(text):findings.append((rel,label))
    hosts=re.findall(r'https?://([^/\s"\'<>]+\.ts\.net)(?::\d+)?',text)
    if any(host!='your-server.your-tailnet.ts.net' for host in hosts):findings.append((rel,'non-placeholder tailnet endpoint'))
for file,label in findings:print(file+': '+label)
if findings:raise SystemExit(1)
print('Public source audit passed:',len(files),'files')
