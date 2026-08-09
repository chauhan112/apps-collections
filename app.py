import secrets
import string
import datetime
import os
import hashlib
import json
import requests as http_requests
from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, Response
from flask_apscheduler import APScheduler

app = Flask(__name__, template_folder='.')


def _load_env_file(path='.env'):
    """Minimal .env loader: KEY=VALUE lines -> os.environ (without overriding set vars)."""
    env_path = os.path.join(os.path.dirname(__file__), path)
    if not os.path.isfile(env_path):
        return
    with open(env_path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.removeprefix('export ').strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_env_file()
app.config['BASE_URL'] = os.environ.get('BASE_URL', '/apps').rstrip('/')
scheduler = APScheduler()

db = {}
counter = 1


# --- CORS: allow cross-origin requests to the gateway and the /backend/* proxy ---
# Set CORS_ORIGINS to a comma-separated allowlist (e.g. "https://a.com,https://b.com")
# in .env; "*" (default) permits any origin.
CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '*').strip()
CORS_METHODS = 'GET, POST, PUT, PATCH, DELETE, OPTIONS'


@app.after_request
def _add_cors_headers(resp):
    """Attach CORS headers to every response, including proxied backend ones."""
    origin = request.headers.get('Origin')
    if CORS_ORIGINS == '*':
        resp.headers['Access-Control-Allow-Origin'] = '*'
    elif origin and origin in [o.strip() for o in CORS_ORIGINS.split(',') if o.strip()]:
        resp.headers['Access-Control-Allow-Origin'] = origin
        resp.headers['Vary'] = 'Origin'
    resp.headers['Access-Control-Allow-Methods'] = CORS_METHODS
    # Reflect whatever headers the preflight asked for; fall back to a sane default.
    requested = request.headers.get('Access-Control-Request-Headers')
    resp.headers['Access-Control-Allow-Headers'] = requested or 'Content-Type, Authorization'
    resp.headers['Access-Control-Max-Age'] = '600'
    return resp

# Security tracking
attempt_tracker = {}  # {ip: {share_id: {'attempts': count, 'last_attempt': timestamp}}}
captcha_challenges = {}  # {share_id: {'nonce': str, 'difficulty': int, 'expires': timestamp}}


def get_client_ip():
    """Get client IP address, handling proxy headers"""
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr


def check_rate_limit(ip, share_id):
    """Check if rate limit allows this attempt, returns (allowed, delay_seconds)"""
    now = datetime.datetime.now().timestamp()
    
    if ip not in attempt_tracker:
        attempt_tracker[ip] = {}
    
    if share_id not in attempt_tracker[ip]:
        attempt_tracker[ip][share_id] = {'attempts': 0, 'last_attempt': now}
        return True, 0
    
    tracking = attempt_tracker[ip][share_id]
    
    # Reset if no attempts in the last hour
    if now - tracking['last_attempt'] > 3600:
        tracking['attempts'] = 0
        tracking['last_attempt'] = now
        return True, 0
    
    tracking['last_attempt'] = now
    
    # Exponential backoff: delays after 3 attempts
    if tracking['attempts'] >= 3:
        delay = 2 ** (tracking['attempts'] - 3)  # 1s, 2s, 4s, 8s, 16s...
        
        # Block for 1 hour after 10 attempts
        if tracking['attempts'] >= 10:
            time_since_block_start = now - tracking['last_attempt']
            if time_since_block_start < 3600:
                remaining = int(3600 - time_since_block_start)
                return False, remaining
            else:
                tracking['attempts'] = 0
                return True, 0
        
        if delay > 0:
            return False, delay
    
    return True, 0


def record_failed_attempt(ip, share_id):
    """Record a failed attempt"""
    if ip not in attempt_tracker:
        attempt_tracker[ip] = {}
    if share_id not in attempt_tracker[ip]:
        attempt_tracker[ip][share_id] = {'attempts': 0, 'last_attempt': datetime.datetime.now().timestamp()}
    attempt_tracker[ip][share_id]['attempts'] += 1


def generate_captcha_challenge(share_id):
    """Generate a proof-of-work challenge"""
    nonce = secrets.token_hex(16)
    difficulty = 3  # Hash must start with 3 zeros (adjustable)
    expires = datetime.datetime.now() + datetime.timedelta(minutes=5)
    
    challenge_data = {
        'nonce': nonce,
        'difficulty': difficulty,
        'expires': expires
    }
    
    captcha_challenges[share_id] = challenge_data
    return nonce, difficulty


def verify_captcha_solution(share_id, solution):
    """Verify the proof-of-work solution"""
    if share_id not in captcha_challenges:
        return False
    
    challenge = captcha_challenges[share_id]
    
    # Check if expired
    if datetime.datetime.now() > challenge['expires']:
        del captcha_challenges[share_id]
        return False
    
    # Verify the solution
    test_string = f"{challenge['nonce']}_{solution}"
    hash_result = hashlib.sha256(test_string.encode()).hexdigest()
    
    # Check if hash starts with required number of zeros
    required_prefix = '0' * challenge['difficulty']
    if hash_result.startswith(required_prefix):
        del captcha_challenges[share_id]
        return True
    
    return False


# --- ROUTE 1: YOUR MAIN HOME PAGE ---
@app.route('/')
def main_dashboard():
    # Renders index.html as a Jinja template. BASE_URL comes from .env and the
    # apps list is read from apps.json at request time, so `invoke deploy`
    # additions appear on the next page load (no restart needed).
    apps_json_path = os.path.join(os.path.dirname(__file__), 'apps.json')
    apps_list = []
    if os.path.isfile(apps_json_path):
        with open(apps_json_path) as fh:
            try:
                apps_list = json.load(fh)
            except json.JSONDecodeError:
                apps_list = []
    return render_template('index.html', base_url=app.config['BASE_URL'], apps=apps_list)


@app.route('/apps/<path:path>')
def serve_apps(path):
    full_path = os.path.join('./appsDeployed', path)
    if os.path.isdir(full_path) and not path.endswith('/'):
        return redirect(f'/apps/{path}/')
    if os.path.isdir(full_path):
        return send_from_directory(full_path, 'index.html')
    return send_from_directory('./appsDeployed', path)


# --- REVERSE PROXY: /backend/* -> any-backend (Django on :8500) ---
BACKEND_TARGET = os.environ.get('BACKEND_TARGET', 'http://127.0.0.1:8500')
HOP_BY_HOP = {
    'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
    'te', 'trailers', 'transfer-encoding', 'upgrade', 'host', 'content-length',
}


def _forward(path):
    url = f"{BACKEND_TARGET}/{path}"
    # Preserve query string
    if request.query_string:
        url += '?' + request.query_string.decode()

    # Forward inbound headers, dropping hop-by-hop ones
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    body = request.get_data()

    try:
        upstream = http_requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=body,
            allow_redirects=False,
            stream=True,
            timeout=60,
        )
    except http_requests.RequestException as exc:
        print(f"[PROXY] backend unreachable: {exc}")
        return jsonify({"error": "Backend unavailable"}), 502

    resp_headers = [(k, v) for k, v in upstream.raw.headers.items() if k.lower() not in HOP_BY_HOP]
    return Response(upstream.iter_content(chunk_size=8192),
                    status=upstream.status_code,
                    headers=resp_headers)


_PROXY_METHODS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']


@app.route('/backend', methods=_PROXY_METHODS, provide_automatic_options=False)
@app.route('/backend/', methods=_PROXY_METHODS, provide_automatic_options=False)
@app.route('/backend/<path:path>', methods=_PROXY_METHODS, provide_automatic_options=False)
def backend_proxy(path=''):
    return _forward(path)


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
    
    # Stronger passcode: letters, numbers, and symbols (5 chars = ~7.3 billion combinations)
    characters = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?"
    passcode = ''.join(secrets.choice(characters) for _ in range(5))
    expiry_time = datetime.datetime.now() + datetime.timedelta(hours=expiry_hours)
    
    db[share_id] = {
        "content": content,
        "password_hash": generate_password_hash(passcode),
        "expires_at": expiry_time
    }
    
    print(f"[SECURITY] New share created: ID={share_id}, expires={expiry_time}")
    
    return jsonify({"link": f"{request.host_url}{share_id}", "passcode": passcode})


@app.route('/api/captcha/<id>', methods=['GET'])
def get_captcha(id):
    """Get a proof-of-work challenge for this share"""
    if id not in db:
        return jsonify({"error": "Share not found"}), 404
    
    nonce, difficulty = generate_captcha_challenge(id)
    return jsonify({
        "nonce": nonce,
        "difficulty": difficulty,
        "instructions": f"Find a number that when appended to '{nonce}' and hashed with SHA256, starts with {difficulty} zeros."
    })


@app.route('/api/unlock/<id>', methods=['POST'])
def api_unlock(id):
    ip = get_client_ip()
    password = request.json.get('password')
    captcha_solution = request.json.get('captcha_solution')
    
    # Check if share exists (generic error to prevent enumeration)
    if id not in db:
        # Still check rate limiting to prevent timing attacks
        check_rate_limit(ip, id)
        return jsonify({"error": "Invalid credentials"}), 401
    
    # Check expiry
    if datetime.datetime.now() > db[id]['expires_at']:
        print(f"[SECURITY] Attempt to access expired share: ID={id}, IP={ip}")
        return jsonify({"error": "Invalid credentials"}), 401
    
    # Check rate limiting
    allowed, delay = check_rate_limit(ip, id)
    if not allowed:
        print(f"[SECURITY] Rate limit exceeded: ID={id}, IP={ip}, delay={delay}s")
        return jsonify({"error": "Too many attempts", "retry_after": delay}), 429
    
    # Check if CAPTCHA is required (after 2 failed attempts)
    if ip in attempt_tracker and id in attempt_tracker[ip] and attempt_tracker[ip][id]['attempts'] >= 2:
        if not captcha_solution:
            print(f"[SECURITY] CAPTCHA required: ID={id}, IP={ip}, attempts={attempt_tracker[ip][id]['attempts']}")
            return jsonify({"error": "CAPTCHA required"}), 403
        
        if not verify_captcha_solution(id, captcha_solution):
            print(f"[SECURITY] Invalid CAPTCHA solution: ID={id}, IP={ip}")
            return jsonify({"error": "Invalid CAPTCHA"}), 403
    
    # Verify password
    if check_password_hash(db[id]['password_hash'], password):
        print(f"[SECURITY] Successful unlock: ID={id}, IP={ip}")
        # Reset attempt counter on success
        if ip in attempt_tracker and id in attempt_tracker[ip]:
            del attempt_tracker[ip][id]
        return jsonify({"content": db[id]['content']})
    
    # Record failed attempt
    record_failed_attempt(ip, id)
    print(f"[SECURITY] Failed unlock attempt: ID={id}, IP={ip}, total_attempts={attempt_tracker[ip][id]['attempts']}")
    
    return jsonify({"error": "Invalid credentials"}), 401


# Scheduler cleanup logic remains the same...
if __name__ == '__main__':
    scheduler.start()
    app.run(debug=True, port=8003, host='0.0.0.0')


# pm2 start "uv run gunicorn --bind 0.0.0.0:8003 --workers 1 --threads 4 app:app" --name "apps-center"