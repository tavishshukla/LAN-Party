import json
import socket
import threading
from datetime import datetime

HOST, PORT = "0.0.0.0", 5050
clients = {}
lock = threading.Lock()


def stamp():
    return datetime.now().strftime("%H:%M:%S")


def send(sock, packet):
    try:
        sock.sendall((json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8"))
        return True
    except OSError:
        return False


def broadcast(packet, exclude=None):
    with lock:
        targets = [s for s in clients if s is not exclude]
    for sock in targets:
        if not send(sock, packet):
            remove_client(sock)


def remove_client(sock):
    with lock:
        name = clients.pop(sock, None)
    try:
        sock.close()
    except OSError:
        pass
    if name:
        broadcast({"type": "system", "time": stamp(), "text": f"{name} left the chat"})


def handle(sock, address):
    name = None
    reader = None
    try:
        reader = sock.makefile("r", encoding="utf-8")
        send(sock, {"type": "prompt", "text": "username"})
        first = reader.readline()
        if not first:
            return

        name = str(json.loads(first).get("name", "")).strip()
        name = "".join(c for c in name if c.isalnum() or c in "_-")[:20]
        if not name:
            send(sock, {"type": "error", "text": "Pick a username using letters, numbers, _ or -."})
            return

        with lock:
            if name.lower() in (n.lower() for n in clients.values()):
                send(sock, {"type": "error", "text": "That username is already in use."})
                return
            clients[sock] = name

        send(sock, {"type": "system", "time": stamp(), "text": f"welcome {name} — type /help"})
        broadcast({"type": "system", "time": stamp(), "text": f"{name} joined"})
        print(f"[{stamp()}] {name} connected from {address[0]}")

        for line in reader:
            try:
                packet = json.loads(line)
            except json.JSONDecodeError:
                continue
            if packet.get("type") != "message":
                continue

            msg = str(packet.get("text", "")).strip()[:500]
            if not msg:
                continue
            if msg == "/quit":
                break
            if msg == "/help":
                send(sock, {"type": "system", "time": stamp(), "text": "commands: /help /users /quit"})
            elif msg == "/users":
                with lock:
                    names = sorted(clients.values(), key=str.lower)
                send(sock, {"type": "system", "time": stamp(), "text": "online: " + ", ".join(names)})
            else:
                broadcast({"type": "message", "time": stamp(), "name": name, "text": msg})
    except (OSError, ValueError, AttributeError):
        pass
    finally:
        if reader:
            try:
                reader.close()
            except OSError:
                pass
        remove_client(sock)
        print(f"[{stamp()}] disconnected: {name or address[0]}")


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"LAN Party server listening on port {PORT}")
    print("trusted LAN only; Ctrl+C to stop")
    try:
        while True:
            sock, address = server.accept()
            threading.Thread(target=handle, args=(sock, address), daemon=True).start()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        server.close()


if __name__ == "__main__":
    main()
