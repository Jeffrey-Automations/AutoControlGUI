==========================
Socket Server (Remote API)
==========================

.. warning::

   This is an **experimental** feature.

The Socket Server allows other programming languages (or remote machines) to use AutoControl
by sending JSON commands over TCP. Every connection must authenticate first.

Starting the Server
===================

.. code-block:: python

   import time
   from je_auto_control import start_autocontrol_socket_server

   server = start_autocontrol_socket_server(host="127.0.0.1", port=9938)
   print("token file:", server.token_path)
   # quit_server closes the listening socket.
   while server.socket.fileno() != -1:
       time.sleep(0.5)

Or from the command line:

.. code-block:: bash

   je_auto_control start-server --port 9938 [--token T] [--token-file PATH] [--no-auth]

The server runs in a background thread and binds ``127.0.0.1`` by default.

Authentication
==============

The first line a client sends on a connection must be ``AUTH <token>``. The
server answers ``AUTH_OK`` and then reads one command as before.

Which token the server accepts:

- **RBAC off** (``JE_AUTOCONTROL_RBAC_USERS`` unset): the server token. It is
  the ``token`` argument (CLI ``--token``), else the environment variable
  ``JE_AUTOCONTROL_SOCKET_TOKEN``, else a random ``secrets.token_urlsafe(32)``
  generated at start. It grants the trusted behaviour the server always had.
- **RBAC on**: a user's token from the RBAC user store, and nothing else. The
  server token is not accepted and no token file is written: as on REST and
  MCP, a token without an identity would switch RBAC off for whoever holds
  it. Each command runs under that user's role. Running an action list needs
  ``drive_input``; the whole list is checked before its first action runs,
  and commands nested in action files are checked by the executor under the
  same role. ``quit_server`` needs ``manage_hosts``.

The server token is written atomically to
``~/.je_auto_control/socket_server_<port>.token`` (the bound port; CLI
``--token-file`` / argument ``token_path`` overrides it). The file is readable
by its owner only: mode 0600 on POSIX, an access list naming only the current
user on Windows. It is deleted when the server closes, unless another server
has since replaced it. The CLI prints the file's path, never the token.

Limits on failed authentication:

- 10 seconds from connecting to ``AUTH_OK``; a client that has not
  authenticated by then is disconnected.
- 3 wrong tokens per connection, then the connection is closed.
- Failed attempts are rate-limited per client address (the REST server's
  gate): after 8 failures in a minute, wrong tokens are answered
  ``authentication refused: too many failed attempts``. A valid token is
  never locked out.

A command (or ``quit_server``) sent without ``AUTH`` is refused with
``authentication required`` and is not run.

**Legacy opt-out.** ``require_auth=False`` (CLI ``--no-auth``) serves every
connection as trusted without an ``AUTH`` line, and logs a warning at start
that any process able to reach the server can run any command, including
``quit_server``. A client that sends ``AUTH`` anyway is answered ``AUTH_OK``.

Sending Commands (Client)
=========================

``send_socket_command`` authenticates, sends one command and returns the
reply lines. The token is the ``token`` argument, else
``JE_AUTOCONTROL_SOCKET_TOKEN``, else the server's token file for that port
(``token_path`` overrides the path). Under RBAC, pass the user's token. A
refused token raises ``SocketAuthError``.

.. code-block:: python

   import je_auto_control as ac

   lines = ac.send_socket_command([
       ["AC_set_mouse_position", {"x": 500, "y": 300}],
       ["AC_click_mouse", {"mouse_keycode": "mouse_left"}],
   ], host="127.0.0.1", port=9938)
   print(lines)
   ac.send_socket_command("quit_server", port=9938)

``read_socket_token(port)`` returns the token from the file, and
``authenticate_connection(connection, stream, token)`` performs the handshake
on a socket you opened yourself. Talking to a ``--no-auth`` server, pass
``require_auth=False``.

A raw client, in any language:

.. code-block:: python

   import json
   import pathlib
   import socket

   token = (pathlib.Path.home() / ".je_auto_control" / "socket_server_9938.token").read_text().strip()
   sock = socket.create_connection(("127.0.0.1", 9938))
   sock.sendall(f"AUTH {token}\n".encode("utf-8"))
   command = json.dumps([["AC_set_mouse_position", {"x": 500, "y": 300}]])
   sock.sendall((command + "\n").encode("utf-8"))

   response = b""
   while b"Return_Data_Over_JE" not in response:
       chunk = sock.recv(8192)
       if not chunk:
           break
       response += chunk
   print(response.decode("utf-8"))  # starts with AUTH_OK
   sock.close()

Migrating an existing client
============================

A client written for the unauthenticated protocol now gets
``authentication required`` and its command does not run. Either:

- send ``AUTH <token>\n`` as the first line and read the ``AUTH_OK`` line
  before the command's reply, taking the token from the token file, from
  ``JE_AUTOCONTROL_SOCKET_TOKEN``, or (under RBAC) from the user's token; or
- start the server with ``--no-auth`` / ``require_auth=False`` to keep the
  old protocol, accepting that any local process can then drive the machine.

Protocol Details
================

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Property
     - Value
   * - Encoding
     - UTF-8
   * - Handshake
     - First line ``AUTH <token>``, answered ``AUTH_OK`` (not needed with ``--no-auth``)
   * - End-of-response marker
     - ``Return_Data_Over_JE``
   * - Refusals
     - One error line, then ``Return_Data_Over_JE``
   * - Shutdown command
     - Send ``"quit_server"`` (after ``AUTH``) to stop the server; no reply
       unless it is refused
   * - Request framing
     - One command per connection: the JSON action list followed by a
       newline. Indented JSON is fine; the command ends at the newline after
       which it parses (or at the client's half-close).
   * - Response framing
     - One line per result, then ``Return_Data_Over_JE`` and a newline. Read
       until the marker; one ``recv`` may return only part of the reply.
   * - Default port
     - 9938
   * - Token file
     - ``~/.je_auto_control/socket_server_<port>.token``, owner-only, deleted on close
