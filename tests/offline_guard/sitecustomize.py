"""Acceptance-test process guard. Allows loopback only, never DNS or external sockets."""
import socket
_original=socket.socket.connect
_original_ex=socket.socket.connect_ex
_original_dns=socket.getaddrinfo
ALLOWED={'127.0.0.1','::1','localhost',None}
def check(address):
    if isinstance(address,tuple) and address[0] not in ALLOWED:raise OSError('External networking is disabled in participant acceptance tests')
def connect(self,address):check(address);return _original(self,address)
def connect_ex(self,address):check(address);return _original_ex(self,address)
def dns(host,*args,**kwargs):
    if host not in ALLOWED:raise OSError('External DNS is disabled in participant acceptance tests')
    return _original_dns(host,*args,**kwargs)
socket.socket.connect=connect;socket.socket.connect_ex=connect_ex;socket.getaddrinfo=dns
