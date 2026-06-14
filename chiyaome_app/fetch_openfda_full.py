#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吃药么 · openFDA 全量药品标签抓取脚本（国际化 v3.2 用）  —— 完整信息度版
=====================================================================
目标：把 openFDA「药品标签(drug/label)」整库（13 个分片 zip）下载，
     **按通用名(active ingredient)去重合并**，**尽量保留完整字段文本**，
     直接产出可随包发布的 SQLite：drugs_en.db（英文原版，作为权威数据）。

== 遇到 SSL「self-signed certificate in certificate chain」怎么办 ==
这通常是你电脑上的**杀毒软件/公司代理在拦截 HTTPS**（往证书链里插了它自己的根证书）。
本脚本对此有两条路：
  路 A（自动）：检测到证书校验失败会**自动切换为不校验证书**继续下载（公开数据，可接受）。
              也可以直接显式加 --insecure。
  路 B（最稳，彻底绕过下载/SSL）：用**浏览器**手动下载那 13 个分片 zip（浏览器走系统证书库，能正常下），
              放到一个文件夹，然后：
                  py fetch_openfda_full.py --zips-dir "C:\\下载\\openfda"
              脚本只读本地 zip，不再联网。
  分片下载页：https://open.fda.gov/apis/drug/label/download/

设计要点见各参数注释。**只依赖 Python 标准库**（certifi 可选），无需 pip 安装。

典型用法：
    # 小跑验证（自动处理证书问题）
    py fetch_openfda_full.py --parts 1 --limit 3000 --insecure
    # 全量、保留完整文本、压缩存储
    py fetch_openfda_full.py --compress --insecure
    # 或：浏览器下好 13 个 zip 后离线处理
    py fetch_openfda_full.py --compress --zips-dir "C:\\path\\to\\zips"

产物：
    drugs_en.db              ← 随包发布的英文权威库（留本机，下一批集成打包）
    openfda_full_report.json ← 很小，发回给我做验证

参数：
    --parts N            只处理前 N 个分片（0=全部；小跑用 1）
    --limit N            每分片最多处理 N 条（0=不限；小跑用 3000）
    --max-field-chars N  每段裁剪上限（默认 0=不裁，保留完整；想压体积可设 8000）
    --lean               只保留最常用字段集（默认全字段，完整度优先）
    --compress           字段文本整体 gzip 后以 BLOB 存入（约 1/3 体积，完整度不变）
    --insecure           不校验 SSL 证书（杀软/代理拦截 HTTPS 时用）
    --zips-dir DIR       改为处理本地已下好的分片 zip 目录（彻底绕过下载/SSL）
    --out-db PATH        输出 SQLite（默认 ./drugs_en.db）
    --keep-zips          保留下载分片（默认用完即删）
    --tmp DIR            临时目录（默认 ./_openfda_tmp）
"""
import os, re, ssl, glob, json, gzip, time, zipfile, sqlite3, argparse
import urllib.request, urllib.error

DOWNLOAD_MANIFEST = "https://api.fda.gov/download.json"
UA = {"User-Agent": "chiyaome-fetch/3.2 (+offline medication reminder)"}

try:
    import certifi
    _CAFILE = certifi.where()
except Exception:
    _CAFILE = None

CTX = {"insecure": False}   # 证书校验失败时会自动置 True


# ---------------- 网络 / SSL ----------------
def _ssl_context():
    if CTX["insecure"]:
        return ssl._create_unverified_context()
    return ssl.create_default_context(cafile=_CAFILE) if _CAFILE else ssl.create_default_context()


def _is_cert_error(e):
    s = str(e)
    return "CERTIFICATE_VERIFY_FAILED" in s or ("certificate" in s.lower() and "ssl" in s.lower())


def _open(url, timeout):
    req = urllib.request.Request(url, headers=UA)
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())
    except Exception as e:
        if not CTX["insecure"] and _is_cert_error(e):
            print("  [提示] 证书校验失败 → 自动切换为「不校验证书」继续（仅用于下载公开数据）")
            CTX["insecure"] = True
            return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())
        raise


def _http_json(url):
    with _open(url, 60) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url, dst, retries=3):
    for attempt in range(1, retries + 1):
        try:
            with _open(url, 180) as r:
                total = int(r.headers.get("Content-Length", 0)); got = 0
                with open(dst, "wb") as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk); got += len(chunk)
                        if total:
                            print(f"\r    下载中 {got//(1<<20)}/{total//(1<<20)} MB "
                                  f"({got*100//total}%)", end="", flush=True)
                print()
            return True
        except Exception as e:
            print(f"\n    [第 {attempt} 次失败] {e}"); time.sleep(3 * attempt)
    return False


# ---------------- 字段集 ----------------
FIELDS_FULL = [
    "indications_and_usage", "dosage_and_administration", "dosage_forms_and_strengths",
    "contraindications", "warnings", "warnings_and_cautions", "boxed_warning",
    "precautions", "adverse_reactions", "drug_interactions",
    "geriatric_use", "use_in_specific_populations",
    "patient_counseling_information", "information_for_patients",
    "purpose", "indications_and_usage_otc", "when_using", "do_not_use",
    "ask_doctor", "ask_doctor_or_pharmacist", "stop_use", "keep_out_of_reach_of_children",
]
FIELDS_LEAN = [
    "indications_and_usage", "dosage_and_administration", "dosage_forms_and_strengths",
    "contraindications", "warnings", "warnings_and_cautions",
    "geriatric_use", "drug_interactions", "purpose", "do_not_use",
]


# ---------------- 解析/合并（已自测，保持不变） ----------------
def _join(v):
    if isinstance(v, list):
        return "  ".join(str(x).strip() for x in v if x)
    return str(v or "").strip()


def _clean(text, max_chars):
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if max_chars and len(text) > max_chars:
        cut = text[:max_chars]
        m = max(cut.rfind(". "), cut.rfind("; "), cut.rfind("。"))
        if m > max_chars * 0.6:
            cut = cut[:m + 1]
        text = cut.rstrip() + " …"
    return text


def _norm_key(generics):
    parts = []
    for g in generics:
        for piece in re.split(r"\s+and\s+|\s*[/,;]\s*", str(g).lower()):
            piece = piece.strip()
            if piece:
                parts.append(piece)
    return "+".join(sorted(set(parts)))


def slim_record(rec, field_list, max_chars):
    ofda = rec.get("openfda", {}) or {}
    generics = ofda.get("generic_name") or ofda.get("substance_name") or []
    if isinstance(generics, str):
        generics = [generics]
    if not generics:
        return None
    key = _norm_key(generics)
    if not key:
        return None
    out = {
        "ingredient_key": key, "generic_name": str(generics[0]).strip(),
        "brand_names": [b for b in (ofda.get("brand_name") or []) if b][:16],
        "ndc": [n for n in (ofda.get("product_ndc") or []) if n][:16],
        "route": [r for r in (ofda.get("route") or []) if r][:8],
        "product_type": (ofda.get("product_type") or [""])[0],
        "manufacturer": (ofda.get("manufacturer_name") or [""])[0],
        "fields": {},
    }
    for fk in field_list:
        if fk in rec:
            v = _clean(_join(rec[fk]), max_chars)
            if v:
                out["fields"][fk] = v
    return out


def _better(a, b):
    la = sum(len(v) for v in a["fields"].values())
    lb = sum(len(v) for v in b["fields"].values())
    keep, drop = (a, b) if la >= lb else (b, a)
    for f in ("brand_names", "ndc", "route"):
        keep[f] = list(dict.fromkeys((keep.get(f) or []) + (drop.get(f) or [])))[:32]
    for fk, v in drop["fields"].items():
        if len(v) > len(keep["fields"].get(fk, "")):
            keep["fields"][fk] = v
    return keep


def _records_from_zip(zpath):
    with zipfile.ZipFile(zpath) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            return json.loads(fh.read().decode("utf-8")).get("results", [])


# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-field-chars", type=int, default=0)
    ap.add_argument("--lean", action="store_true")
    ap.add_argument("--compress", action="store_true")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--zips-dir", default="")
    ap.add_argument("--out-db", default="drugs_en.db")
    ap.add_argument("--keep-zips", action="store_true")
    ap.add_argument("--tmp", default="_openfda_tmp")
    args = ap.parse_args()
    field_list = FIELDS_LEAN if args.lean else FIELDS_FULL
    if args.insecure:
        CTX["insecure"] = True
        print("  [提示] 已启用 --insecure：不校验 SSL 证书")

    # 组装数据源：本地 zip 目录 或 联网分片
    export_date, total_records = "?", "?"
    if args.zips_dir:
        local = sorted(glob.glob(os.path.join(args.zips_dir, "*.json.zip")) +
                       glob.glob(os.path.join(args.zips_dir, "*.json.gz")))
        if not local:
            print(f"[错误] 在 {args.zips_dir} 没找到任何 *.json.zip 分片文件")
            return
        print(f"本地分片模式：{args.zips_dir}，找到 {len(local)} 个文件")
        sources = [("local", p, os.path.basename(p),
                    round(os.path.getsize(p) / (1 << 20), 1)) for p in local]
        if args.parts:
            sources = sources[:args.parts]
    else:
        print("读取 openFDA 下载清单 …")
        label = _http_json(DOWNLOAD_MANIFEST)["results"]["drug"]["label"]
        parts = label.get("partitions", [])
        total_records = label.get("total_records", "?")
        export_date = label.get("export_date", "?")
        print(f"  药品标签整库：{total_records} 条，导出日期 {export_date}，{len(parts)} 个分片")
        if args.parts:
            parts = parts[:args.parts]; print(f"  本次只处理前 {len(parts)} 个分片")
        sources = [("url", p.get("file"), os.path.basename(p.get("file")),
                    p.get("size_mb", "?")) for p in parts]

    print(f"  字段集：{'精简(lean)' if args.lean else '完整(full)'}  "
          f"裁剪：{'不裁(完整)' if not args.max_field_chars else str(args.max_field_chars)+'字符/段'}  "
          f"压缩：{'是' if args.compress else '否'}")
    os.makedirs(args.tmp, exist_ok=True)

    merged, seen_raw = {}, 0
    for i, src in enumerate(sources, 1):
        kind, ref, label_name, size_mb = src
        print(f"[{i}/{len(sources)}] {label_name}（约 {size_mb} MB）")
        if kind == "local":
            zpath = ref
        else:
            zpath = os.path.join(args.tmp, label_name)
            if not (os.path.exists(zpath) and args.keep_zips):
                if not _download(ref, zpath):
                    print("    下载失败，跳过"); continue
        try:
            results = _records_from_zip(zpath)
        except Exception as e:
            print(f"    解析失败：{e}")
            if kind == "url" and not args.keep_zips and os.path.exists(zpath):
                os.remove(zpath)
            continue
        for n, rec in enumerate(results, 1):
            if args.limit and n > args.limit:
                break
            seen_raw += 1
            s = slim_record(rec, field_list, args.max_field_chars)
            if not s:
                continue
            k = s["ingredient_key"]
            merged[k] = _better(merged[k], s) if k in merged else s
        print(f"    本分片 {len(results)} 条 → 累计去重通用名 {len(merged)} 种")
        if kind == "url" and not args.keep_zips and os.path.exists(zpath):
            os.remove(zpath)

    if not merged:
        print("[错误] 没有得到任何记录，请检查网络/证书，或改用 --zips-dir 本地模式")
        return

    # ---- 写 SQLite ----
    if os.path.exists(args.out_db):
        os.remove(args.out_db)
    con = sqlite3.connect(args.out_db); cur = con.cursor()
    cur.execute("""CREATE TABLE drugs_en(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ingredient_key TEXT UNIQUE,
        generic_name TEXT, brand_names TEXT, ndc TEXT, route TEXT,
        product_type TEXT, manufacturer TEXT,
        fields_json BLOB, compressed INTEGER, spl_count INTEGER, updated_at TEXT)""")
    cur.execute("CREATE INDEX idx_generic ON drugs_en(generic_name)")
    cur.execute("CREATE TABLE drug_names(ingredient_key TEXT, name TEXT, kind TEXT)")
    cur.execute("CREATE INDEX idx_name ON drug_names(name)")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    raw_field_bytes = stored_field_bytes = 0
    for s in merged.values():
        fjson = json.dumps(s["fields"], ensure_ascii=False)
        raw_field_bytes += len(fjson.encode("utf-8"))
        blob, comp = (gzip.compress(fjson.encode("utf-8")), 1) if args.compress else (fjson, 0)
        stored_field_bytes += (len(blob) if isinstance(blob, bytes) else len(blob.encode("utf-8")))
        cur.execute("""INSERT INTO drugs_en(ingredient_key,generic_name,brand_names,ndc,route,
            product_type,manufacturer,fields_json,compressed,spl_count,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (s["ingredient_key"], s["generic_name"],
             json.dumps(s["brand_names"], ensure_ascii=False),
             json.dumps(s["ndc"], ensure_ascii=False),
             json.dumps(s["route"], ensure_ascii=False),
             s["product_type"], s["manufacturer"], blob, comp, 1, now))
        for nm, kind in [(s["generic_name"], "generic")] + [(b, "brand") for b in s["brand_names"]]:
            if nm:
                cur.execute("INSERT INTO drug_names VALUES(?,?,?)",
                            (s["ingredient_key"], nm.lower().strip(), kind))
        for nd in s["ndc"]:
            cur.execute("INSERT INTO drug_names VALUES(?,?,?)",
                        (s["ingredient_key"], re.sub(r"\D", "", nd), "ndc"))
    con.commit()
    db_bytes = os.path.getsize(args.out_db)
    per_drug = [sum(len(v) for v in s["fields"].values()) for s in merged.values()] or [0]
    con.close()

    samples = []
    for s in list(merged.values())[:20]:
        samples.append({"ingredient_key": s["ingredient_key"], "generic_name": s["generic_name"],
                        "brand_names": s["brand_names"][:3], "ndc": s["ndc"][:2],
                        "product_type": s["product_type"],
                        "fields_present": sorted(s["fields"].keys()),
                        "field_chars": {k: len(v) for k, v in s["fields"].items()},
                        "indications_head": s["fields"].get("indications_and_usage", "")[:200]})
    report = {"_meta": {"source": "openFDA drug/label", "generated_at": now,
              "export_date": export_date, "raw_records_total": total_records,
              "raw_records_seen": seen_raw, "unique_ingredients": len(merged),
              "field_set": "lean" if args.lean else "full",
              "max_field_chars": args.max_field_chars or "uncapped",
              "compressed": bool(args.compress), "insecure_used": CTX["insecure"],
              "out_db": os.path.abspath(args.out_db), "out_db_mb": round(db_bytes / (1 << 20), 1),
              "field_text_raw_mb": round(raw_field_bytes / (1 << 20), 1),
              "field_text_stored_mb": round(stored_field_bytes / (1 << 20), 1),
              "per_drug_chars_avg": int(sum(per_drug) / len(per_drug)),
              "per_drug_chars_max": max(per_drug),
              "note": "把 openfda_full_report.json 发回给 Claude 验证；drugs_en.db 留本机打包。"},
              "samples": samples}
    with open("openfda_full_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    m = report["_meta"]
    print("\n========== 完成 ==========")
    print(f"原始处理 {seen_raw} 条 → 去重通用名 {len(merged)} 种")
    print(f"字段文本：明文 {m['field_text_raw_mb']}MB → 入库 {m['field_text_stored_mb']}MB"
          f"（{'压缩' if args.compress else '未压缩'}）")
    print(f"每药平均 {m['per_drug_chars_avg']} 字符，最长 {m['per_drug_chars_max']} 字符")
    print(f"输出 SQLite：{m['out_db']}（{m['out_db_mb']} MB）")
    print("验证报告：openfda_full_report.json（请把这个小文件发回给我）")


if __name__ == "__main__":
    main()
