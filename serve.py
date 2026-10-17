"""Production HTTP parsing via Waitress; reuses the tested request handlers."""
import io,os
from email.message import Message
from types import SimpleNamespace
from urllib.parse import quote
from http import HTTPStatus
from server import Handler

class Request(Handler):
    def __init__(self,environ):
        self.command=environ['REQUEST_METHOD']
        self.path=quote(environ.get('PATH_INFO','/'))+('?' + environ['QUERY_STRING'] if environ.get('QUERY_STRING') else '')
        self.headers=Message()
        for key,value in environ.items():
            if key.startswith('HTTP_'):self.headers[key[5:].replace('_','-')]=str(value)
        for key in ['CONTENT_TYPE','CONTENT_LENGTH']:
            if environ.get(key):self.headers[key.replace('_','-')]=str(environ[key])
        self.rfile=environ['wsgi.input'];self.wfile=io.BytesIO()
        self.server=SimpleNamespace(server_port=int(environ.get('SERVER_PORT','8080')))
        self.client_address=(environ.get('REMOTE_ADDR','unknown'),0)
        self.response_headers=[];self.status=500
    def send_response(self,code,message=None):self.status=code
    def send_header(self,name,value):self.response_headers.append((str(name),str(value)))
    def end_headers(self):pass

def application(environ,start_response):
    request=Request(environ);request.run(request.command)
    start_response(str(request.status)+' '+HTTPStatus(request.status).phrase,request.response_headers)
    return [b'' if request.command=='HEAD' else request.wfile.getvalue()]

if __name__=='__main__':
    from waitress import serve
    serve(application,host='0.0.0.0',port=int(os.environ.get('PORT','8080')),threads=4,
          max_request_body_size=16384,channel_timeout=30,expose_tracebacks=False,
          trusted_proxy='*',trusted_proxy_count=1,
          trusted_proxy_headers={'x-forwarded-for','x-forwarded-proto'},clear_untrusted_proxy_headers=True)
