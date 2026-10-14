class EscalationStore:
    def __init__(self,repository):
        self.repository=repository
        with repository._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS unanswered_questions (
                    id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),
                    utterance_id TEXT,participant_id TEXT,speaker TEXT NOT NULL,question TEXT NOT NULL,
                    state TEXT NOT NULL,asked_at REAL NOT NULL,urgency_deadline REAL NOT NULL,
                    prompt_key TEXT NOT NULL,parent_message_id TEXT,thread_id TEXT,error TEXT
                );
                CREATE TABLE IF NOT EXISTS escalation_outbox (
                    id TEXT PRIMARY KEY,question_id TEXT UNIQUE NOT NULL REFERENCES unanswered_questions(id),
                    state TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,next_at REAL NOT NULL DEFAULT 0,
                    parent_message_id TEXT,thread_id TEXT,error TEXT
                );
                CREATE TABLE IF NOT EXISTS owner_replies (
                    id TEXT PRIMARY KEY,question_id TEXT NOT NULL REFERENCES unanswered_questions(id),
                    text TEXT NOT NULL,created_at TEXT NOT NULL,state TEXT NOT NULL,error TEXT
                );
            ''')

    def all(self,sql,args=()):
        with self.repository._connect() as db: return [dict(row) for row in db.execute(sql,args).fetchall()]

    def one(self,sql,args=()):
        rows=self.all(sql,args)
        return rows[0] if rows else None

    def execute(self,sql,args=()):
        with self.repository._connect() as db: return db.execute(sql,args).rowcount
