# -*- coding: utf-8 -*-
"""
吃药么 · 本地药品库读取层 v3.2（四表结构：drugs_en / drug_names / drugs_cn / terms）
=====================================================================================
- 出厂随包预构建 drugs.db（由 build_drugs_db_v32.py 用 openFDA 英文权威库 + 中文卡片生成）；
  首启复制到 ~/.chiyaome/ 以便可写（用户可继续增药/导入）。
- 拍盒/查名：英文/品牌/NDC 走 drug_names 索引秒级命中；中文名走 drugs_cn 模糊匹配。
- 按语言输出：zh 优先中文卡片，缺失则英文原文+提示(en_fallback)；en 优先英文原文。
- 兼容压缩与未压缩库（drugs_en.compressed 标记，fields_json 可为 gzip BLOB）。
对外（与 v3.1 保持一致，新增可选 lang）：
  exists() count() seed_from_resource(src) lookup(approval_no,name,lang)
  add_entry(entry) import_entries(list)
"""
import os, re, json, gzip, time, shutil, sqlite3

try:
    from rapidfuzz import fuzz
    def _ratio(a, b): return fuzz.partial_ratio(a, b)
except Exception:
    from difflib import SequenceMatcher
    def _ratio(a, b): return SequenceMatcher(None, a, b).ratio() * 100


def _data_dir():
    d = os.path.join(os.path.expanduser("~"), ".chiyaome")
    os.makedirs(d, exist_ok=True)
    return d

DB = os.path.join(_data_dir(), "drugs.db")


def exists():
    return os.path.exists(DB)


def _con():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _has_table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (name,)).fetchone() is not None


def count():
    """收录种数：英文权威库为主（约一万多种）；缺失则退中文卡片数。"""
    if not exists():
        return 0
    con = _con()
    try:
        if _has_table(con, "drugs_en"):
            return con.execute("SELECT COUNT(*) FROM drugs_en").fetchone()[0]
        if _has_table(con, "drugs_cn"):
            return con.execute("SELECT COUNT(*) FROM drugs_cn").fetchone()[0]
        return 0
    except Exception:
        return 0
    finally:
        con.close()


def seed_from_resource(src_db):
    """把随包预构建的 drugs.db 复制到可写数据目录（首启用）。"""
    try:
        if src_db and os.path.exists(src_db):
            shutil.copyfile(src_db, DB)
            return True
    except Exception:
        pass
    return False


# ---------------- 内部：字段解码 / 取值 ----------------
def _fields(row):
    """drugs_en.fields_json → dict（兼容 gzip BLOB 与明文 JSON）。"""
    if row is None:
        return {}
    fj, comp = row["fields_json"], row["compressed"]
    if not fj:
        return {}
    try:
        if comp:
            txt = gzip.decompress(fj).decode("utf-8")
        elif isinstance(fj, (bytes, bytearray)):
            txt = fj.decode("utf-8")
        else:
            txt = str(fj)
        return json.loads(txt)
    except Exception:
        return {}


def _pick(fields, keys):
    for k in keys:
        v = fields.get(k)
        if v:
            return v
    return ""


def _norm(s):
    return (s or "").strip().lower()


# ---------------- 内部：匹配 ----------------
def _en_by_key(con, ik):
    if not ik:
        return None
    return con.execute("SELECT * FROM drugs_en WHERE ingredient_key=?", (ik,)).fetchone()


def _cn_by_key(con, ik):
    if not ik:
        return None
    return con.execute("SELECT * FROM drugs_cn WHERE ingredient_key=? LIMIT 1", (ik,)).fetchone()


def _ingredient_by_name(con, name):
    """英文通用名/品牌/NDC → ingredient_key（走 drug_names 索引）。"""
    n = _norm(name)
    if not n:
        return ""
    r = con.execute("SELECT ingredient_key FROM drug_names WHERE name=? LIMIT 1", (n,)).fetchone()
    if r:
        return r[0]
    # 前缀：OCR 到 'amlodipine'，库里键是 'amlodipine besylate'
    r = con.execute("SELECT ingredient_key FROM drug_names WHERE name LIKE ? LIMIT 1",
                    (n + " %",)).fetchone()
    if r:
        return r[0]
    # 反向：名字更长（品牌带规格词），用首词再试
    head = n.split()[0] if n.split() else ""
    if len(head) >= 4:
        r = con.execute("SELECT ingredient_key FROM drug_names WHERE name=? LIMIT 1",
                        (head,)).fetchone()
        if r:
            return r[0]
    return ""


def _cn_fuzzy(con, name):
    """中文名 → drugs_cn 行（模糊匹配 cn_name/别名/英文名）。"""
    q = (name or "").strip()
    if not q or not _has_table(con, "drugs_cn"):
        return None
    best, bs = None, 0
    for r in con.execute("SELECT * FROM drugs_cn"):
        cands = [r["cn_name"], r["en_key"]] + json.loads(r["aliases"] or "[]")
        b = 0
        for a in cands:
            a = (a or "").strip()
            if not a:
                continue
            s = _ratio(q, a)
            if a in q or q in a:
                s = max(s, 92)
            b = max(b, s)
        if b > bs:
            bs, best = b, r
    return best if bs >= 60 else None


def _is_skin(en_row, cn_row):
    if en_row is not None:
        route = " ".join(json.loads(en_row["route"] or "[]")).lower()
        if any(k in route for k in ("topical", "ophthalmic", "otic", "nasal", "rectal", "transdermal")):
            return True
    if cn_row is not None:
        blob = (cn_row["category"] or "") + (cn_row["cn_name"] or "")
        if any(k in blob for k in ("滴眼", "外用", "乳膏", "软膏", "凝胶", "贴", "栓", "吸入", "喷")):
            return True
    return False


def _build(cn_row, en_row, lang):
    enf = _fields(en_row)
    en_name = en_row["generic_name"] if en_row is not None else ""
    timings = json.loads(cn_row["timings"]) if (cn_row is not None and cn_row["timings"]) else []
    freq_cn = cn_row["freq_cn"] if cn_row is not None else ""

    if lang == "en":
        if en_row is not None:
            drug = {"name_cn": cn_row["cn_name"] if cn_row is not None else "",
                    "name_en": en_name,
                    "indications": _pick(enf, ["indications_and_usage", "purpose"]),
                    "usage": _pick(enf, ["dosage_and_administration"]),
                    "contraindication": _pick(enf, ["contraindications", "do_not_use"]),
                    "cautions": _pick(enf, ["warnings_and_cautions", "warnings"]),
                    "elderly_caution": _pick(enf, ["geriatric_use"]),
                    "source": "openfda_en"}
        else:  # 仅中文卡片（国内特有药，openFDA 无）
            drug = {"name_cn": cn_row["cn_name"], "name_en": cn_row["en_key"],
                    "indications": "", "usage": "", "contraindication": "",
                    "cautions": "", "elderly_caution": "", "source": "cn_only"}
    else:  # zh
        if cn_row is not None:
            drug = {"name_cn": cn_row["cn_name"], "name_en": en_name or cn_row["en_key"],
                    "indications": cn_row["use_cn"], "usage": cn_row["freq_cn"],
                    "contraindication": cn_row["caution_cn"], "cautions": "",
                    "elderly_caution": cn_row["geriatric_cn"], "source": "seed_cn"}
        elif en_row is not None:  # 无中文卡片 → 英文原文 + 前端提示“暂无中文资料”
            drug = {"name_cn": "", "name_en": en_name,
                    "indications": _pick(enf, ["indications_and_usage", "purpose"]),
                    "usage": _pick(enf, ["dosage_and_administration"]),
                    "contraindication": _pick(enf, ["contraindications", "do_not_use"]),
                    "cautions": _pick(enf, ["warnings_and_cautions", "warnings"]),
                    "elderly_caution": _pick(enf, ["geriatric_use"]),
                    "source": "en_fallback"}
        else:
            return None
    suggest = {"name": (cn_row["cn_name"] if (cn_row is not None) else en_name),
               "type": "skin" if _is_skin(en_row, cn_row) else "pill",
               "timings": timings, "dose": "", "freq": freq_cn}
    return {"drug": drug, "suggest": suggest}


def lookup(approval_no="", name="", lang="zh"):
    """命中返回 {drug, suggest}；未命中 None。lang: 'zh'(默认) / 'en'。"""
    if not exists():
        return None
    con = _con()
    try:
        if not _has_table(con, "drugs_en") and not _has_table(con, "drugs_cn"):
            return None
        ik, cn_row, en_row = "", None, None
        # NDC（数字）锚点；国药准字在英文库无对应，digits 提取后查不到即跳过
        if approval_no:
            digits = re.sub(r"\D", "", approval_no)
            if digits and _has_table(con, "drug_names"):
                r = con.execute("SELECT ingredient_key FROM drug_names WHERE kind='ndc' AND name=? LIMIT 1",
                                (digits,)).fetchone()
                if r:
                    ik = r[0]
        if not ik and name and _has_table(con, "drug_names"):
            ik = _ingredient_by_name(con, name)
        en_index_hit = bool(ik)
        # 仅当英文/NDC 索引没命中（名字多半是中文）才做中文模糊匹配；
        # 英文已精确命中成分时，中文卡片只按 ingredient_key 精确取，避免误挂错卡片。
        if name and not en_index_hit:
            cn_row = _cn_fuzzy(con, name)
            if cn_row is not None and cn_row["ingredient_key"]:
                ik = cn_row["ingredient_key"]
        if ik and cn_row is None:
            cn_row = _cn_by_key(con, ik)
        if ik:
            en_row = _en_by_key(con, ik)
        if cn_row is None and en_row is None:
            return None
        return _build(cn_row, en_row, lang)
    finally:
        con.close()


# ---------------- 用户自添加 / 导入（写入 drugs_cn）----------------
def _ensure_cn(con):
    if not _has_table(con, "drugs_cn"):
        con.execute("""CREATE TABLE drugs_cn(
            id INTEGER PRIMARY KEY AUTOINCREMENT, cn_name TEXT, en_key TEXT, ingredient_key TEXT,
            category TEXT, use_cn TEXT, geriatric_cn TEXT, caution_cn TEXT,
            freq_cn TEXT, timings TEXT, aliases TEXT, source TEXT, updated_at TEXT)""")


def add_entry(entry):
    cn = (entry.get("name") or entry.get("cn_name") or "").strip()
    if not cn:
        return {"ok": False, "msg": "缺少药品名称"}
    if not exists():
        return {"ok": False, "msg": "药品库尚未建立"}
    con = _con()
    try:
        _ensure_cn(con)
        con.execute("""INSERT INTO drugs_cn(cn_name,en_key,ingredient_key,category,use_cn,
            geriatric_cn,caution_cn,freq_cn,timings,aliases,source,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cn, entry.get("en_name", ""), "", entry.get("category", "自添加"),
             entry.get("desc") or entry.get("use") or "", entry.get("geriatric", ""),
             entry.get("caution", ""), entry.get("usage") or entry.get("freq", ""),
             json.dumps(entry.get("timings") or []), json.dumps([cn], ensure_ascii=False),
             "manual", time.strftime("%Y-%m-%d %H:%M:%S")))
        con.commit()
        return {"ok": True, "msg": f"已添加到资料库：{cn}", "count": count()}
    finally:
        con.close()


def import_entries(entries):
    if not isinstance(entries, list):
        return {"ok": False, "msg": "JSON 顶层应是一个数组 [ ... ]"}
    if not exists():
        return {"ok": False, "msg": "药品库尚未建立"}
    added = updated = skipped = 0
    con = _con()
    try:
        _ensure_cn(con)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        for e in entries:
            if not isinstance(e, dict):
                skipped += 1; continue
            cn = (e.get("name") or e.get("cn_name") or "").strip()
            if not cn:
                skipped += 1; continue
            use = e.get("desc") or e.get("use") or ""
            usage = e.get("usage") or e.get("freq") or ""
            timings = e.get("timings") or []
            row = con.execute("SELECT id FROM drugs_cn WHERE cn_name=?", (cn,)).fetchone()
            if row:
                con.execute("""UPDATE drugs_cn SET use_cn=?,freq_cn=?,timings=?,category=?,
                    caution_cn=?,geriatric_cn=?,updated_at=? WHERE id=?""",
                    (use, usage, json.dumps(timings), e.get("category", "自添加"),
                     e.get("caution", ""), e.get("geriatric", ""), now, row["id"]))
                updated += 1
            else:
                con.execute("""INSERT INTO drugs_cn(cn_name,en_key,ingredient_key,category,use_cn,
                    geriatric_cn,caution_cn,freq_cn,timings,aliases,source,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cn, e.get("en_name", ""), "", e.get("category", "自添加"), use,
                     e.get("geriatric", ""), e.get("caution", ""), usage,
                     json.dumps(timings), json.dumps([cn], ensure_ascii=False), "import", now))
                added += 1
        con.commit()
        return {"ok": True, "added": added, "updated": updated, "skipped": skipped,
                "count": count(),
                "msg": f"导入完成：新增 {added}，更新 {updated}，跳过 {skipped}"}
    finally:
        con.close()
