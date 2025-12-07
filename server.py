
#!/usr/bin/env python3
import argparse
import socket
import threading
import time
import json
import sys
from utils import create_multicast_socket, send_multicast_message, send_msg, recv_msg, MCAST_ADDR
from game import GameState

# Message types on multicast:
# HELLO {type:'HELLO', node_id, tcp_port, replication_port}
# PRIMARY_ANNOUNCE {type:'PRIMARY', node_id, tcp_port, replication_port}
# HEARTBEAT {type:'HEARTBEAT', node_id}
# ELECTION {type:'ELECTION', node_id}
# ELECTION_OK {type:'ELECTION_OK', node_id}

HEARTBEAT_INTERVAL = 1.0
HEARTBEAT_TIMEOUT = 3.0

class ServerNode:
    def __init__(self, node_id, host='0.0.0.0', tcp_port=9001, replication_port=9101):
        self.node_id = int(node_id)
        self.host = host
        self.tcp_port = tcp_port
        self.replication_port = replication_port
        self.is_primary = False
        self.known_nodes = {}  # node_id -> (host, tcp_port, replication_port, last_seen)
        self.primary_info = None
        self.mcast_sock = create_multicast_socket()
        self.mcast_running = True
        self.game = GameState(n=3, blanks=3)
        self.replication_sockets = {}  # node_id -> socket (for primary to send updates)
        self.backup_connections = {}  # for backups to primary (not used as dict here)
        self.client_handlers = []
        self.clients = {}  # client socket -> name
        self.lock = threading.Lock()
        self.server_sock = None
        self.replication_server_sock = None
        self.stop_event = threading.Event()

    def start(self):
        print(f"[{self.node_id}] starting node. tcp:{self.tcp_port} repl:{self.replication_port}")
        threading.Thread(target=self._mcast_listener, daemon=True).start()
        time.sleep(0.2)
        # announce presence
        send_multicast_message({'type':'HELLO','node_id':self.node_id,'tcp_port':self.tcp_port,'replication_port':self.replication_port})
        # small delay to collect HELLOs
        threading.Thread(target=self._heartbeat_sender, daemon=True).start()
        threading.Thread(target=self._heartbeat_checker, daemon=True).start()
        # start TCP servers for clients and replication
        threading.Thread(target=self._start_tcp_servers, daemon=True).start()
        # start election after short delay
        time.sleep(0.5)
        threading.Thread(target=self._start_election_if_needed, daemon=True).start()

    def _mcast_listener(self):
        print(f"[{self.node_id}] multicast listener started")
        while self.mcast_running:
            try:
                data, addr = self.mcast_sock.recvfrom(65536)
                msg = json.loads(data.decode('utf-8'))
                t = msg.get('type')
                nid = msg.get('node_id')
                if t == 'HELLO':
                    self.known_nodes[nid] = (addr[0], msg['tcp_port'], msg['replication_port'], time.time())
                elif t == 'PRIMARY':
                    # primary announce
                    self.primary_info = (nid, addr[0], msg['tcp_port'], msg['replication_port'])
                    print(f"[{self.node_id}] saw primary announce: {self.primary_info}")
                elif t == 'HEARTBEAT':
                    # primary heartbeat - update last seen
                    if nid in self.known_nodes:
                        host, tcp, repl, _ = self.known_nodes[nid]
                        self.known_nodes[nid] = (host, tcp, repl, time.time())
                    else:
                        self.known_nodes[nid] = (addr[0], msg.get('tcp_port', None), msg.get('replication_port', None), time.time())
                elif t == 'ELECTION':
                    # if we have higher id, reply OK
                    if self.node_id > nid:
                        send_multicast_message({'type':'ELECTION_OK','node_id':self.node_id})
                        # start our own election
                        threading.Thread(target=self._start_election_if_needed, daemon=True).start()
                elif t == 'ELECTION_OK':
                    # someone higher exists
                    pass
            except Exception as e:
                # ignore for clean shutdown
                if not self.stop_event.is_set():
                    print(f"[{self.node_id}] mcast listen error: {e}")

    def _heartbeat_sender(self):
        while not self.stop_event.is_set():
            send_multicast_message({'type':'HEARTBEAT','node_id':self.node_id,'tcp_port':self.tcp_port,'replication_port':self.replication_port})
            time.sleep(HEARTBEAT_INTERVAL)

    def _heartbeat_checker(self):
        while not self.stop_event.is_set():
            now = time.time()
            # find primary in known nodes
            primary = None
            for nid, (host,tcp,repl,last) in list(self.known_nodes.items()):
                if now - last > HEARTBEAT_TIMEOUT:
                    print(f"[{self.node_id}] node {nid} timed out (last {last})")
                    del self.known_nodes[nid]
            # check primary heartbeat via primary_info if set
            if self.primary_info:
                pid, host, tcp, repl = self.primary_info
                # if we haven't seen primary recently
                last = self.known_nodes.get(pid, (None,None,None,0))[3]
                if now - last > HEARTBEAT_TIMEOUT:
                    print(f"[{self.node_id}] primary {pid} heartbeat missing -> start election")
                    self.primary_info = None
                    threading.Thread(target=self._start_election_if_needed, daemon=True).start()
            time.sleep(1.0)

    def _start_tcp_servers(self):
        # client server
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.tcp_port))
        s.listen(8)
        self.server_sock = s
        print(f"[{self.node_id}] client TCP server listening on {self.tcp_port}")
        threading.Thread(target=self._accept_clients, daemon=True).start()
        # replication server (primary will accept connections from backups)
        rs = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        rs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rs.bind((self.host, self.replication_port))
        rs.listen(8)
        self.replication_server_sock = rs
        print(f"[{self.node_id}] replication TCP server listening on {self.replication_port}")
        threading.Thread(target=self._accept_replication_connections, daemon=True).start()

    def _accept_clients(self):
        while not self.stop_event.is_set():
            try:
                client_sock, addr = self.server_sock.accept()
                print(f"[{self.node_id}] client connected {addr}")
                t = threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True)
                t.start()
                self.client_handlers.append(t)
            except Exception as e:
                if not self.stop_event.is_set():
                    print(f"[{self.node_id}] accept client error: {e}")

    def _handle_client(self, sock):
        try:
            # simple handshake: expect {'type':'HELLO','name':...}
            hello = recv_msg(sock)
            if not hello:
                sock.close()
                return
            name = hello.get('name','anon')
            with self.lock:
                self.clients[sock] = name
                self.game.scores.setdefault(name, 0)
            # send initial state (if primary known)
            # If I'm primary, serve; if backup, redirect client to primary
            if not self.is_primary:
                # if we know primary, tell client to connect to primary
                if self.primary_info:
                    pid, phost, ptcp, prepl = self.primary_info
                    send_msg(sock, {'type':'REDIRECT','host':phost,'port':ptcp,'reason':'not_primary'})
                    sock.close()
                    return
                else:
                    # no primary known yet: accept as spectator
                    send_msg(sock, {'type':'STATE','state': self.game.as_dict(), 'note':'spectator'})
            else:
                send_msg(sock, {'type':'STATE','state': self.game.as_dict(), 'note':'primary'})

            while True:
                msg = recv_msg(sock)
                if not msg:
                    break
                mtype = msg.get('type')
                if mtype == 'MOVE':
                    r = msg.get('r'); c = msg.get('c'); val = msg.get('val')
                    player = name
                    # only primary accepts moves
                    if not self.is_primary:
                        send_msg(sock, {'type':'ERROR','error':'not_primary'})
                        continue
                    ok, reason = self.game.apply_move(player, r, c, val)
                    # after applying, broadcast updated state to clients and replicate to backups
                    state = self.game.as_dict()
                    if ok:
                        send_msg(sock, {'type':'MOVE_ACK','result':'ok','state':state})
                        self._broadcast_state_to_clients(state)
                        self._replicate_state_to_backups(state)
                    else:
                        send_msg(sock, {'type':'MOVE_ACK','result':'fail','reason':reason,'state':state})
                elif mtype == 'GET_STATE':
                    send_msg(sock, {'type':'STATE','state': self.game.as_dict()})
                else:
                    send_msg(sock, {'type':'ERROR','error':'unknown'})
        except Exception as e:
            print(f"[{self.node_id}] client handler error: {e}")
        finally:
            with self.lock:
                if sock in self.clients:
                    del self.clients[sock]
            try:
                sock.close()
            except:
                pass

    def _broadcast_state_to_clients(self, state):
        # send STATE to all connected clients
        for sock, name in list(self.clients.items()):
            try:
                send_msg(sock, {'type':'STATE','state':state})
            except:
                # client dead
                try:
                    sock.close()
                except:
                    pass
                del self.clients[sock]

    def _accept_replication_connections(self):
        # This accepts connections but used primarily to let backups connect to primary's replication port.
        while not self.stop_event.is_set():
            try:
                conn, addr = self.replication_server_sock.accept()
                # store last bytes to identify node? We'll accept and store socket for primary to write if we are primary
                print(f"[{self.node_id}] replication incoming connection from {addr}")
                # For simplicity: store and keep reading in thread if backup -> primary
                t = threading.Thread(target=self._handle_replication_conn, args=(conn,), daemon=True)
                t.start()
            except Exception as e:
                if not self.stop_event.is_set():
                    print(f"[{self.node_id}] accept replication error: {e}")

    def _handle_replication_conn(self, conn):
        # If we are backup connecting to primary's replication port, primary will send STATE updates.
        # If we are primary and a backup connected to us, we keep the socket to write updates out.
        # First message from connecting peer should be {'type':'REPL_HELLO','node_id':...}
        hello = recv_msg(conn)
        if not hello:
            conn.close()
            return
        if hello.get('role') == 'backup':
            # backup connected to primary: store socket for writing
            peer_id = hello.get('node_id')
            print(f"[{self.node_id}] backup {peer_id} connected for replication")
            self.replication_sockets[peer_id] = conn
            # keep connection alive
            try:
                while True:
                    time.sleep(1.0)
                    # optionally read keepalive
                    # try receiving (non-block) to detect closure
                    conn.settimeout(0.1)
                    try:
                        dat = conn.recv(1)
                        if not dat:
                            break
                        # else ignore
                    except socket.timeout:
                        pass
                    except Exception:
                        break
            finally:
                print(f"[{self.node_id}] replication socket for {peer_id} closed")
                if peer_id in self.replication_sockets:
                    del self.replication_sockets[peer_id]
                try: conn.close()
                except: pass
        elif hello.get('role') == 'primary':
            # we are backup connecting to primary: receive state updates
            print(f"[{self.node_id}] connected as backup to primary replication socket")
            try:
                while True:
                    msg = recv_msg(conn)
                    if not msg:
                        break
                    if msg.get('type') == 'STATE_UPDATE':
                        state = msg.get('state')
                        print(f"[{self.node_id}] received state update v{state.get('version')}")
                        self.game.set_state(state)
                        # update primary_info from hello meta if present
                        # continue loop
            except Exception as e:
                print(f"[{self.node_id}] replication read error: {e}")
            finally:
                try: conn.close()
                except: pass
        else:
            conn.close()

    def _replicate_state_to_backups(self, state):
        # primary writes full state to each connected backup
        for nid, sock in list(self.replication_sockets.items()):
            try:
                send_msg(sock, {'type':'STATE_UPDATE','state':state})
            except Exception as e:
                print(f"[{self.node_id}] replication write to {nid} failed: {e}")
                try:
                    sock.close()
                except:
                    pass
                del self.replication_sockets[nid]

    def _start_election_if_needed(self):
        # simple bully: if we are max id among known nodes+us, become primary
        highest = self.node_id
        for nid in self.known_nodes.keys():
            if nid > highest:
                highest = nid
        if highest == self.node_id:
            # become primary
            self._become_primary()
        else:
            # else wait for primary announce; if none after timeout, start election
            print(f"[{self.node_id}] higher node exists -> waiting for primary")
            # wait for primary announce for a while
            t0 = time.time()
            while time.time() - t0 < 3.0:
                if self.primary_info:
                    return
                time.sleep(0.2)
            # if still none, broadcast ELECTION
            send_multicast_message({'type':'ELECTION','node_id':self.node_id})
            # wait short for OK messages
            t1 = time.time()
            got_ok = False
            while time.time() - t1 < 2.0:
                # during this time, mcast listener may receive ELECTION_OK and spawn higher election
                time.sleep(0.1)
            # after waiting, if no primary_info, check again
            if not self.primary_info:
                # determine again
                highest = self.node_id
                for nid in self.known_nodes.keys():
                    if nid > highest:
                        highest = nid
                if highest == self.node_id:
                    self._become_primary()

    def _become_primary(self):
        self.is_primary = True
        self.primary_info = (self.node_id, '127.0.0.1', self.tcp_port, self.replication_port)
        print(f"[{self.node_id}] I am becoming primary")
        send_multicast_message({'type':'PRIMARY','node_id':self.node_id,'tcp_port':self.tcp_port,'replication_port':self.replication_port})
        # accept backup replication connections: backups will connect to my replication port
        # Additionally, attempt to connect to other nodes' replication ports? Not necessary.
        # If backups existed and previously connected to me, replication sockets will be populated in _accept_replication_connections.
        # Nothing else to do special here.

    def connect_to_primary_for_replication(self, primary_host, primary_repl_port):
        # called when this node is backup: connect to primary's replication port and send REPL_HELLO role=backup
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((primary_host, primary_repl_port))
            send_msg(s, {'role':'backup','node_id':self.node_id})
            # store socket so primary can write? No: primary stores incoming sockets. Here backup must listen for incoming STATE_UPDATE messages.
            # Start background thread to receive state updates from primary
            t = threading.Thread(target=self._handle_replication_conn, args=(s,), daemon=True)
            t.start()
            self.backup_connections['primary'] = s
        except Exception as e:
            print(f"[{self.node_id}] failed to connect to primary repl {primary_host}:{primary_repl_port} -> {e}")

    def stop(self):
        self.stop_event.set()
        self.mcast_running = False
        try:
            self.mcast_sock.close()
        except:
            pass
        try:
            if self.server_sock:
                self.server_sock.close()
        except:
            pass
        try:
            if self.replication_server_sock:
                self.replication_server_sock.close()
        except:
            pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', required=True, type=int, help='numeric node id')
    parser.add_argument('--tcp-port', type=int, default=9001)
    parser.add_argument('--replication-port', type=int, default=9101)
    args = parser.parse_args()

    node = ServerNode(node_id=args.id, tcp_port=args.tcp_port, replication_port=args.replication_port)
    try:
        node.start()
        print("server running. press Ctrl+C to stop")
        while True:
            time.sleep(1.0)
            # if backup and primary_info known, and not connected for replication, try to connect
            if not node.is_primary and node.primary_info and 'primary' not in node.backup_connections:
                pid, phost, ptcp, prepl = node.primary_info
                node.connect_to_primary_for_replication(phost, prepl)
    except KeyboardInterrupt:
        print("shutting down")
        node.stop()
        sys.exit(0)
