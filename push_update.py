"""変更をコミット＆GitHubにpushするスクリプト"""
import re, subprocess, sys, os

CONFIG_PATH = r"C:\Users\Shoichi\Desktop\wc2026\wc2026_config.json"
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
LOG_PATH    = os.path.join(SCRIPT_DIR, "push_log.txt")

with open(CONFIG_PATH, "rb") as f:
    raw = f.read().decode("latin-1")
m = re.search(r'"github_token":\s*"([^"]+)"', raw)
TOKEN = m.group(1)

git_paths = [r"C:\Program Files\Git\bin\git.exe",
             r"C:\Program Files (x86)\Git\bin\git.exe", "git"]
GIT = None
for p in git_paths:
    try:
        r = subprocess.run([p, "--version"], capture_output=True)
        if r.returncode == 0:
            GIT = p
            break
    except Exception:
        pass

log_lines = []
def log(msg):
    print(msg)
    log_lines.append(msg)

log(f"GIT: {GIT}")

# ロックファイル削除
for lock in ["index.lock", "HEAD.lock"]:
    lpath = os.path.join(SCRIPT_DIR, ".git", lock)
    if os.path.exists(lpath):
        try:
            os.remove(lpath)
            log(f"[OK] ロック解除: {lock}")
        except Exception as e:
            log(f"[WARN] ロック解除失敗: {e}")

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=SCRIPT_DIR, **kw)
    out = (r.stdout + r.stderr).strip()
    if out: log(out)
    return r

REMOTE = f"https://{TOKEN}@github.com/shotakdecsix-oss/detective-ai.git"
run([GIT, "remote", "set-url", "origin", REMOTE])

log("\n--- git add & commit ---")
run([GIT, "add", "app.py", "index.html"])
run([GIT, "commit", "-m", "fix: 直接特定質問をサーバー側でguessに強制変換"])

log("\n--- git push ---")
result = run([GIT, "push", "origin", "main"])
log(f"\nreturncode: {result.returncode}")

with open(LOG_PATH, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines))
