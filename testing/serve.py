

import http.server
import socketserver
import os
import mimetypes

PORT = 8000
DIRECTORY = "site"

mimetypes.add_type('application/json', '.json')
mimetypes.add_type('application/vnd.mapbox-vector-tile', '.pbf')

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"Serving at http://localhost:{PORT}")
    httpd.serve_forever()

