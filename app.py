"""
名探偵AI — Flask バックエンド
Claude が何でも推理する探偵ゲーム
Config: akinator_config.json
"""

import json, os, anthropic
from flask import Flask, request, jsonify, send_from_directory

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "akinator_config.json")

CFG = {}
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        CFG = json.load(f)

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY") or CFG.get("anthropic_key", "")
MODEL         = CFG.get("model", "claude-haiku-4-5")
PORT          = int(CFG.get("port", 5052))

client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
app    = Flask(__name__, static_folder=BASE_DIR)

# ---------------------------------------------------------------------------
# システムプロンプト
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """あなたは「名探偵AI」です。
ユーザーが頭の中でイメージしているものを、鋭い質問と論理的推理で突き止めます。
対象は何でも構いません。人物、動物、植物、食べ物、飲み物、乗り物、道具、建物、場所、
スポーツ、映画、キャラクター、概念、現象、素材、色、数字…文字通り万物が対象です。

## 推理戦略
1. 最初の数問で大カテゴリを特定（物理的存在か抽象的か、生物か無生物か、現実か架空かなど）
2. 次に中カテゴリへ絞り込む（食べ物なら和洋甘塩など）
3. 徐々に特定の特徴を追求する
4. 確信が高まったら「犯人」を特定する

## 特定の条件
- 質問が5問以上で確信度75%以上 → 特定する
- 質問が15問以上で確信度50%以上 → 特定する（最善の推理）
- 質問が20問を超えたら必ず特定する（諦めずに最善の推理）

## 出力形式
必ず以下どちらかのJSONのみを返すこと。他のテキストは一切不要。

質問する場合:
{"type":"question","text":"質問文（15字以内・はい/いいえで答えられる形）","turn":N}

特定する場合:
{"type":"guess","answer":"答え","confidence":85,"reason":"推理の根拠（50字以内）","turn":N}

## 注意
- 質問は必ずはい/いいえ/たぶんはい/たぶんいいえ/わからない で答えられる形にする
- 「〜ですか？」で終わること
- 同じ質問を繰り返さない
- 「わからない」と答えた場合は別の角度から攻める
"""

def build_history_text(history: list[dict]) -> str:
    if not history:
        return "（まだ手がかりなし）"
    lines = []
    for i, h in enumerate(history, 1):
        ans_map = {
            "yes":      "はい",
            "no":       "いいえ",
            "maybe":    "たぶんはい",
            "maybe_no": "たぶんいいえ",
            "dunno":    "わからない",
        }
        ans = ans_map.get(h.get("answer", ""), h.get("answer", ""))
        lines.append(f"Q{i}: {h['question']} → {ans}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# ルート
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/api/next", methods=["POST"])
def next_step():
    body    = request.get_json(force=True)
    history = body.get("history", [])
    turn    = len(history) + 1

    history_text = build_history_text(history)

    user_msg = f"""これまでの手がかり（{len(history)}問済み）:
{history_text}

現在{turn}問目です。推理戦略に従って次の行動をJSONで返してください。"""

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].split("```")[0].replace("json", "").strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        data = json.loads(raw)
        data["turn"] = turn
        return jsonify(data)

    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON parse失敗: {e}\nraw: {resp.content[0].text[:200]}")
        return jsonify({"type": "question", "text": "生き物ですか？", "turn": turn})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/verify", methods=["POST"])
def verify():
    body    = request.get_json(force=True)
    guess   = body.get("guess", "")
    actual  = body.get("actual", "")
    correct = body.get("correct", False)

    if correct or not actual:
        return jsonify({"message": f"事件解決！やはり「{guess}」でしたね。名探偵の推理に狂いはない。"})

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=120,
            messages=[{"role": "user", "content":
                f"名探偵ゲームで「{guess}」と推理したが不正解で、正解は「{actual}」だった。"
                f"名探偵らしく悔しがりながら「なるほど、次こそは」という口調で一言。30字以内。"}]
        )
        msg = resp.content[0].text.strip()
    except:
        msg = f"なんと…「{actual}」でしたか。この名探偵が見誤るとは。次は必ず。"
    return jsonify({"message": msg})


if __name__ == "__main__":
    print(f"[名探偵AI] http://localhost:{PORT}")
    print(f"  Anthropic API: {'✓' if ANTHROPIC_KEY else '✗ 未設定'}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
