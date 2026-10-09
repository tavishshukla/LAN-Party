import json
import socket
import threading

PORT = 5050


def receive(sock, stopped):
    reader = sock.makefile("r", encoding="utf-8")
    try:
        for line in reader:
            try:
                packet = json.loads(line)
            except json.JSONDecodeError:
                continue

            kind = packet.get("type")
            if kind == "system":
                print(f"\n[{packet.get('time', '--:--:--')}] * {packet.get('text', '')}")
            elif kind == "message":
                print(f"\n[{packet.get('time', '--:--:--')}] {packet.get('name', '?')}: {packet.get('text', '')}")
            elif kind == "action":
                print(f"\n[{packet.get('time', '--:--:--')}] * {packet.get('name', '?')} {packet.get('text', '')}")
            elif kind == "private":
                sender = packet.get("from", "?")
                recipient = packet.get("to", "?")
                print(f"\n[{packet.get('time', '--:--:--')}] [DM] {sender} -> {recipient}: {packet.get('text', '')}")
            elif kind == "error":
                print(f"\n[error] {packet.get('text', '')}")
            print("> ", end="", flush=True)
    except OSError:
        pass
    finally:
        stopped.set()
        reader.close()


def main():
    print("=== LAN Party ===")
    host = input("server IP: ").strip()
    name = input("username: ").strip()
    if not host or not name:
        print("need both a server IP and username")
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, PORT))
    except OSError as exc:
        print(f"couldn't connect: {exc}")
        print("check the IP, server, and private-network firewall setting")
        sock.close()
        return

    stopped = threading.Event()
    threading.Thread(target=receive, args=(sock, stopped), daemon=True).start()
    sock.sendall((json.dumps({"name": name}) + "\n").encode())
    print("connected. /help for commands.")

    try:
        while not stopped.is_set():
            try:
                msg = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                msg = "/quit"
            if msg:
                try:
                    sock.sendall((json.dumps({"type": "message", "text": msg[:500]}, ensure_ascii=False) + "\n").encode())
                except OSError:
                    break
            if msg == "/quit":
                break
    finally:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        sock.close()
        print("disconnected")


if __name__ == "__main__":
    main()
