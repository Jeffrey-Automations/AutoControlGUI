=================
Socket Server API
=================

TCP server for receiving and executing JSON automation commands, and its
client. Every connection authenticates first; see the Socket Server guide for
the protocol.

----

start_autocontrol_socket_server
===============================

.. function:: start_autocontrol_socket_server(host="127.0.0.1", port=9938, *, token=None, require_auth=True, token_path=None)

   Starts a threaded TCP server that accepts JSON automation commands.

   :param str host: Bind address. Defaults to ``"127.0.0.1"``.
   :param int port: Server port. Defaults to ``9938``; ``0`` picks a free one.
   :param str token: The server token. Defaults to ``$JE_AUTOCONTROL_SOCKET_TOKEN``,
      else a random ``secrets.token_urlsafe(32)``. Ignored under RBAC
      (``JE_AUTOCONTROL_RBAC_USERS``), where only user tokens authenticate.
   :param bool require_auth: ``False`` is the legacy opt-out: no ``AUTH``
      line, every connection trusted; logged as a warning.
   :param pathlib.Path token_path: Where the server token is written,
      owner-only. Defaults to ``~/.je_auto_control/socket_server_<port>.token``.
   :returns: The running server.
   :rtype: TCPServer

----

TCPServer
=========

.. class:: TCPServer(server_address, RequestHandlerClass)

   Threaded TCP server (extends ``socketserver.ThreadingMixIn`` and ``socketserver.TCPServer``).
   ``server.socket.fileno()`` is ``-1`` once ``quit_server`` has closed it.

   .. attribute:: token
      :type: str | None

      The server token clients authenticate with; ``None`` with
      ``require_auth=False`` or under RBAC.

   .. attribute:: token_path
      :type: pathlib.Path | None

      The token file; ``server_close()`` deletes it if it still holds this
      server's token.

----

TCPServerHandler
================

.. class:: TCPServerHandler

   Request handler for the TCP server. Per connection it:

   - requires a first line ``AUTH <token>`` (answered ``AUTH_OK``) within 10
     seconds, allowing 3 wrong tokens before closing; failures are
     rate-limited per client address;
   - then reads one newline-terminated command: ``"quit_server"`` shuts the
     server down (``manage_hosts`` under RBAC); anything else is parsed as
     JSON and passed to ``execute_action()`` under the caller's role
     (``drive_input`` under RBAC). Results are sent back one per line,
     terminated by ``"Return_Data_Over_JE"``.

----

Client
======

.. function:: send_socket_command(command, host="127.0.0.1", port=9938, *, token=None, token_path=None, require_auth=True, timeout=30.0)

   Authenticate, send one command (an action list or ``"quit_server"``) and
   return the reply lines. The token is ``token``, else
   ``$JE_AUTOCONTROL_SOCKET_TOKEN``, else the token file for ``port``.
   Raises ``SocketAuthError`` when the token is refused.

.. function:: read_socket_token(port=9938, token_path=None)

   The token a server on ``port`` wrote to its token file.

.. function:: authenticate_connection(connection, stream, token)

   Send ``AUTH <token>`` on an open socket and read the answer from
   ``stream`` (``connection.makefile("rb")``); raises ``SocketAuthError``
   unless the server answered ``AUTH_OK``.
