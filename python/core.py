"""Transactional local reference workflows. Money is always integer cents."""
import hashlib, hmac, json, sqlite3, threading, time
from contextlib import contextmanager

class Problem(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)

class Engine:
    def __init__(self, database=':memory:', secret='local-fixture-signing-key'):
        self.db=sqlite3.connect(database,check_same_thread=False,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.lock=threading.RLock()
        self.secret=secret.encode()
        self.db.executescript("""
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS stock(sku TEXT PRIMARY KEY,quantity INTEGER NOT NULL CHECK(quantity>=0),version INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,sku TEXT,quantity INTEGER,status TEXT,version INTEGER,expires REAL);
        CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY,amount INTEGER,balance INTEGER);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,body TEXT,result TEXT);
        CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,invoice TEXT,amount INTEGER,status TEXT);
        CREATE TABLE IF NOT EXISTS grades(id TEXT PRIMARY KEY,student TEXT,score INTEGER,feedback TEXT,status TEXT,version INTEGER);
        CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,body TEXT,delivered INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT,action TEXT,detail TEXT);
        INSERT OR IGNORE INTO stock VALUES('BOOK',10,0);
        INSERT OR IGNORE INTO invoices VALUES('INV-100',10000,10000);
        INSERT OR IGNORE INTO invoices VALUES('INV-200',2500,2500);
        """)

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except Exception:
                self.db.execute('ROLLBACK')
                raise

    def record(self,actor,action,payload):
        self.db.execute('INSERT INTO audit(actor,action,detail) VALUES(?,?,?)',(actor,action,json.dumps(payload,sort_keys=True)))

    def integer(self,p,key,minimum=0):
        value=p.get(key)
        if type(value) is not int or value<minimum: raise Problem(422,f'{key} must be an integer >= {minimum}')
        return value

    def text(self,p,key):
        value=p.get(key)
        if not isinstance(value,str) or not value.strip() or len(value)>100: raise Problem(422,f'{key} is required (1-100 characters)')
        return value

    def signature(self,p):
        return hmac.new(self.secret,json.dumps(p,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()

    def _row(self,table,id):
        row=self.db.execute(f'SELECT * FROM {table} WHERE id=?',(id,)).fetchone()
        if row is None: raise Problem(404,'Record not found')
        return dict(row)

    def state(self):
        with self.lock:
            return {table:[dict(r) for r in self.db.execute(f'SELECT * FROM {table} ORDER BY 1')] for table in ['stock','orders','invoices','events','proposals','grades','outbox','audit']}

    def command(self,action,p,actor='learner'):
        with self.transaction():
            result=self._command(action,p,actor)
            self.record(actor,action,p)
            return result

    def _command(self,action,p,actor):
        if action=='reserve':
            id=self.text(p,'id'); sku=self.text(p,'sku'); qty=self.integer(p,'quantity',1)
            old=self.db.execute('SELECT * FROM orders WHERE id=?',(id,)).fetchone()
            if old:
                if old['sku']!=sku or old['quantity']!=qty: raise Problem(409,'Idempotency key reused with a different order')
                return dict(old)
            version=self.integer(p,'version')
            count=self.db.execute('UPDATE stock SET quantity=quantity-?,version=version+1 WHERE sku=? AND version=? AND quantity>=?',(qty,sku,version,qty)).rowcount
            if count!=1: raise Problem(409,'Insufficient stock or stale stock version')
            self.db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?)',(id,sku,qty,'reserved',0,time.time()+300))
            self.db.execute('INSERT INTO outbox(kind,body) VALUES(?,?)',('order.reserved',json.dumps({'id':id})))
            return self._row('orders',id)
        if action in ['cancel','ship','refund']:
            if actor!='operator': raise Problem(403,'Operator role required')
            id=self.text(p,'id'); row=self._row('orders',id)
            target={'cancel':'cancelled','ship':'shipped','refund':'refunded'}[action]
            if row['status']==target: return row
            expected='shipped' if action=='refund' else 'reserved'
            if row['status']!=expected or row['version']!=self.integer(p,'version'): raise Problem(409,'Invalid transition or stale order version')
            if action=='ship' and row['expires']<time.time(): raise Problem(409,'Reservation expired; cancel to release stock')
            if action=='cancel': self.db.execute('UPDATE stock SET quantity=quantity+?,version=version+1 WHERE sku=?',(row['quantity'],row['sku']))
            self.db.execute('UPDATE orders SET status=?,version=version+1 WHERE id=?',(target,id))
            self.db.execute('INSERT INTO outbox(kind,body) VALUES(?,?)',('order.'+target,json.dumps({'id':id})))
            return self._row('orders',id)
        if action=='relay':
            if actor!='operator': raise Problem(403,'Operator role required')
            rows=[dict(r) for r in self.db.execute('SELECT * FROM outbox WHERE delivered=0')]
            if p.get('simulateFailure'): raise Problem(503,'Relay fixture failure; pending messages retained')
            self.db.execute('UPDATE outbox SET delivered=1 WHERE delivered=0')
            return {'delivered':rows}
        if action=='callback':
            signature=p.get('signature',''); body={k:v for k,v in p.items() if k!='signature'}
            if not isinstance(signature,str) or not hmac.compare_digest(signature,self.signature(body)): raise Problem(401,'Invalid callback signature')
            id=self.text(body,'id'); invoice=self.text(body,'invoice'); amount=self.integer(body,'amount',1)
            encoded=json.dumps(body,sort_keys=True)
            old=self.db.execute('SELECT * FROM events WHERE id=?',(id,)).fetchone()
            if old:
                if old['body']!=encoded: raise Problem(409,'Event id reused with different payload')
                return json.loads(old['result'])
            row=self._row('invoices',invoice)
            status='matched' if amount==row['balance'] else 'exception'
            if status=='matched': self.db.execute('UPDATE invoices SET balance=0 WHERE id=?',(invoice,))
            result={'id':id,'status':status,'invoice':invoice,'amount':amount}
            self.db.execute('INSERT INTO events VALUES(?,?,?)',(id,encoded,json.dumps(result)))
            return result
        if action=='propose':
            if actor!='reviewer': raise Problem(403,'Reviewer role required')
            id=self.text(p,'id'); invoice=self.text(p,'invoice'); amount=self.integer(p,'amount',1)
            row=self._row('invoices',invoice)
            if amount>row['balance']: raise Problem(422,'Adjustment exceeds remaining balance')
            try: self.db.execute('INSERT INTO proposals VALUES(?,?,?,?)',(id,invoice,amount,'pending'))
            except sqlite3.IntegrityError: raise Problem(409,'Proposal already exists')
            return self._row('proposals',id)
        if action=='approve':
            if actor!='reviewer': raise Problem(403,'Reviewer role required')
            id=self.text(p,'id'); row=self._row('proposals',id)
            if row['status']=='approved': return row
            if self.db.execute('UPDATE invoices SET balance=balance-? WHERE id=? AND balance>=?',(row['amount'],row['invoice'],row['amount'])).rowcount!=1: raise Problem(409,'Balance changed; proposal requires review')
            self.db.execute('UPDATE proposals SET status=? WHERE id=?',('approved',id))
            return self._row('proposals',id)
        if action=='submit':
            id=self.text(p,'id'); student=self.text(p,'student'); answers=p.get('answers')
            if not isinstance(answers,list) or len(answers)!=3 or any(type(a) is not str for a in answers): raise Problem(422,'Exactly three answer strings are required')
            deadline=p.get('deadline')
            if type(deadline) not in (int,float) or deadline<time.time(): raise Problem(422,'Submission deadline has passed or is invalid')
            if actor not in ['learner','instructor']: raise Problem(403,'Learner role required')
            score=sum(a.strip().lower()==b for a,b in zip(answers,['transaction','idempotency','audit']))
            try:self.db.execute('INSERT INTO grades VALUES(?,?,?,?,?,?)',(id,student,score,'','pending',0))
            except sqlite3.IntegrityError: raise Problem(409,'Submission already exists')
            return self._row('grades',id)
        if action in ['feedback','publish']:
            if actor!='instructor': raise Problem(403,'Instructor role required')
            id=self.text(p,'id'); row=self._row('grades',id)
            if row['version']!=self.integer(p,'version'): raise Problem(409,'Stale assessment version')
            if action=='feedback':
                feedback=self.text(p,'feedback')
                self.db.execute('UPDATE grades SET feedback=?,status=?,version=version+1 WHERE id=?',(feedback,'review',id))
            else:
                if row['status']!='review' or not row['feedback']: raise Problem(409,'Feedback must be reviewed before publishing')
                self.db.execute('UPDATE grades SET status=?,version=version+1 WHERE id=?',('published',id))
            return self._row('grades',id)
        raise Problem(404,'Unknown action')
