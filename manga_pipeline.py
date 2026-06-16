# -*- coding: utf-8 -*-
"""
Pipeline dich manga: mokuro (OCR) -> extract -> translate -> render -> export

    python manga_pipeline.py ocr       "Chapter 14"
    python manga_pipeline.py extract   "Chapter 14"
    python manga_pipeline.py translate "Chapter 14" --engine google   # dich tu dong
    python manga_pipeline.py addbox    "Chapter 14" --img 002.jpg --box 153 35 826 93 --vi "..."
    python manga_pipeline.py render    "Chapter 14" --clean inpaint    # xoa chu thong minh
    python manga_pipeline.py export    "Chapter 14"

Yeu cau: pip install mokuro pillow opencv-python numpy deep-translator
"""
import argparse, json, os, subprocess, sys, zipfile, glob, re, shutil

# Console Windows mac dinh la cp1252 -> ep UTF-8 de in tieng Viet/Nhat khong loi
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- Cau hinh mac dinh -------------------------------------------------------
FONT_PATH   = "C:/Windows/Fonts/arialbd.ttf"
PAD         = 3
MAX_FONT    = 64
MIN_FONT    = 11
JPG_QUALITY = 92
CLEAN_MODE  = "inpaint"        # "inpaint" (mac dinh) hoac "white"


def trans_path(ch):
    return f"{ch}.trans.json"


# =============================================================================
# Doc/ghi anh ho tro duong dan unicode tren Windows
# =============================================================================
def imread(path):
    import cv2, numpy as np
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)

def imwrite(path, img):
    import cv2
    ext = os.path.splitext(path)[1]
    ok, buf = cv2.imencode(ext, img,
                           [cv2.IMWRITE_JPEG_QUALITY, JPG_QUALITY] if ext.lower() in (".jpg", ".jpeg") else [])
    buf.tofile(path)


# =============================================================================
# 0) UNZIP  (giai nen zip -> thu muc anh cua chuong)
# =============================================================================
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")

def _flatten(dest):
    """Neu anh nam trong 1 thu muc con long nhau, keo het len thang dest/."""
    for _ in range(4):
        entries = os.listdir(dest)
        imgs = [e for e in entries if e.lower().endswith(IMG_EXT)]
        dirs = [e for e in entries if os.path.isdir(os.path.join(dest, e))]
        if imgs or len(dirs) != 1:
            break
        inner = os.path.join(dest, dirs[0])
        for f in os.listdir(inner):
            shutil.move(os.path.join(inner, f), os.path.join(dest, f))
        os.rmdir(inner)


def cmd_unzip(a):
    zip_path = a.chapter        # voi buoc nay, 'chapter' la duong dan file .zip
    if not zipfile.is_zipfile(zip_path):
        sys.exit(f"[unzip] '{zip_path}' khong phai file zip hop le.")
    dest = a.dest or os.path.splitext(os.path.basename(zip_path))[0]
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)
    _flatten(dest)
    n = len([f for f in os.listdir(dest) if f.lower().endswith(IMG_EXT)])
    print(f"[unzip] Da giai nen {n} anh -> '{dest}'")


# =============================================================================
# 1) OCR
# =============================================================================
def cmd_ocr(a):
    print(f"[ocr] mokuro '{a.chapter}' ...")
    # Tu dong tra loi "yes" cho prompt "Continue? [yes/no]" cua mokuro
    subprocess.run(["mokuro", a.chapter], input="yes\n" * 5, text=True, check=True)
    print("[ocr] Xong.")


# =============================================================================
# 2) EXTRACT  (giu ban dich cu + giu cac box thu cong 'manual')
# =============================================================================
def cmd_extract(a):
    ch = a.chapter
    mok = json.load(open(f"{ch}.mokuro", encoding="utf-8"))
    out = trans_path(ch)

    old_vi, old_manual = {}, {}      # theo ten anh
    if os.path.exists(out):
        prev = json.load(open(out, encoding="utf-8"))
        for p in prev.get("pages", []):
            old_vi[p["img"]]     = [b.get("vi", "") for b in p["blocks"] if b.get("src") != "manual"]
            old_manual[p["img"]] = [b for b in p["blocks"] if b.get("src") == "manual"]

    pages = []
    for p in mok["pages"]:
        img = p["img_path"]
        blocks = []
        for bi, b in enumerate(p["blocks"]):
            vis = old_vi.get(img, [])
            blocks.append({"box": b["box"], "vertical": b["vertical"],
                           "font_size": b["font_size"], "src": "mokuro",
                           "jp": "".join(b["lines"]),
                           "vi": vis[bi] if bi < len(vis) else ""})
        blocks += old_manual.get(img, [])         # giu lai box them tay
        pages.append({"img": img, "w": p["img_width"], "h": p["img_height"],
                      "blocks": blocks})

    json.dump({"title": mok.get("title"), "pages": pages},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n = sum(len(p["blocks"]) for p in pages)
    print(f"[extract] '{out}' — {n} o text. Dien ban dich vao truong \"vi\".")


# =============================================================================
# 3) ADDBOX  (them o text thu cong cho SFX mokuro bo sot)
# =============================================================================
def cmd_addbox(a):
    out = trans_path(a.chapter)
    data = json.load(open(out, encoding="utf-8"))
    page = next((p for p in data["pages"] if p["img"] == a.img), None)
    if page is None:
        sys.exit(f"[addbox] Khong tim thay trang '{a.img}' trong {out}.")
    page["blocks"].append({"box": list(a.box), "vertical": False,
                           "font_size": 0, "src": "manual",
                           "jp": a.jp or "", "vi": a.vi or ""})
    json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[addbox] Da them box {a.box} vao {a.img}: \"{a.vi}\"")


# =============================================================================
# 4) TRANSLATE  (dien tu dong cac o 'vi' con trong)
#    engine: ollama (LLM offline, FREE) | gemini (free tier) | claude | google | deepl
# =============================================================================
# Prompt chung quyet dinh CHAT LUONG: yeu cau van phong tu nhien, dung giong nhan vat.
SYS_PROMPT = (
    "Bạn là dịch giả truyện tranh Nhật->Việt chuyên nghiệp. Dịch các dòng thoại manga "
    "sau sang tiếng Việt sao cho TỰ NHIÊN, ĐỜI THƯỜNG như người Việt nói, đúng giọng "
    "điệu và cảm xúc nhân vật (giận, sợ, mỉa mai, thân mật...). KHÔNG dịch word-by-word, "
    "KHÔNG cứng nhắc. Hiệu ứng âm thanh (SFX) dịch thành SFX tiếng Việt (vd: ầm, rầm, "
    "khự). Giữ nguyên các dấu '...' và '!!'. Xưng hô hợp ngữ cảnh. "
    "CHỈ trả về JSON: {\"translations\":[{\"id\":<số>,\"vi\":\"<bản dịch>\"}, ...]} "
    "với id khớp đầu vào, không thêm chữ nào ngoài JSON."
)


def _items_json(todo):
    return json.dumps([{"id": i, "jp": b["jp"]} for i, b in enumerate(todo)],
                      ensure_ascii=False)


def _apply(todo, text):
    """Tach JSON tu output (chiu duoc rac quanh JSON) va dien vao todo."""
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0) if m else text)
    n = 0
    for item in data["translations"]:
        idx = item.get("id")
        if isinstance(idx, int) and 0 <= idx < len(todo) and item.get("vi"):
            todo[idx]["vi"] = item["vi"]; n += 1
    print(f"  da dien {n}/{len(todo)} o")


def _translate_ollama(a, todo):
    """LLM chay offline qua Ollama (http://localhost:11434). MIEN PHI, khong key."""
    import requests
    url = (a.key or "http://localhost:11434").rstrip("/") + "/api/chat"
    r = requests.post(url, timeout=600, json={
        "model": a.model, "stream": False, "format": "json",
        "options": {"temperature": 0.4},
        "messages": [{"role": "system", "content": SYS_PROMPT},
                     {"role": "user", "content": _items_json(todo)}],
    })
    r.raise_for_status()
    _apply(todo, r.json()["message"]["content"])


def _translate_gemini(a, todo):
    """Google Gemini API (free tier). Can --key hoac GEMINI_API_KEY.
    Tu thu lai khi bi rate limit (429) hoac loi tam thoi (5xx)."""
    import requests, time
    key = a.key or os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("[translate] Gemini can --key hoac bien moi truong GEMINI_API_KEY.")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{a.model}:generateContent?key={key}")
    payload = {
        "system_instruction": {"parts": [{"text": SYS_PROMPT}]},
        "contents": [{"parts": [{"text": _items_json(todo)}]}],
        "generationConfig": {"response_mime_type": "application/json",
                             "temperature": 0.4, "maxOutputTokens": 16000},
    }
    last = None
    for attempt in range(6):                       # thu toi da 6 lan
        r = requests.post(url, timeout=300, json=payload)
        if r.status_code == 200:
            _apply(todo, r.json()["candidates"][0]["content"]["parts"][0]["text"])
            return
        last = f"HTTP {r.status_code}: {r.text[:200]}"
        if r.status_code in (429, 500, 503):       # rate limit / tam thoi -> cho roi thu lai
            wait = 20 * (attempt + 1)              # 20s, 40s, 60s, ...
            print(f"  ! {r.status_code} (rate limit?), cho {wait}s roi thu lai "
                  f"({attempt + 1}/6)...")
            time.sleep(wait)
        else:
            break                                  # loi khac (vd key sai) -> dung
    sys.exit(f"[translate] Gemini that bai sau khi thu lai: {last}")


def _translate_claude(a, todo):
    """Claude API (anthropic SDK). Can ANTHROPIC_API_KEY (tra phi)."""
    import anthropic
    client = anthropic.Anthropic(api_key=a.key) if a.key else anthropic.Anthropic()
    resp = client.messages.create(
        model=a.model, max_tokens=16000,
        system=SYS_PROMPT,
        messages=[{"role": "user", "content": _items_json(todo)}],
    )
    _apply(todo, next(b.text for b in resp.content if b.type == "text"))
    u = resp.usage
    print(f"  tokens: in={u.input_tokens} out={u.output_tokens}")


def _translate_google_deepl(a, todo):
    from deep_translator import GoogleTranslator, DeeplTranslator
    if a.engine == "deepl":
        if not a.key:
            sys.exit("[translate] DeepL can --key <API_KEY>.")
        tr = DeeplTranslator(api_key=a.key, source="ja", target="vi")
    else:
        tr = GoogleTranslator(source="ja", target="vi")
    for i, b in enumerate(todo, 1):                     # tung o mot (cham)
        try:
            b["vi"] = tr.translate(b["jp"]) or ""
        except Exception as e:
            print(f"  ! loi o {i}: {e}")
        if i % 10 == 0:
            print(f"  ...{i}/{len(todo)}")


_ENGINES = {"ollama": _translate_ollama, "gemini": _translate_gemini,
            "claude": _translate_claude,
            "google": _translate_google_deepl, "deepl": _translate_google_deepl}


def cmd_translate(a):
    out = trans_path(a.chapter)
    data = json.load(open(out, encoding="utf-8"))
    todo = [b for p in data["pages"] for b in p["blocks"]
            if not (b.get("vi") or "").strip()
            and re.search(r"[^\W\d_．。、！？…\s]", b.get("jp", ""))]   # bo qua o chi co dau cau

    llm = a.engine in ("ollama", "gemini", "claude")
    if llm and not getattr(a, "model", None):           # model mac dinh theo engine
        a.model = {"ollama": "qwen2.5", "gemini": "gemini-2.5-flash",
                   "claude": "claude-opus-4-8"}[a.engine]
    print(f"[translate] {len(todo)} o can dich qua {a.engine}"
          + (f" ({a.model})" if llm else "") + " ...")
    if todo:
        _ENGINES[a.engine](a, todo)
    json.dump(data, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[translate] Xong. Nen ra soat lai '{out}'.")


# =============================================================================
# 5) RENDER
# =============================================================================
def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, ImageFont, text, bw, bh):
    avail_w = max(bw, 70)
    best = None
    for fs in range(MAX_FONT, MIN_FONT - 1, -1):
        font = ImageFont.truetype(FONT_PATH, fs)
        lines = _wrap(draw, text, font, avail_w)
        asc, desc = font.getmetrics(); lh = asc + desc + 2
        w = max((draw.textlength(l, font=font) for l in lines), default=0)
        h = lh * len(lines)
        if w <= avail_w and h <= bh:
            return font, lines, lh, h
        best = (font, lines, lh, h)
    return best


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _inpaint_box(cv_img, box, pad):
    """Xoa rieng net chu (giu lai nen) bang cv2.inpaint."""
    import cv2, numpy as np
    h, w = cv_img.shape[:2]
    x1 = _clamp(box[0] - pad, 0, w); y1 = _clamp(box[1] - pad, 0, h)
    x2 = _clamp(box[2] + pad, 0, w); y2 = _clamp(box[3] + pad, 0, h)
    if x2 <= x1 or y2 <= y1:
        return
    roi = cv_img[y1:y2, x1:x2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # net chu la mau thieu so; chon mask tuong ung (chu toi tren nen sang & nguoc lai)
    mask = (th == (0 if (th == 255).sum() >= (th == 0).sum() else 255)).astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=2)
    cv_img[y1:y2, x1:x2] = cv2.inpaint(roi, mask, 3, cv2.INPAINT_TELEA)


def cmd_render(a):
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np, cv2
    mode = a.clean or CLEAN_MODE
    data = json.load(open(trans_path(a.chapter), encoding="utf-8"))

    # An toan: neu CHUA dich o nao (vi rong het) thi tu choi, tranh xuat ban goc
    n_filled = sum(1 for p in data["pages"] for b in p["blocks"]
                   if (b.get("vi") or "").strip())
    if n_filled == 0 and not getattr(a, "force", False):
        sys.exit(f"[render] '{a.chapter}' chua co ban dich nao (vi rong het) -> bo qua "
                 "de khong xuat ban goc. Chay 'translate' truoc, hoac --force neu co y do.")

    out_dir = f"{a.chapter} VI"
    os.makedirs(out_dir, exist_ok=True)

    for p in data["pages"]:
        src = os.path.join(a.chapter, p["img"])
        boxes = [b for b in p["blocks"] if (b.get("vi") or "").strip()]

        if mode == "inpaint":
            cv_img = imread(src)
            for b in boxes:
                _inpaint_box(cv_img, b["box"], PAD)
            img = Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))
        else:
            img = Image.open(src).convert("RGB")

        draw = ImageDraw.Draw(img)
        for b in boxes:
            if mode == "white":
                x1, y1, x2, y2 = b["box"]
                draw.rectangle([x1 - PAD, y1 - PAD, x2 + PAD, y2 + PAD], fill="white")
            x1, y1, x2, y2 = b["box"]
            font, lines, lh, th = _fit(draw, ImageFont, b["vi"].strip(), x2 - x1, y2 - y1)
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            ty = cy - th / 2
            for ln in lines:
                lw = draw.textlength(ln, font=font)
                # vien trang mong giup chu noi tren nen da inpaint
                draw.text((cx - lw / 2, ty), ln, font=font, fill="black",
                          stroke_width=2, stroke_fill="white")
                ty += lh
        img.save(os.path.join(out_dir, p["img"]), quality=JPG_QUALITY)
        print("[render]", p["img"])
    print(f"[render] ({mode}) Xong -> '{out_dir}'")


# =============================================================================
# 6) EXPORT
# =============================================================================
def cmd_export(a):
    from PIL import Image
    src = f"{a.chapter} VI"
    imgs = sorted(glob.glob(os.path.join(src, "*.jpg")) + glob.glob(os.path.join(src, "*.png")))
    if not imgs:
        sys.exit(f"[export] Khong co anh trong '{src}'. Chay 'render' truoc.")
    pdf = f"{a.chapter} VI.pdf"
    frames = [Image.open(i).convert("RGB") for i in imgs]
    frames[0].save(pdf, save_all=True, append_images=frames[1:])
    print(f"[export] PDF -> {pdf}")
    cbz = f"{a.chapter} VI.cbz"
    with zipfile.ZipFile(cbz, "w", zipfile.ZIP_DEFLATED) as z:
        for i in imgs:
            z.write(i, os.path.basename(i))
    print(f"[export] CBZ -> {cbz}")


# =============================================================================
# 7) CLEAN  (xoa file trung gian, chi giu lai PDF ket qua)
# =============================================================================
def cmd_clean(a):
    ch = a.chapter
    keep = f"{ch} VI.pdf"
    if not os.path.exists(keep):
        sys.exit(f"[clean] Chua co '{keep}'. Chay 'export' truoc khi don dep.")

    targets = [ch, f"{ch} VI", f"{ch}.mokuro", f"{ch}.html",
               f"{ch}.trans.json", f"{ch} VI.cbz", os.path.join("_ocr", ch)]
    targets = [t for t in targets if os.path.exists(t)]
    if not targets:
        print("[clean] Khong co gi de xoa."); return

    print(f"[clean] Giu lai: {keep}")
    print("[clean] Se xoa:")
    for t in targets:
        print("   -", t + ("/" if os.path.isdir(t) else ""))
    # Mac dinh xoa that su; them --dry-run de chi xem truoc
    if a.dry_run:
        print("\n[clean] Che do thu (--dry-run): khong xoa gi.")
        return
    for t in targets:
        shutil.rmtree(t) if os.path.isdir(t) else os.remove(t)
        print("   da xoa", t)
    if os.path.isdir("_ocr") and not os.listdir("_ocr"):
        os.rmdir("_ocr")
    print(f"[clean] Xong. Chi con: {keep}")


# =============================================================================
# 8) AUTO  (chay toan bo pipeline trong 1 lenh)
# =============================================================================
def cmd_auto(a):
    from argparse import Namespace as NS
    ch = a.chapter
    if ch.lower().endswith(".zip"):                       # neu dau vao la file zip
        zip_path = ch
        ch = a.dest or os.path.splitext(os.path.basename(zip_path))[0]
        cmd_unzip(NS(chapter=zip_path, dest=ch))
    print(f"\n===== AUTO: '{ch}' =====")
    cmd_ocr(NS(chapter=ch))
    cmd_extract(NS(chapter=ch))
    if not a.no_translate:
        cmd_translate(NS(chapter=ch, engine=a.engine, key=a.key, model=a.model))
    cmd_render(NS(chapter=ch, clean=a.mode))
    cmd_export(NS(chapter=ch))
    if a.clean:
        cmd_clean(NS(chapter=ch, dry_run=False))
    print(f"\n[auto] HOAN TAT -> '{ch} VI.pdf'")


# =============================================================================
# 9) BATCH  (chay auto cho nhieu chuong: vd 'batch 15 27')
# =============================================================================
def _find_input(n):
    """Tim dau vao cho chuong n: uu tien file .zip, roi thu muc anh co san."""
    zips = glob.glob(f"*Chapter {n}.zip") + glob.glob(f"*Chapter {n} *.zip")
    if zips:
        return zips[0]
    if os.path.isdir(f"Chapter {n}"):
        return f"Chapter {n}"
    return None


def cmd_batch(a):
    from argparse import Namespace as NS
    ok, fail = [], []
    for n in range(a.start, a.end + 1):
        src = _find_input(n)
        if not src:
            print(f"\n##### Chapter {n}: KHONG tim thay zip/thu muc -> bo qua")
            fail.append(n); continue
        print(f"\n############ Chapter {n}  (nguon: {src}) ############")
        try:
            cmd_auto(NS(chapter=src, dest=f"Chapter {n}", engine=a.engine,
                        model=a.model, key=a.key, no_translate=a.no_translate,
                        mode=a.mode, clean=a.clean))
            ok.append(n)
        except Exception as e:
            print(f"##### Chapter {n}: LOI -> {e}")
            fail.append(n)
    print(f"\n[batch] Xong. Thanh cong: {ok or '-'} | That bai: {fail or '-'}")


# =============================================================================
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pipeline dich manga voi mokuro")
    sub = ap.add_subparsers(dest="step", required=True)

    def add(name, fn, **kw):
        sp = sub.add_parser(name); sp.add_argument("chapter"); sp.set_defaults(fn=fn)
        return sp

    sp = add("unzip", cmd_unzip)        # 'chapter' o day la duong dan file .zip
    sp.add_argument("--dest", help="ten thu muc dich (mac dinh = ten file zip)")
    add("ocr", cmd_ocr)
    add("extract", cmd_extract)
    sp = add("translate", cmd_translate)
    sp.add_argument("--engine", choices=["ollama", "gemini", "claude", "google", "deepl"],
                    default="ollama")
    sp.add_argument("--model", default=None,
                    help="model LLM (ollama: qwen2.5; gemini: gemini-2.0-flash; claude: claude-opus-4-8)")
    sp.add_argument("--key", help="API key/URL (gemini/claude/deepl key; ollama: URL server neu khac mac dinh)")
    sp = add("addbox", cmd_addbox)
    sp.add_argument("--img", required=True)
    sp.add_argument("--box", required=True, type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"))
    sp.add_argument("--jp", default="")
    sp.add_argument("--vi", required=True)
    sp = add("render", cmd_render)
    sp.add_argument("--clean", choices=["inpaint", "white"], default=None)
    sp.add_argument("--force", action="store_true",
                    help="van render du chua co ban dich nao (xuat ban goc)")
    add("export", cmd_export)
    sp = add("clean", cmd_clean)
    sp.add_argument("--dry-run", action="store_true", help="chi xem truoc, khong xoa")
    def add_pipeline_opts(sp):           # cac tuy chon chung cho auto/batch
        sp.add_argument("--engine",
                        choices=["ollama", "gemini", "claude", "google", "deepl"],
                        default="gemini")
        sp.add_argument("--model", default=None,
                        help="model LLM (gemini: gemini-2.5-flash; ollama: qwen2.5; claude: claude-opus-4-8)")
        sp.add_argument("--key", help="API key (gemini/claude/deepl; hoac bien moi truong)")
        sp.add_argument("--no-translate", action="store_true", help="bo qua dich tu dong")
        sp.add_argument("--mode", choices=["inpaint", "white"], default="inpaint",
                        help="che do xoa chu khi render")
        sp.add_argument("--clean", action="store_true",
                        help="xoa file trung gian sau khi xong, chi giu PDF")

    sp = add("auto", cmd_auto)          # 'chapter' co the la file .zip hoac thu muc anh
    sp.add_argument("--dest", help="ten thu muc dich khi dau vao la zip")
    add_pipeline_opts(sp)

    sp = sub.add_parser("batch")        # 'batch START END' -> chay auto cho chuong START..END
    sp.add_argument("start", type=int)
    sp.add_argument("end", type=int)
    sp.set_defaults(fn=cmd_batch)
    add_pipeline_opts(sp)

    a = ap.parse_args()
    a.fn(a)
