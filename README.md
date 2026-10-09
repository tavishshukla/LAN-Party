# LAN Party

A terminal chat app for computers on the same trusted local network. Built with Python 3.10+ and no third-party packages.

## Run it

1. On the host computer, run `python server.py`.
2. Find the host's local IPv4 address (run `ipconfig` on Windows).
3. On each computer, run `python client.py`, then enter the host IP and a username.
4. If Windows Firewall asks, allow Python on **Private networks only**.

## Commands

- `/help` — show commands
- `/users` — list who's online
- `/msg <username> <message>` — send a private message to someone online
- `/me <action>` — show an action in chat, e.g. `/me is ready to play`
- `/quit` — disconnect

## Notes

Chat is currently unencrypted plain text. Use it only on a trusted LAN and never expose port 5050 to the internet. Private messages are private from other chat participants, but they are not encrypted from anyone who can monitor the network.

## What's next

Rooms, terminal multiplayer games, scoreboards, and chat log export.
