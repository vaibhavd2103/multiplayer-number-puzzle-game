# Distributed Multiplayer Number Puzzle (Course Project)

**What this is**

- A minimal distributed system implementing a multiplayer number puzzle.
- Demonstrates: TCP client-server, UDP multicast discovery & heartbeats, Bully leader election, primary-backup replication, concurrency control (locks), and simple fault tolerance.
- Implemented with plain Python sockets — **no third-party packages**.

**Project layout**

```
multiplayer_puzzle/
  server.py            # server node (primary/backup) entrypoint
  client.py            # CLI client to connect to primary and play
  game.py              # puzzle generation and game state
  utils.py             # message framing, sockets helpers
  run_examples.sh      # helper script to run example servers/clients (unix shells)
  README.md
```

**How it works (short)**

- Servers discover each other by joining a UDP multicast group (224.1.1.1:5007).
- Servers announce presence, and the one with highest `node_id` becomes primary (Bully-style).
- Primary accepts TCP clients on its `tcp_port`. Clients send moves; primary validates and updates state.
- After each valid move primary sends a STATE_UPDATE over persistent TCP replication connections to backups.
- Backups maintain replicated state and take over on primary failure (they run election and become primary if highest).
- Clients can discover primary via multicast announcements or by connecting directly to a known server.

**Important**

- This is a functional educational demo — not production-grade.
- Use separate terminals to run multiple servers and clients on the same machine (choose different node IDs and ports as instructed).

---

## Quick start (Linux / macOS)

Open three terminals.

1. Start first server (node id 1):

```
python3 server.py --id 1 --tcp-port 9001 --replication-port 9101
```

2. Start second server (node id 2):

```
python3 server.py --id 2 --tcp-port 9002 --replication-port 9102
```

3. Start client:

```
python3 client.py --name alice
```

Run multiple clients in separate terminals using different `--name`.

To simulate primary failure: stop the terminal running the primary server (the one with highest id at start becomes primary). Backups will elect and one will become primary.

---

## Quick start (Windows)

Use PowerShell or CMD, run the same `python server.py --id 1 --tcp-port 9001 --replication-port 9101` commands.

---

## Files of interest

- `server.py` : complete server node (primary/backup) implementation.
- `client.py` : simple CLI client.
- `game.py` : puzzle generator, validation, scoring.
- `utils.py` : framing and multicast helpers.

---

## Notes & Tips

- If running multiple servers on the same machine, ensure different `--tcp-port` and `--replication-port`.
- You can also run multiple clients pointing to a known primary: `python3 client.py --host 127.0.0.1 --port 9001 --name bob`
- The project avoids using any middleware or libraries for coordination — everything is implemented using sockets and plain Python.

If anything fails when you run it locally, paste the terminal output here and I'll debug it.
