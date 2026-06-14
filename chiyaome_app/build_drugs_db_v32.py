#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
吃药么 · v3.2 建库脚本（自包含版，无需任何其它文件）
====================================================
输入：只需要 drugs_en.db（fetch_openfda_full.py 产出的英文权威库）。
     74 种中文卡片 + 中文名↔英文名对照，已**内置在本文件里**，不再依赖
     build_drugs_db.py 或 openfda_slim.json。

输出：drugs.db（最终随包库），4 张表：
  drugs_en   英文权威库（从 drugs_en.db 复制；--compress 时 fields_json 压成 gzip BLOB）
  drug_names 名称索引（通用名/品牌/NDC，小写）—— 拍盒快速匹配
  drugs_cn   中文卡片（每条带 ingredient_key 关联到 drugs_en）
  terms      双语词表（类别/时机/频次/途径/剂型）

用法（drugs_en.db 在哪就在哪跑都行）：
  py build_drugs_db_v32.py --en drugs_en.db --compress
  # 或绝对路径：
  py build_drugs_db_v32.py --en "C:\\Users\\mabha\\drugs_en.db" --compress
"""
import os, re, json, gzip, time, sqlite3, argparse

# ====== 内置数据（自动从 v3.1 build_drugs_db.py 与 openfda_slim.json 提取，勿手改）======
CURATED = {'氨氯地平': {'cat': '降压', 'use': '高血压、冠心病心绞痛', 'ger': '起始剂量宜小，注意低血压', 'cau': '对本品过敏禁用；可能踝部水肿', 'freq': '每日一次', 'tm': ['after_breakfast']}, '硝苯地平': {'cat': '降压', 'use': '高血压、心绞痛', 'ger': '缓释片不可掰开，警惕低血压', 'cau': '严重主动脉狭窄慎用', 'freq': '缓释每日一次', 'tm': ['after_breakfast']}, '非洛地平': {'cat': '降压', 'use': '高血压', 'ger': '从小剂量起，注意水肿头痛', 'cau': '避免与西柚同服', 'freq': '每日一次，晨服', 'tm': ['after_breakfast']}, '美托洛尔': {'cat': '降压', 'use': '高血压、心绞痛、心衰、心律失常', 'ger': '勿突然停药，监测心率', 'cau': '心动过缓、哮喘、严重传导阻滞禁用', 'freq': '每日1–2次', 'tm': ['after_breakfast', 'after_dinner']}, '比索洛尔': {'cat': '降压', 'use': '高血压、冠心病、慢性心衰', 'ger': '监测心率血压，勿骤停', 'cau': '重度心动过缓/哮喘慎用', 'freq': '每日一次，晨服', 'tm': ['after_breakfast']}, '阿替洛尔': {'cat': '降压', 'use': '高血压、心绞痛', 'ger': '肾功能下降者需减量', 'cau': '心动过缓、哮喘禁用，勿骤停', 'freq': '每日一次', 'tm': ['after_breakfast']}, '缬沙坦': {'cat': '降压', 'use': '高血压、心衰', 'ger': '注意血钾与肾功能', 'cau': '妊娠禁用', 'freq': '每日一次', 'tm': ['after_breakfast']}, '氯沙坦': {'cat': '降压', 'use': '高血压、糖尿病肾病', 'ger': '监测血钾肾功能', 'cau': '妊娠禁用', 'freq': '每日一次', 'tm': ['after_breakfast']}, '厄贝沙坦': {'cat': '降压', 'use': '高血压、糖尿病肾病', 'ger': '监测血钾肾功能', 'cau': '妊娠禁用', 'freq': '每日一次', 'tm': ['after_breakfast']}, '替米沙坦': {'cat': '降压', 'use': '高血压', 'ger': '监测血钾肾功能', 'cau': '妊娠、胆道梗阻禁用', 'freq': '每日一次', 'tm': ['after_breakfast']}, '卡托普利': {'cat': '降压', 'use': '高血压、心衰', 'ger': '注意干咳、首剂低血压', 'cau': '妊娠、血管性水肿史禁用；宜空腹', 'freq': '每日2–3次，饭前', 'tm': ['before_breakfast', 'after_dinner']}, '依那普利': {'cat': '降压', 'use': '高血压、心衰', 'ger': '注意干咳、血钾', 'cau': '妊娠、血管性水肿史禁用', 'freq': '每日1–2次', 'tm': ['after_breakfast']}, '贝那普利': {'cat': '降压', 'use': '高血压', 'ger': '注意干咳、肾功能', 'cau': '妊娠禁用', 'freq': '每日一次', 'tm': ['after_breakfast']}, '培哚普利': {'cat': '降压', 'use': '高血压、冠心病', 'ger': '晨起空腹服，注意干咳', 'cau': '妊娠禁用', 'freq': '每日一次，晨服空腹', 'tm': ['before_breakfast']}, '氢氯噻嗪': {'cat': '利尿降压', 'use': '高血压、水肿', 'ger': '注意低血钾、脱水', 'cau': '无尿、严重肾衰慎用', 'freq': '每日一次，晨服', 'tm': ['after_breakfast']}, '吲达帕胺': {'cat': '利尿降压', 'use': '高血压', 'ger': '注意低血钾', 'cau': '严重肝肾不全慎用', 'freq': '每日一次，晨服', 'tm': ['after_breakfast']}, '二甲双胍': {'cat': '降糖', 'use': '2型糖尿病一线', 'ger': '监测肾功能，警惕乳酸酸中毒', 'cau': '严重肝肾不全禁用；造影前后停', 'freq': '随餐，每日2–3次', 'tm': ['after_breakfast', 'after_dinner']}, '格列美脲': {'cat': '降糖', 'use': '2型糖尿病', 'ger': '易低血糖，从小剂量起', 'cau': '1型糖尿病、酮症禁用', 'freq': '每日一次，早餐前/随早餐', 'tm': ['before_breakfast']}, '格列吡嗪': {'cat': '降糖', 'use': '2型糖尿病', 'ger': '警惕低血糖', 'cau': '餐前30分钟服', 'freq': '餐前，每日1–3次', 'tm': ['before_breakfast']}, '阿卡波糖': {'cat': '降糖', 'use': '2型糖尿病、餐后高血糖', 'ger': '常见腹胀排气', 'cau': '随第一口饭嚼服；肠病慎用', 'freq': '随餐嚼服，每日三次', 'tm': ['after_breakfast', 'after_lunch', 'after_dinner']}, '西格列汀': {'cat': '降糖', 'use': '2型糖尿病', 'ger': '肾功能不全需减量', 'cau': '胰腺炎史慎用', 'freq': '每日一次', 'tm': ['after_breakfast']}, '瑞格列奈': {'cat': '降糖', 'use': '2型糖尿病餐时血糖', 'ger': '警惕低血糖', 'cau': '餐前服，不进餐不服', 'freq': '餐前，每日三次', 'tm': ['before_breakfast']}, '达格列净': {'cat': '降糖', 'use': '2型糖尿病、心衰、肾病', 'ger': '注意泌尿生殖道感染、脱水', 'cau': '多饮水；1型糖尿病不推荐', 'freq': '每日一次', 'tm': ['after_breakfast']}, '甘精胰岛素': {'cat': '降糖', 'use': '糖尿病基础胰岛素', 'ger': '警惕夜间低血糖', 'cau': '皮下注射，不可静脉；固定时间', 'freq': '每日一次，固定时间', 'tm': ['bedtime']}, '格列齐特': {'cat': '降糖', 'use': '2型糖尿病', 'ger': '警惕低血糖', 'cau': '餐前服；严重肝肾不全禁用', 'freq': '早餐前，每日1–2次', 'tm': ['before_breakfast']}, '阿托伐他汀': {'cat': '降脂', 'use': '高胆固醇、防动脉硬化', 'ger': '监测肝功能、肌痛', 'cau': '活动性肝病、妊娠禁用', 'freq': '每日一次，任意时间', 'tm': ['after_dinner']}, '瑞舒伐他汀': {'cat': '降脂', 'use': '高胆固醇', 'ger': '亚洲人剂量宜小，监测肌痛', 'cau': '活动性肝病、妊娠禁用', 'freq': '每日一次', 'tm': ['after_dinner']}, '辛伐他汀': {'cat': '降脂', 'use': '高胆固醇', 'ger': '监测肌痛肝功能', 'cau': '晚服效果好；避免大量西柚', 'freq': '每日一次，晚服', 'tm': ['after_dinner']}, '普伐他汀': {'cat': '降脂', 'use': '高胆固醇', 'ger': '监测肝功能肌痛', 'cau': '活动性肝病、妊娠禁用', 'freq': '每日一次，晚服', 'tm': ['after_dinner']}, '非诺贝特': {'cat': '降脂', 'use': '高甘油三酯', 'ger': '监测肝功能、肌痛、肾功能', 'cau': '严重肝肾、胆囊病禁用', 'freq': '每日一次，随餐', 'tm': ['after_dinner']}, '阿司匹林': {'cat': '抗血小板', 'use': '防心梗脑卒中(小剂量)；解热镇痛(大剂量)', 'ger': '警惕消化道出血', 'cau': '活动性溃疡/出血禁用；肠溶片整片吞', 'freq': '护心每日一次', 'tm': ['after_breakfast']}, '氯吡格雷': {'cat': '抗血小板', 'use': '防血栓、支架术后', 'ger': '警惕出血', 'cau': '活动性出血禁用；术前遵医嘱停', 'freq': '每日一次', 'tm': ['after_breakfast']}, '华法林': {'cat': '抗凝', 'use': '房颤、血栓栓塞防治', 'ger': '需定期查INR，饮食药物影响大', 'cau': '出血风险高；多种相互作用', 'freq': '每日一次，固定时间', 'tm': ['after_dinner']}, '利伐沙班': {'cat': '抗凝', 'use': '房颤防卒中、静脉血栓', 'ger': '注意出血、肾功能', 'cau': '活动性出血禁用；15/20mg随餐', 'freq': '每日一次，随餐', 'tm': ['after_dinner']}, '达比加群': {'cat': '抗凝', 'use': '房颤防卒中、静脉血栓', 'ger': '注意出血、肾功能', 'cau': '胶囊整粒吞，不可拆开', 'freq': '每日两次', 'tm': ['after_breakfast', 'after_dinner']}, '地高辛': {'cat': '强心', 'use': '心衰、房颤心室率控制', 'ger': '治疗窗窄易中毒，监测血药浓度', 'cau': '注意恶心、视物异常等中毒征', 'freq': '每日一次', 'tm': ['after_breakfast']}, '单硝酸异山梨酯': {'cat': '硝酸酯', 'use': '冠心病心绞痛预防', 'ger': '警惕体位性低血压、头痛', 'cau': '不与西地那非类同用', 'freq': '每日1–2次', 'tm': ['after_breakfast']}, '硝酸甘油': {'cat': '硝酸酯', 'use': '心绞痛急性发作舌下含服', 'ger': '坐位含服防跌倒，警惕低血压', 'cau': '不与西地那非类同用；避光定期更换', 'freq': '发作时舌下含服', 'tm': []}, '曲美他嗪': {'cat': '抗心绞痛', 'use': '心绞痛辅助治疗', 'ger': '帕金森、震颤者慎用', 'cau': '运动障碍疾病禁用', 'freq': '每日2–3次，随餐', 'tm': ['after_breakfast', 'after_dinner']}, '奥美拉唑': {'cat': '抑酸', 'use': '胃溃疡、反流性食管炎', 'ger': '长期注意骨质、低镁', 'cau': '餐前空腹服', 'freq': '每日一次，早餐前', 'tm': ['before_breakfast']}, '泮托拉唑': {'cat': '抑酸', 'use': '胃溃疡、反流', 'ger': '长期注意骨折、低镁', 'cau': '餐前服', 'freq': '每日一次，早餐前', 'tm': ['before_breakfast']}, '雷贝拉唑': {'cat': '抑酸', 'use': '胃溃疡、反流', 'ger': '长期注意低镁、骨质', 'cau': '餐前服整片吞', 'freq': '每日一次', 'tm': ['before_breakfast']}, '兰索拉唑': {'cat': '抑酸', 'use': '胃溃疡、反流', 'ger': '长期注意骨折、低镁', 'cau': '餐前空腹服', 'freq': '每日一次，早餐前', 'tm': ['before_breakfast']}, '多潘立酮': {'cat': '促胃动力', 'use': '恶心、腹胀、消化不良', 'ger': '警惕心律(QT)，最低有效量短期', 'cau': '心脏病、严重肝损慎用；餐前服', 'freq': '餐前，每日三次', 'tm': ['before_breakfast']}, '莫沙必利': {'cat': '促胃动力', 'use': '功能性消化不良、反流', 'ger': '观察腹泻、肝功能', 'cau': '餐前服', 'freq': '餐前，每日三次', 'tm': ['before_breakfast']}, '沙丁胺醇': {'cat': '平喘', 'use': '哮喘、慢阻肺喘息', 'ger': '警惕心悸、手抖、低血钾', 'cau': '按需吸入；心脏病慎用', 'freq': '发作时吸入', 'tm': []}, '布地奈德': {'cat': '吸入激素', 'use': '哮喘、慢阻肺维持', 'ger': '吸入后漱口防口腔念珠菌', 'cau': '需规律使用，非急救用', 'freq': '每日两次，吸入', 'tm': ['after_breakfast', 'after_dinner']}, '茶碱': {'cat': '平喘', 'use': '哮喘、慢阻肺', 'ger': '治疗窗窄易中毒，监测血药浓度', 'cau': '缓释片不可掰碎；多相互作用', 'freq': '每日1–2次', 'tm': ['after_breakfast', 'after_dinner']}, '孟鲁司特': {'cat': '平喘', 'use': '哮喘、过敏性鼻炎', 'ger': '注意情绪/睡眠变化', 'cau': '非急救用', 'freq': '每日一次，睡前', 'tm': ['bedtime']}, '氨溴索': {'cat': '祛痰', 'use': '痰多咳嗽', 'ger': '一般耐受良好', 'cau': '餐后服，多饮水', 'freq': '每日2–3次，餐后', 'tm': ['after_breakfast', 'after_dinner']}, '布洛芬': {'cat': '解热镇痛', 'use': '疼痛、发热、关节炎', 'ger': '警惕胃肠出血、肾损、血压升高', 'cau': '溃疡、严重心肾病慎用；餐后服', 'freq': '需要时，餐后', 'tm': ['after_breakfast']}, '对乙酰氨基酚': {'cat': '解热镇痛', 'use': '疼痛、发热', 'ger': '注意每日总量防肝损', 'cau': '肝病、大量饮酒慎用；勿超量', 'freq': '需要时，每4–6小时', 'tm': []}, '塞来昔布': {'cat': '镇痛', 'use': '关节炎、镇痛', 'ger': '警惕心血管、胃肠、肾风险', 'cau': '磺胺过敏、严重心血管病慎用', 'freq': '每日1–2次，随餐', 'tm': ['after_breakfast', 'after_dinner']}, '双氯芬酸': {'cat': '镇痛', 'use': '疼痛、关节炎', 'ger': '警惕胃肠出血、心血管风险', 'cau': '溃疡、严重心肾病慎用；餐后服', 'freq': '每日2–3次，餐后', 'tm': ['after_breakfast', 'after_dinner']}, '碳酸钙': {'cat': '补钙', 'use': '补钙、骨质疏松辅助', 'ger': '便秘者注意，分次服吸收好', 'cau': '高钙血症、结石慎用；随餐服', 'freq': '每日1–2次，随餐', 'tm': ['after_breakfast', 'after_dinner']}, '阿仑膦酸钠': {'cat': '抗骨质疏松', 'use': '骨质疏松', 'ger': '服后保持直立30分钟', 'cau': '晨起空腹整片大量水送服；食管病禁用', 'freq': '每周一次，晨起空腹', 'tm': ['before_breakfast']}, '骨化三醇': {'cat': '活性维D', 'use': '骨质疏松、低钙、肾性骨病', 'ger': '监测血钙', 'cau': '高钙血症禁用', 'freq': '每日1–2次', 'tm': ['after_breakfast']}, '多奈哌齐': {'cat': '抗痴呆', 'use': '阿尔茨海默病', 'ger': '注意心动过缓、胃肠反应、失眠', 'cau': '睡前服；病窦综合征慎用', 'freq': '每日一次，睡前', 'tm': ['bedtime']}, '美金刚': {'cat': '抗痴呆', 'use': '中重度阿尔茨海默病', 'ger': '肾功能不全减量', 'cau': '逐步加量', 'freq': '每日1–2次', 'tm': ['after_breakfast']}, '左旋多巴': {'cat': '抗帕金森', 'use': '帕金森病', 'ger': '注意体位性低血压、剂末现象', 'cau': '与高蛋白餐间隔；不可骤停', 'freq': '每日多次，餐前1小时', 'tm': ['before_breakfast']}, '阿普唑仑': {'cat': '镇静', 'use': '焦虑、失眠', 'ger': '跌倒/嗜睡风险高，宜短期小量', 'cau': '不可骤停；避免与酒/镇静药合用', 'freq': '睡前或遵医嘱', 'tm': ['bedtime']}, '艾司唑仑': {'cat': '镇静催眠', 'use': '失眠', 'ger': '跌倒、次日困倦风险', 'cau': '短期使用，不可骤停', 'freq': '睡前', 'tm': ['bedtime']}, '倍他司汀': {'cat': '改善眩晕', 'use': '梅尼埃病、内耳眩晕', 'ger': '消化道溃疡、哮喘慎用', 'cau': '餐后服', 'freq': '每日三次，餐后', 'tm': ['after_breakfast', 'after_lunch', 'after_dinner']}, '左甲状腺素': {'cat': '甲状腺激素', 'use': '甲状腺功能减退', 'ger': '从小剂量起，监测心率甲功', 'cau': '晨起空腹服，与钙铁间隔', 'freq': '每日一次，晨起空腹', 'tm': ['before_breakfast']}, '甲巯咪唑': {'cat': '抗甲亢', 'use': '甲状腺功能亢进', 'ger': '监测血常规、肝功能', 'cau': '警惕粒细胞缺乏(发热咽痛即就医)', 'freq': '每日1–3次', 'tm': ['after_breakfast']}, '坦索罗辛': {'cat': '前列腺', 'use': '前列腺增生排尿困难', 'ger': '警惕体位性低血压、头晕', 'cau': '饭后同一时间服；眼手术前告知', 'freq': '每日一次，餐后', 'tm': ['after_dinner']}, '非那雄胺': {'cat': '前列腺', 'use': '前列腺增生', 'ger': '起效慢需长期', 'cau': '孕妇禁触碰；影响PSA', 'freq': '每日一次', 'tm': ['after_breakfast']}, '拉坦前列素': {'cat': '降眼压滴眼', 'use': '青光眼、高眼压', 'ger': '可致虹膜变深、睫毛增长', 'cau': '每晚一次，多药间隔5分钟', 'freq': '每晚一次，滴眼', 'tm': ['bedtime']}, '噻吗洛尔': {'cat': '降眼压滴眼', 'use': '青光眼', 'ger': '警惕心率、哮喘(经鼻泪管吸收)', 'cau': '哮喘、心动过缓慎用；滴后压内眼角', 'freq': '每日1–2次，滴眼', 'tm': ['after_breakfast']}, '呋塞米': {'cat': '利尿', 'use': '水肿、心衰、高血压', 'ger': '警惕脱水、低钾、跌倒', 'cau': '晨服避免夜尿；监测电解质', 'freq': '每日1–2次，晨服', 'tm': ['after_breakfast']}, '螺内酯': {'cat': '保钾利尿', 'use': '水肿、心衰、高血压', 'ger': '警惕高血钾', 'cau': '高血钾、严重肾衰禁用', 'freq': '每日1–2次', 'tm': ['after_breakfast']}, '别嘌醇': {'cat': '降尿酸', 'use': '痛风、高尿酸', 'ger': '警惕皮疹(重症药疹)', 'cau': '出皮疹即停药就医；餐后多饮水', 'freq': '每日1–3次，餐后', 'tm': ['after_breakfast']}, '非布司他': {'cat': '降尿酸', 'use': '痛风高尿酸', 'ger': '心血管病史者慎用', 'cau': '初期可能痛风发作；餐后服', 'freq': '每日一次', 'tm': ['after_breakfast']}, '氯化钾': {'cat': '补钾', 'use': '低钾血症', 'ger': '警惕高血钾、胃肠刺激', 'cau': '餐后多饮水；缓释片整片吞；肾衰禁用', 'freq': '每日2–3次，餐后', 'tm': ['after_breakfast', 'after_dinner']}}

CN2EN = {'氨氯地平': 'amlodipine', '硝苯地平': 'nifedipine', '非洛地平': 'felodipine', '美托洛尔': 'metoprolol', '比索洛尔': 'bisoprolol', '阿替洛尔': 'atenolol', '缬沙坦': 'valsartan', '氯沙坦': 'losartan', '厄贝沙坦': 'irbesartan', '替米沙坦': 'telmisartan', '卡托普利': 'captopril', '依那普利': 'enalapril', '贝那普利': 'benazepril', '培哚普利': 'perindopril', '氢氯噻嗪': 'hydrochlorothiazide', '吲达帕胺': 'indapamide', '二甲双胍': 'metformin', '格列美脲': 'glimepiride', '格列吡嗪': 'glipizide', '阿卡波糖': 'acarbose', '西格列汀': 'sitagliptin', '瑞格列奈': 'repaglinide', '达格列净': 'dapagliflozin', '甘精胰岛素': 'insulin glargine', '阿托伐他汀': 'atorvastatin', '瑞舒伐他汀': 'rosuvastatin', '辛伐他汀': 'simvastatin', '普伐他汀': 'pravastatin', '非诺贝特': 'fenofibrate', '阿司匹林': 'aspirin', '氯吡格雷': 'clopidogrel', '华法林': 'warfarin', '利伐沙班': 'rivaroxaban', '达比加群': 'dabigatran', '地高辛': 'digoxin', '单硝酸异山梨酯': 'isosorbide mononitrate', '硝酸甘油': 'nitroglycerin', '奥美拉唑': 'omeprazole', '泮托拉唑': 'pantoprazole', '雷贝拉唑': 'rabeprazole', '兰索拉唑': 'lansoprazole', '沙丁胺醇': 'albuterol', '布地奈德': 'budesonide', '茶碱': 'theophylline', '孟鲁司特': 'montelukast', '布洛芬': 'ibuprofen', '对乙酰氨基酚': 'acetaminophen', '塞来昔布': 'celecoxib', '双氯芬酸': 'diclofenac', '碳酸钙': 'calcium carbonate', '阿仑膦酸钠': 'alendronate', '骨化三醇': 'calcitriol', '多奈哌齐': 'donepezil', '美金刚': 'memantine', '左旋多巴': 'levodopa', '阿普唑仑': 'alprazolam', '艾司唑仑': 'estazolam', '左甲状腺素': 'levothyroxine', '甲巯咪唑': 'methimazole', '坦索罗辛': 'tamsulosin', '非那雄胺': 'finasteride', '拉坦前列素': 'latanoprost', '噻吗洛尔': 'timolol', '呋塞米': 'furosemide', '螺内酯': 'spironolactone', '别嘌醇': 'allopurinol', '非布司他': 'febuxostat', '氯化钾': 'potassium chloride', '格列齐特': 'gliclazide', '曲美他嗪': 'trimetazidine', '多潘立酮': 'domperidone', '莫沙必利': 'mosapride', '氨溴索': 'ambroxol', '倍他司汀': 'betahistine'}


# 常见盐基/水合词：中英成分匹配时从英文通用名尾部剥离（calcium/sodium 等可能是药本身，故只做“前缀成分”匹配，不盲删）
SALTS = {"besylate", "hydrochloride", "hcl", "mesylate", "maleate", "tartrate", "fumarate",
         "succinate", "citrate", "sulfate", "sulphate", "phosphate", "acetate", "bromide",
         "hydrobromide", "nitrate", "dihydrate", "monohydrate", "trihydrate", "potassium",
         "calcium", "sodium", "magnesium", "dipropionate", "valerate", "furoate", "xinafoate"}

TIMING_TERMS = [("before_breakfast", "早饭前", "Before breakfast"),
                ("after_breakfast", "早饭后", "After breakfast"),
                ("before_lunch", "午饭前", "Before lunch"),
                ("after_lunch", "午饭后", "After lunch"),
                ("before_dinner", "晚饭前", "Before dinner"),
                ("after_dinner", "晚饭后", "After dinner"),
                ("bedtime", "睡前", "At bedtime")]
ROUTE_TERMS = [("oral", "口服", "Oral"), ("topical", "外用", "Topical"),
               ("ophthalmic", "滴眼", "Ophthalmic"), ("inhalation", "吸入", "Inhalation"),
               ("subcutaneous", "皮下注射", "Subcutaneous")]
FORM_TERMS = [("tablet", "片", "Tablet"), ("capsule", "胶囊", "Capsule"),
              ("cream", "乳膏", "Cream"), ("ointment", "软膏", "Ointment"),
              ("drops", "滴剂", "Drops"), ("spray", "喷雾", "Spray"),
              ("patch", "贴", "Patch"), ("injection", "注射", "Injection")]
FREQ_TERMS = [("qd", "每日一次", "Once daily"), ("bid", "每日两次", "Twice daily"),
              ("tid", "每日三次", "Three times daily"), ("qid", "每日四次", "Four times daily"),
              ("hs", "睡前", "At bedtime"), ("prn", "按需服用", "As needed")]
CATEGORY_EN = {
 "降压": "Antihypertensive", "利尿降压": "Diuretic / Antihypertensive", "降糖": "Antidiabetic",
 "降脂": "Lipid-lowering", "抗血小板": "Antiplatelet", "抗凝": "Anticoagulant", "强心": "Cardiac glycoside",
 "硝酸酯": "Nitrate", "抗心绞痛": "Antianginal", "抑酸": "Acid suppressant", "促胃动力": "Prokinetic",
 "平喘": "Bronchodilator / Antiasthmatic", "吸入激素": "Inhaled corticosteroid", "祛痰": "Expectorant",
 "解热镇痛": "Analgesic / Antipyretic", "镇痛": "Analgesic", "补钙": "Calcium supplement",
 "抗骨质疏松": "Anti-osteoporosis", "活性维D": "Active vitamin D", "抗痴呆": "Anti-dementia",
 "抗帕金森": "Anti-Parkinson", "镇静": "Sedative", "镇静催眠": "Sedative / Hypnotic",
 "改善眩晕": "Anti-vertigo", "甲状腺激素": "Thyroid hormone", "抗甲亢": "Antithyroid",
 "前列腺": "BPH / Prostate", "降眼压滴眼": "Ophthalmic (IOP-lowering)", "利尿": "Diuretic",
 "保钾利尿": "Potassium-sparing diuretic", "降尿酸": "Urate-lowering", "补钾": "Potassium supplement"}


def build_en_base_index(con_en):
    exact, base_map, field_len = set(), {}, {}
    for row in con_en.execute("SELECT ingredient_key, length(CAST(fields_json AS TEXT)) AS fl FROM drugs_en"):
        k = row[0]; exact.add(k)
        if "+" in k:
            continue
        toks = k.split()
        while len(toks) > 1 and toks[-1] in SALTS:
            toks = toks[:-1]
        base = " ".join(toks)
        if base and (base not in base_map or (row[1] or 0) > field_len.get(base, -1)):
            base_map[base] = k; field_len[base] = row[1] or 0
    return exact, base_map


def match_ingredient(en_base, exact, base_map):
    if not en_base:
        return ""
    b = en_base.lower().strip()
    if b in exact:
        return b
    if b in base_map:
        return base_map[b]
    for base, key in base_map.items():
        if base == b or base.startswith(b + " ") or b.startswith(base + " "):
            return key
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", default="drugs_en.db", help="英文权威库路径（fetch 产出）")
    ap.add_argument("--out", default="drugs.db")
    ap.add_argument("--compress", action="store_true", help="把 drugs_en.fields_json 压成 gzip BLOB")
    args = ap.parse_args()

    if not os.path.exists(args.en):
        print(f"[错误] 找不到英文权威库 {args.en}，请先跑 fetch_openfda_full.py，或用 --en 指定正确路径")
        return
    print(f"内置中文卡片 {len(CURATED)} 种；中文→英文对照 {len(CN2EN)} 条")

    if os.path.exists(args.out):
        os.remove(args.out)
    con = sqlite3.connect(args.out); cur = con.cursor()
    con_en = sqlite3.connect(args.en); con_en.row_factory = sqlite3.Row

    cur.execute("""CREATE TABLE drugs_en(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ingredient_key TEXT UNIQUE,
        generic_name TEXT, brand_names TEXT, ndc TEXT, route TEXT, product_type TEXT,
        manufacturer TEXT, fields_json BLOB, compressed INTEGER, spl_count INTEGER, updated_at TEXT)""")
    cur.execute("CREATE INDEX idx_generic ON drugs_en(generic_name)")
    n_en = recomp = 0
    for r in con_en.execute("SELECT * FROM drugs_en"):
        fj, comp = r["fields_json"], r["compressed"]
        if args.compress and not comp:
            raw = fj if isinstance(fj, (bytes, bytearray)) else str(fj).encode("utf-8")
            fj = gzip.compress(raw); comp = 1; recomp += 1
        cur.execute("""INSERT INTO drugs_en(ingredient_key,generic_name,brand_names,ndc,route,
            product_type,manufacturer,fields_json,compressed,spl_count,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (r["ingredient_key"], r["generic_name"], r["brand_names"], r["ndc"], r["route"],
             r["product_type"], r["manufacturer"], fj, comp, r["spl_count"], r["updated_at"]))
        n_en += 1
    cur.execute("CREATE TABLE drug_names(ingredient_key TEXT, name TEXT, kind TEXT)")
    cur.execute("CREATE INDEX idx_name ON drug_names(name)")
    n_names = 0
    for r in con_en.execute("SELECT ingredient_key,name,kind FROM drug_names"):
        cur.execute("INSERT INTO drug_names VALUES(?,?,?)", (r[0], r[1], r[2])); n_names += 1
    con.commit()

    cur.execute("""CREATE TABLE drugs_cn(
        id INTEGER PRIMARY KEY AUTOINCREMENT, cn_name TEXT, en_key TEXT, ingredient_key TEXT,
        category TEXT, use_cn TEXT, geriatric_cn TEXT, caution_cn TEXT,
        freq_cn TEXT, timings TEXT, aliases TEXT, source TEXT, updated_at TEXT)""")
    cur.execute("CREATE INDEX idx_cn_ing ON drugs_cn(ingredient_key)")
    cur.execute("CREATE INDEX idx_cn_name ON drugs_cn(cn_name)")
    exact, base_map = build_en_base_index(con_en)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    linked = 0
    for cn, c in CURATED.items():
        en_base = CN2EN.get(cn, "")
        ik = match_ingredient(en_base, exact, base_map)
        if ik:
            linked += 1
        cur.execute("""INSERT INTO drugs_cn(cn_name,en_key,ingredient_key,category,use_cn,
            geriatric_cn,caution_cn,freq_cn,timings,aliases,source,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cn, en_base, ik, c["cat"], c["use"], c["ger"], c["cau"], c["freq"],
             json.dumps(c["tm"]), json.dumps([cn, en_base], ensure_ascii=False), "curated", now))
    con.commit()

    cur.execute("CREATE TABLE terms(kind TEXT, key TEXT, zh TEXT, en TEXT)")
    rows = ([("timing",) + t for t in TIMING_TERMS] + [("route",) + t for t in ROUTE_TERMS] +
            [("form",) + t for t in FORM_TERMS] + [("freq",) + t for t in FREQ_TERMS] +
            [("category", z, z, e) for z, e in CATEGORY_EN.items()])
    cur.executemany("INSERT INTO terms(kind,key,zh,en) VALUES(?,?,?,?)", rows)
    con.commit()
    con_en.close()
    cur.execute("VACUUM")
    db_mb = round(os.path.getsize(args.out) / (1 << 20), 1)
    con.close()

    report = {"generated_at": now, "out_db": os.path.abspath(args.out), "out_db_mb": db_mb,
              "compressed": bool(args.compress), "recompressed_rows": recomp,
              "drugs_en_rows": n_en, "drug_names_rows": n_names,
              "drugs_cn_rows": len(CURATED), "drugs_cn_linked_to_en": linked,
              "drugs_cn_unlinked": len(CURATED) - linked, "terms_rows": len(rows),
              "note": "把 build_report.json 发回给我看关联命中率与体积。"}
    json.dump(report, open("build_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n========== 建库完成 ==========")
    print(f"drugs_en {n_en} 种 | drug_names {n_names} 行 | drugs_cn {len(CURATED)} 种"
          f"（关联到英文 {linked} 种，未关联 {len(CURATED)-linked}）| terms {len(rows)} 条")
    print(f"输出：{os.path.abspath(args.out)}（{db_mb} MB，压缩={'是' if args.compress else '否'}）")
    print("报告：build_report.json（发回给我）")


if __name__ == "__main__":
    main()
