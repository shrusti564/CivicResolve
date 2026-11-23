import sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "civicresolve.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def connect():
    conn = sqlite3.connect(DB_PATH)
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


def create_complaint(data):
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with connect() as c:
        cur = c.execute("""INSERT INTO complaints
            (reference,title,description,category,priority,status,latitude,longitude,address,ward_name,corporation,location_source,image_path,image_analysis,created_at,updated_at)
            VALUES (?,?,?,?,?,'Submitted',?,?,?,?,?,?,?,?,?,?)""",
            (data['reference'], data['title'], data['description'], data['category'], data.get('priority','Medium'),
             data.get('latitude'), data.get('longitude'), data.get('address'), data.get('ward_name'), data.get('corporation'),
             data.get('location_source','manual'), data.get('image_path'), data.get('image_analysis'), now, now))
        c.execute("""INSERT INTO complaint_status_history
            (complaint_id, previous_status, new_status, remarks, updated_by, created_at)
            VALUES (?, NULL, 'Submitted', NULL, ?, ?)""", (cur.lastrowid, 'Citizen', now))
        c.commit()
        return get_complaint_by_id(cur.lastrowid)


def get_complaint_by_id(cid):
    with connect() as c:
        row = c.execute("SELECT * FROM complaints WHERE id=?", (cid,)).fetchone()
        return dict(row) if row else None


def list_complaints():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM complaints ORDER BY created_at DESC").fetchall()]


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


def replace_chunks(chunks):
    with connect() as c:
        c.execute("DELETE FROM rag_chunks")
        c.executemany("INSERT INTO rag_chunks(source_name,source_path,chunk_text,chunk_index,created_at) VALUES(?,?,?,?,?)", chunks)
        c.commit()


def get_chunks():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM rag_chunks ORDER BY id").fetchall()]
