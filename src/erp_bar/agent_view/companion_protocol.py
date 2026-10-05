"""Durable public event journal for the paired kiosk protocol; no model tokens."""
import json
from pathlib import Path
import sqlite3
import threading
import time

BUILD = '2026.10.05.1'
PROTOCOL = 2
PUBLIC_KINDS = {'mission_start', 'mission_end', 'session_idle', 'tool_start', 'tool_end',
                'instruction', 'agent_start', 'agent_end', 'handoff', 'connecting',
                'display_wait', 'display_ready', 'display_timeout', 'product_ready', 'product_error'}


class EventJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.condition = threading.Condition(threading.RLock())
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS companion_events (
                cursor INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT,
                kind TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL)''')
            db.execute('CREATE INDEX IF NOT EXISTS companion_events_mission ON companion_events(mission_id, cursor)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def append(self, event):
        if event.get('kind') not in PUBLIC_KINDS:
            return None
        with self.condition, self.connect() as db:
            cur = db.execute('INSERT INTO companion_events(mission_id,kind,payload,created) VALUES (?,?,?,?)',
                (event.get('mission_id'), event['kind'], json.dumps(event), time.time()))
            cursor = cur.lastrowid
        with self.condition:
            self.condition.notify_all()
        return cursor

    def latest(self):
        with self.connect() as db:
            return db.execute('SELECT COALESCE(MAX(cursor),0) FROM companion_events').fetchone()[0]

    def since(self, cursor, limit=250):
        with self.connect() as db:
            rows = db.execute('SELECT cursor,payload FROM companion_events WHERE cursor>? ORDER BY cursor LIMIT ?', (cursor, limit)).fetchall()
        return [{'cursor': row[0], 'event': json.loads(row[1])} for row in rows]

    def mission_events(self, mission_id):
        if not mission_id:
            return []
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM companion_events WHERE mission_id=? ORDER BY cursor', (mission_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def final(self, mission_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM companion_events WHERE mission_id=? AND kind='mission_end' ORDER BY cursor DESC LIMIT 1", (mission_id,)).fetchone()
        return json.loads(row[0]) if row else None
