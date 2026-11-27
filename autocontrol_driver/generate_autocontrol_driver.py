import sys
import time

from je_auto_control import start_autocontrol_socket_server

# Clients authenticate with the token written to
# ~/.je_auto_control/socket_server_9938.token (or $JE_AUTOCONTROL_SOCKET_TOKEN).
server = start_autocontrol_socket_server()
# quit_server closes the listening socket; the old close_flag no longer exists.
while server.socket.fileno() != -1:
    time.sleep(0.5)
sys.exit(0)
