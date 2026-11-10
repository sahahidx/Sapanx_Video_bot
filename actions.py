"""লেখা অনুযায়ী কার্টুনের কাজ (দৌড়, হাঁটা, লাফ, নাচ...) — bot.py এটা ব্যবহার করে।"""
import math
import subprocess
import time
import unicodedata
from functools import lru_cache

from PIL import Image, ImageDraw

FW, FH = 540, 960
PANEL_Y = 705
GROUND_Y, FEET_Y = 560, 640
SS = 2
SHIRT, PANTS, SHOE, SKIN = (52, 112, 224), (60, 60, 110), (40, 30, 30), (255, 214, 170)


def _n(s):
    return unicodedata.normalize("NFC", s)


# ---- কোন শব্দ দেখলে কোন কাজ হবে (নতুন শব্দ চাইলে এখানে যোগ করুন)
ACTIONS = {k: [_n(w) for w in v] for k, v in {
    "run": ["দৌড়", "ছুটে", "ছুটছ", "ছুটল", "ছুটতে"],
    "walk": ["হাঁট", "হেঁট", "হাটছ", "হাটতে", "হাটল"],
    "jump": ["লাফ", "ঝাঁপ"],
    "dance": ["নাচ", "নেচে", "নৃত্য"],
    "wave": ["হ্যালো", "নমস্কার", "সালাম", "স্বাগত", "বিদায়", "হাত নাড়"],
    "laugh": ["হাসছ", "হাসি", "হাসল", "হাসে", "হেসে", "হাসতে"],
    "cry": ["কান্না", "কাঁদ", "কেঁদ"],
    "sleep": ["ঘুম", "শুয়ে"],
    "fly": ["উড়"],
}.items()}
THEMES = {k: [_n(w) for w in v] for k, v in {
    "night": ["রাত", "অন্ধকার", "চাঁদ", "নক্ষত্র"],
    "rain": ["বৃষ্টি", "বর্ষা", "ঝড়"],
    "day": ["সকাল", "সূর্য", "রোদ", "দুপুর"],
}.items()}


def find_actions(chunk):
    s = _n(chunk)
    hits = []
    for act, words in ACTIONS.items():
        pos = [p for p in (s.find(w) for w in words) if p >= 0]
        if pos:
            hits.append((min(pos), act))
    return [a for _, a in sorted(hits)] or ["idle"]


def find_theme(chunk, current):
    s = _n(chunk)
    best, name = -1, current
    for th, words in THEMES.items():
        for w in words:
            p = s.rfind(w)
            if p > best:
                best, name = p, th
    return name


# ---- দৃশ্য
def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


PAL = {  # আকাশ উপরে, আকাশ নিচে, মাটি
    "day": ((110, 190, 255), (205, 238, 255), (95, 185, 95)),
    "night": ((8, 8, 40), (45, 35, 100), (30, 75, 55)),
    "rain": ((95, 105, 125), (165, 172, 188), (70, 130, 80)),
}


@lru_cache(maxsize=None)
def scene(theme):
    top, bot, gr = PAL[theme]
    img = Image.new("RGB", (FW, FH))
    d = ImageDraw.Draw(img)
    for y in range(GROUND_Y):
        d.line([(0, y), (FW, y)], fill=lerp(top, bot, y / GROUND_Y))
    d.rectangle([0, GROUND_Y, FW, FH], fill=gr)
    d.rectangle([0, GROUND_Y, FW, GROUND_Y + 14], fill=lerp(gr, (255, 255, 255), 0.18))
    if theme == "night":
        d.ellipse([400, 70, 480, 150], fill=(250, 245, 200))
        d.ellipse([424, 60, 504, 140], fill=lerp(top, bot, 100 / GROUND_Y))
        for i in range(40):
            x, y = (i * 97) % FW, (i * 53) % 330 + 20
            d.ellipse([x, y, x + 3, y + 3], fill=(255, 255, 220))
    elif theme == "day":
        d.ellipse([60, 70, 150, 160], fill=(255, 225, 90))
    ov = Image.new("RGBA", (FW, FH), (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle([24, PANEL_Y, FW - 24, PANEL_Y + 225], radius=28, fill=(0, 0, 0, 130))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


@lru_cache(maxsize=None)
def layers(theme):
    far = Image.new("RGBA", (FW, 170), (0, 0, 0, 0))
    d = ImageDraw.Draw(far)
    col = {"day": (255, 255, 255, 235), "rain": (120, 125, 140, 240), "night": (60, 60, 110, 160)}[theme]
    for cx, cy in ((70, 50), (250, 90), (420, 40)):
        for dx, dy, r in ((0, 0, 34), (32, 8, 28), (-32, 10, 26), (8, -14, 24)):
            d.ellipse([cx + dx - r, cy + dy - r, cx + dx + r, cy + dy + r], fill=col)
    near = Image.new("RGBA", (FW, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(near)
    leaf = {"day": (40, 140, 60), "rain": (35, 100, 55), "night": (15, 55, 40)}[theme]
    for x in (90, 250, 410):
        d.rectangle([x - 8, 100, x + 8, 190], fill=(95, 60, 35))
        d.ellipse([x - 45, 30, x + 45, 125], fill=leaf)
    return far, near


# ---- শরীর ও কাজের ভঙ্গি
def limb(ox, oy, a1, a2, l1, l2):
    """কোণ: ০ = সোজা নিচে, + = ডানে। দুই খণ্ডের হাত/পা।"""
    r1, r2 = math.radians(a1), math.radians(a1 + a2)
    jx, jy = ox + l1 * math.sin(r1), oy + l1 * math.cos(r1)
    return [(ox, oy), (jx, jy), (jx + l2 * math.sin(r2), jy + l2 * math.cos(r2))]


def pose(a, t, lv):
    p = dict(dx=0, dy=0, la=(-8, 6), ra=(8, 6), ll=(-3, 0), rl=(3, 0),
             scroll=0, shut=False, mouth=None)
    w = 2 * math.pi * t
    if a == "run":
        s, c = math.sin(w * 2.4), math.cos(w * 2.4)
        p.update(dy=-abs(s) * 16, scroll=24, ll=(62 * s, -(38 + 30 * c)), rl=(-62 * s, -(38 - 30 * c)),
                 la=(-55 * s, 75), ra=(55 * s, 75))
    elif a == "walk":
        s = math.sin(w * 1.4)
        p.update(dy=-abs(s) * 4, scroll=7, ll=(26 * s, -8), rl=(-26 * s, -8), la=(-22 * s, 12), ra=(22 * s, 12))
    elif a == "jump":
        h = math.sin(math.pi * ((t % 0.9) / 0.9))
        p.update(dy=-150 * h, la=(-(25 + 125 * h), 15), ra=(25 + 125 * h, -15),
                 ll=(-(6 + 16 * h), -(8 + 55 * h)), rl=(6 + 16 * h, -(8 + 55 * h)))
    elif a == "dance":
        s = math.sin(w * 1.8)
        p.update(dx=16 * s, dy=-abs(s) * 9, la=(-(105 + 45 * s), 25), ra=(105 - 45 * s, -25),
                 ll=(-10 + 14 * s, -(14 + 14 * abs(s))), rl=(10 + 14 * s, -(14 + 14 * abs(s))))
    elif a == "wave":
        p.update(dy=-abs(math.sin(w * 1.5)) * 3, ra=(152, 30 * math.sin(w * 3.5)))
    elif a == "laugh":
        p.update(dy=-abs(math.sin(w * 3.5)) * 10, la=(-30, 85), ra=(30, -85), shut=True, mouth=3)
    elif a == "cry":
        p.update(dy=math.sin(w * 6) * 3, shut=True)
    elif a == "sleep":
        p.update(dy=math.sin(w * 0.7) * 2, shut=True)
    elif a == "fly":
        p.update(dy=-110 + 10 * math.sin(w * 1.6), scroll=14, la=(-115, 10), ra=(115, -10),
                 ll=(-8, -10), rl=(8, -10))
    else:  # কথা বলার সময় হাত নাড়ানো
        p.update(la=(-10 - 30 * lv, 10 + 25 * lv), ra=(10 + 30 * lv, 10 + 25 * lv), dy=-lv * 3)
    return p


def figure(p):
    im = Image.new("RGBA", (360 * SS, 520 * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    def line(pts, w, col):
        d.line([(x * SS, y * SS) for x, y in pts], fill=col, width=int(w * SS), joint="curve")
        for x, y in pts:
            r = w / 2
            d.ellipse([(x - r) * SS, (y - r) * SS, (x + r) * SS, (y + r) * SS], fill=col)

    for side, (a1, a2) in ((-1, p["ll"]), (1, p["rl"])):
        pts = limb(180 + side * 28, 325, a1, a2, 70, 70)
        line(pts, 34, PANTS)
        x, y = pts[2]
        d.ellipse([(x - 22 + 8) * SS, (y - 8) * SS, (x + 22 + 8) * SS, (y + 14) * SS], fill=SHOE)
    d.rounded_rectangle([120 * SS, 200 * SS, 240 * SS, 345 * SS], radius=40 * SS, fill=SHIRT)
    d.polygon([(165 * SS, 200 * SS), (195 * SS, 200 * SS), (180 * SS, 228 * SS)], fill="white")
    for side, (a1, a2) in ((-1, p["la"]), (1, p["ra"])):
        pts = limb(180 + side * 60, 212, a1, a2, 58, 52)
        line(pts, 26, SHIRT)
        x, y = pts[2]
        d.ellipse([(x - 14) * SS, (y - 14) * SS, (x + 14) * SS, (y + 14) * SS], fill=SKIN)
    return im.reduce(SS)


@lru_cache(maxsize=None)
def head_small(B, m, b):
    return B.head_sprite(m, b).resize((165, 182), Image.Resampling.LANCZOS)


def draw_extras(d, a, t, fx, fy):
    hx, hy = fx + 97, fy + 43
    if a == "dance":
        for k in range(3):
            ph = (t * 0.8 + k / 3) % 1
            x, y = fx + 30 + k * 120 + 8 * math.sin(ph * 6), fy + 120 - ph * 130
            d.ellipse([x, y, x + 14, y + 10], fill="white")
            d.line([(x + 13, y + 5), (x + 13, y - 22)], fill="white", width=3)
    elif a == "cry":
        for ex in (hx + 59, hx + 106):
            for k in range(2):
                y = hy + 104 + ((t * 1.5 + k * 0.5) % 1) * 70
                d.ellipse([ex - 4, y, ex + 4, y + 12], fill=(90, 170, 255))
    elif a == "sleep":
        for k in range(3):
            ph = (t * 0.5 + k / 3) % 1
            sz, x, y = 10 + ph * 14, hx + 150 + ph * 40, hy - ph * 90
            d.line([(x, y), (x + sz, y), (x, y + sz), (x + sz, y + sz)], fill="white", width=3)


def draw_frame(B, bg, theme, a, t, lv, fi, pos):
    p = pose(a, t, lv)
    frame = bg.copy()
    far, near = layers(theme)
    for img, speed, y in ((far, 0.25, 70), (near, 0.6, GROUND_Y + 20 - 200)):
        off = int(pos * speed) % FW
        frame.paste(img, (-off, y), img)
        frame.paste(img, (FW - off, y), img)
    d = ImageDraw.Draw(frame)
    gr = PAL[theme][2]
    for k in range(5):
        x = ((k * 150 - pos) % (FW + 150)) - 150
        d.rectangle([x, 672, x + 80, 682], fill=lerp(gr, (255, 255, 255), 0.25))
    fx, fy = FW // 2 - 180 + int(p["dx"]), FEET_Y - 485 + int(p["dy"])
    sw = max(40, 70 + p["dy"] * 0.25)
    d.ellipse([FW // 2 + p["dx"] - sw, FEET_Y - 2, FW // 2 + p["dx"] + sw, FEET_Y + 18], fill=lerp(gr, (0, 0, 0), 0.3))
    fig = figure(p)
    frame.paste(fig, (fx, fy), fig)
    m = p["mouth"] if p["mouth"] is not None else B.mouth_state(lv)
    blink = 1 if p["shut"] or (fi % 33) in (30, 31) else 0
    head = head_small(B, m, blink)
    frame.paste(head, (fx + 97, fy + 43 - int(4 * lv)), head)
    draw_extras(d, a, t, fx, fy)
    if theme == "rain":
        for i in range(40):
            x, y = (i * 53 + fi * 7) % FW, (i * 89 + fi * 38) % GROUND_Y
            d.line([(x, y), (x - 5, y + 20)], fill=(210, 225, 245), width=2)
    return frame, p["scroll"]


# ---- পুরো ভিডিও
def make_action_video(B, text, wav_path, out_path):
    levels, duration = B.mouth_levels(wav_path, B.FPS)
    if not levels:
        raise RuntimeError("অডিও খালি")
    fps = B.FPS
    font = B.load_font(B.SUB_SIZE)
    chunks = B.split_subtitles(text, font, B.SUB_MAX_W, B.SUB_LINES)
    total = sum(len(c) for c in chunks) or 1

    plan, theme, acc = [], "day", 0
    for c in chunks:
        theme = find_theme(c, theme)
        t0 = acc / total * duration
        acc += len(c)
        bg = scene(theme).copy()
        lines = B.wrap_text(ImageDraw.Draw(bg), c, font, B.SUB_MAX_W)[:B.SUB_LINES]
        B.draw_subtitle(bg, lines, font)
        plan.append((t0, acc / total * duration, find_actions(c), theme, bg))

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{FW}x{FH}", "-r", str(fps), "-i", "-",
           "-i", wav_path, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", out_path]
    log_path = out_path + ".log"
    started, pos, ci = time.time(), 0.0, 0
    with open(log_path, "wb") as logf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=logf)
        try:
            for fi, lv in enumerate(levels):
                t = fi / fps
                while ci < len(plan) - 1 and t >= plan[ci][1]:
                    ci += 1
                t0, t1, acts, th, bg = plan[ci]
                seg = (t1 - t0) / len(acts)
                ai = min(len(acts) - 1, int(max(0.0, t - t0) / (seg or 1)))
                frame, sc = draw_frame(B, bg, th, acts[ai], t - t0 - ai * seg, lv, fi, pos)
                pos += sc
                proc.stdin.write(frame.tobytes())
                if time.time() - started > B.MAX_RENDER_SECONDS:
                    raise RuntimeError("ভিডিও বানাতে বেশি সময় লাগছে")
        except BrokenPipeError:
            pass
        except Exception:
            proc.kill()
            raise
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
        rc = proc.wait(timeout=180)
    if rc != 0:
        with open(log_path, "rb") as f:
            raise RuntimeError(f.read()[-500:].decode(errors="ignore"))
