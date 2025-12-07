
#!/bin/bash
# Example usage: run three servers and a client (Unix-like shell)
python3 server.py --id 1 --tcp-port 9001 --replication-port 9101 &
sleep 0.5
python3 server.py --id 2 --tcp-port 9002 --replication-port 9102 &
sleep 0.5
python3 client.py --name alice &
python3 client.py --name bob &
echo "Servers 1 and 2 started, clients alice and bob started."
