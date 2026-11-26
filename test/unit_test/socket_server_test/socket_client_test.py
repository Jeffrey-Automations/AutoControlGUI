from je_auto_control.utils.socket_server.socket_client import send_socket_command

HOST, PORT = "localhost", 9938

# The token comes from $JE_AUTOCONTROL_SOCKET_TOKEN, else the file the server
# wrote (~/.je_auto_control/socket_server_9938.token).
send_socket_command("quit_server", HOST, PORT)
