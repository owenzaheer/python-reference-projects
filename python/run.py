import argparse, json
from pathlib import Path
import uvicorn
from api import create_app
parser=argparse.ArgumentParser()
parser.add_argument('project')
parser.add_argument('--port',type=int,default=8000)
args=parser.parse_args()
config=Path(args.project)/'project.json'
if not config.exists(): config=Path(__file__).parent/args.project/'project.json'
uvicorn.run(create_app(config),host='127.0.0.1',port=args.port)
