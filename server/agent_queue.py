"""FIFO per conversation, leased/fenced Agent turns; never mutates baseline runs."""
import json
from uuid import uuid4
from sqlalchemy import text
from server.uploads import APIError


class AgentLeaseLost(Exception):
    pass


class AgentQueue:
    def __init__(self, engine, lease_seconds=90):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError('Invalid lease duration')
        self.engine, self.lease_seconds = engine, lease_seconds

    def event(self, c, conversation_id, turn_id, kind, payload):
        seq = c.execute(text('UPDATE conversations SET next_seq=next_seq+1 WHERE id=:id RETURNING next_seq-1'),
                        {'id': conversation_id}).scalar_one()
        c.execute(text('''INSERT INTO conversation_events(conversation_id,seq,turn_id,kind,payload)
                          VALUES(:cid,:seq,:tid,:kind,CAST(:payload AS jsonb))'''),
                  {'cid': conversation_id, 'seq': seq, 'tid': turn_id, 'kind': kind,
                   'payload': json.dumps(payload, allow_nan=False)})
        return seq

    def claim(self, worker_id):
        if not worker_id or len(worker_id)>200:
            raise ValueError('Invalid worker identity')
        with self.engine.begin() as c:
            head = c.execute(text('''SELECT v.id FROM conversations v
                JOIN LATERAL (SELECT status,lease_until FROM agent_turns t
                  WHERE t.conversation_id=v.id AND t.status IN ('queued','running') ORDER BY ordinal LIMIT 1) h ON true
                WHERE h.status='queued' OR h.lease_until<=clock_timestamp()
                ORDER BY v.created_at,v.id FOR UPDATE OF v SKIP LOCKED LIMIT 1''')).scalar_one_or_none()
            if head is None:
                return None
            row = c.execute(text("""SELECT *,lease_until>clock_timestamp() AS lease_active
                FROM agent_turns WHERE conversation_id=:cid
                AND status IN ('queued','running') ORDER BY ordinal LIMIT 1 FOR UPDATE"""), {'cid': head}).mappings().one_or_none()
            # The lateral eligibility read can precede another claimant's commit.
            # Recheck the current head after obtaining the conversation lock.
            if row is None or (row['status']=='running' and row['lease_active']):
                return None
            if row['status']=='running':
                c.execute(text("UPDATE agent_turn_attempts SET finished_at=clock_timestamp(),outcome='lease_expired' WHERE turn_id=:id AND fence=:f"), {'id':row['id'],'f':row['fence']})
            if row['fence']>=row['max_attempts']:
                c.execute(text("UPDATE agent_turns SET status='failed',error=CAST(:error AS jsonb),lease_until=NULL,worker_id=NULL WHERE id=:id"), {'id':row['id'],'error':json.dumps({'code':'AGENT_RETRY_LIMIT'})})
                self.event(c,head,row['id'],'turn_failed',{'code':'AGENT_RETRY_LIMIT'})
                return None
            turn = dict(c.execute(text("""UPDATE agent_turns SET status='running',worker_id=:worker,
                fence=fence+1,lease_until=clock_timestamp()+:seconds*interval '1 second'
                WHERE id=:id RETURNING *"""), {'worker':worker_id,'seconds':self.lease_seconds,'id':row['id']}).mappings().one())
            c.execute(text('INSERT INTO agent_turn_attempts(turn_id,fence,worker_id) VALUES(:id,:f,:w)'),
                      {'id':turn['id'],'f':turn['fence'],'w':worker_id})
            self.event(c,head,turn['id'],'turn_running',{'fence':turn['fence']})
            return turn

    def owned(self, c, claim):
        c.execute(text('SELECT id FROM conversations WHERE id=:id FOR UPDATE'), {'id':claim['conversation_id']}).scalar_one()
        row = c.execute(text("""SELECT * FROM agent_turns WHERE id=:id AND conversation_id=:cid
          AND status='running' AND fence=:f AND worker_id=:w AND lease_until>clock_timestamp() FOR UPDATE"""),
          {'id':claim['id'],'cid':claim['conversation_id'],'f':claim['fence'],'w':claim['worker_id']}).mappings().one_or_none()
        if row is None:
            raise AgentLeaseLost()
        return row

    def heartbeat(self, claim):
        with self.engine.begin() as c:
            self.owned(c,claim)
            c.execute(text("UPDATE agent_turns SET lease_until=clock_timestamp()+:s*interval '1 second' WHERE id=:id"),
                      {'s':self.lease_seconds,'id':claim['id']})

    def fail(self, claim, code):
        allowed={'AGENT_MODEL_FAILED','AGENT_CANCELLED','AGENT_TIMEOUT','AGENT_REFERENCE_INVALID','AGENT_OUTPUT_LIMIT',
                 'AGENT_STEP_LIMIT','OPENROUTER_NOT_CONFIGURED','AGENT_CONTEXT_LIMIT','AGENT_WORKER_FAILED','AGENT_RUNTIME_CONFIG_CHANGED'}
        if code not in allowed:
            code='AGENT_WORKER_FAILED'
        with self.engine.begin() as c:
            row=self.owned(c,claim)
            c.execute(text("UPDATE agent_turns SET status='failed',error=CAST(:error AS jsonb),lease_until=NULL,worker_id=NULL WHERE id=:id"),
                      {'id':row['id'],'error':json.dumps({'code':code})})
            c.execute(text("UPDATE agent_turn_attempts SET finished_at=clock_timestamp(),outcome='failed' WHERE turn_id=:id AND fence=:f"),{'id':row['id'],'f':row['fence']})
            self.event(c,row['conversation_id'],row['id'],'turn_failed',{'code':code})

    def finish(self, claim, content):
        if not isinstance(content,str) or not content.strip() or len(content)>20000:
            raise APIError('INVALID_ASSISTANT_MESSAGE',422)
        with self.engine.begin() as c:
            row=self.owned(c,claim)
            context={'selected_run_id':str(row['selected_run_id']),'selected_candidate_id':row['selected_candidate_id'],
                     'report_version':row['report_version']}
            identity=uuid4()
            seq=self.event(c,row['conversation_id'],row['id'],'message_created',
                {'message_id':str(identity),'role':'assistant','content':content,'context':context})
            c.execute(text('''INSERT INTO messages(id,conversation_id,turn_id,seq,role,content,context)
                VALUES(:id,:cid,:tid,:seq,'assistant',:content,CAST(:context AS jsonb))'''),
                {'id':identity,'cid':row['conversation_id'],'tid':row['id'],'seq':seq,'content':content,'context':json.dumps(context)})
            self.owned(c,claim)  # Do not publish if the lease expired during the transaction.
            c.execute(text("UPDATE agent_turns SET status='succeeded',lease_until=NULL,worker_id=NULL WHERE id=:id"),{'id':row['id']})
            c.execute(text("UPDATE agent_turn_attempts SET finished_at=clock_timestamp(),outcome='succeeded' WHERE turn_id=:id AND fence=:f"),{'id':row['id'],'f':row['fence']})
            self.event(c,row['conversation_id'],row['id'],'turn_succeeded',{})
