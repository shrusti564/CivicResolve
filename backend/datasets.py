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
    manifest=json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    return {"files":items,"sources":manifest}
