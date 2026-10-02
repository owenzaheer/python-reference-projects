import time, threading
import pytest
from core import Engine, Problem
from api import create_app
from fastapi.testclient import TestClient
from pathlib import Path

@pytest.fixture
def e():return Engine()

def fails(status,call):
    with pytest.raises(Problem) as ex:call()
    assert ex.value.status==status

def test_reserve_replay_and_conflict(e):
    p={'id':'order1','sku':'BOOK','quantity':3,'version':0}
    assert e.command('reserve',p)==e.command('reserve',p)
    assert e.state()['stock'][0]['quantity']==7
    fails(409,lambda:e.command('reserve',{**p,'quantity':2}))

def test_stock_concurrent_reservations(e):
    outcomes=[]
    def reserve(id):
        try:e.command('reserve',{'id':id,'sku':'BOOK','quantity':8,'version':0});outcomes.append(200)
        except Problem as ex:outcomes.append(ex.status)
    a=threading.Thread(target=reserve,args=('a',));b=threading.Thread(target=reserve,args=('b',))
    a.start();b.start();a.join();b.join()
    assert sorted(outcomes)==[200,409]
    assert e.state()['stock'][0]['quantity']==2

def test_cancel_once_and_role(e):
    e.command('reserve',{'id':'o','sku':'BOOK','quantity':2,'version':0})
    fails(403,lambda:e.command('cancel',{'id':'o','version':0}))
    e.command('cancel',{'id':'o','version':0},'operator')
    e.command('cancel',{'id':'o','version':0},'operator')
    assert e.state()['stock'][0]['quantity']==10

def test_expiry_and_outbox_retry(e):
    e.command('reserve',{'id':'o','sku':'BOOK','quantity':1,'version':0})
    e.db.execute('UPDATE orders SET expires=0')
    fails(409,lambda:e.command('ship',{'id':'o','version':0},'operator'))
    fails(503,lambda:e.command('relay',{'simulateFailure':True},'operator'))
    assert e.state()['outbox'][0]['delivered']==0
    assert len(e.command('relay',{},'operator')['delivered'])==1
    assert e.command('relay',{},'operator')['delivered']==[]

def test_signed_callback_dupes(e):
    body={'id':'payment','invoice':'INV-100','amount':10000}
    fails(401,lambda:e.command('callback',body))
    p={**body,'signature':e.signature(body)}
    assert e.command('callback',p)['status']=='matched'
    assert e.command('callback',p)['status']=='matched'
    assert e.state()['invoices'][0]['balance']==0
    changed={**body,'amount':9999}
    fails(409,lambda:e.command('callback',{**changed,'signature':e.signature(changed)}))

def test_exception_approval_and_balance_race(e):
    body={'id':'partial','invoice':'INV-100','amount':2000}
    assert e.command('callback',{**body,'signature':e.signature(body)})['status']=='exception'
    e.command('propose',{'id':'a','invoice':'INV-100','amount':8000},'reviewer')
    e.command('propose',{'id':'b','invoice':'INV-100','amount':8000},'reviewer')
    fails(403,lambda:e.command('approve',{'id':'a'}))
    e.command('approve',{'id':'a'},'reviewer')
    e.command('approve',{'id':'a'},'reviewer')
    fails(409,lambda:e.command('approve',{'id':'b'},'reviewer'))
    assert e.state()['invoices'][0]['balance']==2000
    assert e.state()['proposals'][1]['status']=='pending'

def test_deterministic_grade_and_human_review(e):
    p={'id':'s','student':'Student1','answers':['transaction','WRONG','audit'],'deadline':time.time()+60}
    assert e.command('submit',p)['score']==2
    fails(409,lambda:e.command('submit',p))
    fails(403,lambda:e.command('feedback',{'id':'s','version':0,'feedback':'Review source 2'}))
    fails(409,lambda:e.command('publish',{'id':'s','version':0},'instructor'))
    e.command('feedback',{'id':'s','version':0,'feedback':'Review source 2'},'instructor')
    fails(409,lambda:e.command('publish',{'id':'s','version':0},'instructor'))
    assert e.command('publish',{'id':'s','version':1},'instructor')['score']==2

def test_invalid_money_deadline_and_persistence(tmp_path):
    e=Engine(str(tmp_path/'local.db'))
    fails(422,lambda:e.command('reserve',{'id':'o','sku':'BOOK','quantity':True,'version':0}))
    fails(422,lambda:e.command('submit',{'id':'s','student':'S','answers':['x']*3,'deadline':0}))
    e.command('reserve',{'id':'o','sku':'BOOK','quantity':1,'version':0})
    assert Engine(str(tmp_path/'local.db')).state()['stock'][0]['quantity']==9

@pytest.mark.parametrize('project',list(Path(__file__).parent.glob('*/project.json')))
def test_every_python_api_is_runnable_and_scoped(project):
    client=TestClient(create_app(project))
    assert client.get('/api/health').status_code==200
    assert client.get('/').status_code==200
    assert client.get('/api/state').status_code==403
    assert client.post('/api/action',json={'action':'relay','payload':{}}).status_code==401
    assert client.post('/api/action',json={'action':'UNAVAILABLE','payload':{}},headers={'Authorization':'Bearer local-operator'}).status_code==404
