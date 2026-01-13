from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import os
import logging

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

        # Construct the path to the correction file based on state        
        file_path = os.path.join(DATA_DIR, 'states', state, f'reported_{state}_alkis_corrections.json')
        
        logger.info(f"Received correction for state {state}. Path: {file_path}")

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

        logger.info("Correction saved successfully.")
        return jsonify({'message': 'Correction saved successfully'}), 200

    except Exception as e:
        logger.error(f"Error saving correction: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
