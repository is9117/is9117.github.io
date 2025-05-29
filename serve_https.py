import http.server
import ssl
import os

PORT = 443
os.chdir('docs')

httpd = http.server.HTTPServer(('0.0.0.0', PORT), http.server.SimpleHTTPRequestHandler)

# Create a secure context
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile='../blog.i544c.com+4.pem', keyfile='../blog.i544c.com+4-key.pem')

httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

print(f"🔒 Serving HTTPS at https://blog.i544c.com:{PORT}")
httpd.serve_forever()