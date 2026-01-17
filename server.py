from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import json
import os
import logging

app = Flask(__name__)
# Tell Flask it is behind a proxy (Nginx).
# x_for=1 means we trust the first X-Forwarded-For value.
# x_proto=1 means we trust X-Forwarded-Proto.
# x_host=1 means we trust X-Forwarded-Host.
# x_port=1 means we trust X-Forwarded-Port.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

CORS(app)  # Enable CORS for all routes

# Configure logging
log_handlers = [logging.StreamHandler()] # Console logging
log_file = os.environ.get('LOG_FILE', '/logs/backend.log')

# Only add FileHandler if the directory exists (Docker) or if we are local and want it
if os.path.exists(os.path.dirname(log_file)):
    log_handlers.append(logging.FileHandler(log_file))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=log_handlers
)
logger = logging.getLogger(__name__)

# Silence the default Werkzeug logger (which logs the proxy IP)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Use environment variable for DATA_DIR if set, otherwise default to relative 'site/public' for local dev
# In Docker, it maps to /data -> public_data
# Locally, public data is in site/public
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(os.getcwd(), 'site', 'public'))

@app.route('/api/save_correction', methods=['POST'])
def save_correction():
    try:
        data = request.json
        state = data.get('state')
        correction = data.get('correction')

        if not state or not correction:
            return jsonify({'error': 'Missing state or correction data'}), 400

        # Get Client IP (ProxyFix ensures remote_addr is the real client IP)
        client_ip = request.remote_addr

        # Construct the path to the correction file based on state        
        file_path = os.path.join(DATA_DIR, 'states', state, f'{state}_alkis_corrections.json')
        
        logger.info(f"Received correction from {client_ip} for state {state}. Path: {file_path}")
        logger.info(f"Correction Content: {json.dumps(correction, ensure_ascii=False)}")

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        corrections_data = []
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content:
                        corrections_data = json.loads(content)
            except json.JSONDecodeError:
                logger.warning(f"File {file_path} exists but is empty or invalid JSON. Starting fresh.")
                corrections_data = []

        corrections_data.append(correction)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(corrections_data, f, indent=4, ensure_ascii=False)

        logger.info(f"Correction saved successfully from {client_ip}.")
        return jsonify({'message': 'Correction saved successfully'}), 200

    except Exception as e:
        logger.error(f"Error saving correction from {request.remote_addr}: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
