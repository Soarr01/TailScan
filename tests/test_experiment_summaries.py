import json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'experiments'

def test_summaries_do_not_include_private_payload_fields():
    forbidden={'text','raw','prediction','reference_blocks','references','prompt','job_id','corners','bbox','input_sha256','direct_file','field_file'}
    def check(value):
        if isinstance(value,dict):
            assert not (set(value)&forbidden)
            for child in value.values():check(child)
        elif isinstance(value,list):
            for child in value:check(child)
        elif isinstance(value,float):assert math.isfinite(value)
    files=list((ROOT/'results').glob('*.json'));assert len(files)==9
    for file in files:
        data=json.loads(file.read_text(encoding='utf-8'));assert data['private_inputs_included'] is False;check(data)

def test_published_cer_matches_edit_counts():
    a=json.loads((ROOT/'results/ocr-private-a.json').read_text())['records']
    for row in a:assert abs(row['cer_percent']-row['errors']/row['reference_characters']*100)<.00051
    b=json.loads((ROOT/'results/ocr-private-b.json').read_text())['records']
    for row in b:assert abs(row['aligned_cer_percent']-row['aligned_errors']/row['reference_characters']*100)<.00051
    filters=json.loads((ROOT/'results/filter-ocr.json').read_text())['records']
    for row in filters:assert abs(row['cer_percent']-row['errors']/row['reference_chars']*100)<.00051

def test_synthetic_fixtures_are_decodable_and_same_size():
    import cv2
    files=list((ROOT/'assets').glob('synthetic-*.png'));assert len(files)==5
    shapes=[cv2.imread(str(file)).shape for file in files]
    assert len(set(shapes))==1
