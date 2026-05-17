import secrets
import string
import datetime
import os
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from flask_apscheduler import APScheduler

app = Flask(__name__)
scheduler = APScheduler()

db = {}
counter = 1

# --- ROUTE 1: YOUR MAIN HOME PAGE ---
@app.route('/')
def main_dashboard():
    # Serves your existing index.html from the root folder
    return send_from_directory('.', 'index.html')

# --- ROUTE 2: SERVE ALL YOUR APPS ---
# Access via: domain.com/apps/share-app/index.html
@app.route('/apps/<path:path>')
def serve_apps(path):
    print(path)
    return send_from_directory('./appsDeployed', path)

# --- ROUTE 3: THE SECRET SHORT LINKS ---
# Matches domain.com/1, domain.com/2 etc.
@app.route('/<id>')
def secret_link(id):
    # Only try to unlock if the ID is numeric (to avoid clashing with other paths)
    if id.isdigit() and id in db:
        return render_template('share_view.html', share_id=id)
    return "Link not found or expired.", 404

# --- API FOR SHARING ---
@app.route('/api/share', methods=['POST'])
def api_share():
    global counter
    content = request.json.get('content')
    expiry_hours = int(request.json.get('expiry', 24))
    
    share_id = str(counter)
    counter += 1
    
    passcode = ''.join(secrets.choice(string.digits) for _ in range(5))
    expiry_time = datetime.datetime.now() + datetime.timedelta(hours=expiry_hours)
    
    db[share_id] = {
        "content": content,
        "password_hash": generate_password_hash(passcode),
        "expires_at": expiry_time
    }
    return jsonify({"link": f"{request.host_url}{share_id}", "passcode": passcode})

@app.route('/api/unlock/<id>', methods=['POST'])
def api_unlock(id):
    password = request.json.get('password')
    if id in db and check_password_hash(db[id]['password_hash'], password):
        return jsonify({"content": db[id]['content']})
    return jsonify({"error": "Invalid"}), 401

# Scheduler cleanup logic remains the same...
if __name__ == '__main__':
    scheduler.start()
    app.run(debug=True, port=8003, host='0.0.0.0')


# pm2 start app.py --interpreter uv --name "apps-center" -- run app.py
