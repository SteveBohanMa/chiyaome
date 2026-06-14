"""
离线识别医嘱：本地 OCR(RapidOCR, 自带模型, 无需联网) + 规则解析。
对外：recognize(image_path) -> [med, ...]
med = {name, dose, type(pill|skin), timings[...], note}
解析为启发式，结果会交给用户在「确认」界面核对修改。
"""
import re

MEAL_ORDER = ["breakfast", "lunch", "dinner"]
FORM_WORDS = ("片", "胶囊", "颗粒", "丸", "散", "口服液", "合剂", "糖浆",
              "分散片", "缓释片", "肠溶片", "咀嚼片", "泡腾片",
              "乳膏", "软膏", "凝胶", "膏", "贴", "栓", "滴眼液", "滴眼",
              "喷雾", "搽剂", "洗剂", "气雾剂")
SKIN_WORDS = ("乳膏", "软膏", "凝胶", "膏", "贴", "栓", "滴眼", "眼药",
              "滴耳", "喷雾", "外用", "涂", "搽", "洗剂")
HEADER_WORDS = ("医院", "处方", "科室", "姓名", "性别", "年龄", "日期",
                "医师", "医生", "签名", "金额", "费用", "诊断", "门诊",
                "住院", "笺", "卡号", "就诊")
DOSE_RE = re.compile(r"(半|\d+(?:\.\d+)?)\s*"
                     r"(片|粒|袋|支|滴|喷|ml|mL|毫升|mg|毫克|μg|ug|g|克|IU|单位)")
# 中文数量词（安全集合，避免误切“三七片”等药名）
CN_DOSE_RE = re.compile(r"(适量|半片|半粒|[一二两三四五]\s*[片粒袋支滴喷瓶包])")
# 用于切出药名的“用法关键词”（多字，避免误切药名里的字）
CUT_WORDS = ["每日", "一日", "每天", "每晚", "每早", "每次", "口服", "外用",
             "饭前", "饭后", "餐前", "餐后", "食后", "睡前", "空腹", "涂抹",
             "涂搽", "含服", "一次", "二次", "两次", "三次", "qd", "bid",
             "tid", "QD", "BID", "TID"]


def _freq(t):
    if re.search(r"三次|3\s*次|tid|TID|日三|一日三", t): return 3
    if re.search(r"[两二]次|2\s*次|bid|BID|日[两二]|一日[两二]", t): return 2
    if re.search(r"[一1]\s*次|qd|QD|每日一|每天一|每晚|每早|顿服", t): return 1
    return 0


def _timings(t):
    bedtime = ("睡前" in t) or ("晚上睡" in t)
    rel = ("after" if re.search(r"饭后|餐后|食后", t)
           else "before" if re.search(r"饭前|餐前|空腹|食前", t) else None)
    meals = set()
    if re.search(r"早|晨", t): meals.add("breakfast")
    if re.search(r"午|中午", t): meals.add("lunch")
    # “每晚/睡前”里的“晚”不算晚餐
    if "晚" in t and not bedtime and "每晚" not in t: meals.add("dinner")
    if "晚饭" in t or "晚餐" in t: meals.add("dinner")
    f = _freq(t)

    if bedtime:
        return ["bedtime"]
    if rel and meals:
        return [f"{rel}_{m}" for m in MEAL_ORDER if m in meals]
    if rel and not meals:
        r = rel
        return ({1: [f"{r}_breakfast"],
                 2: [f"{r}_breakfast", f"{r}_dinner"],
                 3: [f"{r}_breakfast", f"{r}_lunch", f"{r}_dinner"]}
                .get(f, [f"{r}_breakfast"]))
    if meals and not rel:
        return [f"after_{m}" for m in MEAL_ORDER if m in meals]
    # 无任何明确时机 -> 按次数默认饭后
    return {1: ["after_breakfast"],
            2: ["after_breakfast", "after_dinner"],
            3: ["after_breakfast", "after_lunch", "after_dinner"]}.get(f or 1,
            ["after_breakfast"])


def _is_skin(t):
    return any(w in t for w in SKIN_WORDS)


def _cut_name(line):
    """返回 (name, 是否像药品行)。name 为用法关键词/剂量之前的部分。"""
    idxs = []
    m = DOSE_RE.search(line)
    if m: idxs.append(m.start())
    m2 = CN_DOSE_RE.search(line)
    if m2: idxs.append(m2.start())
    for w in CUT_WORDS:
        i = line.find(w)
        if i >= 0: idxs.append(i)
    cut = min(idxs) if idxs else len(line)
    name = line[:cut].strip(" 　·.、:：-—()（）")
    return name


def parse_text(raw):
    """raw 可为整段文本或按行。返回 med 列表。"""
    lines = [l.strip() for l in re.split(r"[\n\r]+", raw) if l.strip()]
    meds, last = [], None
    for line in lines:
        # 去行首编号：1. / 1、/ (1) / 三、 / ①（仅当带分隔符，避免误删“三七片”这类药名）
        line = re.sub(
            r"^\s*(?:[\(（]?\s*(?:[0-9０-９]+|[一二三四五六七八九十]+)\s*[\.\、\)）]|[①-⑩])\s*",
            "", line).strip()
        if not line:
            continue
        is_header = (any(w in line for w in HEADER_WORDS)
                     and not DOSE_RE.search(line)
                     and not any(w in line for w in FORM_WORDS))
        if is_header:
            continue
        name = _cut_name(line)
        has_form = any(w in name for w in FORM_WORDS)
        dose_m = DOSE_RE.search(line)
        freq = _freq(line)
        has_timing = bool(re.search(r"饭前|饭后|餐前|餐后|睡前|空腹", line))

        looks_med = bool(name) and (has_form or dose_m or freq or
                                    _is_skin(line))
        if not looks_med:
            # 可能是上一条药的续行（只有用法）
            if last and (dose_m or freq or has_timing):
                if dose_m and not last["dose"]:
                    last["dose"] = dose_m.group(0)
                t2 = _timings(line)
                if t2:
                    last["timings"] = t2
            continue

        skin = _is_skin(line)
        cn = CN_DOSE_RE.search(line)
        if dose_m:
            dose = dose_m.group(0)
        elif cn:
            dose = cn.group(0)
        elif skin:
            dose = "适量涂抹患处"
        else:
            dose = ""
        med = {
            "name": name or "未识别药名",
            "dose": dose,
            "type": "skin" if skin else "pill",
            "timings": _timings(line),
            "note": "外用" if skin and "外用" in line else "",
        }
        meds.append(med)
        last = med
    return meds


def ocr_image(image_path):
    """本地 OCR，返回每行文本。无网络。"""
    from rapidocr_onnxruntime import RapidOCR
    global _OCR
    try:
        _OCR
    except NameError:
        _OCR = RapidOCR()
    result, _ = _OCR(image_path)
    if not result:
        return ""
    # 按 y 坐标排序，拼成行
    items = sorted(result, key=lambda r: (round(r[0][0][1] / 14), r[0][0][0]))
    return "\n".join(txt for _, txt, _ in items)


def recognize(image_path):
    return parse_text(ocr_image(image_path))


# ===== 需求4：药盒识别（独立通道，不复用处方行解析）=====
APPROVAL_RE = re.compile(r"国药准字[A-Z]\d{8}")
# 保健品/进口锚点（先留出，后续可扩匹配逻辑）
OTHER_NO_RE = re.compile(r"(国食健字[A-Z]?\d+|卫食健字.*?\d+|注册证号[\w\-]+)")

def _candidate_names(lines):
    """从药盒文本行里挑可能的药名：含剂型词、且不含明显非药名特征的行。"""
    cands = []
    for ln in lines:
        s = ln.strip(" 　·.、:：-—()（）")
        if not s or len(s) > 30:
            continue
        if any(w in s for w in HEADER_WORDS):
            continue
        # 优先：含剂型词的行（如“二甲双胍片”“硝苯地平缓释片”）
        if any(w in s for w in FORM_WORDS):
            cands.append(s)
    # 没有带剂型词的，退而取较短的纯中文行
    if not cands:
        for ln in lines:
            s = ln.strip(" 　·.、:：-—()（）")
            if 2 <= len(s) <= 12 and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9]+", s or ""):
                cands.append(s)
    # 去重保序
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c); out.append(c)
    return out[:8]

def recognize_box(image_path):
    """返回 {raw_text, approval_no, names[]}。匹配 drugs.db 的工作交给 app/drugdb。"""
    text = ocr_image(image_path)
    lines = [l.strip() for l in re.split(r"[\n\r]+", text) if l.strip()]
    m = APPROVAL_RE.search(text)
    approval = m.group(0) if m else ""
    return {"raw_text": text, "approval_no": approval, "names": _candidate_names(lines)}


if __name__ == "__main__":
    import sys, json
    print(json.dumps(recognize(sys.argv[1]), ensure_ascii=False, indent=2))
