import csv,io,json,os
from pathlib import Path
from django.http import HttpResponse
from django.urls import path
from rest_framework.decorators import api_view
from rest_framework.response import Response
from core import Engine,Problem

engine=Engine(os.getenv('DEMO_DATABASE',':memory:'))
root=Path(__file__).resolve().parents[2]
config=json.loads((root/'python/ecommerce-fulfillment-and-exception-portal-python/project.json').read_text(encoding='utf-8'))
roles={'Bearer local-learner':'learner','Bearer local-operator':'operator'}

def index(request):return HttpResponse((root/'ui/console.html').read_text(encoding='utf-8').replace('__CONFIG__',json.dumps(config)))

@api_view(['GET'])
def state(request):
    if roles.get(request.headers.get('Authorization'))!='operator':return Response({'detail':'Operator required'},status=403)
    return Response(engine.state())

@api_view(['POST'])
def command(request):
    role=roles.get(request.headers.get('Authorization'))
    if not role:return Response({'detail':'Explicit local fixture token required'},status=401)
    if request.data.get('action') not in config['actions']:return Response({'detail':'Action unavailable'},status=404)
    if not isinstance(request.data.get('payload'),dict):return Response({'detail':'Object payload required'},status=422)
    try:return Response(engine.command(request.data['action'],request.data['payload'],role))
    except Problem as e:return Response({'detail':e.message},status=e.status)

@api_view(['POST'])
def import_orders(request):
    if roles.get(request.headers.get('Authorization'))!='operator':return Response({'detail':'Operator required'},status=403)
    source=request.data.get('csv')
    if not isinstance(source,str) or len(source)>100000:return Response({'detail':'CSV string is required, maximum 100KB'},status=422)
    reader=csv.DictReader(io.StringIO(source))
    if reader.fieldnames!=['id','sku','quantity','version']:return Response({'detail':'Expected id,sku,quantity,version headers'},status=422)
    try:
        rows=list(reader)
        if not rows or len(rows)>100:return Response({'detail':'Import requires 1-100 rows'},status=422)
        normalized=[{'id':r['id'],'sku':r['sku'],'quantity':int(r['quantity']),'version':int(r['version'])} for r in rows]
        with engine.transaction():
            results=[engine._command('reserve',p,'operator') for p in normalized]
            engine.record('operator','csv.import',{'rows':len(results)})
        return Response({'imported':results})
    except (ValueError,TypeError,KeyError):return Response({'detail':'Invalid CSV row values'},status=422)
    except Problem as e:return Response({'detail':e.message},status=e.status)

urlpatterns=[path('',index),path('api/state',state),path('api/action',command),path('api/import',import_orders),path('api/config',lambda r:HttpResponse(json.dumps(config),content_type='application/json')),path('api/health',lambda r:HttpResponse('{"status":"ok","framework":"Django/DRF"}',content_type='application/json'))]
