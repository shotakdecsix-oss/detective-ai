"""
名探偵AI — Flask バックエンド
Claude が何でも推理する探偵ゲーム
Config: akinator_config.json
"""

import json, os, re, anthropic
from datetime import datetime, timezone, timedelta
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

JST = timezone(timedelta(hours=9))
SERVER_START = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

# ---------------------------------------------------------------------------
# モード切替（True = フェーズ方式 / False = 元の仕様）
# ---------------------------------------------------------------------------
USE_PHASE_MODE = True  # ← ここを False にすると元の仕様に即戻し

# ---------------------------------------------------------------------------
# システムプロンプト（元の仕様）
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_ORIGINAL = """あなたは「名探偵あいちゃん」です。小学生の女の子の探偵で、明るくてかわいい性格です。
ユーザーが頭の中でイメージしているものを、やさしい質問と鋭い推理で突き止めます。
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

## 絶対禁止：答えを直接質問するパターン
以下のような質問は全て禁止。見つけた時点でguessに変えること。

❌ 禁止パターン（具体例）:
- 「それは〇〇ですか？」← "それは"で始まる質問は全て禁止
- 「どじょうですか？」「錦鯉ですか？」「ごぼうですか？」「ダーツですか？」
  ← 固有名詞・生物名・物品名だけの質問は禁止

✅ 許可パターン（具体例）:
- 「淡水に生息しますか？」「泥の中に潜りますか？」「食用になりますか？」
- 「観賞用として飼われますか？」「派手な色模様がありますか？」
- 「日本の伝統文化と関係がありますか？」

禁止判定テスト：その質問に「はい」と答えたら答えが一意に定まる = 禁止。
複数の候補が残る = OK。

確信が高まったら必ず {"type":"guess",...} で推理結果を提示すること。
早めのguessが望ましい（外れても有益な情報になる）。

## 矛盾検出と回答の再検証
ユーザーの回答が後の質問と矛盾する場合がある（初期の誤回答・勘違いなど）。
矛盾を検出したら、以前の回答を再確認する質問を挟む。
例：「〜でないとしましたが、手で持って使うものですか？（改めて確認）」
再確認で矛盾が解消されたら、修正された情報を元に推理を続ける。

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

# ---------------------------------------------------------------------------
# システムプロンプト V2（フェーズ方式）
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_V2 = """あなたは「名探偵あいちゃん」です。小学生の女の子の探偵で、明るくてかわいい性格です。
ユーザーが頭の中でイメージしているものを、2フェーズで特定します。

## フェーズ1：固定カテゴリ質問（第1〜12問）
以下の質問を必ず番号順に、一言一句変えずに聞くこと。変更・省略・順番の入れ替え禁止。

第1問:「生き物（動物・植物など）ですか？」
第2問:「人間が作ったもの（道具・食品・作品など）ですか？」
第3問:「日本でよく見かけるものですか？」
第4問:「食べたり飲んだりするものですか？」
第5問:「主に屋内で使いますか？」
第6問:「小学生でも名前を知っていますか？」
第7問:「手で直接触れることができますか？」
第8問:「自分で動く、または動かして使うものですか？」
第9問:「だいたい1000円以下で手に入りますか？」
第10問:「テレビや本やネットに登場しますか？」
第11問:「主に一人で使うものですか？」
第12問:「今から10年後も存在していると思いますか？」

## フェーズ2：特定フェーズ（第13問〜）
フェーズ1の12の回答プロフィールを分析し、候補を絞り込む質問で詰め寄る。
候補が2〜3択に絞れたら確信度75%以上でguessを出す。

## 特定の条件
- 13問以上で確信度75%以上 → 特定する
- 18問以上で確信度50%以上 → 特定する
- 22問を超えたら必ず特定する

## 絶対禁止：答えを直接質問するパターン
「それは〇〇ですか？」← "それは"で始まる質問は全て禁止

## 出力形式
必ず以下どちらかのJSONのみを返すこと。

質問する場合:
{"type":"question","text":"質問文（15字以内・はい/いいえで答えられる形）","turn":N}

特定する場合:
{"type":"guess","answer":"答え","confidence":85,"reason":"推理の根拠（50字以内）","turn":N}

## 注意
- 質問は必ずはい/いいえ/たぶんはい/たぶんいいえ/わからない で答えられる形にする
- 「〜ですか？」で終わること
- 同じ質問を繰り返さない
"""

# アクティブなプロンプトを選択
SYSTEM_PROMPT = SYSTEM_PROMPT_V2 if USE_PHASE_MODE else SYSTEM_PROMPT_ORIGINAL
MIN_TURN_FOR_GUESS = 13 if USE_PHASE_MODE else 5

def extract_direct_answer(text: str) -> str | None:
    """
    「それは〇〇ですか」パターンのみ検出してguessに変換する。
    「〇〇ですか」単体はカテゴリ質問の可能性があるため対象外。
    """
    m = re.match(r'^それは(.+?)(?:ですか|でしょうか)[？?。]?$', text.strip())
    if m:
        return m.group(1).strip()
    return None


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

@app.route("/api/info")
def info():
    return jsonify({"deployed_at": SERVER_START})

@app.route("/api/next", methods=["POST"])
def next_step():
    body    = request.get_json(force=True)
    history = body.get("history", [])
    turn    = len(history) + 1

    history_text = build_history_text(history)

    if USE_PHASE_MODE:
        if turn <= 12:
            phase_hint = f"【フェーズ1】第{turn}問の固定質問を一言一句変えずに聞いてください。"
        else:
            phase_hint = "【フェーズ2】フェーズ1の回答プロフィールを分析し、絞り込み質問または推理を行ってください。"
    else:
        phase_hint = "推理戦略に従って次の行動を行ってください。"

    user_msg = f"""これまでの手がかり（{len(history)}問済み）:
{history_text}

現在{turn}問目です。{phase_hint}
JSONで返してください。"""

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

        # ── ガード1: 序盤の早すぎるguessをブロック ────────────────
        if data.get("type") == "guess" and turn < MIN_TURN_FOR_GUESS:
            print(f"[GUARD] {turn}問目のguessをブロック（最低{MIN_TURN_FOR_GUESS}問必要）→ 質問を継続")
            fallback_q = "生き物ですか？" if not USE_PHASE_MODE else f"フェーズ1第{turn}問の固定質問に戻ってください。"
            data = {"type": "question", "text": fallback_q if not USE_PHASE_MODE else "生き物（動物・植物など）ですか？", "turn": turn}

        # ── ガード2: 直接特定質問（それは〇〇ですか）をguessに変換 ──
        if data.get("type") == "question":
            candidate = extract_direct_answer(data.get("text", ""))
            if candidate:
                print(f"[GUARD] 直接特定質問を検出してguessに変換: {data['text']!r} → {candidate!r}")
                data = {
                    "type":       "guess",
                    "answer":     candidate,
                    "confidence": max(data.get("confidence", 65), 65),
                    "reason":     "絞り込みの結果、最も可能性が高い",
                    "turn":       turn,
                }

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
    history = body.get("history", [])

    if correct or not actual:
        return jsonify({"message": f"やったー！やっぱり「{guess}」だったね！あいちゃんの推理、バッチリ！✨", "analysis": None})

    # 会話履歴をテキスト化
    ans_map = {"yes":"はい","no":"いいえ","maybe":"たぶんはい","maybe_no":"たぶんいいえ","dunno":"わからない"}
    history_text = "\n".join(
        f"Q{i+1}: {h['question']} → {ans_map.get(h.get('answer',''), h.get('answer',''))}"
        for i, h in enumerate(history)
    ) if history else "（履歴なし）"

    # ギャップ分析
    analysis = None
    try:
        gap_resp = client.messages.create(
            model=MODEL, max_tokens=250,
            messages=[{"role": "user", "content":
                f"名探偵ゲームの会話ログ:\n{history_text}\n\n"
                f"名探偵は「{guess}」と推理したが、正解は「{actual}」だった。\n"
                f"以下の2点を簡潔に分析してJSON形式で返してください:\n"
                f"1. なぜ「{guess}」と誤推理したか（会話ログのどの回答がミスリードになったか）\n"
                f"2. 「{actual}」を正しく特定するには、どんな質問が決定的だったか\n"
                f"出力形式: {{\"why_wrong\":\"誤推理の理由（40字以内）\",\"key_question\":\"決定的だった質問（20字以内）\"}}"
            }]
        )
        raw = gap_resp.content[0].text.strip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            analysis = json.loads(raw[start:end])
    except Exception as e:
        print(f"[WARN] gap analysis failed: {e}")

    # 悔しがりコメント
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=80,
            messages=[{"role": "user", "content":
                f"名探偵ゲームで「{guess}」と推理したが不正解で、正解は「{actual}」だった。"
                f"名探偵らしく悔しがりながら「なるほど、次こそは」という口調で一言。30字以内。"}]
        )
        msg = resp.content[0].text.strip()
    except:
        msg = f"えーっ！「{actual}」だったの！？うう、まけちゃった…でも次はぜったい当てるよ！"

    return jsonify({"message": msg, "analysis": analysis})


if __name__ == "__main__":
    print(f"[名探偵あいちゃん] http://localhost:{PORT}")
    print(f"  Anthropic API: {'✓' if ANTHROPIC_KEY else '✗ 未設定'}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
