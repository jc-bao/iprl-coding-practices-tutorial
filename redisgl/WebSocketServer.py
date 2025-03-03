"""
WebSocketServer.py

Author: Toki Migimatsu
Created: April 2017
"""

import socket
import struct
import threading
from base64 import b64encode
from hashlib import sha1


class WebSocketServer:
  """
  Basic implementation for web sockets.

  Usage:

  ws_server = WebSocketServer()
  ws_server.serve_forever(client_connection_callback, client_message_callback)

  ws_server.lock.acquire()
  for client in ws_server.clients:
      client.send(ws_server.encode_message("Hello World!"))
  ws_server.lock.release()

  def client_connection_callback(ws_server, socket):
      socket.send(ws_server.encode_message("Welcome!"))

  def client_message_callback(ws_server, socket, message):
      print(message)
  """

  MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
  STR_HANDSHAKE = (
    "HTTP/1.1 101 Web Socket Protocol Handshake\r\n"
    "Upgrade: websocket\r\n"
    "Connection: Upgrade\r\n"
    "Sec-WebSocket-Accept: %s\r\n\r\n"
  )
  STR_REJECT = "HTTP/1.1 400 Bad Request\r\n\r\n"

  def __init__(self, port=8001):
    """
    Set up web socket server on specified port.
    """

    self.port = port
    self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    self.socket.bind(("", self.port))
    self.socket.listen(1)
    self.clients = []
    self.lock = threading.Lock()

  def serve_forever(
      self, client_connection_callback=None, client_message_callback=None
  ):
    """
    Listen for web socket requests and spawn new thread for each client.

    On connection, the thread will call client_connection_callback(WebSocketServer, socket).
    On receiving client messages, the thread will call client_message_callback(WebSocketServer, socket).
    """

    while True:
      client, _ = self.socket.accept()
      t = threading.Thread(
        target=self.handle_client,
        args=(client, client_connection_callback, client_message_callback),
      )
      t.daemon = True
      t.start()

  def handle_client(
      self, client, client_connection_callback, client_message_callback
  ):
    """
    Connect to client and listen for messages until connection is closed.
    """

    # Handshake with client
    client_key = None
    for line in client.recv(2048).splitlines():
      if line.startswith(b"Sec-WebSocket-Key"):
        client_key = line[line.index(b":") + 1:].strip()
        break
    if client_key is None:
      print("handle_client(): client key not found")
      client.send((WebSocketServer.STR_REJECT).encode("utf-8"))
      return

    accept_key = b64encode(
      sha1(client_key + WebSocketServer.MAGIC).digest()
    ).decode("utf-8")
    client.send((WebSocketServer.STR_HANDSHAKE % accept_key).encode("utf-8"))

    # Send client all keys
    if client_connection_callback is not None:
      client_connection_callback(self, client)

    # Add client to list
    self.lock.acquire()
    self.clients.append(client)
    self.lock.release()

    # Listen for messages
    while True:
      try:
        message = client.recv(1024)
      except:
        continue
      message = self.decode_message(message)
      if client_message_callback is not None:
        client_message_callback(self, client, message)
      if message is None:
        break

    # Close connection to client
    self.lock.acquire()
    self.clients.remove(client)
    self.lock.release()
    client.close()

  @staticmethod
  def encode_bytes(message):
    """
    Encode web socket message to send to client.
    If the message is an object, it will be encoded as JSON.
    """

    # Send entire message as one frame
    b1 = 0b10000000

    if type(message) == str:
      b1 |= 0b00000001
      message = message.encode("utf-8")
    else:
      b1 |= 0b00000010

    # Send text data
    encoded_bytes = struct.pack("!B", b1)

    # Encode message length
    length = len(message)
    if length < 126:
      b2 = length
      encoded_bytes += struct.pack("!B", b2)  # byte
    elif length < (2**16) - 1:
      b2 = 126
      encoded_bytes += struct.pack("!BH", b2, length)  # byte, short
    else:
      b2 = 127
      encoded_bytes += struct.pack("!BQ", b2, length)  # byte, long long

    # Append encoded_bytes
    encoded_bytes += message

    return encoded_bytes

  @staticmethod
  def encode_message(message):
    """
    Encode web socket message to send to client.
    If the message is an object, it will be encoded as JSON.
    """

    if type(message) is bytes:
      pass
    elif type(message) is str:
      message = message.encode("utf-8")
    else:
      update_message = struct.pack("!L", len(message["update"]))  # long
      for key, val in message["update"]:
        update_message += WebSocketServer.encode_bytes(
          key
        ) + WebSocketServer.encode_bytes(val)

      delete_message = struct.pack("!L", len(message["delete"]))  # long
      for key in message["delete"]:
        delete_message += WebSocketServer.encode_bytes(key)

      message = update_message + delete_message

    return WebSocketServer.encode_bytes(message)

  @staticmethod
  def decode_message(message):
    """
    Decode web socket message from client
    """

    if not message:
      return None
    elif type(message) == str:
      message = bytearray(message)

    # Read opcode and length
    b1, b2 = struct.unpack("!BB", message[:2])
    op_code = b1 & 0b00001111
    payload_length = b2 & 0b01111111

    # Extract masks
    idx_first_mask = 2
    if payload_length == 126:
      idx_first_mask = 4
    elif payload_length == 127:
      idx_first_mask = 10
    idx_first_data = idx_first_mask + 4
    masks = message[idx_first_mask:idx_first_data]

    # Decode data
    decoded_bytes = bytearray(
      [
        message[j] ^ masks[i % 4]
        for i, j in enumerate(range(idx_first_data, len(message)))
      ]
    )
    if decoded_bytes == b"\x03\xe9":
      return None

    return decoded_bytes
