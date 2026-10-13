# LAN Party

A terminal chat app for computers on the same trusted local network. Built with Python 3.10+ and no third-party packages.

## Run it

1. On the host computer, run `python server.py`.
2. Find the host's local IPv4 address (run `ipconfig` on Windows).
3. On each computer, run `python client.py`, then enter the host IP and a username.
4. If Windows Firewall asks, allow Python on **Private networks only**.

## Commands

- `/help` — show commands
- `/users` — list who's online in your current room
- `/rooms` — list rooms and how many people are in each
- `/history` — show the last 10 messages/actions in your current room
- `/game` — start a room-wide number guessing game
- `/guess <number>` — guess from 1 to 100; first correct guess wins
- `/join <room>` — switch rooms; names can use letters, numbers, `_` and `-`
- `/msg <username> <message>` — send a private message to someone online
- `/me <action>` — show an action in your current room, e.g. `/me is ready to play`
- `/quit` — disconnect

Everyone starts in `#lobby`. Messages and actions only appear to people in the same room. Private messages can reach any online user regardless of room. Each room keeps its latest 10 messages/actions in a local SQLite database (`chat_history.sqlite3`), so history survives server restarts.

## Number guessing game

Start a game with `/game`. Everyone in the current room can guess using `/guess 42` (replace `42` with your guess). The server tells you if your guess is too high or too low, and announces the first winner. Each room can run its own game.

## Tests

Run the built-in tests with `python -m unittest discover -s tests -v`. GitHub Actions runs the same tests on pushes to `main` and on pull requests.

## Notes

Chat is currently unencrypted plain text. Use it only on a trusted LAN and never expose port 5050 to the internet. Private messages are private from other chat participants, but they are not encrypted from anyone who can monitor the network.

## What's next

Terminal multiplayer games, scoreboards, and chat log export.
