import json
from datetime import UTC,datetime
class DiscordStore:
    def __init__(self,repository):
        self.repository=repository
        with repository._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS discord_attendance(
                session_id TEXT PRIMARY KEY REFERENCES sessions(id),guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,
                generation TEXT NOT NULL,state TEXT NOT NULL,health_json TEXT NOT NULL DEFAULT '{}',
                muted INTEGER NOT NULL DEFAULT 0,started_at TEXT NOT NULL,ended_at TEXT,error TEXT,introduction TEXT NOT NULL DEFAULT 'pending');
            CREATE UNIQUE INDEX IF NOT EXISTS discord_one_call ON discord_attendance(guild_id) WHERE state IN ('joining','active','leaving');
            CREATE TABLE IF NOT EXISTS discord_interactions(id TEXT PRIMARY KEY,result_json TEXT NOT NULL);
            """)
    def one(self,sql,args=()):
        with self.repository._connect() as db:
            row=db.execute(sql,args).fetchone()
            return dict(row) if row else None
    def all(self,sql,args=()):
        with self.repository._connect() as db:return [dict(r) for r in db.execute(sql,args)]
    def execute(self,sql,args=()):
        with self.repository._connect() as db:return db.execute(sql,args).rowcount
    def active(self,guild):return self.one("SELECT * FROM discord_attendance WHERE guild_id=? AND state IN ('joining','active','leaving')",(guild,))
    def attendance(self,sid):return self.one('SELECT * FROM discord_attendance WHERE session_id=?',(sid,))
    def transition(self,sid,state,*,error=None,health=None):
        terminal=state in {'ended','failed','interrupted','budget_stopped'}
        with self.repository._connect() as db:
            db.execute('UPDATE discord_attendance SET state=?,error=?,ended_at=CASE WHEN ? THEN ? ELSE ended_at END,health_json=COALESCE(?,health_json) WHERE session_id=?',(state,error,terminal,datetime.now(UTC).isoformat(),json.dumps(health) if health is not None else None,sid))
            db.execute('UPDATE sessions SET status=? WHERE id=?',('ended' if terminal else 'active' if state=='active' else 'created',sid))
        self.repository.record_event(sid,'discord.attendance',{'state':state,'error':error})
