from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from api import create_app
app=create_app(Path(__file__).with_name('project.json'))
