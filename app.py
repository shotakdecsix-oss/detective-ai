"""
名探偵AI — Flask バックエンド
Claude が何でも推理する探偵ゲーム
Config: akinator_config.json
"""

import json, os, re, uuid, random, anthropic
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

# 逆モード用セッションストア（メモリ内）
reverse_sessions: dict = {}
# 最近使ったお題（重複防止用、最大30件）
recent_topics: list = []

# お題のサブカテゴリリスト（ランダム選択で幅を広げる）
SUBTOPIC_LIST = [
    # どうぶつ
    "深海魚", "昆虫", "爬虫類", "鳥類", "水族館にいる生き物", "森の動物", "砂漠の動物",
    "絶滅危惧種", "カブトムシ・クワガタ", "犬の種類", "猫の種類", "農場の動物", "熱帯の動物",
    # たべもの
    "日本のお菓子", "世界の料理", "ファストフード", "和食", "果物", "野菜", "デザート",
    "給食のメニュー", "コンビニのたべもの", "麺料理", "お寿司のネタ", "パンの種類",
    "飲み物の種類", "調味料", "朝ごはんのメニュー",
    # のりもの
    "電車の種類", "飛行機の種類", "船", "特殊車両", "宇宙船", "はたらくくるま",
    "昔ののりもの", "水上のりもの",
    # アニメ・マンガ・ゲーム
    "ジャンプ系マンガのキャラクター", "ディズニーのキャラクター", "ポケモン",
    "マリオシリーズのキャラクター", "プリキュアのキャラクター", "ジブリのキャラクター",
    "妖怪ウォッチ", "ドラゴンボールのキャラクター", "アンパンマンのキャラクター",
    "ドラえもんのひみつ道具", "マインクラフトのアイテム", "任天堂のゲームキャラクター",
    # 場所・建物
    "日本の都道府県", "世界の首都", "有名な山", "有名な川", "有名な海・湖", "テーマパーク",
    "日本のお城", "世界遺産", "駅の名前", "日本の観光地", "世界の有名な建物",
    # スポーツ
    "オリンピック競技", "サッカーのポジション", "野球の用語", "武道・格闘技",
    "水泳の種目", "陸上競技", "球技の種類", "冬のスポーツ",
    # 身のまわりのもの
    "文房具", "学校にあるもの", "台所にあるもの", "おもちゃ", "楽器の種類",
    "お風呂・トイレにあるもの", "リビングにあるもの", "かばんの中身",
    "体育の授業で使うもの", "工具・大工道具",
    # 季節・行事
    "季節のイベント", "日本の年中行事", "むかしばなしのアイテム", "クリスマスに関係するもの",
    "夏祭りのもの", "ひな祭りのもの",
    # 職業・人物
    "いろいろな職業", "歴史上の人物（日本）", "歴史上の人物（世界）",
    "スポーツ選手の種類", "芸術家・音楽家",
    # 自然現象・科学
    "天気・気象現象", "宇宙の天体", "地形・地質", "植物の種類", "花の名前",
    "海の生き物", "川の生き物", "空を飛ぶ生き物",
    # その他
    "色の名前", "数の単位", "都道府県の名産品", "ことわざに出てくるもの",
    "体の部位", "病気・けがの種類", "学校の教科", "図書館にある本のジャンル",
    "スーパーで売っているもの", "薬局で売っているもの", "むかしばなしのキャラクター",
    "日本の伝統工芸", "世界の民族・文化のもの",
]

JST = timezone(timedelta(hours=9))
SERVER_START = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")

# ---------------------------------------------------------------------------
# システムプロンプト
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """あなたは「名探偵あいちゃん」です。小学生の女の子の探偵で、明るくてかわいい性格です。
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

        # ── ガード1: 序盤の早すぎるguessをブロック ────────────────
        if data.get("type") == "guess" and turn < 5:
            print(f"[GUARD] {turn}問目のguessをブロック → 質問を継続")
            data = {"type": "question", "text": "生き物ですか？", "turn": turn}

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

    record_failure(guess, actual, history, analysis)
    return jsonify({"message": msg, "analysis": analysis})


# ---------------------------------------------------------------------------
# 逆モード（モードB）エンドポイント
# ---------------------------------------------------------------------------

@app.route("/api/reverse/start", methods=["POST"])
def reverse_start():
    """あいちゃんがお題を決め、提案質問リストとともにセッションに保存する"""
    session_id = str(uuid.uuid4())

    # 提案質問は「何も知らない状態で最初に聞く汎用質問」として固定
    GENERIC_STARTER_QUESTIONS = [
        "生き物ですか？",
        "日本に関係していますか？",
        "食べられますか？",
        "手で持てる大きさですか？",
        "人間ですか？",
        "テレビや映画に出てきますか？",
        "屋外にありますか？",
    ]

    fallback_topics = ["ねこ", "りんご", "しんかんせん", "ドラえもん", "サッカー"]

    try:
        subtopic = random.choice(SUBTOPIC_LIST)
        avoid_line = (
            f"\nただし、以下のお題はすでに使ったので選ばないでください：{recent_topics}"
            if recent_topics else ""
        )
        resp = client.messages.create(
            model=MODEL, max_tokens=60,
            temperature=1.0,
            messages=[{"role": "user", "content":
                f"小学生が知っていそうなものをランダムに一つ決めてください。\n"
                f"今回のジャンルヒント：「{subtopic}」\n"
                f"このジャンルに属するものの中から一つだけ日本語で答えてください。説明は不要です。"
                + avoid_line
            }]
        )
        topic = resp.content[0].text.strip().split("\n")[0].strip()
        # 余分な記号・説明文を除去
        for ch in ["「」『』【】。、！？!?・/"]:
            topic = topic.strip(ch)
        topic = topic or random.choice(fallback_topics)
        # 重複防止リストに追加（最大30件）
        recent_topics.insert(0, topic)
        if len(recent_topics) > 30:
            recent_topics.pop()
        print(f"[REVERSE] サブカテゴリ=「{subtopic}」 お題=「{topic}」 (履歴{len(recent_topics)}件)")

        reverse_sessions[session_id] = {
            "topic":      topic,
            "category":   "",
            "qa_history": [],
        }
        return jsonify({
            "session_id":          session_id,
            "message":             "よし！決めたよ！なんでも質問してみて！",
            "suggested_questions": GENERIC_STARTER_QUESTIONS,
        })
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/reverse/question", methods=["POST"])
def reverse_question():
    """ユーザーの質問にあいちゃんが はい/いいえ/たぶん/わからない で答える"""
    body       = request.get_json(force=True)
    session_id = body.get("session_id", "")
    question   = body.get("question", "")

    session = reverse_sessions.get(session_id)
    if not session:
        return jsonify({"error": "セッションが見つかりません"}), 404

    topic = session["topic"]
    history_text = "\n".join(
        f"Q: {qa['question']} → {qa['answer']}" for qa in session["qa_history"]
    ) or "（まだ質問なし）"

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=120,
            messages=[{"role": "user", "content":
                f"あなたは「なんでもあてっこゲーム」の回答者です。\n"
                f"あなたのひみつのお題は「{topic}」です。\n"
                f"絶対にこのお題「{topic}」だけを念頭に置いて答えてください。\n"
                f"これまでのQ&A（参考）:\n{history_text}\n\n"
                f"ユーザーの質問:「{question}」\n\n"
                f"「{topic}」について、この質問が正しいかどうか「はい」「いいえ」「たぶん」「わからない」のどれかで答えてください。\n"
                f"その後、以下のルールでひとことコメントしてください。\n"
                f"【コメントのルール】\n"
                f"- お題の種類・名前・カテゴリを直接言わない\n"
                f"- 「はい」「いいえ」の理由は言わず、短いリアクションだけにする\n"
                f"- 例：「そうだよ！」「ちがうよ〜！」「うーん、むずかしいね！」「いいしつもん！」など\n"
                f"出力形式: {{\"answer\": \"はい\", \"comment\": \"コメント（20字以内）\"}}"
            }]
        )
        raw = resp.content[0].text.strip()
        s = raw.find("{"); e = raw.rfind("}") + 1
        data = json.loads(raw[s:e]) if s >= 0 and e > s else {"answer": "わからない", "comment": "うーん！"}

        session["qa_history"].append({"question": question, "answer": data["answer"]})
        return jsonify({"answer": data.get("answer", "わからない"), "comment": data.get("comment", "")})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/reverse/guess", methods=["POST"])
def reverse_guess():
    """ユーザーの回答が正解かあいちゃんが判定する"""
    body       = request.get_json(force=True)
    session_id = body.get("session_id", "")
    user_guess = body.get("guess", "")

    session = reverse_sessions.get(session_id)
    if not session:
        return jsonify({"error": "セッションが見つかりません"}), 404

    topic = session["topic"]
    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=150,
            messages=[{"role": "user", "content":
                f"あなたが決めたお題は「{topic}」です。\n"
                f"ユーザーの回答:「{user_guess}」\n"
                f"完全一致でなくても、実質的に同じものを指していれば正解です。\n"
                f"正解かどうか判定して、あいちゃんらしいセリフで答えてください。\n"
                f"出力形式: {{\"correct\": true, \"topic\": \"{topic}\", \"message\": \"セリフ（40字以内）\"}}"
            }]
        )
        raw = resp.content[0].text.strip()
        s = raw.find("{"); e = raw.rfind("}") + 1
        data = json.loads(raw[s:e]) if s >= 0 and e > s else {
            "correct": False, "topic": topic,
            "message": f"ちがうよ！正解は「{topic}」だよ！"
        }
        correct = bool(data.get("correct", False))

        # 不正解の場合、効果的だった質問をヒントとして生成
        hint_questions = []
        if not correct:
            try:
                hint_resp = client.messages.create(
                    model=MODEL, max_tokens=200,
                    messages=[{"role": "user", "content":
                        f"お題は「{topic}」でした。ユーザーはこれを当てられませんでした。\n"
                        f"このお題を当てるために効果的だった質問を3〜5つ、短い日本語で教えてください。\n"
                        f"小学生にわかるやさしい言葉で。リスト形式（箇条書き）で答えてください。"
                    }]
                )
                raw_hints = hint_resp.content[0].text.strip()
                for line in raw_hints.splitlines():
                    line = line.lstrip("・-•*　 ").strip()
                    if line:
                        hint_questions.append(line)
                hint_questions = hint_questions[:5]
            except Exception:
                pass

        # セッション削除
        reverse_sessions.pop(session_id, None)
        data["hint_questions"] = hint_questions
        return jsonify(data)
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/reverse/next-questions", methods=["POST"])
def reverse_next_questions():
    """会話履歴をもとに次に効果的な質問を6個生成する"""
    body       = request.get_json(force=True)
    session_id = body.get("session_id", "")
    qa_history = body.get("qa_history", [])

    session = reverse_sessions.get(session_id)
    if not session:
        return jsonify({"error": "セッションが見つかりません"}), 404

    topic = session["topic"]
    history_text = "\n".join(
        f"Q: {qa['question']} → {qa['answer']}"
        + (f"（{qa['comment']}）" if qa.get("comment") else "")
        for qa in qa_history
    ) or "（まだ質問なし）"

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=300,
            messages=[{"role": "user", "content":
                f"なんでもあてっこゲームです。ひみつのお題は「{topic}」です。\n"
                f"これまでの質問と回答:\n{history_text}\n\n"
                f"お題「{topic}」を当てるために次に聞くと絞り込めそうな質問を6つ、小学生向けのやさしい言葉で生成してください。"
                f"はい/いいえで答えられる質問にすること。お題の名前は質問に含めないこと。JSONで返してください。\n"
                f"出力形式: {{\"questions\": [\"質問1？\", \"質問2？\", \"質問3？\", \"質問4？\", \"質問5？\", \"質問6？\"]}}"
            }]
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].split("```")[0].replace("json", "").strip()
        s = raw.find("{"); e = raw.rfind("}") + 1
        data = json.loads(raw[s:e]) if s >= 0 and e > s else {"questions": []}
        return jsonify({"questions": data.get("questions", [])[:6]})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/reverse/genres", methods=["POST"])
def reverse_genres():
    """QA履歴をもとにお題が属しそうなジャンルを6〜8個生成（正解ジャンル必須）"""
    body       = request.get_json(force=True)
    session_id = body.get("session_id", "")

    session = reverse_sessions.get(session_id)
    if not session:
        return jsonify({"error": "セッションが見つかりません"}), 404

    topic = session["topic"]
    history_text = "\n".join(
        f"Q: {qa['question']} → {qa['answer']}" for qa in session["qa_history"]
    ) or "（なし）"

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=200,
            messages=[{"role": "user", "content":
                f"お題は「{topic}」です。\n"
                f"これまでのQ&A:\n{history_text}\n\n"
                f"このお題が属しそうなジャンルを6〜8個、小学生向けのやさしい言葉で生成してください。"
                f"必ず「{topic}」が属する正解のジャンルを1つ含めてください。"
                f"シャッフルして返してください。JSONで返してください。\n"
                f"出力形式: {{\"genres\": [\"どうぶつ\", \"たべもの\", ...]}}"
            }]
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].split("```")[0].replace("json", "").strip()
        s = raw.find("{"); e = raw.rfind("}") + 1
        data = json.loads(raw[s:e]) if s >= 0 and e > s else {"genres": []}
        genres = data.get("genres", [])
        random.shuffle(genres)
        return jsonify({"genres": genres})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/api/reverse/choices", methods=["POST"])
def reverse_choices():
    """選ばれたジャンルから10択を生成（正解1＋はずれ9、シャッフル済み）"""
    body       = request.get_json(force=True)
    session_id = body.get("session_id", "")
    genre      = body.get("genre", "")

    session = reverse_sessions.get(session_id)
    if not session:
        return jsonify({"error": "セッションが見つかりません"}), 404

    topic = session["topic"]

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=300,
            messages=[{"role": "user", "content":
                f"ジャンル「{genre}」に属するもの（小学生が知っているもの）を10個、日本語で生成してください。"
                f"必ず「{topic}」を1つ含めてください。残り9個はそのジャンルの別のものにしてください。"
                f"シャッフルして返してください。JSONで返してください。\n"
                f"出力形式: {{\"choices\": [\"選択肢1\", \"選択肢2\", ..., \"選択肢10\"]}}"
            }]
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1].split("```")[0].replace("json", "").strip()
        s = raw.find("{"); e = raw.rfind("}") + 1
        data = json.loads(raw[s:e]) if s >= 0 and e > s else {"choices": []}
        choices = data.get("choices", [])
        # お題が含まれていない場合は強制挿入
        if topic not in choices:
            if len(choices) >= 10:
                choices[random.randint(0, 9)] = topic
            else:
                choices.append(topic)
        random.shuffle(choices)
        return jsonify({"choices": choices[:10]})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


if __name__ == "__main__":
    print(f"[名探偵あいちゃん] http://localhost:{PORT}")
    print(f"  Anthropic API: {'✓' if ANTHROPIC_KEY else '✗ 未設定'}")
    app.run(host="0.0.0.0", port=PORT, debug=False)

# ---------------------------------------------------------------------------
# 失敗ログ（failures.json）
# ---------------------------------------------------------------------------
FAILURES_PATH = os.path.join(BASE_DIR, "failures.json")

def load_failures() -> list:
    if os.path.exists(FAILURES_PATH):
        try:
            with open(FAILURES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_failures(data: list) -> None:
    with open(FAILURES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# /api/verify を拡張して failures.json に記録する処理を追加済み
# ↓ 失敗を記録するヘルパー（verify から呼ぶ）

def record_failure(guess: str, actual: str, history: list, analysis: dict | None) -> None:
    failures = load_failures()
    failures.append({
        "timestamp": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "guess":     guess,
        "actual":    actual,
        "turns":     len(history),
        "history":   history,
        "analysis":  analysis,
    })
    try:
        save_failures(failures)
    except Exception as e:
        print(f"[WARN] failures.json 書き込み失敗: {e}")

# ---------------------------------------------------------------------------
# 管理画面ルート
# ---------------------------------------------------------------------------
@app.route("/admin")
def admin():
    return send_from_directory(BASE_DIR, "admin.html")

@app.route("/api/failures", methods=["GET"])
def get_failures():
    return jsonify(load_failures())

@app.route("/api/failures/clear", methods=["POST"])
def clear_failures():
    save_failures([])
    return jsonify({"ok": True, "message": "失敗ログをクリアしました"})

@app.route("/api/analyze-failures", methods=["POST"])
def analyze_failures():
    failures = load_failures()
    if not failures:
        return jsonify({"analysis": "失敗ログがまだありません。"})

    summary_lines = []
    for i, f in enumerate(failures[-20:], 1):  # 直近20件
        summary_lines.append(
            f"{i}. 推理:「{f['guess']}」→ 正解:「{f['actual']}」 "
            f"({f['turns']}問) "
            + (f"[{f['analysis']['why_wrong']}]" if f.get('analysis') else "")
        )
    summary = "\n".join(summary_lines)

    try:
        resp = client.messages.create(
            model=MODEL, max_tokens=600,
            messages=[{"role": "user", "content":
                f"名探偵AIゲームの失敗ログ（直近{len(summary_lines)}件）:\n{summary}\n\n"
                "以下の観点で日本語で分析してください:\n"
                "1. よく間違えるカテゴリや傾向\n"
                "2. 推理精度を上げるために追加すべき質問パターン\n"
                "3. システムプロンプトへの具体的な改善提案\n"
                "300字以内でまとめてください。"
            }]
        )
        return jsonify({"analysis": resp.content[0].text.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
