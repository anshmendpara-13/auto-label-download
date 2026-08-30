"""Meesho Bot Web Dashboard - python app.py - http://localhost:5000"""

import os, json, shutil, logging, threading, sys, subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, abort
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__, template_folder="templates", static_folder="static")

@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        response = jsonify({"success": True})
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        return response

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

DATA_DIR = Path("data")
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
LOGS_DIR = Path("logs")
ENV_FILE = Path(".env")

for d in [DATA_DIR, DOWNLOAD_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

state = {"running": False, "current_account": None, "last_run": None, "next_run": None, "logs": []}


class WH(logging.Handler):
    def __init__(self, n=200):
        super().__init__()
        self.n = n

    def emit(self, r):
        state["logs"].append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": r.levelname,
            "message": self.format(r)
        })
        if len(state["logs"]) > self.n:
            state["logs"] = state["logs"][-self.n:]


def setup_log():
    from meesho_bot import log
    h = WH()
    h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(h)


setup_log()


def get_accounts():
    load_dotenv(override=True)
    a = [x.strip() for x in os.getenv("ACCOUNTS", "").split(",") if x.strip()]
    if DATA_DIR.exists():
        for d in DATA_DIR.iterdir():
            if d.is_dir() and (d / "state.json").exists() and d.name not in a:
                a.append(d.name)
    return a


def acc_status(aid):
    sf = DATA_DIR / aid / "state.json"
    return {
        "id": aid,
        "has_session": sf.exists(),
        "session_modified": datetime.fromtimestamp(sf.stat().st_mtime).isoformat() if sf.exists() else None,
        "session_size_kb": round(sf.stat().st_size / 1024, 1) if sf.exists() else 0
    }


def sched_times():
    load_dotenv(override=True)
    return [t.strip() for t in os.getenv("SCHEDULE_TIMES", "09:00,13:00,17:00,20:00").split(",") if ":" in t.strip()]


def sched_days():
    load_dotenv(override=True)
    raw = os.getenv("SCHEDULE_DAYS", "").strip().lower()
    if not raw or raw in ("all", "everyday", "daily", "*"):
        return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    valid = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    days = []
    for d in raw.split(","):
        d = d.strip().lower()
        if d in valid and d not in days:
            days.append(d)
    return days if days else ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def env_set(lines, key, val):
    found = False
    out = []
    for l in lines:
        if l.strip().startswith(f"{key}="):
            out.append(f"{key}={val}\n")
            found = True
        else:
            out.append(l)
    if not found:
        out.append(f"{key}={val}\n")
    return out


def env_write(key, val):
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True) if ENV_FILE.exists() else []
    ENV_FILE.write_text("".join(env_set(lines, key, val)), encoding="utf-8")


_lock = threading.Lock()


def run_bg(aid=None):
    if state["running"]:
        return  # Already running — skip duplicate trigger (e.g. from scheduler)
    def _r():
        with _lock:
            state["running"] = True
            state["current_account"] = aid if aid else "all accounts"
            try:
                if aid:
                    from meesho_bot import run_once
                    run_once(aid)
                else:
                    from meesho_bot import run_all
                    run_all()
            finally:
                state["running"] = False
                state["current_account"] = None
                state["last_run"] = datetime.now().isoformat()
    threading.Thread(target=_r, daemon=True).start()


def get_next_run_info():
    """Calculate next run time based on schedule times and days."""
    try:
        import datetime as dt
        times = sched_times()
        days = sched_days()
        if not times or not days:
            return None

        day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        allowed = set(day_map.get(d) for d in days)
        now = dt.datetime.now()
        today_wd = now.weekday()

        # Try today
        if today_wd in allowed:
            for t_str in sorted(times):
                try:
                    h, m = t_str.strip().split(":")
                    rt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                    if rt > now:
                        return rt.strftime("%I:%M %p")
                except Exception:
                    pass

        # Try next 14 days
        for offset in range(1, 15):
            check = now + dt.timedelta(days=offset)
            if check.weekday() in allowed:
                for t_str in sorted(times):
                    try:
                        h, m = t_str.strip().split(":")
                        rt = check.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
                        return rt.strftime("%a %I:%M %p")
                    except Exception:
                        pass
        return None
    except Exception:
        return None


# Start scheduler daemon in background
try:
    import scheduler as _sched_mod
    _sched_mod._run_func = run_bg
    _sched_mod.start()
    print("[+] Scheduler started in background.")
except Exception as e:
    print(f"[!] Failed to start scheduler: {e}")


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/status")
def st():
    accs = get_accounts()
    det = [acc_status(a) for a in accs]
    today = datetime.now().strftime("%Y-%m-%d")
    dl = []
    td = DOWNLOAD_DIR / today
    if td.exists():
        for ad in td.iterdir():
            if ad.is_dir():
                for p in ad.glob("*.pdf"):
                    dl.append({
                        "file": p.name,
                        "account": ad.name,
                        "size_kb": round(p.stat().st_size / 1024, 1),
                        "time": datetime.fromtimestamp(p.stat().st_mtime).strftime("%H:%M:%S"),
                        "path": str(p.relative_to(DOWNLOAD_DIR)).replace("\\", "/")
                    })
    return jsonify({
        "accounts": det,
        "schedule": sched_times(),
        "days": sched_days(),
        "running": state["running"],
        "current_account": state["current_account"],
        "last_run": state["last_run"],
        "next_run": get_next_run_info(),
        "today_downloads": dl,
        "headless": os.getenv("HEADLESS", "false").lower() == "true",
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/logs")
def lg():
    import re
    f = LOGS_DIR / f"run_{datetime.now():%Y%m%d}.log"
    parsed_logs = []
    if f.exists():
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            for line in lines[-150:]:
                line = line.rstrip("\n")
                if not line:
                    continue
                # Match line format: 2026-08-30 15:07:46,123 [INFO] Message
                m = re.match(r"^\d{4}-\d{2}-\d{2}\s+(\d{2}:\d{2}:\d{2}),\d+\s+\[(\w+)\]\s+(.*)$", line)
                if m:
                    parsed_logs.append({
                        "time": m.group(1),
                        "level": m.group(2),
                        "message": m.group(3)
                    })
                else:
                    if parsed_logs:
                        parsed_logs[-1]["message"] += "\n" + line
                    else:
                        parsed_logs.append({
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "level": "INFO",
                            "message": line
                        })
        except Exception as e:
            print(f"Error parsing log file: {e}")
            
    if not parsed_logs:
        parsed_logs = state["logs"][-100:]
    else:
        parsed_logs = parsed_logs[-100:]
        
    return jsonify({"logs": parsed_logs})


@app.route("/api/logs/file")
def lf():
    f = LOGS_DIR / f"run_{datetime.now():%Y%m%d}.log"
    if not f.exists():
        return jsonify({"content": "No log today.", "filename": None})
    return jsonify({"content": f.read_text(encoding="utf-8", errors="replace")[-50000:], "filename": f.name})


@app.route("/api/accounts", methods=["GET", "POST", "DELETE"])
def acc():
    if request.method == "GET":
        return jsonify({"accounts": [acc_status(a) for a in get_accounts()]})

    if request.method == "POST":
        d = request.json
        aid = d.get("account_id", "").strip().lower()
        aid = "".join(c for c in aid if c.isalnum() or c == "_")
        if not aid:
            return jsonify({"error": "ID required"}), 400
        (DATA_DIR / aid).mkdir(parents=True, exist_ok=True)
        em = d.get("email", "").strip()
        pw = d.get("password", "").strip()
        if em and pw:
            k = aid.upper()
            env_write(f"MEESHO_EMAIL_{k}", em)
            env_write(f"MEESHO_PASSWORD_{k}", pw)
        accs = get_accounts()
        if aid not in accs:
            accs.append(aid)
            env_write("ACCOUNTS", ",".join(accs))
        return jsonify({"success": True})

    if request.method == "DELETE":
        aid = request.json.get("account_id", "").strip()
        if not aid:
            return jsonify({"error": "ID required"}), 400
        accs = get_accounts()
        if aid in accs:
            accs.remove(aid)
            env_write("ACCOUNTS", ",".join(accs))
        if request.json.get("delete_session"):
            sf = DATA_DIR / aid / "state.json"
            if sf.exists():
                sf.unlink()
        return jsonify({"success": True})


@app.route("/api/schedule", methods=["GET", "POST"])
def sch():
    if request.method == "GET":
        return jsonify({"times": sched_times(), "days": sched_days()})

    data = request.json

    ts = data.get("times", "").strip()
    times = [t.strip() for t in ts.split(",") if t.strip()]
    for t in times:
        p = t.split(":")
        if len(p) != 2:
            return jsonify({"error": f"Bad time: '{t}'"}), 400
        try:
            h, m = int(p[0]), int(p[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError()
        except Exception:
            return jsonify({"error": f"Bad time: '{t}'"}), 400
    env_write("SCHEDULE_TIMES", ts)

    days = data.get("days", [])
    valid = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    clean = [d for d in days if d in valid]
    if len(clean) == 7:
        env_write("SCHEDULE_DAYS", "")
    elif clean:
        env_write("SCHEDULE_DAYS", ",".join(clean))
    else:
        env_write("SCHEDULE_DAYS", "")

    # Reset fired cache so newly scheduled times are ready to trigger
    try:
        import scheduler as _sched_mod
        _sched_mod._fired.clear()
    except Exception:
        pass

    return jsonify({"success": True, "times": times, "days": clean if clean else valid})


@app.route("/api/run", methods=["POST"])
def rn():
    if state["running"]:
        return jsonify({"error": "Already running"}), 409
    run_bg(request.json.get("account_id"))
    return jsonify({"success": True})


def run_login_setup_subprocess(account_id):
    from meesho_bot import log
    log.info(f"[{account_id}] Starting automatic login setup...")
    try:
        # Run login_setup.py as a subprocess
        cmd = [sys.executable, "login_setup.py", account_id]
        
        # We start the subprocess with stdout and stderr piped
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # Read output line by line in real-time
        for line in process.stdout:
            line_str = line.strip()
            if line_str:
                log.info(f"[{account_id}] {line_str}")
                
        process.wait()
        if process.returncode == 0:
            log.info(f"[{account_id}] Automatic login completed successfully!")
            return True
        else:
            log.error(f"[{account_id}] Automatic login failed with return code {process.returncode}")
            return False
    except Exception as e:
        log.error(f"[{account_id}] Error running login_setup: {e}")
        return False


@app.route("/api/create-session", methods=["POST"])
def create_session():
    if state["running"]:
        return jsonify({"error": "A process is already running"}), 409
        
    aid = request.json.get("account_id", "").strip().lower()
    aid = "".join(c for c in aid if c.isalnum() or c == "_")
    if not aid:
        return jsonify({"error": "Account ID required"}), 400
        
    # Verify credentials exist
    load_dotenv(override=True)
    k = aid.upper()
    email = os.getenv(f"MEESHO_EMAIL_{k}")
    password = os.getenv(f"MEESHO_PASSWORD_{k}")
    if not email or not password:
        return jsonify({"error": f"Credentials for {aid} not found in .env. Please configure them in accounts first."}), 400
        
    def _run_login():
        with _lock:
            state["running"] = True
            state["current_account"] = f"{aid} (login)"
            try:
                run_login_setup_subprocess(aid)
            finally:
                state["running"] = False
                state["current_account"] = None
                
    threading.Thread(target=_run_login, daemon=True).start()
    return jsonify({"success": True})


@app.route("/api/upload-session", methods=["POST"])
def ups():
    aid = request.form.get("account_id", "").strip().lower()
    f = request.files.get("file")
    if not aid:
        return jsonify({"error": "ID required"}), 400
    if not f:
        return jsonify({"error": "No file"}), 400
    if not f.filename.endswith(".json"):
        return jsonify({"error": "Must be .json"}), 400
    try:
        c = f.read()
        d = json.loads(c)
        if "cookies" not in d and "origins" not in d:
            return jsonify({"error": "Invalid session file"}), 400
        if len(c) < 100:
            return jsonify({"error": "File too small"}), 400
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400

    ad = DATA_DIR / aid
    ad.mkdir(parents=True, exist_ok=True)
    sp = ad / "state.json"
    if sp.exists():
        shutil.copy2(sp, ad / f"state.json.bak.{datetime.now():%Y%m%d_%H%M%S}")
    with open(sp, "w", encoding="utf-8") as fh:
        fh.write(c.decode("utf-8"))

    accs = get_accounts()
    if aid not in accs:
        accs.append(aid)
        env_write("ACCOUNTS", ",".join(accs))
    return jsonify({"success": True, "account_id": aid, "file_size_kb": round(len(c) / 1024, 1)})


@app.route("/api/download-session/<aid>")
def ds(aid):
    sf = DATA_DIR / aid / "state.json"
    if not sf.exists():
        abort(404)
    return send_file(sf, as_attachment=True, download_name=f"{aid}_state.json")


@app.route("/api/downloads")
def adl():
    dl = []
    if DOWNLOAD_DIR.exists():
        for dd in sorted(DOWNLOAD_DIR.iterdir(), reverse=True):
            if not dd.is_dir():
                continue
            for ad in dd.iterdir():
                if not ad.is_dir():
                    continue
                for p in ad.glob("*.pdf"):
                    dl.append({
                        "date": dd.name,
                        "account": ad.name,
                        "file": p.name,
                        "size_kb": round(p.stat().st_size / 1024, 1),
                        "path": str(p.relative_to(DOWNLOAD_DIR)).replace("\\", "/"),
                        "time": datetime.fromtimestamp(p.stat().st_mtime).strftime("%H:%M:%S")
                    })
    return jsonify({"downloads": dl[:200]})


@app.route("/api/download-pdf/<path:fp>", methods=["GET", "DELETE"])
def dpf(fp):
    p = (DOWNLOAD_DIR / fp).resolve()
    # Security check: prevent directory traversal
    if not str(p).startswith(str(DOWNLOAD_DIR.resolve())):
        abort(403)
        
    if request.method == "DELETE":
        if p.exists() and p.is_file():
            try:
                p.unlink()
                # Clean up empty parent directories
                parent = p.parent
                if parent.exists() and parent != DOWNLOAD_DIR and not any(parent.iterdir()):
                    parent.rmdir()
                date_parent = parent.parent
                if date_parent.exists() and date_parent != DOWNLOAD_DIR and not any(date_parent.iterdir()):
                    date_parent.rmdir()
            except Exception:
                pass
            return jsonify({"success": True})
        return jsonify({"error": "File not found"}), 404

    if not p.exists() or not p.is_file():
        abort(404)
    return send_file(p, as_attachment=True)


@app.route("/api/settings", methods=["GET", "POST"])
def set_():
    if request.method == "GET":
        load_dotenv(override=True)
        return jsonify({
            "headless": os.getenv("HEADLESS", "false"),
            "download_dir": os.getenv("DOWNLOAD_DIR", "./downloads"),
            "schedule_times": sched_times(),
            "schedule_days": sched_days(),
        })
    if "headless" in request.json:
        env_write("HEADLESS", "true" if request.json["headless"] else "false")
    load_dotenv(override=True)
    return jsonify({"success": True})


if __name__ == "__main__":
    port = int(os.getenv("PORT", os.getenv("DASHBOARD_PORT", 5000)))
    print(f"\n{'='*45}\n  Meesho Bot Dashboard\n  http://localhost:{port}\n{'='*45}\n")
    app.run(host="0.0.0.0", port=port, debug=False)