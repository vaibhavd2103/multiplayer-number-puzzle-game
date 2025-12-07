
import socket
import struct
import json
import threading

MCAST_GRP = '224.1.1.1'
MCAST_PORT = 5007
MCAST_ADDR = (MCAST_GRP, MCAST_PORT)

def create_multicast_socket(bind=True, reuse=True):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    if reuse:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if bind:
        s.bind(('', MCAST_PORT))
    mreq = struct.pack('4sl', socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    return s

def send_multicast_message(msg_obj, addr=MCAST_ADDR):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    data = json.dumps(msg_obj).encode('utf-8')
    s.sendto(data, addr)
    s.close()

# Simple length-prefixed JSON framing for TCP
def send_msg(sock, obj):
    data = json.dumps(obj).encode('utf-8')
    length = len(data)
    sock.sendall(length.to_bytes(4, 'big') + data)

def recv_msg(sock):
    # read 4 bytes length
    buf = b''
    while len(buf) < 4:
        chunk = sock.recv(4 - len(buf))
        if not chunk:
            return None
        buf += chunk
    length = int.from_bytes(buf, 'big')
    data = b''
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            return None
        data += chunk
    return json.loads(data.decode('utf-8'))
