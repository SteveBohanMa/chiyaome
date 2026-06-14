"""
吃药么 (ChiYaoMe) — 用药提醒桌面应用
pywebview 前端 + Python 后端。
特性：离线拍照识别(本地 OCR) · 到点系统响铃 · 离线语音播报 · 后台提醒(最小化也能弹出)。
数据格式沿用：settings.json / medications.json / history.json
"""
import os, sys, json, re, base64, datetime, threading, time, traceback
import webview

APP_NAME = "吃药么"
IS_WIN = sys.platform.startswith("win")

# ---------- 资源 / 数据目录 ----------
def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)

def data_dir():
    d = os.path.join(os.path.expanduser("~"), ".chiyaome")
    os.makedirs(d, exist_ok=True)
    return d

SETTINGS_FILE = os.path.join(data_dir(), "settings.json")
MEDS_FILE     = os.path.join(data_dir(), "medications.json")
HISTORY_FILE  = os.path.join(data_dir(), "history.json")

DEFAULT_SETTINGS = {
    "lang": "zh",                # 界面/语音/资料语言：zh(默认) / en
    "user_name": "王奶奶",
    "family_note": "",           # 需求6：给家属看的说明文字
    "autostart": True,           # 需求·运行模式：开机自启，默认开，可在「自定义」关
    "sound_on": True,            # 到点响铃
    "voice_on": True,            # 语音播报
    "use_online": False,         # 默认离线识别；开启且填了 key 才走联网
    "api_key": "",
    "model": "claude-opus-4-5",
    "after_meal_delay": 30,
    "times": {"wake": "08:00", "breakfast": "08:30", "lunch": "12:30",
              "dinner": "17:30", "bedtime": "21:00"},
}

TIMINGS = {
    "before_breakfast": ("breakfast", False, "早饭前", "早"),
    "after_breakfast":  ("breakfast", True,  "早饭后", "早"),
    "before_lunch":     ("lunch",     False, "午饭前", "午"),
    "after_lunch":      ("lunch",     True,  "午饭后", "午"),
    "before_dinner":    ("dinner",    False, "晚饭前", "晚"),
    "after_dinner":     ("dinner",    True,  "晚饭后", "晚"),
    "bedtime":          ("bedtime",   False, "睡前",   "睡前"),
}

# ---------- 读写 ----------
def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(default))

def _save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def load_settings():
    s = _load(SETTINGS_FILE, DEFAULT_SETTINGS)
    for k, v in DEFAULT_SETTINGS.items():
        s.setdefault(k, v)
    for k, v in DEFAULT_SETTINGS["times"].items():
        s["times"].setdefault(k, v)
    return s

def add_minutes(hhmm, minutes):
    h, m = map(int, hhmm.split(":"))
    t = (h * 60 + m + minutes) % (24 * 60)
    return f"{t//60:02d}:{t%60:02d}"

def today_str():
    return datetime.date.today().isoformat()

def event_time(settings, timing, custom_time=None):
    if timing == "custom":
        return custom_time or "09:00"
    meal, add_delay, _, _ = TIMINGS.get(timing, ("breakfast", False, "", "早"))
    base = settings["times"].get(meal, "08:30")
    return add_minutes(base, settings["after_meal_delay"]) if add_delay else base

def timing_label(timing):
    return "指定时间" if timing == "custom" else TIMINGS.get(timing, ("", 0, "用药", ""))[2]

# ---------- 需求2：疗程 ----------
def _in_course(med, date_iso):
    """该药在 date_iso 当天是否仍在疗程内。start_date 必填；end_date 空=长期。"""
    sd = med.get("start_date")
    if sd and date_iso < sd:
        return False
    ed = med.get("end_date")
    if ed and date_iso > ed:
        return False
    return True

def calc_end(start_iso, course_text):
    """按疗程描述算结束日（含当天）。返回 None 表示长期。"""
    if not start_iso:
        return None
    days = {"3天": 3, "1周": 7, "一周": 7, "两周": 14, "2周": 14,
            "1个月": 30, "一个月": 30}.get((course_text or "").strip())
    if not days:
        return None
    d = datetime.date.fromisoformat(start_iso) + datetime.timedelta(days=days - 1)
    return d.isoformat()

def day_events(settings, meds, date_iso, history):
    hist = history.get(date_iso, {})
    evs = []
    for med in meds:
        if not _in_course(med, date_iso):   # 需求2：不在疗程内的药当天不生成事件
            continue
        for timing in med.get("timings", []):
            key = f'{med["id"]}@{timing}'
            evs.append({
                "med_id": med["id"], "key": key,
                "name": med["name"], "dose": med.get("dose", ""),
                "type": med.get("type", "pill"), "note": med.get("note", ""),
                "timing": timing, "slot": timing_label(timing),
                "time": event_time(settings, timing, med.get("custom_time")),
                "status": hist.get(key, "wait"),
            })
    evs.sort(key=lambda e: e["time"])
    return evs

# ========== 运行模式：开机自启（HKCU，免管理员） ==========
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_NAME = "ChiYaoMe"

def _autostart_target():
    # 打包成 exe 时 sys.executable 即程序本身；源码运行时回退到 pythonw app.py
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'

def set_autostart(on=True):
    if not IS_WIN:
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if on:
            winreg.SetValueEx(k, _RUN_NAME, 0, winreg.REG_SZ, _autostart_target())
        else:
            try:
                winreg.DeleteValue(k, _RUN_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(k)
        return True
    except Exception:
        traceback.print_exc()
        return False

def open_url(url):
    """用系统默认浏览器打开（需求4/5 官方核验入口）。"""
    try:
        import webbrowser
        webbrowser.open(url, new=2)
        return True
    except Exception:
        return False

# ========== 提醒：响铃 + 语音 ==========
class Alerter:
    def __init__(self):
        self._tts_lock = threading.Lock()

    def ring(self):
        if not IS_WIN:
            return
        try:
            import winsound
            winsound.PlaySound(resource_path("alarm.wav"),
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
        except Exception:
            traceback.print_exc()

    def stop(self):
        if not IS_WIN:
            return
        try:
            import winsound
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

    def speak(self, text, lang="zh"):
        def run():
            with self._tts_lock:
                try:
                    import pyttsx3
                    e = pyttsx3.init()
                    e.setProperty("rate", 155)      # 慢一点，长辈听清
                    want_en = (lang == "en")
                    picked = None
                    for v in e.getProperty("voices"):
                        nm = (getattr(v, "name", "") or "").lower()
                        vid = (getattr(v, "id", "") or "").lower()
                        is_cn = ("chinese" in nm or "huihui" in nm or "zh" in vid or "kangkang" in nm)
                        is_en = (("english" in nm or "en-" in vid or "en_" in vid or "zira" in nm
                                  or "david" in nm or "hazel" in nm or "mark" in nm) and not is_cn)
                        if want_en and is_en:
                            picked = v.id; break
                        if (not want_en) and is_cn:
                            picked = v.id; break
                    if picked:
                        e.setProperty("voice", picked)
                    e.say(text); e.runAndWait()
                    try: e.stop()
                    except Exception: pass
                except Exception:
                    traceback.print_exc()
        threading.Thread(target=run, daemon=True).start()

ALERTER = Alerter()
CURRENT = {"key": None, "ev": None, "t0": 0.0, "spoke": 0.0}

def alarm_speech(ev, lang="zh"):
    if lang == "en":
        if ev.get("type") == "skin":
            return f"Time to apply your medicine. Please apply {ev['name']}."
        return f"Time to take your medicine. Please take {ev['name']}, {ev.get('dose','')}."
    if ev.get("type") == "skin":
        return f"该涂药了。请涂抹{ev['name']}。"
    return f"该吃药了。请服用{ev['name']}，{ev.get('dose','')}。"

def bring_to_front(win):
    try: win.restore()
    except Exception: pass
    try:
        win.on_top = True; time.sleep(0.4); win.on_top = False
    except Exception: pass

def _trigger(win, ev):
    s = load_settings()
    CURRENT.update(key=ev["key"], ev=ev, t0=time.time(), spoke=time.time())
    if s.get("sound_on", True):
        ALERTER.ring()
    bring_to_front(win)
    try:
        win.evaluate_js("window.showAlarmFromPython(%s)" % json.dumps(ev, ensure_ascii=False))
    except Exception:
        pass
    if s.get("voice_on", True):
        ALERTER.speak(alarm_speech(ev, s.get("lang", "zh")), s.get("lang", "zh"))

def scheduler_main():
    time.sleep(4)
    win = webview.windows[0]
    while True:
        try:
            s = load_settings()
            if CURRENT["key"] is None:
                ev = API.check_due()
                if ev:
                    _trigger(win, ev)
            else:
                if s.get("voice_on", True) and time.time() - CURRENT["spoke"] > 45:
                    ALERTER.speak(alarm_speech(CURRENT["ev"], s.get("lang", "zh")), s.get("lang", "zh"))
                    CURRENT["spoke"] = time.time()
        except Exception:
            traceback.print_exc()
        time.sleep(8)

# ========== 离线/在线识别 ==========
def parse_offline(image_path):
    import ocr_parse
    return ocr_parse.recognize(image_path)

def parse_online(image_path, settings):
    from anthropic import Anthropic
    key = settings.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("未填写 API Key")
    with open(image_path, "rb") as f:
        b64 = base64.standard_b64encode(f.read()).decode()
    ext = os.path.splitext(image_path)[1].lower().lstrip(".")
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
             "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    prompt = ('阅读药单/医嘱图片，只输出 JSON 数组：'
              '[{"name","dose","type":"pill|skin","timings":["after_breakfast等"],"note"}]')
    cli = Anthropic(api_key=key)
    r = cli.messages.create(model=settings.get("model", "claude-opus-4-5"),
        max_tokens=1500, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
            {"type": "text", "text": prompt}]}])
    txt = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip())
    return [{"name": m.get("name", "未命名"), "dose": m.get("dose", ""),
             "type": "skin" if m.get("type") == "skin" else "pill",
             "timings": m.get("timings") or ["after_breakfast"],
             "note": m.get("note", "")} for m in json.loads(txt)]

# ========== 暴露给前端 ==========
class Api:
    def get_state(self):
        s = load_settings(); meds = _load(MEDS_FILE, []); history = _load(HISTORY_FILE, {})
        return {"settings": s, "meds": meds,
                "today_label": _cn_date(datetime.date.today()),
                "today": day_events(s, meds, today_str(), history),
                "week": week_report(s, meds, history)}

    def mark(self, key, status, date_iso=None):
        date_iso = date_iso or today_str()
        history = _load(HISTORY_FILE, {})
        history.setdefault(date_iso, {})[key] = status
        _save(HISTORY_FILE, history)
        self._resolve()
        return self.get_state()

    def snooze(self, key, minutes=10):
        self._snoozed[key] = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
        self._resolve()
        return True

    def stop_alarm(self):
        self._resolve(); return True

    def _resolve(self):
        ALERTER.stop()
        CURRENT.update(key=None, ev=None)

    _snoozed = {}

    def check_due(self):
        s = load_settings(); meds = _load(MEDS_FILE, []); history = _load(HISTORY_FILE, {})
        now = datetime.datetime.now(); nowmin = now.hour * 60 + now.minute
        for ev in day_events(s, meds, today_str(), history):
            if ev["status"] != "wait":
                continue
            h, m = map(int, ev["time"].split(":"))
            sn = self._snoozed.get(ev["key"])
            if sn and now < sn:
                continue
            if 0 <= (nowmin - (h * 60 + m)) <= 120:
                return ev
        return None

    def add_med(self, med):
        meds = _load(MEDS_FILE, [])
        med["id"] = med.get("id") or _new_id(meds)
        med.setdefault("timings", ["after_breakfast"]); med.setdefault("type", "pill")
        # 需求2：疗程。前端传 start_date(+course_text)；end_date 缺省由 course_text 推算
        med.setdefault("start_date", today_str())
        if not med.get("end_date"):
            med["end_date"] = calc_end(med.get("start_date"), med.get("course_text"))
        med.setdefault("source", med.get("source", "manual"))
        meds.append(med); _save(MEDS_FILE, meds)
        return self.get_state()

    def update_med(self, med_id, partial):
        """需求3:识别生成的药随时可在「自定义」修改。"""
        meds = _load(MEDS_FILE, [])
        for m in meds:
            if m["id"] == med_id:
                for k, v in partial.items():
                    m[k] = v
                if "course_text" in partial and not partial.get("end_date"):
                    m["end_date"] = calc_end(m.get("start_date"), m.get("course_text"))
                break
        _save(MEDS_FILE, meds)
        return self.get_state()

    def delete_med(self, med_id):
        _save(MEDS_FILE, [m for m in _load(MEDS_FILE, []) if m["id"] != med_id])
        return self.get_state()

    def confirm_parsed(self, parsed_list):
        meds = _load(MEDS_FILE, [])
        for m in parsed_list:
            m["id"] = _new_id(meds); meds.append(m)
        _save(MEDS_FILE, meds)
        return self.get_state()

    def update_settings(self, partial):
        s = load_settings()
        for k, v in partial.items():
            if k == "times" and isinstance(v, dict):
                s["times"].update(v)
            else:
                s[k] = v
        _save(SETTINGS_FILE, s)
        if "autostart" in partial:          # 运行模式：开关即写注册表
            set_autostart(bool(partial["autostart"]))
        return self.get_state()

    def get_day(self, date_iso):
        """需求2：返回任意一天的事件（月历点选某天用）。"""
        s = load_settings(); meds = _load(MEDS_FILE, []); history = _load(HISTORY_FILE, {})
        d = datetime.date.fromisoformat(date_iso)
        return {"date": date_iso, "label": _cn_date(d),
                "events": day_events(s, meds, date_iso, history)}

    def med_days(self, ym):
        """需求2：返回某月(YYYY-MM)内“有用药安排”的日期列表，供月历标注。"""
        meds = _load(MEDS_FILE, [])
        y, m = map(int, ym.split("-"))
        first = datetime.date(y, m, 1)
        nm = datetime.date(y + (m == 12), (m % 12) + 1, 1)
        out = []
        d = first
        while d < nm:
            di = d.isoformat()
            if any(_in_course(med, di) and med.get("timings") for med in meds):
                out.append(di)
            d += datetime.timedelta(days=1)
        return out

    def open_verify_url(self, which, name="", approval_no=""):
        """需求4/5：打开核验入口。深链不稳，尽力拼搜索 URL。
        英文模式只给第三方 Drugs.com（非 FDA 官方）。"""
        import urllib.parse
        q = urllib.parse.quote((approval_no or name or "").strip())
        if which == "nmpa":
            url = "https://www.nmpa.gov.cn/datasearch/home-index.html"   # 单页站，深链不稳，落到搜索首页
        elif which == "mozun":
            url = f"https://www.pharnexcloud.com/search?q={q}" if q else "https://www.pharnexcloud.com/"
        elif which == "drugscom":
            qn = urllib.parse.quote((name or "").strip())   # Drugs.com 用药名搜索更准
            url = f"https://www.drugs.com/search.php?searchterm={qn}" if qn else "https://www.drugs.com/"
        else:
            url = "about:blank"
        ok = open_url(url)
        return {"ok": ok, "url": url}

    def pick_and_parse(self):
        win = webview.windows[0]
        files = win.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("图片 (*.png;*.jpg;*.jpeg;*.webp)", "所有文件 (*.*)"))
        if not files:
            return {"ok": False, "msg": "未选择图片"}
        path = files[0] if isinstance(files, (list, tuple)) else files
        s = load_settings()
        online = bool(s.get("use_online") and s.get("api_key"))
        try:
            meds = parse_online(path, s) if online else parse_offline(path)
            if not meds:
                return {"ok": False, "msg": "没识别到药品，请把药单拍清楚些，或在「自定义」手动添加"}
            return {"ok": True, "meds": meds, "offline": not online}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "msg": f"识别失败：{e}"}

    def pick_and_parse_box(self):
        """需求4：拍药盒 → OCR(抓国药准字+候选名) → 查本地 drugs.db(含 openFDA) → 指南+建议方案。"""
        win = webview.windows[0]
        files = win.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("图片 (*.png;*.jpg;*.jpeg;*.webp)", "所有文件 (*.*)"))
        if not files:
            return {"ok": False, "msg": "未选择图片"}
        path = files[0] if isinstance(files, (list, tuple)) else files
        try:
            import ocr_parse
            box = ocr_parse.recognize_box(path)
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "msg": f"识别失败：{e}"}
        hit = self._lookup_drug(box.get("approval_no", ""), box.get("names", []))
        raw_name = (box.get("names") or [""])[0]
        if hit:
            return {"ok": True, "found": True, "approval_no": box.get("approval_no", ""),
                    "raw_name": raw_name, "names": box.get("names", []),
                    "drug": hit["drug"], "suggest": hit["suggest"]}
        # 未找到：给出 OCR 到的候选名，便于家属手动添加时参考
        return {"ok": True, "found": False, "approval_no": box.get("approval_no", ""),
                "raw_name": raw_name, "names": box.get("names", [])}

    def _lookup_drug(self, approval_no="", names=None):
        try:
            import drugdb
        except Exception:
            return None
        lang = load_settings().get("lang", "zh")
        names = names or []
        if approval_no:
            r = drugdb.lookup(approval_no=approval_no, lang=lang)
            if r: return r
        for nm in names:
            r = drugdb.lookup(name=nm, lang=lang)
            if r: return r
        return None

    def lookup_drug(self, name="", approval_no=""):
        """供前端在确认页手动改名后重查。"""
        return self._lookup_drug(approval_no, [name] if name else [])

    def drugdb_count(self):
        try:
            import drugdb
            return drugdb.count()
        except Exception:
            return 0

    def add_drug_entry(self, entry):
        """新功能：在「自定义」里手动往离线资料库添加一种药（名称/说明/用法）。"""
        try:
            import drugdb
            return drugdb.add_entry(entry or {})
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "msg": f"添加失败：{e}"}

    def import_drugs_json(self):
        """新功能：选一个 JSON 文件，批量导入到离线资料库。
        接受格式：[{"name":"药名","desc":"用途说明","usage":"每日两次，随餐",
                   "category":"降压","timings":["after_breakfast","after_dinner"]}, ...]
        也兼容 fetch_openfda.py 的 openfda_slim.json（取其中文名+英文名入库占位）。"""
        win = webview.windows[0]
        files = win.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("JSON 文件 (*.json)", "所有文件 (*.*)"))
        if not files:
            return {"ok": False, "msg": "未选择文件"}
        path = files[0] if isinstance(files, (list, tuple)) else files
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return {"ok": False, "msg": f"读取/解析 JSON 失败：{e}"}
        # 兼容 openfda_slim.json：{drugs:[{cn,en,...}]} -> 转成导入条目
        if isinstance(data, dict) and "drugs" in data:
            data = [{"name": d.get("cn"), "en_name": d.get("en"),
                     "category": d.get("category", "进口/openFDA"),
                     "desc": "（来自 openFDA，建议补充中文用途）"} for d in data["drugs"]]
        try:
            import drugdb
            return drugdb.import_entries(data)
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "msg": f"导入失败：{e}"}

    def test_alarm(self):
        s = load_settings(); meds = _load(MEDS_FILE, []); history = _load(HISTORY_FILE, {})
        evs = day_events(s, meds, today_str(), history)
        ev = dict(evs[0]) if evs else {"key": "_test", "name": "测试药品", "dose": "1 片",
            "type": "pill", "slot": "测试", "note": "这是一次测试提醒"}
        ev["key"] = "_test"; ev.setdefault("time", datetime.datetime.now().strftime("%H:%M"))
        _trigger(webview.windows[0], ev)
        return True

    def export_week(self):
        s = load_settings(); meds = _load(MEDS_FILE, []); history = _load(HISTORY_FILE, {})
        rep = week_report(s, meds, history)
        win = webview.windows[0]
        path = win.create_file_dialog(webview.SAVE_DIALOG, save_filename="用药周报.csv",
                                      file_types=("CSV 表格 (*.csv)",))
        if not path:
            return {"ok": False}
        if isinstance(path, (list, tuple)):
            path = path[0]
        cells = {"y": "已服", "n": "漏服", "x": "无"}
        with open(path, "w", encoding="utf-8-sig") as f:
            f.write("日期," + ",".join(rep["columns"]) + "\n")
            for row in rep["rows"]:
                f.write(row["day"] + "," + ",".join(cells.get(c, "") for c in row["cells"]) + "\n")
        return {"ok": True, "path": path}

# ---------- 辅助 ----------
def _new_id(meds):
    nums = [int(m["id"]) for m in meds if str(m.get("id", "")).isdigit()]
    return str((max(nums) + 1) if nums else 1)

def _cn_date(d):
    return f"{d.month}月{d.day}日 星期{'一二三四五六日'[d.weekday()]}"

def week_report(settings, meds, history):
    cols = ["早", "午", "晚", "睡前"]
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    rows, done, missed = [], 0, 0
    for i in range(7):
        d = monday + datetime.timedelta(days=i); di = d.isoformat()
        future = d > today; is_today = d == today; tracked = bool(history.get(di))
        evs = day_events(settings, meds, di, history)
        per = {c: [] for c in cols}
        for ev in evs:
            col = "午" if ev["timing"] == "custom" else TIMINGS[ev["timing"]][3]
            per.setdefault(col, []).append(ev["status"])
        cells = []
        for c in cols:
            sts = per.get(c, [])
            if not sts or future or (not is_today and not tracked):
                cells.append("x")
            elif is_today:
                cells.append("n" if any(s == "skip" for s in sts)
                             else "y" if all(s == "done" for s in sts) else "x")
            else:
                cells.append("y" if all(s == "done" for s in sts) else "n")
        if is_today:
            for ev in evs:
                if ev["status"] == "done": done += 1
                elif ev["status"] == "skip": missed += 1
        elif not future and tracked:
            for ev in evs:
                done += 1 if ev["status"] == "done" else 0
                missed += 0 if ev["status"] == "done" else 1
        rows.append({"day": "周" + "一二三四五六日"[i], "cells": cells})
    total = done + missed
    return {"columns": cols, "rows": rows,
            "rate": round(done / total * 100) if total else 100,
            "done": done, "missed": missed, "total": total}

def _demo_meds():
    return [
        {"id": "1", "name": "阿司匹林肠溶片", "dose": "1 片", "type": "pill",
         "timings": ["after_breakfast"], "note": "餐后服用"},
        {"id": "2", "name": "二甲双胍片", "dose": "1 片", "type": "pill",
         "timings": ["after_breakfast", "after_dinner"], "note": "用温水送服"},
        {"id": "3", "name": "硝苯地平缓释片", "dose": "1 片", "type": "pill",
         "timings": ["after_lunch"], "note": ""},
        {"id": "4", "name": "外用药膏", "dose": "适量涂抹患处", "type": "skin",
         "timings": ["bedtime"], "note": "睡前薄涂"},
    ]

API = Api()

# ========== 运行模式：托盘常驻 ==========
QUIT = {"v": False}
TRAY = {"icon": None}

def _on_closing():
    """拦截关窗：未真正退出时隐藏到托盘，保证调度线程存活。"""
    if QUIT["v"]:
        return True
    try:
        webview.windows[0].hide()
    except Exception:
        pass
    return False        # 取消关闭

def _tray_thread():
    if not IS_WIN:
        return
    try:
        import pystray
        from PIL import Image
        img = Image.open(resource_path("chiyaome.ico"))

        def _show(icon, item):
            try: webview.windows[0].show()
            except Exception: pass

        def _quit(icon, item):
            QUIT["v"] = True
            try: icon.stop()
            except Exception: pass
            try: webview.windows[0].destroy()
            except Exception: pass

        menu = pystray.Menu(
            pystray.MenuItem("打开吃药么", _show, default=True),
            pystray.MenuItem("退出", _quit),
        )
        TRAY["icon"] = pystray.Icon(APP_NAME, img, APP_NAME, menu)
        TRAY["icon"].run()
    except Exception:
        traceback.print_exc()    # 托盘不可用则降级：仍可运行，仅关窗即退

def on_start():
    # 后台线程：调度提醒 + 托盘
    threading.Thread(target=scheduler_main, daemon=True).start()
    threading.Thread(target=_tray_thread, daemon=True).start()

def main():
    if not os.path.exists(SETTINGS_FILE):
        _save(SETTINGS_FILE, DEFAULT_SETTINGS)
    if not os.path.exists(MEDS_FILE):
        _save(MEDS_FILE, _demo_meds())
    # 需求3：首启把随包预构建的 drugs.db 复制到可写数据目录（打包后必须，否则药盒识别永远“未找到”）
    try:
        import drugdb
        if not drugdb.exists() or drugdb.count() == 0:
            drugdb.seed_from_resource(resource_path("drugs.db"))
    except Exception:
        traceback.print_exc()
    # 首启按设置同步开机自启（默认开）
    s = load_settings()
    set_autostart(bool(s.get("autostart", True)))
    win = webview.create_window(APP_NAME, resource_path(os.path.join("web", "index.html")),
                          js_api=API, width=430, height=860,
                          min_size=(390, 720), background_color="#EFF4FB")
    try:
        win.events.closing += _on_closing      # 关窗→托盘（pywebview 新版支持取消）
    except Exception:
        pass
    webview.start(on_start)   # 启动后台提醒 + 托盘

if __name__ == "__main__":
    main()
