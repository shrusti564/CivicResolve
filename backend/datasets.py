from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
MANIFEST = ROOT / 'data' / 'dataset_manifest.json'


def inventory():
    items=[]
    if RAW.exists():
        for p in sorted(RAW.iterdir()):
            if p.is_file():
                item={"file":p.name,"size_kb":round(p.stat().st_size/1024,1),"type":p.suffix.lower()}
                if p.suffix.lower()=='.csv':
                    try:
                        df=pd.read_csv(p,nrows=5)
                        item['columns']=list(df.columns)
                    except Exception: item['columns']=[]
                items.append(item)
    manifest=json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {"datasets": []}
    sources = manifest.get('datasets', []) if isinstance(manifest, dict) else manifest
    local_names = {item['file'] for item in items}
    for source in sources:
        filename = source.get('file')
        source['local_file_available'] = bool(filename and filename in local_names)
        if not source['local_file_available'] and source.get('status') == 'downloaded':
            source['status'] = 'missing_locally'
    return {"files":items,"sources":manifest}
