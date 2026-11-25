import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "civicresolve.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            priority TEXT DEFAULT 'Medium',
            status TEXT DEFAULT 'Submitted',
            latitude REAL,
            longitude REAL,
            address TEXT,
            ward_name TEXT,
            corporation TEXT,
            location_source TEXT DEFAULT 'manual',
            image_path TEXT,
            image_analysis TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_name TEXT NOT NULL,
            source_path TEXT NOT NULL,
            chunk_text TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS complaint_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL REFERENCES complaints(id),
            previous_status TEXT,
            new_status TEXT NOT NULL,
            remarks TEXT,
            updated_by TEXT,
            created_at TEXT NOT NULL
        )""")
        cols = [r['name'] for r in c.execute('PRAGMA table_info(complaints)').fetchall()]
        if 'image_analysis' not in cols: c.execute('ALTER TABLE complaints ADD COLUMN image_analysis TEXT')
        if 'group_id' not in cols: c.execute('ALTER TABLE complaints ADD COLUMN group_id INTEGER REFERENCES complaint_groups(id)')
        if 'priority_score' not in cols: c.execute('ALTER TABLE complaints ADD COLUMN priority_score INTEGER DEFAULT 50')
        if 'priority_reason' not in cols: c.execute('ALTER TABLE complaints ADD COLUMN priority_reason TEXT')
        if 'priority_factors' not in cols: c.execute('ALTER TABLE complaints ADD COLUMN priority_factors TEXT')
        if 'priority_override' not in cols: c.execute('ALTER TABLE complaints ADD COLUMN priority_override INTEGER DEFAULT 0')

        c.execute("""CREATE TABLE IF NOT EXISTS complaint_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            category TEXT NOT NULL,
            ward_name TEXT,
            corporation TEXT,
            address TEXT,
            latitude REAL,
            longitude REAL,
            status TEXT DEFAULT 'Submitted',
            priority TEXT DEFAULT 'Medium',
            priority_score INTEGER DEFAULT 50,
            priority_reason TEXT,
            priority_factors TEXT,
            priority_override INTEGER DEFAULT 0,
            priority_override_reason TEXT,
            priority_override_by TEXT,
            priority_override_at TEXT,
            assigned_department TEXT,
            assigned_officer TEXT,
            complaints_count INTEGER DEFAULT 1,
            first_reported_at TEXT NOT NULL,
            last_reported_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")

        cols_groups = [r['name'] for r in c.execute('PRAGMA table_info(complaint_groups)').fetchall()]
        if 'priority_score' not in cols_groups: c.execute('ALTER TABLE complaint_groups ADD COLUMN priority_score INTEGER DEFAULT 50')
        if 'priority_reason' not in cols_groups: c.execute('ALTER TABLE complaint_groups ADD COLUMN priority_reason TEXT')
        if 'priority_factors' not in cols_groups: c.execute('ALTER TABLE complaint_groups ADD COLUMN priority_factors TEXT')
        if 'priority_override' not in cols_groups: c.execute('ALTER TABLE complaint_groups ADD COLUMN priority_override INTEGER DEFAULT 0')
        if 'priority_override_reason' not in cols_groups: c.execute('ALTER TABLE complaint_groups ADD COLUMN priority_override_reason TEXT')
        if 'priority_override_by' not in cols_groups: c.execute('ALTER TABLE complaint_groups ADD COLUMN priority_override_by TEXT')
        if 'priority_override_at' not in cols_groups: c.execute('ALTER TABLE complaint_groups ADD COLUMN priority_override_at TEXT')

        c.execute("""CREATE TABLE IF NOT EXISTS citizen_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL REFERENCES complaints(id),
            complaint_reference TEXT NOT NULL,
            group_id INTEGER REFERENCES complaint_groups(id),
            group_reference TEXT,
            notification_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'Delivered',
            sent_at TEXT NOT NULL
        )""")

        c.execute("CREATE INDEX IF NOT EXISTS idx_complaints_group_id ON complaints(group_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_complaint_groups_reference ON complaint_groups(reference)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_notifications_complaint ON citizen_notifications(complaint_id)")

        # Existing records have no trustworthy earlier history. Preserve only their
        # currently stored status and updated timestamp as the migration baseline.
        c.execute("""INSERT INTO complaint_status_history
            (complaint_id, previous_status, new_status, remarks, updated_by, created_at)
            SELECT c.id, NULL, c.status, NULL, NULL, c.updated_at
            FROM complaints c
            WHERE NOT EXISTS (
                SELECT 1 FROM complaint_status_history h WHERE h.complaint_id=c.id
            )""")
        c.commit()


def _calc_days_unresolved(reported_at, status):
    if not reported_at or status in ("Resolved", "Rejected"):
        return 0
    try:
        clean = reported_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        delta = datetime.now(timezone.utc) - dt
        return max(0, delta.days)
    except Exception:
        return 0


def _format_group_data(g):
    if not g:
        return None
    factors = g.get('priority_factors')
    if isinstance(factors, str):
        try:
            g['priority_factors'] = json.loads(factors)
        except Exception:
            g['priority_factors'] = {}
    elif not factors:
        g['priority_factors'] = {}

    g['days_unresolved'] = _calc_days_unresolved(g.get('first_reported_at'), g.get('status'))
    return g


def create_complaint(data):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    factors = data.get('priority_factors')
    factors_json = json.dumps(factors) if isinstance(factors, dict) else (factors or None)

    with connect() as c:
        cur = c.execute("""INSERT INTO complaints
            (reference,title,description,category,priority,priority_score,priority_reason,priority_factors,priority_override,status,latitude,longitude,address,ward_name,corporation,location_source,image_path,image_analysis,created_at,updated_at,group_id)
            VALUES (?,?,?,?,?,?,?,?,?,'Submitted',?,?,?,?,?,?,?,?,?,?,?)""",
            (data['reference'], data['title'], data['description'], data['category'],
             data.get('priority', 'Medium'), data.get('priority_score', 50), data.get('priority_reason'),
             factors_json, data.get('priority_override', 0),
             data.get('latitude'), data.get('longitude'), data.get('address'), data.get('ward_name'), data.get('corporation'),
             data.get('location_source', 'manual'), data.get('image_path'), data.get('image_analysis'), now, now, data.get('group_id')))
        c.execute("""INSERT INTO complaint_status_history
            (complaint_id, previous_status, new_status, remarks, updated_by, created_at)
            VALUES (?, NULL, 'Submitted', NULL, ?, ?)""", (cur.lastrowid, 'Citizen', now))
        c.commit()
        return get_complaint_by_id(cur.lastrowid)


def get_complaint_by_id(cid):
    with connect() as c:
        row = c.execute("SELECT * FROM complaints WHERE id=?", (cid,)).fetchone()
        if not row:
            return None
        item = dict(row)
        factors = item.get('priority_factors')
        if isinstance(factors, str):
            try: item['priority_factors'] = json.loads(factors)
            except Exception: item['priority_factors'] = {}
        item['days_unresolved'] = _calc_days_unresolved(item.get('created_at'), item.get('status'))
        return item


def list_complaints():
    with connect() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM complaints ORDER BY created_at DESC").fetchall()]
        for r in rows:
            factors = r.get('priority_factors')
            if isinstance(factors, str):
                try: r['priority_factors'] = json.loads(factors)
                except Exception: r['priority_factors'] = {}
            r['days_unresolved'] = _calc_days_unresolved(r.get('created_at'), r.get('status'))
        return rows


def update_status(cid, status, remarks=None, updated_by='Admin'):
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with connect() as c:
        current = c.execute("SELECT status FROM complaints WHERE id=?", (cid,)).fetchone()
        if not current:
            return False
        previous = current['status']
        if previous != status:
            c.execute("UPDATE complaints SET status=?, updated_at=? WHERE id=?", (status, now, cid))
            c.execute("""INSERT INTO complaint_status_history
                (complaint_id, previous_status, new_status, remarks, updated_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""", (cid, previous, status, remarks, updated_by, now))
        elif remarks:
            c.execute("UPDATE complaints SET updated_at=? WHERE id=?", (now, cid))
            c.execute("""INSERT INTO complaint_status_history
                (complaint_id, previous_status, new_status, remarks, updated_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""", (cid, previous, status, remarks, updated_by, now))
        c.commit()
        return True


def get_status_history(cid):
    with connect() as c:
        return [dict(row) for row in c.execute(
            "SELECT * FROM complaint_status_history WHERE complaint_id=? ORDER BY created_at, id",
            (cid,)
        ).fetchall()]


def create_complaint_group(data):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    factors = data.get('priority_factors')
    factors_json = json.dumps(factors) if isinstance(factors, dict) else (factors or None)

    with connect() as c:
        cur = c.execute("""INSERT INTO complaint_groups
            (reference, title, summary, category, ward_name, corporation, address, latitude, longitude, status, priority, priority_score, priority_reason, priority_factors, priority_override, assigned_department, assigned_officer, complaints_count, first_reported_at, last_reported_at, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data['reference'],
                data['title'],
                data['summary'],
                data['category'],
                data.get('ward_name'),
                data.get('corporation'),
                data.get('address'),
                data.get('latitude'),
                data.get('longitude'),
                data.get('status', 'Submitted'),
                data.get('priority', 'Medium'),
                data.get('priority_score', 50),
                data.get('priority_reason'),
                factors_json,
                data.get('priority_override', 0),
                data.get('assigned_department'),
                data.get('assigned_officer'),
                data.get('complaints_count', 1),
                data.get('first_reported_at', now),
                data.get('last_reported_at', now),
                now,
                now
            )
        )
        c.commit()
        return get_complaint_group(cur.lastrowid)


def get_complaint_group(gid):
    with connect() as c:
        row = c.execute("SELECT * FROM complaint_groups WHERE id=?", (gid,)).fetchone()
        if not row:
            return None
        group = dict(row)
        complaints = [dict(r) for r in c.execute("SELECT * FROM complaints WHERE group_id=? ORDER BY created_at ASC", (gid,)).fetchall()]
        for comp in complaints:
            f = comp.get('priority_factors')
            if isinstance(f, str):
                try: comp['priority_factors'] = json.loads(f)
                except Exception: comp['priority_factors'] = {}
            comp['days_unresolved'] = _calc_days_unresolved(comp.get('created_at'), comp.get('status'))

        group['complaints'] = complaints
        group['complaints_count'] = len(complaints) if complaints else group['complaints_count']
        group['linked_complaint_ids'] = [r['id'] for r in complaints]
        group['linked_references'] = [r['reference'] for r in complaints]
        return _format_group_data(group)


def get_complaint_group_by_reference(ref):
    with connect() as c:
        row = c.execute("SELECT id FROM complaint_groups WHERE upper(reference)=upper(?)", (ref.strip(),)).fetchone()
        if not row:
            return None
        return get_complaint_group(row['id'])


def list_complaint_groups(status=None, category=None, priority=None, ward=None, search=None, sort_by_priority=False):
    with connect() as c:
        query = "SELECT * FROM complaint_groups WHERE 1=1"
        params = []
        if status:
            if status == "Unresolved":
                query += " AND status NOT IN ('Resolved', 'Rejected')"
            else:
                query += " AND status = ?"
                params.append(status)
        if category:
            query += " AND category = ?"
            params.append(category)
        if priority:
            query += " AND priority = ?"
            params.append(priority)
        if ward:
            query += " AND ward_name = ?"
            params.append(ward)
        if search:
            query += " AND (title LIKE ? OR summary LIKE ? OR ward_name LIKE ? OR address LIKE ? OR reference LIKE ?)"
            s = f"%{search}%"
            params.extend([s, s, s, s, s])

        if sort_by_priority:
            query += """ ORDER BY 
                CASE priority 
                    WHEN 'Critical' THEN 1 
                    WHEN 'High' THEN 2 
                    WHEN 'Medium' THEN 3 
                    WHEN 'Low' THEN 4 
                    ELSE 5 
                END, 
                priority_score DESC, 
                first_reported_at ASC,
                id DESC"""
        else:
            query += " ORDER BY last_reported_at DESC, id DESC"

        rows = [dict(r) for r in c.execute(query, params).fetchall()]

        for r in rows:
            linked = c.execute("SELECT id, reference, title, created_at, status, latitude, longitude, address, ward_name, image_path, priority FROM complaints WHERE group_id=? ORDER BY created_at ASC", (r['id'],)).fetchall()
            r['complaints_count'] = len(linked)
            r['linked_references'] = [x['reference'] for x in linked]
            r['linked_complaint_ids'] = [x['id'] for x in linked]
            _format_group_data(r)
        return rows


def get_priority_summary():
    """
    Returns counts of active UNRESOLVED consolidated issues by priority tier.
    Only counts issues that are not Resolved and not Rejected.
    """
    with connect() as c:
        group_rows = c.execute("""
            SELECT priority, COUNT(*) as cnt
            FROM complaint_groups
            WHERE status NOT IN ('Resolved', 'Rejected')
            GROUP BY priority
        """).fetchall()

        group_counts = {r['priority']: r['cnt'] for r in group_rows}
        critical = group_counts.get('Critical', 0)
        high = group_counts.get('High', 0)
        medium = group_counts.get('Medium', 0)
        low = group_counts.get('Low', 0)
        total_unresolved = critical + high + medium + low

        resolved_count = c.execute("SELECT COUNT(*) FROM complaint_groups WHERE status = 'Resolved'").fetchone()[0]
        total_groups = c.execute("SELECT COUNT(*) FROM complaint_groups").fetchone()[0]
        total_citizens = c.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]

        return {
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
            "total_unresolved": total_unresolved,
            "total_resolved": resolved_count,
            "total_groups": total_groups,
            "total_citizens": total_citizens
        }


def update_group_priority(gid, priority, reason=None, updated_by='Admin'):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    allowed = {'Critical', 'High', 'Medium', 'Low'}
    if priority not in allowed:
        raise ValueError(f"Invalid priority: {priority}")

    tier_scores = {'Critical': 90, 'High': 75, 'Medium': 50, 'Low': 25}
    score = tier_scores.get(priority, 50)

    with connect() as c:
        grp = c.execute("SELECT * FROM complaint_groups WHERE id=?", (gid,)).fetchone()
        if not grp:
            return None
        grp = dict(grp)
        prev_priority = grp['priority']
        override_reason = reason or f"Priority manually overridden to {priority} by {updated_by}"

        c.execute("""
            UPDATE complaint_groups
            SET priority=?, priority_score=?, priority_override=1, priority_override_reason=?,
                priority_override_by=?, priority_override_at=?, priority_reason=?, updated_at=?
            WHERE id=?
        """, (priority, score, override_reason, updated_by, now, override_reason, now, gid))

        c.execute("""
            UPDATE complaints
            SET priority=?, priority_score=?, priority_override=1, priority_reason=?, updated_at=?
            WHERE group_id=?
        """, (priority, score, override_reason, now, gid))

        linked = c.execute("SELECT id, reference FROM complaints WHERE group_id=?", (gid,)).fetchall()
        for comp in linked:
            c.execute("""
                INSERT INTO citizen_notifications
                (complaint_id, complaint_reference, group_id, group_reference, notification_type, title, message, status, sent_at)
                VALUES (?, ?, ?, ?, 'priority_changed', ?, ?, 'Delivered', ?)
            """, (comp['id'], comp['reference'], gid, grp['reference'],
                  f"Priority Escalation: {priority}",
                  f"Consolidated issue '{grp['title']}' priority updated from {prev_priority} to {priority}. Reason: {override_reason}",
                  now))
        c.commit()
        return get_complaint_group(gid)


def get_complaints_by_group_id(gid):
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM complaints WHERE group_id=? ORDER BY created_at ASC", (gid,)).fetchall()]


def link_complaint_to_group(cid, gid):
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with connect() as c:
        comp = c.execute("SELECT created_at, latitude, longitude, ward_name, address FROM complaints WHERE id=?", (cid,)).fetchone()
        if not comp:
            return False
        c.execute("UPDATE complaints SET group_id=?, updated_at=? WHERE id=?", (gid, now, cid))

        stats = c.execute("SELECT COUNT(*) as cnt, MIN(created_at) as min_date, MAX(created_at) as max_date FROM complaints WHERE group_id=?", (gid,)).fetchone()
        grp = c.execute("SELECT latitude, longitude, ward_name, address FROM complaint_groups WHERE id=?", (gid,)).fetchone()

        new_lat = grp['latitude'] if grp['latitude'] is not None else comp['latitude']
        new_lon = grp['longitude'] if grp['longitude'] is not None else comp['longitude']
        new_ward = grp['ward_name'] or comp['ward_name']
        new_addr = grp['address'] or comp['address']

        c.execute("""UPDATE complaint_groups 
            SET complaints_count=?, first_reported_at=?, last_reported_at=?, latitude=?, longitude=?, ward_name=?, address=?, updated_at=?
            WHERE id=?""",
            (stats['cnt'], stats['min_date'], stats['max_date'], new_lat, new_lon, new_ward, new_addr, now, gid))
        c.commit()
        return True


def update_group_status(gid, status, remarks=None, updated_by='Admin', assigned_department=None, assigned_officer=None):
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with connect() as c:
        grp = c.execute("SELECT * FROM complaint_groups WHERE id=?", (gid,)).fetchone()
        if not grp:
            return None
        grp = dict(grp)
        previous_status = grp['status']

        update_fields = ["status=?", "updated_at=?"]
        params = [status, now]

        if assigned_department is not None:
            update_fields.append("assigned_department=?")
            params.append(assigned_department)
        if assigned_officer is not None:
            update_fields.append("assigned_officer=?")
            params.append(assigned_officer)

        params.append(gid)
        c.execute(f"UPDATE complaint_groups SET {', '.join(update_fields)} WHERE id=?", params)

        linked = [dict(r) for r in c.execute("SELECT * FROM complaints WHERE group_id=?", (gid,)).fetchall()]

        for comp in linked:
            comp_id = comp['id']
            c.execute("UPDATE complaints SET status=?, updated_at=? WHERE id=?", (status, now, comp_id))
            c.execute("""INSERT INTO complaint_status_history
                (complaint_id, previous_status, new_status, remarks, updated_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (comp_id, comp['status'], status, remarks or f"Synchronized from consolidated issue {grp['reference']}", updated_by, now)
            )

            if status == 'Resolved':
                notif_type = 'issue_resolved'
                notif_title = f"Resolved: {grp['title']}"
                notif_msg = f"Your complaint ({comp['reference']}) regarding '{grp['title']}' has been resolved. {remarks or 'Resolution completed by civic department.'}"
            else:
                notif_type = 'status_updated'
                notif_title = f"Issue Updated: {status}"
                notif_msg = f"Your complaint ({comp['reference']}) part of consolidated issue '{grp['title']}' was updated to '{status}'. {remarks or ''}".strip()

            c.execute("""INSERT INTO citizen_notifications
                (complaint_id, complaint_reference, group_id, group_reference, notification_type, title, message, status, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Delivered', ?)""",
                (comp_id, comp['reference'], gid, grp['reference'], notif_type, notif_title, notif_msg, now)
            )

        c.commit()
        return get_complaint_group(gid)


def update_group_info(gid, title=None, summary=None, priority=None, priority_score=None, priority_reason=None, priority_factors=None):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as c:
        fields = ["updated_at=?"]
        params = [now]
        if title:
            fields.append("title=?")
            params.append(title)
        if summary:
            fields.append("summary=?")
            params.append(summary)
        if priority:
            fields.append("priority=?")
            params.append(priority)
        if priority_score is not None:
            fields.append("priority_score=?")
            params.append(priority_score)
        if priority_reason is not None:
            fields.append("priority_reason=?")
            params.append(priority_reason)
        if priority_factors is not None:
            fields.append("priority_factors=?")
            params.append(json.dumps(priority_factors) if isinstance(priority_factors, dict) else priority_factors)
        params.append(gid)
        c.execute(f"UPDATE complaint_groups SET {', '.join(fields)} WHERE id=?", params)
        c.commit()
        return get_complaint_group(gid)


def get_notifications_for_complaint(cid):
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM citizen_notifications WHERE complaint_id=? ORDER BY sent_at DESC, id DESC", (cid,)).fetchall()]


def get_notifications_for_group(gid):
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM citizen_notifications WHERE group_id=? ORDER BY sent_at DESC, id DESC", (gid,)).fetchall()]


def replace_chunks(chunks):
    with connect() as c:
        c.execute("DELETE FROM rag_chunks")
        c.executemany("INSERT INTO rag_chunks(source_name,source_path,chunk_text,chunk_index,created_at) VALUES(?,?,?,?,?)", chunks)
        c.commit()


def get_chunks():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM rag_chunks ORDER BY id").fetchall()]
