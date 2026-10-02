import os
import json
import time
import secrets
import random
from flask import Flask, render_template, request, jsonify, session

app = Flask(__name__)
app.secret_key = os.getenv("atxscripter", secrets.token_hex(32))

# ==================== CONFIG ====================
DATA_DIR = os.getenv("DATA_DIR", "/data")
KEYS_FILE = os.path.join(DATA_DIR, "keys.json")

TELEGRAM_CHANNEL = "https://t.me/+_eEH_XgASVFhNmNl"

KEY_VALID_HOURS = 24
TASK_COOLDOWN_SECONDS = 30


# ==================== STORAGE ====================
def ensure_storage():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(KEYS_FILE):
            with open(KEYS_FILE, "w") as f:
                json.dump({}, f)
    except Exception as e:
        print(f"[storage error] {e}")


def load_keys():
    ensure_storage()
    try:
        with open(KEYS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_keys(data):
    ensure_storage()
    with open(KEYS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def gen_key():
    return "AD-" + "-".join(secrets.token_hex(2).upper() for _ in range(3))


# ==================== CAPTCHA GENERATOR ====================
def gen_math_challenge():
    ops = [
        ("+", lambda a, b: a + b),
        ("-", lambda a, b: a - b),
        ("x", lambda a, b: a * b),
    ]
    op_sym, op_fn = random.choice(ops)
    if op_sym == "x":
        a = random.randint(2, 12)
        b = random.randint(2, 12)
    else:
        a = random.randint(10, 50)
        b = random.randint(5, 30)
        if op_sym == "-" and b > a:
            a, b = b, a

    answer = op_fn(a, b)
    question = f"What is {a} {op_sym} {b}?"
    return {"question": question, "answer": str(answer)}


def gen_text_challenge():
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(random.choices(chars, k=5))
    return {"question": f"Type this code: {code}", "answer": code}


def gen_sequence_challenge():
    start = random.randint(1, 5)
    step = random.randint(2, 4)
    seq = [start + step * i for i in range(4)]
    answer = start + step * 4
    question = f"What comes next? {', '.join(map(str, seq))}, ?"
    return {"question": question, "answer": str(answer)}


def gen_challenge():
    generators = [gen_math_challenge, gen_text_challenge, gen_sequence_challenge]
    return random.choice(generators)()


# ==================== ROUTES ====================
@app.route("/")
def index():
    return render_template(
        "index.html",
        telegram_channel=TELEGRAM_CHANNEL,
    )


@app.route("/api/get-challenge", methods=["POST"])
def get_challenge():
    challenge = gen_challenge()
    session["captcha_answer"] = challenge["answer"].upper()
    session["captcha_time"] = time.time()
    session["captcha_solved"] = False
    return jsonify({"success": True, "question": challenge["question"]})


@app.route("/api/verify-human", methods=["POST"])
def verify_human():
    data = request.get_json() or {}
    answer = data.get("answer", "").strip().upper()

    expected = session.get("captcha_answer", "")
    challenge_time = session.get("captcha_time", 0)

    if not expected:
        return jsonify({"success": False, "error": "No challenge. Get a new one."}), 400

    if time.time() - challenge_time > 300:
        return jsonify({"success": False, "error": "Challenge expired. Get a new one."}), 410

    if answer != expected:
        session.pop("captcha_answer", None)
        return jsonify({"success": False, "error": "Wrong answer. Try again."}), 400

    session["captcha_solved"] = True
    session["captcha_solved_time"] = time.time()
    session.pop("captcha_answer", None)

    return jsonify({"success": True})


@app.route("/api/generate-key", methods=["POST"])
def generate_key():
    if not session.get("captcha_solved"):
        return jsonify({"success": False, "error": "Complete verification first"}), 403

    solved_time = session.get("captcha_solved_time", 0)
    elapsed = time.time() - solved_time
    if elapsed < TASK_COOLDOWN_SECONDS:
        remaining = int(TASK_COOLDOWN_SECONDS - elapsed)
        return jsonify({"success": False, "error": f"Wait {remaining}s"}), 429

    keys = load_keys()
    new_key = gen_key()
    keys[new_key] = {
        "created": int(time.time()),
        "expires": int(time.time()) + KEY_VALID_HOURS * 3600,
    }
    save_keys(keys)

    session.pop("captcha_solved", None)
    session.pop("captcha_solved_time", None)

    return jsonify({
        "success": True,
        "key": new_key,
        "expires_in_hours": KEY_VALID_HOURS,
    })


@app.route("/api/validate-key", methods=["POST"])
def validate_key():
    data = request.get_json() or {}
    key = data.get("key", "").strip()

    if not key:
        return jsonify({"valid": False, "error": "No key"}), 400

    keys = load_keys()
    entry = keys.get(key)

    if not entry:
        return jsonify({"valid": False, "error": "Invalid key"}), 404

    if entry.get("expires", 0) < time.time():
        return jsonify({"valid": False, "error": "Key expired"}), 410

    return jsonify({
        "valid": True,
        "expires": entry.get("expires"),
    })


@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": int(time.time())})


# ==================== ENTRY ====================
ensure_storage()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)