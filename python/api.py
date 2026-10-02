import json, os
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from core import Engine, Problem

class Command(BaseModel):
    action: str = Field(min_length=1,max_length=30)
    payload: dict

def create_app(config_path):
    config=json.loads(Path(config_path).read_text(encoding='utf-8'))
    engine=Engine(os.getenv('DEMO_DATABASE',':memory:'))
    app=FastAPI(title=config['title'],description='Local demo with synthetic data. Token roles are fixtures, not production authentication.')
    app.state.engine=engine
    @app.get('/api/config')
    def project_config(): return config
    @app.get('/api/state')
    def state(authorization: str=Header(default='')):
        if authorization!='Bearer local-operator': raise HTTPException(403,'Operator token required to inspect audit records')
        return engine.state()
    @app.post('/api/action')
    def action(command:Command, authorization:str=Header(default='')):
        roles={'Bearer local-learner':'learner','Bearer local-operator':'operator','Bearer local-reviewer':'reviewer','Bearer local-instructor':'instructor'}
        role=roles.get(authorization)
        if role is None: raise HTTPException(401,'Use an explicit local fixture token')
        if command.action not in config['actions']: raise HTTPException(404,'Action unavailable in this project')
        try:return engine.command(command.action,command.payload,role)
        except Problem as e:raise HTTPException(e.status,e.message)
    @app.get('/api/health')
    def health():return {'status':'ok','project':config['id'],'storage':'SQLite','mode':'local synthetic demo'}
    @app.get('/',response_class=HTMLResponse)
    def page():
        ui=Path(__file__).resolve().parents[1]/'ui'/'console.html'
        return ui.read_text(encoding='utf-8').replace('__CONFIG__',json.dumps(config).replace('</',r'<\/'))
    return app
