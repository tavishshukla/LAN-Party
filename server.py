import json
import random
import socket
import sqlite3
import threading
from datetime import datetime

HOST, PORT = "0.0.0.0", 5050
DEFAULT_ROOM = "lobby"
clients = {}
rooms = {}
games = {}
ttt_games = {}
polls = {}
HISTORY_LIMIT = 10
HISTORY_DB = "chat_history.sqlite3"
lock = threading.Lock()


def stamp():
    return datetime.now().strftime("%H:%M:%S")


def clean_username(value):
    return "".join(ch for ch in str(value).strip() if ch.isalnum() or ch in "_-")[:20]


def clean_room_name(value):
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in "_-")[:24].lower()


def compare_guess(secret, guess):
    if guess < secret:
        return "low"
    if guess > secret:
        return "high"
    return "correct"


def ttt_winner(board):
    lines = (
        (0, 1, 2), (3, 4, 5), (6, 7, 8),
        (0, 3, 6), (1, 4, 7), (2, 5, 8),
        (0, 4, 8), (2, 4, 6),
    )
    for a, b, c in lines:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None


def ttt_draw(board):
    cells = [board[i] or str(i + 1) for i in range(9)]
    return (
        f" {cells[0]} | {cells[1]} | {cells[2]} \n"
        "---+---+---\n"
        f" {cells[3]} | {cells[4]} | {cells[5]} \n"
        "---+---+---\n"
        f" {cells[6]} | {cells[7]} | {cells[8]} "
    )


def poll_summary(poll):
    counts = [0] * len(poll["options"])
    for choice in poll["votes"].values():
        counts[choice] += 1
    lines = [f"Poll: {poll['question']}"]
    lines.extend(f"{i + 1}. {option} — {counts[i]} vote(s)" for i, option in enumerate(poll["options"]))
    lines.append(f"Total votes: {len(poll['votes'])}")
    return "\n".join(lines)


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


def record_win(room, username):
    """Add one win to a player's room scoreboard."""
    with sqlite3.connect(HISTORY_DB, timeout=5) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS scores (
                room TEXT NOT NULL,
                name TEXT NOT NULL,
                wins INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (room, name)
            )"""
        )
        db.execute(
            """INSERT INTO scores (room, name, wins) VALUES (?, ?, 1)
               ON CONFLICT(room, name) DO UPDATE SET wins = wins + 1""",
            (room, username),
        )


def load_scores(room):
    """Return room scores from most wins to least."""
    with sqlite3.connect(HISTORY_DB, timeout=5) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS scores (
                room TEXT NOT NULL,
                name TEXT NOT NULL,
                wins INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (room, name)
            )"""
        )
        return db.execute(
            "SELECT name, wins FROM scores WHERE room = ? ORDER BY wins DESC, name COLLATE NOCASE ASC",
            (room,),
        ).fetchall()


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
        if name:
            for game_room, game in list(ttt_games.items()):
                if name.lower() in (player.lower() for player in game["players"].values()):
                    ttt_games.pop(game_room, None)
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
                send(sock, {"type": "system", "time": stamp(), "text": "commands: /help /users /rooms /history /poll question | option 1 | option 2 /vote <number> /endpoll /game /guess <1-100> /scores /ttt <username> /ttt /move <1-9> /join <room> /msg <username> <message> /me <action> /quit"})
            elif msg == "/history":
                current_room = rooms.get(sock, DEFAULT_ROOM)
                history = load_history(current_room)
                send(sock, {"type": "history", "room": current_room, "items": history})
            elif msg == "/poll" or msg.startswith("/poll "):
                current_room = rooms.get(sock, DEFAULT_ROOM)
                parts = msg[6:].split("|")
                if len(parts) < 3 or len(parts) > 6:
                    send(sock, {"type": "error", "text": "usage: /poll question | option 1 | option 2 (up to 5 options)"})
                    continue
                question = parts[0].strip()[:180]
                options = [part.strip()[:80] for part in parts[1:]]
                if not question or any(not option for option in options) or len(set(option.lower() for option in options)) != len(options):
                    send(sock, {"type": "error", "text": "add a question and 2–5 different, non-empty options"})
                    continue
                with lock:
                    if current_room in polls:
                        poll_started = False
                    else:
                        polls[current_room] = {"question": question, "options": options, "votes": {}, "creator": name}
                        poll_started = True
                if not poll_started:
                    send(sock, {"type": "error", "text": "there's already a poll in this room; use /poll to view it"})
                else:
                    poll = polls[current_room]
                    broadcast({"type": "system", "time": stamp(), "text": poll_summary(poll) + "\nVote with /vote <number>. Only one active poll per room."}, room=current_room)
            elif msg == "/vote" or msg.startswith("/vote "):
                parts = msg.split(maxsplit=1)
                if len(parts) != 2 or not parts[1].isdigit():
                    send(sock, {"type": "error", "text": "usage: /vote <option number>"})
                    continue
                current_room = rooms.get(sock, DEFAULT_ROOM)
                with lock:
                    poll = polls.get(current_room)
                    if poll is None:
                        vote_result = "missing"
                    elif not 1 <= int(parts[1]) <= len(poll["options"]):
                        vote_result = "invalid"
                    else:
                        poll["votes"][name.lower()] = int(parts[1]) - 1
                        vote_result = "voted"
                        summary = poll_summary(poll)
                if vote_result == "missing":
                    send(sock, {"type": "error", "text": "there's no active poll in this room"})
                elif vote_result == "invalid":
                    send(sock, {"type": "error", "text": "that option number doesn't exist"})
                else:
                    broadcast({"type": "system", "time": stamp(), "text": f"{name} voted.\n{summary}"}, room=current_room)
            elif msg == "/endpoll":
                current_room = rooms.get(sock, DEFAULT_ROOM)
                with lock:
                    poll = polls.get(current_room)
                    if poll is None:
                        poll_result = "missing"
                    elif poll["creator"].lower() != name.lower():
                        poll_result = "not_creator"
                    else:
                        summary = poll_summary(poll)
                        polls.pop(current_room, None)
                        poll_result = "ended"
                if poll_result == "missing":
                    send(sock, {"type": "error", "text": "there's no active poll in this room"})
                elif poll_result == "not_creator":
                    send(sock, {"type": "error", "text": "only the person who started the poll can end it"})
                else:
                    broadcast({"type": "system", "time": stamp(), "text": "Poll closed.\n" + summary}, room=current_room)
            elif msg == "/ttt" or msg.startswith("/ttt "):
                current_room = rooms.get(sock, DEFAULT_ROOM)
                parts = msg.split(maxsplit=1)
                with lock:
                    active_game = ttt_games.get(current_room)
                if len(parts) == 1:
                    if active_game is None:
                        send(sock, {"type": "error", "text": "no tic-tac-toe game in this room; challenge someone with /ttt <username>"})
                    else:
                        mark = "X" if active_game["players"]["X"].lower() == name.lower() else "O" if active_game["players"]["O"].lower() == name.lower() else None
                        next_player = active_game["players"][active_game["turn"]]
                        send(sock, {"type": "system", "time": stamp(), "text": f"Tic-tac-toe in #{current_room}\n{ttt_draw(active_game['board'])}\nX: {active_game['players']['X']} | O: {active_game['players']['O']}\nTurn: {next_player}"})
                else:
                    target_sock, target_name = find_client(parts[1])
                    if target_sock is None:
                        send(sock, {"type": "error", "text": f"{parts[1]} isn't online"})
                    elif target_sock is sock:
                        send(sock, {"type": "error", "text": "you can't challenge yourself"})
                    elif rooms.get(target_sock, DEFAULT_ROOM) != current_room:
                        send(sock, {"type": "error", "text": "you can only challenge someone in your current room"})
                    elif active_game is not None:
                        send(sock, {"type": "error", "text": "there's already a tic-tac-toe game in this room"})
                    else:
                        with lock:
                            ttt_games[current_room] = {
                                "board": [None] * 9,
                                "players": {"X": name, "O": target_name},
                                "turn": "X",
                            }
                        broadcast({"type": "system", "time": stamp(), "text": f"Tic-tac-toe: {name} (X) vs {target_name} (O)!\n{ttt_draw([None] * 9)}\n{ name } starts. Use /move <1-9>."}, room=current_room)
            elif msg == "/move" or msg.startswith("/move "):
                parts = msg.split(maxsplit=1)
                if len(parts) != 2 or not parts[1].isdigit() or not 1 <= int(parts[1]) <= 9:
                    send(sock, {"type": "error", "text": "usage: /move <number from 1 to 9>"})
                    continue
                position = int(parts[1]) - 1
                current_room = rooms.get(sock, DEFAULT_ROOM)
                with lock:
                    active_game = ttt_games.get(current_room)
                    if active_game is None:
                        move_result = "missing"
                    else:
                        mark = next((mark for mark, player in active_game["players"].items() if player.lower() == name.lower()), None)
                        if mark is None:
                            move_result = "spectator"
                        elif mark != active_game["turn"]:
                            move_result = "turn"
                        elif active_game["board"][position] is not None:
                            move_result = "occupied"
                        else:
                            active_game["board"][position] = mark
                            winner = ttt_winner(active_game["board"])
                            draw = winner is None and all(active_game["board"])
                            if winner or draw:
                                finished_game = ttt_games.pop(current_room)
                                move_result = "won" if winner else "draw"
                            else:
                                active_game["turn"] = "O" if mark == "X" else "X"
                                finished_game = None
                                move_result = "moved"
                            board_text = ttt_draw(active_game["board"])
                            players_text = f"X: {active_game['players']['X']} | O: {active_game['players']['O']}"
                            next_name = active_game["players"][active_game["turn"]] if move_result == "moved" else None
                if move_result == "missing":
                    send(sock, {"type": "error", "text": "no tic-tac-toe game in this room"})
                elif move_result == "spectator":
                    send(sock, {"type": "error", "text": "only the two players can make moves"})
                elif move_result == "turn":
                    send(sock, {"type": "error", "text": "it's not your turn"})
                elif move_result == "occupied":
                    send(sock, {"type": "error", "text": "that square is taken"})
                elif move_result == "won":
                    broadcast({"type": "system", "time": stamp(), "text": f"{board_text}\n{players_text}\n{name} wins tic-tac-toe!"}, room=current_room)
                elif move_result == "draw":
                    broadcast({"type": "system", "time": stamp(), "text": f"{board_text}\n{players_text}\nIt's a draw."}, room=current_room)
                else:
                    broadcast({"type": "system", "time": stamp(), "text": f"{board_text}\n{players_text}\nNext turn: {next_name}"}, room=current_room)
            elif msg == "/game":
                current_room = rooms.get(sock, DEFAULT_ROOM)
                with lock:
                    if current_room in games:
                        game_exists = True
                    else:
                        games[current_room] = {"secret": random.randint(1, 100), "starter": name}
                        game_exists = False
                if game_exists:
                    send(sock, {"type": "error", "text": "there's already a guessing game running in this room"})
                else:
                    broadcast({"type": "system", "time": stamp(), "text": f"{name} started a number guessing game in #{current_room}. Guess a number from 1 to 100 with /guess <number>!"}, room=current_room)
            elif msg == "/guess" or msg.startswith("/guess "):
                parts = msg.split(maxsplit=1)
                if len(parts) != 2:
                    send(sock, {"type": "error", "text": "usage: /guess <number from 1 to 100>"})
                    continue
                try:
                    guess = int(parts[1])
                except ValueError:
                    send(sock, {"type": "error", "text": "guess must be a whole number from 1 to 100"})
                    continue
                if not 1 <= guess <= 100:
                    send(sock, {"type": "error", "text": "guess must be between 1 and 100"})
                    continue
                current_room = rooms.get(sock, DEFAULT_ROOM)
                with lock:
                    game = games.get(current_room)
                    if game is None:
                        result = "missing"
                    else:
                        result = compare_guess(game["secret"], guess)
                        if result == "correct":
                            games.pop(current_room, None)
                if result == "missing":
                    send(sock, {"type": "error", "text": "no game is running in this room; start one with /game"})
                elif result == "low":
                    send(sock, {"type": "system", "time": stamp(), "text": "too low — try again"})
                elif result == "high":
                    send(sock, {"type": "system", "time": stamp(), "text": "too high — try again"})
                else:
                    record_win(current_room, name)
                    broadcast({"type": "system", "time": stamp(), "text": f"{name} guessed {guess} and won the game in #{current_room}! Use /scores to see the room leaderboard."}, room=current_room)
            elif msg == "/scores":
                current_room = rooms.get(sock, DEFAULT_ROOM)
                scores = load_scores(current_room)
                if scores:
                    summary = ", ".join(f"{player}: {wins}" for player, wins in scores)
                    text = f"guessing game scores in #{current_room}: {summary}"
                else:
                    text = f"no wins recorded in #{current_room} yet"
                send(sock, {"type": "system", "time": stamp(), "text": text})
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
