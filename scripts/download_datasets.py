"""Download selected public Bengaluru datasets from OpenCity CKAN and GBA ward GeoJSON."""
from pathlib import Path
from datetime import datetime, timezone
import json, re, urllib.request, urllib.parse

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data'/'raw'; RAW.mkdir(parents=True,exist_ok=True)
API='https://data.opencity.in/api/3/action'
QUERIES=[
 'BBMP Grievances Data','BBMP Fix My Street Data','BBMP Ward Information',
 'Bengaluru Streetlights','BBMP Solid Waste Management Data','Flooding Locations in Bengaluru Urban',
 'BBMP Work Orders 2023-24','BDA Jurisdiction and Boundary'
]

def get_json(url):
    req=urllib.request.Request(url,headers={'User-Agent':'CivicResolve-Student-Project/1.0'})
    with urllib.request.urlopen(req,timeout=45) as r: return json.loads(r.read().decode('utf-8'))

def safe(s): return re.sub(r'[^a-z0-9]+','_',s.lower()).strip('_')[:70]

def main():
    manifest=[]
    # Public research copy of the I Change My City Bengaluru complaint log (2019-2022; 16,071 rows).
    complaint_url='https://raw.githubusercontent.com/Vaibhav-code15/Bengaluru-Municipality-Issue-Analysis/main/data/a60abf5c-3a15-4967-af32-c3074248580f.csv'
    try:
        req=urllib.request.Request(complaint_url,headers={'User-Agent':'CivicResolve-Student-Project/1.0'})
        with urllib.request.urlopen(req,timeout=90) as r, (RAW/'bengaluru_icmc_complaints_2019_2022.csv').open('wb') as out: out.write(r.read())
        manifest.append({'title':'I Change My City Bengaluru civic complaints 2019-2022','file':'bengaluru_icmc_complaints_2019_2022.csv','url':complaint_url,'status':'downloaded','records_reported_by_source':16071,'period':'2019-01 to 2022-12','note':'Community research repository mirror; attribute original OpenCity / I Change My City / Janaagraha and the repository. Inspect licence and dataset terms before redistribution.'})
        print('DOWNLOADED: bengaluru_icmc_complaints_2019_2022.csv')
    except Exception as e:
        manifest.append({'title':'I Change My City Bengaluru civic complaints 2019-2022','url':complaint_url,'status':'failed','error':str(e)})
        print('COMPLAINT DATASET DOWNLOAD FAILED:',e)
    for query in QUERIES:
        try:
            search=get_json(API+'/package_search?'+urllib.parse.urlencode({'q':query,'rows':5}))
            results=search.get('result',{}).get('results',[])
            if not results:
                manifest.append({'query':query,'status':'not_found'}); print('NOT FOUND:',query); continue
            pkg=results[0]
            detail=get_json(API+'/package_show?'+urllib.parse.urlencode({'id':pkg['id']})).get('result',{})
            resources=detail.get('resources',[])
            downloaded=[]
            for res in resources:
                fmt=(res.get('format') or '').lower()
                if fmt not in {'csv','geojson','json','kml','zip'}: continue
                url=res.get('url')
                if not url: continue
                ext='.'+('geojson' if fmt=='json' and 'geojson' in (res.get('name') or '').lower() else fmt)
                name=safe(detail.get('title') or query)+'_'+safe(res.get('name') or fmt)+ext
                dest=RAW/name
                try:
                    req=urllib.request.Request(url,headers={'User-Agent':'CivicResolve-Student-Project/1.0'})
                    with urllib.request.urlopen(req,timeout=90) as response, dest.open('wb') as out:
                        out.write(response.read())
                    downloaded.append({'file':name,'url':url,'format':fmt,'license':detail.get('license_title')})
                    print('DOWNLOADED:',name)
                except Exception as e: print('RESOURCE FAILED:',url,e)
            manifest.append({'query':query,'title':detail.get('title'),'package_url':detail.get('url'),'license':detail.get('license_title'),'downloaded':downloaded,'status':'downloaded' if downloaded else 'no_resource_downloaded'})
        except Exception as e:
            manifest.append({'query':query,'status':'failed','error':str(e)}); print('FAILED:',query,e)
    # Current GBA 2025 ward boundary layer: 369 wards, CC0 listing on Bharatlas.
    ward_url='https://pub-0429b8e3b5a946e69ea007df844a6f1c.r2.dev/admin/wards-bengaluru-gba/wards_bengaluru_gba.geojson'
    try:
        req=urllib.request.Request(ward_url,headers={'User-Agent':'CivicResolve-Student-Project/1.0'})
        with urllib.request.urlopen(req,timeout=90) as r, (RAW/'gba_wards_2025.geojson').open('wb') as out: out.write(r.read())
        manifest.append({'title':'Greater Bengaluru Wards 2025','file':'gba_wards_2025.geojson','url':ward_url,'license':'CC0-1.0','status':'downloaded'})
        print('DOWNLOADED: gba_wards_2025.geojson')
    except Exception as e:
        manifest.append({'title':'Greater Bengaluru Wards 2025','url':ward_url,'status':'failed','error':str(e)})
        print('WARD BOUNDARY DOWNLOAD FAILED:',e)
    (ROOT/'data'/'dataset_manifest.json').write_text(json.dumps({'retrieved_at':datetime.now(timezone.utc).isoformat(),'datasets':manifest},indent=2),encoding='utf-8')
    print('\nFinished. See data/dataset_manifest.json and data/raw/.')

if __name__=='__main__': main()
