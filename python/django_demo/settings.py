SECRET_KEY='local-development-fixture-only'
DEBUG=False
ALLOWED_HOSTS=['localhost','127.0.0.1','testserver']
ROOT_URLCONF='django_demo.urls'
INSTALLED_APPS=['rest_framework']
MIDDLEWARE=['django.middleware.security.SecurityMiddleware']
REST_FRAMEWORK={'DEFAULT_AUTHENTICATION_CLASSES':[],'UNAUTHENTICATED_USER':None}
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}
