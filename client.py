
#!/usr/bin/env python3
import socket, argparse, time, threading
from utils import send_msg, recv_msg, send_multicast_message, create_multicast_socket, MCAST_ADDR
import json, sys

def discover_primary(timeout=3.0):
    # listen for multicast PRIMARY announce for a short time
    s = create_multicast_socket()
    s.settimeout(timeout)
    try:
        while True:
            data, addr = s.recvfrom(65536)
            msg = json.loads(data.decode('utf-8'))
            if msg.get('type') == 'PRIMARY':
                return (addr[0], msg.get('tcp_port'))
    except Exception:
        return "Some error in discovering the primary server"

def run_client(name, host='127.0.0.1', port=9001):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    try:
        s.connect((host, port))
    except Exception as e:
        print("failed connect to server:", e)
        return
    send_msg(s, {'type':'HELLO','name':name})
    initial = recv_msg(s)
    if not initial:
        print("no response")
        s.close()
        return
    if initial.get('type') == 'REDIRECT':
        print("Server redirected to primary", initial)
        s.close()
        host = initial['host']; port = initial['port']
        print("connecting to", host, port)
        time.sleep(0.2)
        run_client(name, host, port)
        return
    print("Initial:", initial.get('note'))
    state = initial.get('state')
    if state:
        display_state(state)
    # start thread to read server messages
    t = threading.Thread(target=reader_thread, args=(s,), daemon=True)
    t.start()

    try:
        while True:
            cmd = input("cmd (move r c val / state / exit): ").strip()
            if cmd == 'exit':
                break
            if cmd == 'state':
                send_msg(s, {'type':'GET_STATE'})
                time.sleep(0.1)
                continue
            parts = cmd.split()
            if len(parts) == 4 and parts[0] == 'move':
                try:
                    r = int(parts[1]); c = int(parts[2]); val = int(parts[3])
                except:
                    print("invalid ints")
                    continue
                send_msg(s, {'type':'MOVE','r':r,'c':c,'val':val})
                time.sleep(0.1)
                continue
            print("unknown command")
    except KeyboardInterrupt:
        pass
    finally:
        try: s.close()
        except: pass

def reader_thread(sock):
    try:
        while True:
            msg = recv_msg(sock)
            if not msg:
                print("server closed")
                break
            mtype = msg.get('type')
            if mtype == 'STATE':
                display_state(msg.get('state'))
            elif mtype == 'MOVE_ACK':
                print("Move ack:", msg.get('result'), msg.get('reason', ''))
                if msg.get('state'):
                    display_state(msg.get('state'))
            elif mtype == 'ERROR':
                print("ERROR:", msg.get('error'))
            else:
                print("MSG:", msg)
    except Exception as e:
        print("reader error", e)

def display_state(state):
    print("=== GAME STATE v{} Round:{} ===".format(state.get('version'), state.get('round')))
    b = state.get('board')
    for r,row in enumerate(b):
        print(' '.join(str(x) if x!=0 else '_' for x in row))
    print("Scores:", state.get('scores'))
    print("=============================")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--host', default=None)
    parser.add_argument('--port', type=int, default=9001)
    args = parser.parse_args()

    if args.host is None:
        print("Discovering primary via multicast for 2s...")
        primary = discover_primary(timeout=2.0)
        if primary:
            host, port = primary
            print("Found primary at", host, port)
            run_client(args.name, host, port)
        else:
            print("No primary discovered; using default 127.0.0.1")
            run_client(args.name, '127.0.0.1', args.port)
    else:
        run_client(args.name, args.host, args.port)
