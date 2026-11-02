"""Loopback-only standard-library service. Static assets are bundled; no outbound clients."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from http.cookies import SimpleCookie
import argparse
import json
import os
import secrets
import sqlite3
import sys
import webbrowser
from contracts.offline_bundle.v1.canonical import loads
from .app import ParticipantApp

STATIC=Path(__file__).resolve().parent/'static'
MAX_BODY=64*1024*1024

def make_server(app,port=0):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        server_version='ResonanceParticipant'
        def log_message(self,*args):pass  # No listening data, URLs or session tokens in logs.
        def respond(self,status,body,media='application/json',cookie=None,filename=None):
            payload=json.dumps(body,ensure_ascii=False).encode() if media=='application/json' else body
            self.send_response(status);self.send_header('Content-Type',media);self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:self.send_header('Set-Cookie',cookie)
            if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
            self.end_headers();self.wfile.write(payload)
        def authorized(self):
            expected='127.0.0.1:'+str(self.server.server_port)
            if self.headers.get('Host')!=expected:raise PermissionError('Use the loopback address printed by the launcher')
            cookie=SimpleCookie()
            try:cookie.load(self.headers.get('Cookie',''))
            except Exception:raise PermissionError('Open the local app using its launch link')
            if 'resonance_local' not in cookie or not secrets.compare_digest(cookie['resonance_local'].value,token):raise PermissionError('Open the local app using its launch link')
            if self.command!='GET':
                if self.headers.get('Origin') not in {None,'http://'+expected}:raise PermissionError('Cross-origin writes are forbidden')
                if not secrets.compare_digest(self.headers.get('X-Resonance-Token',''),token):raise PermissionError('Local request token required')
        def body(self):
            length=self.headers.get('Content-Length','')
            if not length.isdigit() or int(length)>MAX_BODY:raise ValueError('Request is missing a valid bounded content length')
            data=self.rfile.read(int(length))
            if len(data)!=int(length):raise ValueError('Request body incomplete')
            return data
        def do_GET(self):
            try:
                parsed=urlparse(self.path)
                if parsed.path=='/' and parse_qs(parsed.query).get('session')==[token]:
                    expected='127.0.0.1:'+str(self.server.server_port)
                    if self.headers.get('Host')!=expected:raise PermissionError('Use the printed loopback address')
                    self.send_response(303);self.send_header('Location','/');self.send_header('Set-Cookie','resonance_local='+token+'; HttpOnly; SameSite=Strict; Path=/');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Length','0');self.end_headers();return
                self.authorized()
                if parsed.path=='/api/state':return self.respond(200,{**app.state(),'request_token':token})
                if parsed.path.startswith('/api/prompts/'):
                    return self.respond(200,app.prompt(parsed.path.split('/')[-1]))
                if parsed.path.startswith('/api/exports/'):
                    name,data=app.download(parsed.path.split('/')[-1]);return self.respond(200,data,'application/octet-stream',filename=name)
                assets={'/':'index.html','/app.js':'app.js','/style.css':'style.css'}
                if parsed.path in assets:
                    name=assets[parsed.path];media='text/html; charset=utf-8' if name.endswith('.html') else 'text/javascript; charset=utf-8' if name.endswith('.js') else 'text/css; charset=utf-8'
                    return self.respond(200,(STATIC/name).read_bytes(),media)
                self.respond(404,{'error':'Not found'})
            except PermissionError as e:self.respond(403,{'error':str(e)})
            except (ValueError,sqlite3.IntegrityError) as e:self.respond(409,{'error':str(e)})
        def do_POST(self):
            try:
                self.authorized();parsed=urlparse(self.path)
                if parsed.path=='/api/import':
                    params=parse_qs(parsed.query);return self.respond(200,app.ingest(self.body(),params.get('zip')==['1'],params.get('start',[None])[0],params.get('end',[None])[0]))
                body=loads(self.body())
                if not isinstance(body,dict):raise ValueError('Expected a JSON object')
                if parsed.path=='/api/config':result=app.configure(body['config'],body['expected_hash'],body.get('processing_consent'),body.get('share_history'))
                elif parsed.path=='/api/allocate':result=app.allocate()
                elif parsed.path=='/api/preview':result=app.preview(body.get('share_responses'))
                elif parsed.path=='/api/export':result=app.export(body['preview_id'],body['preview_hash'],body.get('confirmed'))
                elif parsed.path=='/api/erase':
                    if body.get('confirmation')!='DELETE MY LOCAL DATA':raise ValueError('Type the exact deletion confirmation')
                    app.store.erase();result={'erased':True,'notice':'Your local app data is deleted. Previously downloaded exports and researcher-held copies require separate deletion.'}
                elif parsed.path.startswith('/api/prompts/'):
                    parts=parsed.path.split('/');prompt=parts[3];action=parts[4] if len(parts)>4 else ''
                    if action=='draft':result=app.save_draft(prompt,body['answers'])
                    elif action=='followup-draft':result=app.save_followup_draft(prompt,body['answers'])
                    elif action=='neutral':result=app.neutral(prompt,body['answers'])
                    elif action=='followups':result=app.followups(prompt)
                    elif action=='followup':result=app.followup(prompt,body['answers'])
                    elif action=='finish':result=app.finish(prompt)
                    else:return self.respond(404,{'error':'Not found'})
                else:return self.respond(404,{'error':'Not found'})
                self.respond(200,result)
            except PermissionError as e:self.respond(403,{'error':str(e)})
            except (ValueError,KeyError,TypeError,sqlite3.IntegrityError) as e:self.respond(409,{'error':str(e) if not isinstance(e,KeyError) else 'Required field missing'})
            except Exception:self.respond(500,{'error':'The operation failed. Your previously saved records remain on this device.'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    return server,'http://127.0.0.1:'+str(server.server_port)+'/?session='+token

def main():
    parser=argparse.ArgumentParser(description='Resonance Participant — offline listening reflection')
    parser.add_argument('--data-dir',type=Path,default=Path.home()/'.local/share/resonance-participant')
    parser.add_argument('--port',type=int,default=8765);parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--study-config',type=Path);parser.add_argument('--config-sha256');parser.add_argument('--share-history',action='store_true')
    args=parser.parse_args()
    app=ParticipantApp(args.data_dir)
    if args.study_config:
        if not args.config_sha256:parser.error('The researcher-provided config fingerprint is required')
        app.configure(loads(args.study_config.read_bytes()),args.config_sha256,True,args.share_history)
    try:server,launch=make_server(app,args.port)
    except OSError:raise SystemExit('The local port is in use. Close the other instance or choose --port 8766.')
    print('Resonance Participant is running only on this computer.\n'+launch+'\nPress Ctrl+C to close. Saved progress remains on this device.',flush=True)
    if not args.no_browser:webbrowser.open(launch)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
