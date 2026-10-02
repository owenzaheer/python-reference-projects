import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','django_demo.settings')
import django
django.setup()
from rest_framework.test import APIClient
from django_demo import urls
from core import Engine

def test_csv_batch_rolls_back_after_invalid_second_row():
    urls.engine=Engine()
    client=APIClient();client.credentials(HTTP_AUTHORIZATION='Bearer local-operator')
    response=client.post('/api/import',{'csv':'id,sku,quantity,version\na,BOOK,2,0\nb,BOOK,99,1'},format='json')
    assert response.status_code==409
    assert urls.engine.state()['orders']==[]
    assert urls.engine.state()['stock'][0]['quantity']==10

def test_csv_permissions_success_and_replay():
    urls.engine=Engine()
    client=APIClient()
    assert client.post('/api/import',{'csv':'x'},format='json').status_code==403
    client.credentials(HTTP_AUTHORIZATION='Bearer local-operator')
    csv='id,sku,quantity,version\na,BOOK,2,0\nb,BOOK,1,1'
    assert client.post('/api/import',{'csv':csv},format='json').status_code==200
    assert client.post('/api/import',{'csv':csv},format='json').status_code==200
    assert urls.engine.state()['stock'][0]['quantity']==7
    assert client.get('/').status_code==200
