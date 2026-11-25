from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from collections import Counter
import uuid, shutil, os, calendar
from dotenv import load_dotenv
try:
    from .database import (
        init_db,
        create_complaint,
        list_complaints,
        get_complaint_by_id,
        update_status,
        get_status_history,
        get_complaint_group,
        list_complaint_groups,
        update_group_status,
        update_group_priority,
        get_priority_summary,
        get_notifications_for_complaint,
        get_notifications_for_group
    )
    from .clustering import process_complaint_clustering, cluster_all_unassigned_complaints, recluster_all_complaints
    from .priority import evaluate_issue_priority
    from .geo import lookup_ward
    from .analytics import (
        get_dashboard_kpis,
        get_category_statistics,
        get_status_statistics,
        get_monthly_statistics,
        get_ward_statistics
    )
    from .rag import ingest_knowledge, retrieve
    from .datasets import inventory
except (ImportError, ValueError):
    from database import (
        init_db,
        create_complaint,
        list_complaints,
        get_complaint_by_id,
        update_status,
        get_status_history,
        get_complaint_group,
        list_complaint_groups,
        update_group_status,
        update_group_priority,
        get_priority_summary,
        get_notifications_for_complaint,
        get_notifications_for_group
    )
    from clustering import process_complaint_clustering, cluster_all_unassigned_complaints, recluster_all_complaints
    from priority import evaluate_issue_priority
    from geo import lookup_ward
    from analytics import (
        get_dashboard_kpis,
        get_category_statistics,
        get_status_statistics,
        get_monthly_statistics,
        get_ward_statistics
    )
    from rag import ingest_knowledge, retrieve
    from datasets import inventory

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
UPLOADS = ROOT / 'uploads'
UPLOADS.mkdir(exist_ok=True)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
app = FastAPI(title='CivicResolve API', version='1.0.0', description='Bengaluru civic assistance and grievance intelligence')
app.mount('/static', StaticFiles(directory=ROOT / 'frontend'), name='static')
app.mount('/uploads', StaticFiles(directory=UPLOADS), name='uploads')

def _citation_metadata(source_path):
    import json
    registry = ROOT / 'data' / 'knowledge_base' / 'sources.json'
    if not registry.exists():
        return {}
    try:
        entries = json.loads(registry.read_text(encoding='utf-8'))
        source_name = str(source_path).replace('\\', '/')
        return next((item for item in entries if item.get('file') in {source_name, Path(source_name).name}), {})
    except (ValueError, OSError):
        return {}

@app.on_event('startup')
def startup():
    init_db()
    # Seed clearly-labelled synthetic rows once so KPI cards and charts render on first launch.
    from .database import connect
    with connect() as conn:
        count = conn.execute('SELECT COUNT(*) FROM complaints').fetchone()[0]
    if count == 0:
        from .database import create_complaint
        samples = [
            ('DEMO-001','Pothole near sample junction','Synthetic demo record for dashboard preview.','Roads & potholes','High','Submitted'),
            ('DEMO-002','Garbage collection delay','Synthetic demo record for dashboard preview.','Garbage & waste','Medium','In Progress'),
            ('DEMO-003','Streetlight not working','Synthetic demo record for dashboard preview.','Streetlights','Medium','Under Review'),
            ('DEMO-004','Water leakage reported','Synthetic demo record for dashboard preview.','Water supply','High','Resolved'),
            ('DEMO-005','Waterlogging after rain','Synthetic demo record for dashboard preview.','Drainage & flooding','Urgent','Submitted'),
            ('DEMO-006','Road surface damage','Synthetic demo record for dashboard preview.','Roads & potholes','Low','Resolved')
        ]
        for ref,title,desc,cat,priority,status in samples:
            row = create_complaint({'reference':ref,'title':title,'description':desc,'category':cat,'priority':priority,'location_source':'demo'})
            update_status(row['id'], status)
    cluster_all_unassigned_complaints()

@app.get('/', response_class=HTMLResponse)
def home(): return (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')

@app.get('/admin', response_class=HTMLResponse)
def admin(): return (ROOT / 'frontend' / 'admin.html').read_text(encoding='utf-8')

@app.get('/track', response_class=HTMLResponse)
def track_page(): return (ROOT / 'frontend' / 'track.html').read_text(encoding='utf-8')

@app.get('/api/health')
def health():
    return {"status":"ok", "app":"CivicResolve", "gemini_enabled":bool(os.getenv('GEMINI_API_KEY'))}

@app.get('/api/geo/ward')
def ward(latitude: float, longitude: float):
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180): raise HTTPException(400, 'Invalid coordinates')
    return lookup_ward(latitude, longitude)

def process_new_complaint(title: str, description: str, category: str, priority: str = 'Medium', latitude: float | None = None, longitude: float | None = None, address: str = '', location_source: str = 'manual', image_path: str | None = None, image_analysis: str | None = None):
    geo = lookup_ward(latitude, longitude) if latitude is not None else {}
    ref = 'CR-' + datetime.now().strftime('%y%m%d') + '-' + uuid.uuid4().hex[:6].upper()

    # Intelligent multi-factor priority evaluation
    p_eval = evaluate_issue_priority(
        title=title.strip(),
        description=description.strip(),
        category=category,
        complaints_count=1,
        address=address.strip(),
        ward_name=geo.get('ward_name', '')
    )
    assigned_priority = p_eval['priority']

    item = create_complaint({
        "reference": ref,
        "title": title.strip(),
        "description": description.strip(),
        "category": category,
        "priority": assigned_priority,
        "priority_score": p_eval['priority_score'],
        "priority_reason": p_eval['priority_reason'],
        "priority_factors": p_eval['priority_factors'],
        "latitude": latitude,
        "longitude": longitude,
        "address": address.strip() or None,
        "ward_name": geo.get('ward_name'),
        "corporation": geo.get('corporation'),
        "location_source": location_source,
        "image_path": image_path,
        "image_analysis": image_analysis
    })
    item['ward_lookup'] = geo

    # Automatic duplicate detection and clustering
    group = process_complaint_clustering(item['id'])
    if group:
        item['group_id'] = group['id']
        item['group_reference'] = group['reference']
        item['group_title'] = group['title']
        item['group_summary'] = group['summary']
        item['complaints_count'] = group['complaints_count']
        item['priority'] = group.get('priority', item['priority'])
        item['priority_score'] = group.get('priority_score', item.get('priority_score', 50))
        item['is_duplicate'] = group['complaints_count'] > 1
    return item

@app.post('/api/complaints')
async def submit_complaint(title: str = Form(...), description: str = Form(...), category: str = Form(...), priority: str = Form('Medium'), latitude: float | None = Form(None), longitude: float | None = Form(None), address: str = Form(''), location_source: str = Form('manual'), image: UploadFile | None = File(None)):
    allowed = {'Roads & potholes','Garbage & waste','Streetlights','Drainage & flooding','Water supply','Other'}
    if category not in allowed: raise HTTPException(400, 'Invalid category')
    if not title.strip() or not description.strip(): raise HTTPException(400, 'Title and description are required')
    if (latitude is None) != (longitude is None): raise HTTPException(400, 'Both latitude and longitude are required')
    if latitude is not None and not (-90 <= latitude <= 90 and -180 <= longitude <= 180): raise HTTPException(400, 'Invalid GPS coordinates')
    image_path = None
    image_analysis = None
    image_bytes = None
    if image is not None and hasattr(image, 'filename') and image.filename:
        ext = Path(image.filename).suffix.lower()
        if ext not in {'.jpg','.jpeg','.png','.webp'}: raise HTTPException(400, 'Only JPG, PNG and WEBP images are supported')
        image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(413, 'Image must be 5 MB or smaller')
        signatures = {'.jpg': (b'\xff\xd8\xff',), '.jpeg': (b'\xff\xd8\xff',), '.png': (b'\x89PNG\r\n\x1a\n',), '.webp': (b'RIFF',)}
        valid_signature = any(image_bytes.startswith(sig) for sig in signatures[ext])
        if ext == '.webp':
            valid_signature = valid_signature and image_bytes[8:12] == b'WEBP'
        if not valid_signature:
            raise HTTPException(400, 'Image content does not match its file type')
        filename = f"{uuid.uuid4().hex}{ext}"
        (UPLOADS / filename).write_bytes(image_bytes)
        image_path = f"/uploads/{filename}"
        # Optional vision analysis; if no API key is configured, the photo is simply attached.
        if os.getenv('GEMINI_API_KEY'):
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
                mime = image.content_type or ('image/png' if ext == '.png' else 'image/jpeg')
                part = types.Part.from_bytes(data=image_bytes, mime_type=mime)
                vision = client.models.generate_content(model=os.getenv('GEMINI_MODEL','gemini-2.5-flash'), contents=['Describe only visible civic-infrastructure conditions in this photo. Do not infer exact location, cause, severity beyond visible evidence, or identify people. If unclear, say so.', part])
                image_analysis = vision.text
            except Exception as e:
                image_analysis = 'Image saved; optional vision analysis was unavailable.'
    return process_new_complaint(
        title=title,
        description=description,
        category=category,
        priority=priority,
        latitude=latitude,
        longitude=longitude,
        address=address,
        location_source=location_source,
        image_path=image_path,
        image_analysis=image_analysis
    )

@app.get('/api/complaints')
def complaints(): return list_complaints()

@app.get('/api/complaints/track/{reference}')
def track_complaint(reference: str):
    """Public exact-reference lookup for citizens tracking their complaint."""
    from .database import connect
    with connect() as conn:
        row = conn.execute('SELECT * FROM complaints WHERE upper(reference)=upper(?)', (reference.strip(),)).fetchone()
    if not row:
        raise HTTPException(404, 'No complaint found with that reference number.')
    item = dict(row)
    item['status_history'] = get_status_history(item['id'])
    item['notifications'] = get_notifications_for_complaint(item['id'])
    if item.get('group_id'):
        grp = get_complaint_group(item['group_id'])
        if grp:
            item['group'] = {
                'id': grp['id'],
                'reference': grp['reference'],
                'title': grp['title'],
                'summary': grp['summary'],
                'complaints_count': grp['complaints_count'],
                'status': grp['status'],
                'first_reported_at': grp['first_reported_at'],
                'last_reported_at': grp['last_reported_at']
            }
    return item

class StatusUpdate(BaseModel):
    status: str
    remarks: str | None = None
@app.patch('/api/complaints/{cid}/status')
def change_status(cid:int, body:StatusUpdate):
    if body.status not in {'Submitted','Under Review','In Progress','Resolved','Rejected'}: raise HTTPException(400,'Invalid status')
    if body.remarks and len(body.remarks) > 2000: raise HTTPException(400, 'Remarks must be 2000 characters or fewer')
    if not update_status(cid, body.status, body.remarks): raise HTTPException(404,'Complaint not found')
    return get_complaint_by_id(cid)

class GroupStatusUpdate(BaseModel):
    status: str
    remarks: str | None = None
    assigned_department: str | None = None
    assigned_officer: str | None = None

class GroupPriorityUpdate(BaseModel):
    priority: str
    reason: str | None = None

@app.get('/api/groups')
def get_groups(
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    ward: str | None = None,
    search: str | None = None,
    sort_by_priority: bool = False
):
    groups = list_complaint_groups(
        status=status,
        category=category,
        priority=priority,
        ward=ward,
        search=search,
        sort_by_priority=sort_by_priority
    )
    total_citizens = sum(g.get('complaints_count', 1) for g in groups)
    multi_report_count = sum(1 for g in groups if g.get('complaints_count', 1) > 1)
    return {
        "groups": groups,
        "total_groups": len(groups),
        "total_citizens": total_citizens,
        "multi_report_groups": multi_report_count
    }

@app.get('/api/priority/summary')
def priority_summary():
    """Returns real-time counts of unresolved issues across Critical, High, Medium, and Low."""
    return get_priority_summary()

@app.get('/api/priority/queue')
def priority_queue(
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    ward: str | None = None,
    search: str | None = None
):
    """
    Returns prioritized issues queue sorted in strict descending order:
    Critical -> High -> Medium -> Low, then by severity score and age.
    """
    groups = list_complaint_groups(
        status=status,
        category=category,
        priority=priority,
        ward=ward,
        search=search,
        sort_by_priority=True
    )
    summary = get_priority_summary()
    return {
        "queue": groups,
        "total": len(groups),
        "summary": summary
    }

@app.get('/api/priority/map-points')
def priority_map_points(
    status: str | None = None,
    category: str | None = None,
    priority: str | None = None,
    ward: str | None = None,
    search: str | None = None
):
    """
    Returns geocoded consolidated issues and unclustered points for the interactive command map.
    Consolidated duplicate complaints appear as a single clustered issue marker.
    """
    groups = list_complaint_groups(
        status=status,
        category=category,
        priority=priority,
        ward=ward,
        search=search,
        sort_by_priority=True
    )

    points = []
    # 1. Add all consolidated groups with valid coordinates
    for g in groups:
        if g.get('latitude') is not None and g.get('longitude') is not None:
            points.append({
                "id": g['id'],
                "group_id": g['id'],
                "type": "consolidated",
                "reference": g['reference'],
                "title": g['title'],
                "summary": g.get('summary', ''),
                "category": g['category'],
                "priority": g.get('priority', 'Medium'),
                "priority_score": g.get('priority_score', 50),
                "priority_reason": g.get('priority_reason', ''),
                "priority_factors": g.get('priority_factors', {}),
                "ward_name": g.get('ward_name') or 'Bengaluru',
                "address": g.get('address') or '',
                "latitude": float(g['latitude']),
                "longitude": float(g['longitude']),
                "complaints_count": g.get('complaints_count', 1),
                "days_unresolved": g.get('days_unresolved', 0),
                "status": g.get('status', 'Submitted'),
                "first_reported_at": g.get('first_reported_at'),
                "last_reported_at": g.get('last_reported_at'),
                "assigned_department": g.get('assigned_department'),
                "assigned_officer": g.get('assigned_officer')
            })

    # 2. Add any individual complaints that have GPS but no group
    from .database import connect
    with connect() as conn:
        unassigned = conn.execute("""
            SELECT * FROM complaints 
            WHERE group_id IS NULL AND latitude IS NOT NULL AND longitude IS NOT NULL
        """).fetchall()

    for row in unassigned:
        c = dict(row)
        # Apply filters
        if status and status != 'Unresolved' and c.get('status') != status:
            continue
        if status == 'Unresolved' and c.get('status') in ('Resolved', 'Rejected'):
            continue
        if category and c.get('category') != category:
            continue
        if priority and c.get('priority') != priority:
            continue
        if ward and c.get('ward_name') != ward:
            continue

        factors = c.get('priority_factors')
        if isinstance(factors, str):
            try: factors = json.loads(factors)
            except Exception: factors = {}

        points.append({
            "id": c['id'],
            "group_id": None,
            "complaint_id": c['id'],
            "type": "individual",
            "reference": c['reference'],
            "title": c['title'],
            "summary": c.get('description', ''),
            "category": c['category'],
            "priority": c.get('priority', 'Medium'),
            "priority_score": c.get('priority_score', 50),
            "priority_reason": c.get('priority_reason', ''),
            "priority_factors": factors or {},
            "ward_name": c.get('ward_name') or 'Bengaluru',
            "address": c.get('address') or '',
            "latitude": float(c['latitude']),
            "longitude": float(c['longitude']),
            "complaints_count": 1,
            "days_unresolved": c.get('days_unresolved', 0),
            "status": c.get('status', 'Submitted'),
            "first_reported_at": c.get('created_at'),
            "last_reported_at": c.get('updated_at'),
            "assigned_department": None,
            "assigned_officer": None
        })

    return {
        "points": points,
        "total_points": len(points),
        "critical_count": sum(1 for p in points if p['priority'] == 'Critical'),
        "high_count": sum(1 for p in points if p['priority'] == 'High'),
        "medium_count": sum(1 for p in points if p['priority'] == 'Medium'),
        "low_count": sum(1 for p in points if p['priority'] == 'Low')
    }

@app.patch('/api/groups/{gid}/priority')
def change_group_priority(gid: int, body: GroupPriorityUpdate):
    allowed = {'Critical', 'High', 'Medium', 'Low'}
    if body.priority not in allowed:
        raise HTTPException(400, f"Invalid priority. Allowed: {', '.join(allowed)}")
    updated = update_group_priority(gid, body.priority, reason=body.reason, updated_by='Admin')
    if not updated:
        raise HTTPException(404, 'Consolidated issue not found')
    return updated

@app.get('/api/groups/{gid}')
def get_group(gid: int):
    grp = get_complaint_group(gid)
    if not grp:
        raise HTTPException(404, 'Consolidated issue not found')
    grp['notifications'] = get_notifications_for_group(gid)
    return grp

@app.patch('/api/groups/{gid}/status')
def change_group_status(gid: int, body: GroupStatusUpdate):
    allowed = {'Submitted', 'Under Review', 'In Progress', 'Resolved', 'Rejected'}
    if body.status not in allowed:
        raise HTTPException(400, 'Invalid status')
    if body.remarks and len(body.remarks) > 2000:
        raise HTTPException(400, 'Remarks must be 2000 characters or fewer')
    updated = update_group_status(
        gid,
        body.status,
        remarks=body.remarks,
        updated_by='Admin',
        assigned_department=body.assigned_department,
        assigned_officer=body.assigned_officer
    )
    if not updated:
        raise HTTPException(404, 'Consolidated issue not found')
    return updated

@app.post('/api/groups/recluster')
def trigger_recluster(force: bool = True):
    return recluster_all_complaints(force=force)

@app.get("/api/dashboard/historical")
def historical_dashboard():
    """Historical Bengaluru civic complaint analytics with automatic live fallback."""
    try:
        return {
            "kpis": get_dashboard_kpis(),
            "categories": get_category_statistics(),
            "statuses": get_status_statistics(),
            "monthly": get_monthly_statistics(),
            "wards": get_ward_statistics()
        }
    except Exception:
        return dashboard()


@app.get("/api/dashboard")
def live_dashboard():
    """Live complaints analytics endpoint."""
    return dashboard()


@app.get("/api/dashboard/historical/geo")
def historical_geo():
    """Return GPS-tagged historical complaint points."""

    from .analytics import load_complaints

    try:
        df = load_complaints()
        df = df.dropna(subset=["latitude", "longitude"])

        records = df[
            [
                "latitude",
                "longitude",
                "category_title",
                "complaint_status_title",
                "ward_title"
            ]
        ].to_dict(orient="records")

        return {
            "data_type": "historical",
            "period": "2019-2022",
            "total_points": len(records),
            "points": records
        }
    except Exception:
        return {"data_type": "live", "points": [], "total_points": 0}

def dashboard():
    rows = list_complaints()
    total = len(rows)
    resolved = sum(r['status'] == 'Resolved' for r in rows)
    open_count = sum(r['status'] not in {'Resolved', 'Rejected'} for r in rows)
    now = datetime.now()
    month_count = sum((r['created_at'] or '')[:7] == now.strftime('%Y-%m') for r in rows)
    geo_count = sum(r['latitude'] is not None and r['longitude'] is not None for r in rows)
    cat_counts = Counter(r['category'] for r in rows)
    categories = [{"category": c, "complaints": count} for c, count in cat_counts.most_common()]
    stat_counts = Counter(r['status'] for r in rows)
    statuses = [{"status": s, "complaints": count} for s, count in stat_counts.items()]
    monthly = Counter((r['created_at'] or '')[:7] for r in rows)
    months = sorted([m for m in monthly.keys() if m])
    monthly_data = [{"month": m, "complaints": monthly[m]} for m in months]
    return {
        "kpis": {
            "total_complaints": total,
            "open_complaints": open_count,
            "resolved_complaints": resolved,
            "resolution_rate_percent": round(resolved / total * 100, 1) if total else 0,
            "this_month": month_count,
            "records_with_gps": geo_count
        },
        "categories": categories,
        "statuses": statuses,
        "monthly": monthly_data,
        "data_type": "live",
        "demo_notice": total > 0 and all(r['reference'].startswith('DEMO-') for r in rows)
    }

class AskRequest(BaseModel): question: str
@app.post('/api/ask')
def ask(body:AskRequest):
    if not body.question.strip(): raise HTTPException(400,'Enter a question')
    hits=retrieve(body.question,5)
    if not hits:
        return {"answer":"I do not yet have official documents indexed. Add verified government circulars, service procedures or grievance documents to data/knowledge, then re-index. I will not invent a complaint process or responsible officer.","sources":[],"grounded":False}
    context='\n\n'.join(f"[{i+1}] {h['source']}: {h['text']}" for i,h in enumerate(hits))
    answer=None
    key=os.getenv('GEMINI_API_KEY')
    if key:
        try:
            from google import genai
            client=genai.Client(api_key=key)
            prompt=("You are CivicResolve, a Bengaluru civic guidance assistant. Answer only from the provided source excerpts. "
                    "Do not invent government contacts, deadlines, jurisdiction, or filing steps. If sources are insufficient, say what is missing. "
                    "Mention that actual filing must be done through the official channel. Cite excerpt numbers like [1].\n\n"
                    f"QUESTION: {body.question}\n\nSOURCES:\n{context}")
            response=client.models.generate_content(model=os.getenv('GEMINI_MODEL','gemini-2.5-flash'),contents=prompt)
            answer=response.text
        except Exception as e:
            answer=None
    if not answer:
        answer="I found these potentially relevant passages in the local knowledge base. Review the cited source documents before acting:\n\n" + '\n\n'.join(f"[{i+1}] {h['text'][:700]}" for i,h in enumerate(hits[:3]))
    return {"answer":answer,"sources":[{"citation":i+1,"source":h['source'],"path":h['path'],"chunk_id":h['chunk_id'],"url":_citation_metadata(h['path']).get('url', _citation_metadata(h['path']).get('source_url'))} for i,h in enumerate(hits)],"grounded":True}

@app.post('/api/rag/ingest')
def ingest(): return ingest_knowledge()

@app.get('/api/datasets')
def datasets(): return inventory()


@app.get("/api/geo/wards")
def get_ward_geojson():
    """Serve Greater Bengaluru 2025 ward boundary GeoJSON."""

    import json
    from pathlib import Path
    from fastapi import HTTPException

    geojson_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "raw"
        / "gba_wards_2025.geojson"
    )

    if not geojson_path.exists():
        raise HTTPException(
            status_code=404,
            detail="GBA ward boundary dataset not found"
        )

    with open(geojson_path, "r", encoding="utf-8") as file:
        return json.load(file)

