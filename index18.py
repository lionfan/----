#!/usr/bin/python3.6
# -*- coding: utf-8 -*-

# index17.py を改良し、プログレスバー表示と初期状態での「作品は以上です。」非表示化

import os, sys, io, re, cgi, cgitb, zipfile, posixpath, base64, subprocess, shutil, tempfile
cgitb.enable()
sys.stdout.write("Content-Type: text/html; charset=utf-8\r\n\r\n")

# ===== 設定 =====
MAX_UPLOAD       = 200 * 1024 * 1024
MAX_IMG_B64      = 12  * 1024 * 1024
MAX_AUDIO_B64    = 10  * 1024 * 1024
MAX_VIDEO_B64    = 20  * 1024 * 1024
MAX_TEXT_SNIPPET = 200 * 1024

IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
AUD_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".mid", ".midi")
VID_EXT = (".mp4", ".webm", ".avi", ".wmv", ".mov")
TXT_EXT = (".txt", ".csv", ".tsv")
DOC_EXT = (".pdf", ".docx")

try:
    from html import escape
except Exception:
    from cgi import escape  # py3.6 fallback

# ===== MIDI → MP3 変換ユーティリティ =====
def _which(cmd):
    try:
        import shutil as _sh
        return _sh.which(cmd)
    except Exception:
        return None

def convert_midi_to_mp3_bytes(midi_bytes, timeout=25):
    """
    MIDI バイト列を MP3 バイト列へ変換（可能なら）して返す。
    変換に使用する候補:
      1) timidity + ffmpeg | lame
      2) fluidsynth + ffmpeg | lame（SoundFont が見つかった場合）
      3) ffmpeg 単体（ビルドにより合成対応の場合のみ）
    失敗時は (None, reason) を返す。
    """
    # 一時ファイルに書き出す
    with tempfile.TemporaryDirectory() as d:
        mid_path = os.path.join(d, "in.mid")
        with open(mid_path, "wb") as f:
            f.write(midi_bytes)

        # 出力先は stdout で受け取る
        have_timidity   = bool(_which("timidity"))
        have_ffmpeg     = bool(_which("ffmpeg"))
        have_lame       = bool(_which("lame"))
        have_fluidsynth = bool(_which("fluidsynth"))

        # 2-step: timidity -> wav -> mp3
        def _timidity_to_wav():
            try:
                p = subprocess.run(["timidity", mid_path, "-Ow", "-o", "-"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout)
                if p.returncode == 0 and p.stdout.startswith(b"RIFF"):
                    return p.stdout
            except Exception:
                pass
            return None

        def _fluidsynth_to_wav():
            # SoundFont の候補パス
            sfs = [
                "/usr/share/sounds/sf2/FluidR3_GM.sf2",
                "/usr/share/soundfonts/FluidR3_GM.sf2",
                "/usr/share/sfbank/TimGM6mb.sf2",
                "/usr/share/sounds/sf2/TimGM6mb.sf2",
            ]
            sf = next((p for p in sfs if os.path.exists(p)), None)
            if not (have_fluidsynth and sf):
                return None
            try:
                # -F - 出力wavファイル、ただし stdout には直接出せないので一旦ファイルへ
                wav_path = os.path.join(d, "out.wav")
                p = subprocess.run(["fluidsynth", "-ni", sf, mid_path, "-F", wav_path, "-r", "44100"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
                if p.returncode == 0 and os.path.exists(wav_path):
                    with open(wav_path, "rb") as wf:
                        return wf.read()
            except Exception:
                pass
            return None

        def _wav_to_mp3_bytes(wav_bytes):
            if not wav_bytes:
                return None
            if have_ffmpeg:
                try:
                    p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                        "-i", "pipe:0", "-f", "mp3", "-"],
                                       input=wav_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       timeout=timeout)
                    if p.returncode == 0 and len(p.stdout) > 0:
                        return p.stdout
                except Exception:
                    pass
            if have_lame:
                try:
                    p = subprocess.run(["lame", "-V4", "-", "-"],
                                       input=wav_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       timeout=timeout)
                    if p.returncode == 0 and len(p.stdout) > 0:
                        return p.stdout
                except Exception:
                    pass
            return None

        # 1) timidity -> ffmpeg/lame
        if have_timidity and (have_ffmpeg or have_lame):
            wav = _timidity_to_wav()
            mp3 = _wav_to_mp3_bytes(wav)
            if mp3:
                return mp3, None

        # 2) fluidsynth（SoundFont がある場合） -> ffmpeg/lame
        if have_fluidsynth and (have_ffmpeg or have_lame):
            wav = _fluidsynth_to_wav()
            mp3 = _wav_to_mp3_bytes(wav)
            if mp3:
                return mp3, None

        # 3) ffmpeg 単体が MIDI を読めるビルドなら（環境依存）
        if have_ffmpeg:
            try:
                p = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                                    "-i", mid_path, "-f", "mp3", "-"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
                if p.returncode == 0 and len(p.stdout) > 0:
                    return p.stdout, None
            except Exception:
                pass

        reason = "サーバに timidity/fluidsynth + ffmpeg/lame が見つかりませんでした。"
        return None, reason

# ===== 感想コメント生成 =====
def ai_comment(entry):
    kind = entry["kind"]
    name = entry["name"]

    if kind == "image":
        if re.search(r"(富士|fuj[iy])", name, re.I):
            return "雄大で感動的な印象を受け、思わず見入ってしまう。"
        elif re.search(r"(虹|rainbow)", name, re.I):
            return "色鮮やかで美しく、希望を感じる。"
        elif re.search(r"(草原|field)", name):
            return "広々としていて、心が癒される。"
        else:
            return "色や雰囲気が目を引き、きれいだと感じる。"

    elif kind == "audio":
        if name.lower().endswith((".mid",".midi")):
            return "シンプルでかわいらしい音色が印象的。"
        else:
            return "心地よく、楽しい雰囲気が伝わってくる。"

    elif kind == "video":
        return "迫力があり、映像に引き込まれる。"

    elif kind in ("text","doc"):
        text = entry.get("text") or ""
        if len(text) > 0:
            return "情景が浮かび、真剣さや熱意が伝わってくる。"
        else:
            return "読んでみたいという期待感を抱かせる。"

    else:
        return "独自性があり、どんな内容か気になる。"

# ===== ローマ字→ひらがな変換など（index16.py 相当） =====
_MACRON = str.maketrans({"Ā":"Aa","Ī":"Ii","Ū":"Uu","Ē":"Ee","Ō":"Ou",
                         "ā":"aa","ī":"ii","ū":"uu","ē":"ee","ō":"ou"})
_DIGRAPHS = {
    "cya":"ちゃ","cyu":"ちゅ","cyo":"ちょ",
    "kya":"きゃ","kyu":"きゅ","kyo":"きょ",
    "gya":"ぎゃ","gyu":"ぎゅ","gyo":"ぎょ",
    "sha":"しゃ","shu":"しゅ","sho":"しょ",
    "sya":"しゃ","syu":"しゅ","syo":"しょ",
    "ja":"じゃ","ju":"じゅ","jo":"じょ",
    "jya":"じゃ","jyu":"じゅ","jyo":"じょ",
    "cha":"ちゃ","chu":"ちゅ","cho":"ちょ",
    "tya":"ちゃ","tyu":"ちゅ","tyo":"ちょ",
    "nya":"にゃ","nyu":"にゅ","nyo":"にょ",
    "hya":"ひゃ","hyu":"ひゅ","hyo":"ひょ",
    "bya":"びゃ","byu":"びゅ","byo":"びょ",
    "pya":"ぴゃ","pyu":"ぴゅ","pyo":"ぴょ",
    "mya":"みゃ","myu":"みゅ","myo":"みょ",
    "rya":"りゃ","ryu":"りゅ","ryo":"りょ",
    "she":"しぇ","che":"ちぇ","je":"じぇ",
    "fa":"ふぁ","fi":"ふぃ","fu":"ふ","fe":"ふぇ","fo":"ふぉ",
    "tsa":"つぁ","tsi":"つぃ","tse":"つぇ","tso":"つぉ",
}
_MONO = {
    "a":"あ","i":"い","u":"う","e":"え","o":"お",
    "ka":"か","ki":"き","ku":"く","ke":"け","ko":"こ",
    "ga":"が","gi":"ぎ","gu":"ぐ","ge":"げ","go":"ご",
    "sa":"さ","shi":"し","si":"し","su":"す","se":"せ","so":"そ",
    "za":"ざ","ji":"じ","zi":"じ","zu":"ず","ze":"ぜ","zo":"ぞ",
    "ta":"た","chi":"ち","ti":"ち","tsu":"つ","tu":"つ","te":"て","to":"と",
    "da":"だ","di":"ぢ","du":"づ","de":"で","do":"ど",
    "na":"な","ni":"に","nu":"ぬ","ne":"ね","no":"の",
    "ha":"は","hi":"ひ","hu":"ふ","fu":"ふ","he":"へ","ho":"ほ",
    "ba":"ば","bi":"び","bu":"ぶ","be":"べ","bo":"ぼ",
    "pa":"ぱ","pi":"ぴ","pu":"ぷ","pe":"ぺ","po":"ぽ",
    "ma":"ま","mi":"み","mu":"む","me":"め","mo":"も",
    "ya":"や","yu":"ゆ","yo":"よ",
    "ra":"ら","ri":"り","ru":"る","re":"れ","ro":"ろ",
    "wa":"わ","wi":"うぃ","we":"うぇ","wo":"を",
    "nn":"ん",
}
_VOWEL = set("aeiou")

def _romaji_to_hiragana(word: str) -> str:
    s = word.strip().lower().translate(_MACRON)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == " ": out.append(" "); i += 1; continue
        if i+1 < len(s) and s[i] == s[i+1] and s[i] not in _VOWEL and s[i] != "n":
            out.append("っ"); i += 1; continue
        if ch == "n":
            if i+1 < len(s) and s[i+1] == "n": out.append("ん"); i += 2; continue
            if i+1 < len(s) and (s[i+1] in _VOWEL or s[i+1] == "y"): pass
            else: out.append("ん"); i += 1; continue
        if i+2 < len(s) and s[i:i+3] in _DIGRAPHS:
            out.append(_DIGRAPHS[s[i:i+3]]); i += 3; continue
        if i+2 < len(s) and s[i:i+3] in _MONO:
            out.append(_MONO[s[i:i+3]]); i += 3; continue
        if i+1 < len(s) and s[i:i+2] in _MONO:
            out.append(_MONO[s[i:i+2]]); i += 2; continue
        if ch in _VOWEL: out.append(_MONO[ch]); i += 1; continue
        out.append(ch); i += 1
    return re.sub(r"\s{2,}", " ", "".join(out)).strip()

def romaji_name_to_hiragana(roman: str) -> str:
    parts = [p for p in re.split(r"\s+", roman.strip()) if p]
    return " ".join(_romaji_to_hiragana(p) for p in parts)

def filetype(name):
    n = name.lower()
    if n.endswith(IMG_EXT):  return "image"
    if n.endswith(AUD_EXT):  return "audio"
    if n.endswith(VID_EXT):  return "video"
    if n.endswith(TXT_EXT):  return "text"
    if n.endswith(DOC_EXT):  return "doc"
    return "other"

def safe_norm(p):
    p = posixpath.normpath(p)
    if p.startswith("../") or p.startswith("/"): return None
    return p

def decode_text_jp(b):
    for enc in ("utf-8-sig","utf-16"):
        try: return b.decode(enc).replace("\x00",""), enc
        except Exception: pass
    for enc in ("cp932","euc_jp","iso2022_jp"):
        try: return b.decode(enc), enc
        except Exception: pass
    return b.decode("utf-8","ignore"), "utf-8(ignore)"

_KATA_RE = re.compile(r"[ァ-ヴー゛゜ぁ-ヶ]+")

def _mime_for(name, kind):
    n = name.lower()
    if kind == "image":
        if n.endswith(".png"):  return "image/png"
        if n.endswith(".jpg") or n.endswith(".jpeg"): return "image/jpeg"
        if n.endswith(".gif"):  return "image/gif"
        if n.endswith(".webp"): return "image/webp"
        return "image/*"
    if kind == "audio":
        if n.endswith(".mp3"):  return "audio/mpeg"
        if n.endswith(".wav"):  return "audio/wav"
        if n.endswith(".m4a"):  return "audio/mp4"
        if n.endswith(".aac"):  return "audio/aac"
        if n.endswith(".ogg"):  return "audio/ogg"
        if n.endswith(".mid") or n.endswith(".midi"): return "audio/midi"
        return "audio/*"
    if kind == "video":
        if n.endswith(".mp4") or n.endswith(".m4v") or n.endswith(".mov"): return "video/mp4"
        if n.endswith(".webm"): return "video/webm"
        return "video/*"
    return "application/octet-stream"

def _extract_docx_text(docx_bytes, limit=4000):
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as dz:
            xml = dz.read("word/document.xml")
        s = xml.decode("utf-8", "ignore")
        s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        return s[:limit]
    except Exception:
        return "(docxの本文プレビューを抽出できませんでした)"

def format_folder_label(raw_folder: str) -> str:
    m = re.match(r"s?(\d+)_([^_]+)", raw_folder)
    if not m:
        return "ZIP直下のファイル" if raw_folder == "(ZIP直下)" else raw_folder
    student_id = m.group(1)
    name_block = m.group(2).strip()
    m2 = re.search(r"\(([^)]+)\)", name_block)
    if m2:
        inner = m2.group(1)
        if _KATA_RE.search(inner):
            jp_name = name_block
        else:
            kana = romaji_name_to_hiragana(inner)
            jp_name = re.sub(r"\([^)]+\)", "(" + kana + ")", name_block)
    else:
        jp_name = name_block
    return "学生番号 {sid} {name}さんの作品".format(sid=student_id, name=jp_name)

# ===== HTML =====
HTML_HEAD = """<!doctype html><html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>作品ギャラリー</title>
<style>
 body{font-family:system-ui,-apple-system,"Hiragino Sans","Noto Sans JP",sans-serif;line-height:1.6;margin:24px;}
 h1{font-size:1.6rem;margin:0 0 1rem;}
 form{margin:1rem 0;padding:.8rem;border:1px solid #ccc;border-radius:12px;background:#fafafa}
 .item{margin:1.6rem 0;padding:1rem;border-bottom:1px solid #ddd;}
 .folder{font-weight:700;margin-bottom:.4rem}
 .file{margin:.35rem 0;}
 .thumb{margin:.4rem 0;}
 img{max-width:260px;max-height:200px;display:block;margin:.3rem 0;}
 audio,video{max-width:360px;display:block;margin:.3rem 0;}
 pre{background:#f9f9f9;padding:.6rem;white-space:pre-wrap;max-height:12em;overflow:auto;}
 .muted{color:#666;font-size:.92rem}
 .bytes{color:#888}
 .note{color:#395; font-size:.92rem; margin:.4rem 0;}

 /* プログレスバー関連のスタイル */
 #progressContainer {
   display: none;
   margin: 1rem 0;
   padding: 1rem;
   border: 1px solid #ddd;
   border-radius: 8px;
   background: #f8f9fa;
 }
 #progressBar {
   width: 100%;
   height: 24px;
   background: #e9ecef;
   border-radius: 12px;
   overflow: hidden;
   margin: 0.5rem 0;
 }
 #progressFill {
   height: 100%;
   background: linear-gradient(90deg, #007bff 0%, #0056b3 100%);
   width: 0%;
   transition: width 0.3s ease;
   border-radius: 12px;
 }
 #progressText {
   text-align: center;
   font-size: 0.9rem;
   color: #495057;
   margin: 0.25rem 0;
 }
 .spinner {
   display: inline-block;
   width: 16px;
   height: 16px;
   border: 2px solid #f3f3f3;
   border-top: 2px solid #007bff;
   border-radius: 50%;
   animation: spin 1s linear infinite;
   margin-right: 8px;
 }
 @keyframes spin {
   0% { transform: rotate(0deg); }
   100% { transform: rotate(360deg); }
 }
</style>
<script>
function showProgress() {
  // フォーム送信時にプログレスバーを表示
  document.getElementById('progressContainer').style.display = 'block';
  document.querySelector('button[type="submit"]').disabled = true;
  
  // プログレスバーをアニメーション
  let progress = 0;
  const progressFill = document.getElementById('progressFill');
  const progressText = document.getElementById('progressText');
  
  const interval = setInterval(() => {
    progress += Math.random() * 15 + 5; // 5-20%ずつランダムに進行
    if (progress > 90) progress = 90; // 90%で一旦停止
    
    progressFill.style.width = progress + '%';
    progressText.textContent = Math.floor(progress) + '% - ZIPファイルを処理中...';
  }, 200);
  
  // フォーム送信完了時に100%にする
  setTimeout(() => {
    clearInterval(interval);
    progressFill.style.width = '100%';
    progressText.innerHTML = '<span class="spinner"></span>処理完了まで少々お待ちください...';
  }, 8000);
}
</script>
</head><body>
<h1>作品ギャラリー</h1>
<form method="post" enctype="multipart/form-data" onsubmit="showProgress()">
  <input type="file" name="zipfile" accept=".zip" required>
  <button type="submit">アップロード</button>
  <div class="muted">※ZIPは展開せずに読み取り。大きいファイルはプレビューを省略。</div>
</form>

<div id="progressContainer">
  <div id="progressText">処理を開始しています...</div>
  <div id="progressBar">
    <div id="progressFill"></div>
  </div>
  <div class="muted">処理には1分程度かかる場合があります。ページを閉じずにお待ちください。</div>
</div>
"""

def render(groups=None, msg=None):
    out = [HTML_HEAD]
    if msg:
        out.append('<p class="muted">{}</p>'.format(escape(msg)))
    if groups:
        keys = list(groups.keys())
        if "(ZIP直下)" in keys:
            keys.remove("(ZIP直下)")
            keys = ["(ZIP直下)"] + sorted(keys, key=str.lower)
        else:
            keys = sorted(keys, key=str.lower)

        for folder in keys:
            out.append('<div class="item"><div class="folder">{}</div>'.format(
                escape(format_folder_label(folder))))
            for e in groups[folder]:
                name, kind, size = e["name"], e["kind"], e["size"]
                b64, text, enc = e.get("b64"), e.get("text"), e.get("encoding")
                mime = e.get("mime")
                is_midi = e.get("is_midi", False)
                mp3_b64 = e.get("mp3_b64")

                out.append('<div class="file"><a href="#">{}</a> '
                           '<span class="bytes">({} bytes{})</span>'.format(
                               escape(name), size, (", "+enc) if enc else ""))
                out.append('<div class="thumb">')
                if kind=="image" and b64:
                    out.append('<img src="data:{};base64,{}" alt="{}">'.format(
                        mime or "image/*", b64, escape(name)))
                elif kind=="audio" and mp3_b64:
                    # 変換済みMP3を優先してプレビュー
                    out.append('<audio controls src="data:audio/mpeg;base64,{}"></audio>'.format(mp3_b64))
                    out.append('<div class="muted">※MIDIをMP3に自動変換したプレビューです。</div>')
                elif kind=="audio" and b64 and not is_midi:
                    out.append('<audio controls src="data:{};base64,{}"></audio>'.format(
                        mime or "audio/*", b64))
                elif kind=="audio" and b64 and is_midi:
                    # 変換に失敗した場合のみ、従来の注意書きつきプレーヤを表示
                    out.append(
                        '<audio controls>'
                        '<source src="data:audio/midi;base64,{}" type="audio/midi">'.format(b64) +
                        '<source src="data:audio/x-midi;base64,{}" type="audio/x-midi">'.format(b64) +
                        '</audio>'
                        '<div class="muted">※ブラウザによってはMIDIを直接再生できません。その場合はダウンロードして再生してください。</div>'
                    )
                elif kind=="video" and b64:
                    out.append('<video controls src="data:{};base64,{}"></video>'.format(
                        mime or "video/*", b64))
                elif kind=="text" and text is not None:
                    out.append('<pre>{}</pre>'.format(escape(text)))
                elif kind=="doc" and text is not None:
                    out.append('<div class="muted">DOCXプレビュー（本文の先頭抜粋）</div>')
                    out.append('<pre>{}</pre>'.format(escape(text)))
                else:
                    out.append('<span class="muted">プレビューなし</span>')
                out.append('</div>')  # thumb

                # ===== 感想コメント =====
                comment = ai_comment(e)
                out.append('<div class="note">{}</div>'.format(escape(comment)))

                out.append('</div>')  # file
            out.append('</div>')  # item
        
        # 作品表示完了時のみフッターメッセージを表示
        out.append('<div class="muted" style="text-align:center;margin-top:2rem">作品は以上です。</div>')
    
    out.append('</body></html>')
    sys.stdout.write("".join(out))

def main():
    form = cgi.FieldStorage()
    if "zipfile" not in form:
        render(msg="ZIPを選んでください。"); return
    f = form["zipfile"]
    if not getattr(f, "file", None):
        render(msg="ファイルが受け取れませんでした。"); return

    buf = io.BytesIO(); total=0; CHUNK=1024*1024
    while True:
        chunk = f.file.read(CHUNK)
        if not chunk: break
        total += len(chunk)
        if total > MAX_UPLOAD:
            render(msg="ファイルが大きすぎます（上限200MB）"); return
        buf.write(chunk)
    buf.seek(0)

    groups = {}
    with zipfile.ZipFile(buf) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            path = safe_norm(info.filename)
            if not path:
                continue

            parts = path.split("/")
            folder = parts[0] if len(parts)>1 else "(ZIP直下)"
            fname  = parts[-1]
            size   = info.file_size
            data   = zf.read(info)

            kind   = filetype(fname)
            rec = {"name": fname, "size": size, "kind": kind}

            if kind=="image" and size<=MAX_IMG_B64:
                rec["b64"]  = base64.b64encode(data).decode("ascii")
                rec["mime"] = _mime_for(fname, "image")

            elif kind=="audio":
                rec["mime"] = _mime_for(fname, "audio")
                is_midi = fname.lower().endswith((".mid", ".midi"))
                if is_midi:
                    rec["is_midi"] = True
                    # ここで MP3 へ変換を試みる（結果は mp3_b64 として保持）
                    mp3_bytes, reason = convert_midi_to_mp3_bytes(data)
                    if mp3_bytes:
                        rec["mp3_b64"] = base64.b64encode(mp3_bytes).decode("ascii")
                    else:
                        # 変換不可の場合はオリジナルMIDIを埋め込んで注意書きへ
                        if size<=MAX_AUDIO_B64:
                            rec["b64"] = base64.b64encode(data).decode("ascii")
                            # 理由をメモ（UIには出しすぎない）
                            rec["conv_note"] = reason
                else:
                    if size<=MAX_AUDIO_B64:
                        rec["b64"] = base64.b64encode(data).decode("ascii")

            elif kind=="video" and size<=MAX_VIDEO_B64:
                mime = _mime_for(fname, "video")
                if "video/mp4" in mime or "video/webm" in mime:
                    rec["b64"]  = base64.b64encode(data).decode("ascii")
                    rec["mime"] = mime

            elif kind=="text":
                snippet = data[:MAX_TEXT_SNIPPET]
                text, enc = decode_text_jp(snippet)
                rec["text"] = text; rec["encoding"] = enc

            elif kind=="doc" and fname.lower().endswith(".docx"):
                rec["text"] = _extract_docx_text(data, limit=4000)

            groups.setdefault(folder, []).append(rec)

    for k in groups:
        groups[k].sort(key=lambda e: e["name"].lower())

    render(groups)

if __name__ == "__main__":
    main()
