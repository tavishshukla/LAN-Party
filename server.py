import json
import socket
import sqlite3
import threading
from datetime import datetime

HOST, PORT = "0.0.0.0", 5050
DEFAULT_ROOM = "lobby"
clients = {}
rooms = {}
HISTORY_LIMIT = 10
HISTORY_DB = "chat_history.sqlite3"
lock = threading.Lock()


def stamp():
    return datetime.now().strftime("%H:%M:%S")


def clean_username(value):
    return "".join(ch for ch in str(value).strip() if ch.isalnum() or ch in "_-")[:20]


def clean_room_name(value):
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in "_-")[:24].lower()


def send(sock, packet):
    try:
        sock.sendall((json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8"))
        return True
    except OSError:
        return False


def remember(room, packet):
    """Save a room message and keep only its latest ten entries."""
    with sqlite3.connect(HISTORY_DB, timeout=5) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room TEXT NOT NULL,
                kind TEXT NOT NULL,
                time TEXT NOT NULL,
                name TEXT NOT NULL,
                text TEXT NOT NULL
            )"""
        )
        db.execute(
            "INSERT INTO history (room, kind, time, name, text) VALUES (?, ?, ?, ?, ?)",
            (room, packet["type"], packet["time"], packet["name"], packet["text"]),
        )
        db.execute(
            """DELETE FROM history
               WHERE room = ? AND id NOT IN (
                   SELECT id FROM history WHERE room = ?
                   ORDER BY id DESC LIMIT ?
               )""",
            (room, room, HISTORY_LIMIT),
        )


def load_history(room):
    """Load a room's latest messages in chronological order."""
    with sqlite3.connect(HISTORY_DB, timeout=5) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room TEXT NOT NULL,
                kind TEXT NOT NULL,
                time TEXT NOT NULL,
                name TEXT NOT NULL,
                text TEXT NOT NULL
            )"""
        )
        rows = db.execute(
            "SELECT kind, time, name, text FROM history WHERE room = ? ORDER BY id DESC LIMIT ?",
            (room, HISTORY_LIMIT),
        ).fetchall()
    rows.reverse()
    return [
        {"type": kind, "time": time, "name": name, "text": text}
        for kind, time, name, text in rows
    ]


def broadcast(packet, exclude=None, room=None):
    with lock:
        targets = [
            client_sock for client_sock in clients
            if client_sock is not exclude
            and (room is None or rooms.get(client_sock, DEFAULT_ROOM) == room)
        ]
    for client_sock in targets:
        if not send(client_sock, packet):
            remove_client(client_sock)


def remove_client(sock):
    with lock:
        name = clients.pop(sock, None)
        room = rooms.pop(sock, DEFAULT_ROOM)
    try:
        sock.close()
    except OSError:
        pass
    if name:
        broadcast({"type": "system", "time": stamp(), "text": f"{name} left #{room}"}, room=room)


def find_client(username):
    with lock:
        for client_sock, client_name in clients.items():
            if client_name.lower() == username.lower():
                return client_sock, client_name
    return None, None


def handle(sock, address):
    name = None
    reader = None
    try:
        reader = sock.makefile("r", encoding="utf-8")
        send(sock, {"type": "prompt", "text": "username"})
        first = reader.readline()
        if not first:
            return

        initial = json.loads(first)
        if not isinstance(initial, dict):
            send(sock, {"type": "error", "text": "Invalid login packet."})
            return
        name = clean_username(initial.get("name", ""))
        if not name:
            send(sock, {"type": "error", "text": "Pick a username using letters, numbers, _ or -."})
            return

        with lock:
            if name.lower() in (existing.lower() for existing in clients.values()):
                send(sock, {"type": "error", "text": "That username is already in use."})
                return
            clients[sock] = name
            rooms[sock] = DEFAULT_ROOM

        send(sock, {"type": "system", "time": stamp(), "text": f"welcome {name} — you're in #{DEFAULT_ROOM}; type /help"})
        broadcast({"type": "system", "time": stamp(), "text": f"{name} joined #{DEFAULT_ROOM}"}, room=DEFAULT_ROOM)
        print(f"[{stamp()}] {name} connected from {address[0]}")

        for line in reader:
            try:
                packet = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(packet, dict) or packet.get("type") != "message":
                continue

            msg = str(packet.get("text", "")).strip()[:500]
            if not msg:
                continue
            if msg == "/quit":
                break
            if msg == "/help":
                send(sock, {"type": "system", "time": stamp(), "text": "commands: /help /users /rooms /history /join <room> /msg <username> <message> /me <action> /quit"})
            elif msg == "/history":
                current_room = rooms.get(sock, DEFAULT_ROOM)
                history = load_history(current_room)
                send(sock, {"type": "history", "room": current_room, "items": history})
            elif msg == "/users":
                with lock:
                    current_room = rooms.get(sock, DEFAULT_ROOM)
                    names = sorted(
                        (client_name for client_sock, client_name in clients.items()
                         if rooms.get(client_sock, DEFAULT_ROOM) == current_room),
                        key=str.lower
                    )
                send(sock, {"type": "system", "time": stamp(), "text": f"online in #{current_room}: " + ", ".join(names)})
            elif msg == "/rooms":
                with lock:
                    counts = {}
                    for current_room in rooms.values():
                        counts[current_room] = counts.get(current_room, 0) + 1
                summary = ", ".join(f"#{room} ({count})" for room, count in sorted(counts.items()))
                send(sock, {"type": "system", "time": stamp(), "text": "rooms: " + (summary or "none")})
            elif msg == "/join" or msg.startswith("/join "):
                parts = msg.split(maxsplit=1)
                if len(parts) != 2:
                    send(sock, {"type": "error", "text": "usage: /join <room>"})
                    continue
                new_room = clean_room_name(parts[1])
                if not new_room:
                    send(sock, {"type": "error", "text": "room names can use letters, numbers, _ and -"})
                    continue
                with lock:
                    old_room = rooms.get(sock, DEFAULT_ROOM)
                    rooms[sock] = new_room
                if old_room != new_room:
                    broadcast({"type": "system", "time": stamp(), "text": f"{name} left #{old_room}"}, room=old_room)
                    broadcast({"type": "system", "time": stamp(), "text": f"{name} joined #{new_room}"}, room=new_room)
                send(sock, {"type": "system", "time": stamp(), "text": f"you're now in #{new_room}"})
            elif msg == "/me" or msg.startswith("/me "):
                action = msg[3:].strip()
                if not action:
                    send(sock, {"type": "error", "text": "usage: /me <action>"})
                    continue
                current_room = rooms.get(sock, DEFAULT_ROOM)
                action_packet = {"type": "action", "time": stamp(), "name": name, "text": action[:450]}
                remember(current_room, action_packet)
                broadcast(action_packet, room=current_room)
            elif msg.startswith("/msg "):
                parts = msg.split(maxsplit=2)
                if len(parts) < 3 or not parts[2].strip():
                    send(sock, {"type": "error", "text": "usage: /msg <username> <message>"})
                    continue
                target_sock, target_name = find_client(parts[1])
                if target_sock is None:
                    send(sock, {"type": "error", "text": f"{parts[1]} isn't online"})
                    continue
                if target_sock is sock:
                    send(sock, {"type": "error", "text": "you can just say that in chat"})
                    continue
                timestamp = stamp()
                private_packet = {"type": "private", "time": timestamp, "from": name, "to": target_name, "text": parts[2]}
                if not send(target_sock, private_packet):
                    remove_client(target_sock)
                    send(sock, {"type": "error", "text": f"couldn't send to {target_name}; they may have disconnected"})
                else:
                    send(sock, private_packet)
            else:
                current_room = rooms.get(sock, DEFAULT_ROOM)
                message_packet = {"type": "message", "time": stamp(), "name": name, "text": msg}
                remember(current_room, message_packet)
                broadcast(message_packet, room=current_room)
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
