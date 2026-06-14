# 吃药么 · Chi Yao Me

> ### ⚠️ 医疗免责声明 | Medical Disclaimer
>
> **本工具仅用于用药提醒，不构成任何医疗建议。**  
> 服药方案、剂量、用药时机请严格遵医嘱；如有疑问，请咨询执业医师或药师。  
>
> *This tool is for medication reminder purposes only and does not constitute medical advice.*  
> *Always follow your doctor's prescription. Consult a licensed physician or pharmacist if in doubt.*

---

面向**中国老年用户**的 Windows 桌面端吃药提醒应用。家属（常为远程）负责配置，老人只需点「已吃 / 没吃」。

**A Windows desktop medication reminder app for elderly Chinese users.**  
Family members (often remote) configure it; the elderly user just taps "已吃 / 没吃".

[![Build & Release](https://github.com/SteveBohanMa/chiyaome/actions/workflows/release.yml/badge.svg)](https://github.com/SteveBohanMa/chiyaome/actions/workflows/release.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-green.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey.svg)]()

---

## 在线试用 · Online Demo

> [**▶ 在线体验 Demo**](https://SteveBohanMa.github.io/chiyaome/demo.html)  
> *（纯浏览器版，使用 JS 模拟后端，无需安装）*
>
> [**▶ Try the Online Demo**](https://SteveBohanMa.github.io/chiyaome/demo.html)  
> *(Browser-only version with JS mock backend — no installation needed)*

---

## 截图 · Screenshots

> 截图待补充 | Screenshots coming soon

---

## 功能特点 · Features

| 功能 | 说明 |
|------|------|
| ⏰ 定时提醒 | 到点自动弹窗 + winsound 响铃 + 离线语音播报（循环直到确认） |
| 📸 药盒拍照识别 | 离线 OCR → 自动提取药名 / 剂量 / 用法，含 5 秒强制免责确认门 |
| 📅 月历视图 | 用药日高亮，集成于「今日」标签，支持日 / 月视图切换 |
| 📊 周报依从性 | 按餐次统计，颜色 + 图标双重编码（照顾色弱用户） |
| 🔍 药品库 | 74 种老年常用药，附老年人警示与禁忌（中文审定卡） |
| 🖥️ 托盘常驻 | 关窗不退出，后台持续提醒 |
| 🔁 开机自启 | 写注册表 HKCU，无需管理员权限 |
| 📴 离线优先 | 所有核心功能无需联网 |

---

## 家属安装说明 · For Family Members

### 方法一：下载 exe（推荐，无需 Python）

1. 前往 **[Releases 页面](https://github.com/SteveBohanMa/chiyaome/releases/latest)**，下载最新的 `MedicationReminder.exe`
2. 双击运行（首次运行 Windows 可能提示「未知发布者」→ 点「仍要运行」即可）
3. 文件约 150–200 MB，内含离线 OCR 模型，属正常大小

### 配置流程

1. 打开应用，进入「自定义」页
2. 添加老人的药品名称、剂量、每日提醒时间
3. 点击「测试提醒」确认响铃和语音正常
4. 最小化窗口（托盘图标常驻，后台持续提醒）

### 老人的日常操作

每到提醒时间，程序自动弹窗、响铃、语音播报，老人只需点击：

- ✅ **已吃** — 记录本次完成
- ❌ **没吃** — 记录跳过

---

## 开发者构建说明 · For Developers

### 环境要求

- **Python 3.12**（必须；`onnxruntime` 暂无 Python 3.13/3.14 wheel）
- Windows 10/11（64 位）

```bash
git clone https://github.com/SteveBohanMa/chiyaome.git
cd chiyaome/chiyaome_app
pip install -r requirements.txt
```

### 本机运行（开发模式）

```bash
py -3.12 app.py
```

### 重建药品数据库

`drugs.db` 不随源码提交（见下方说明），首次运行或更新需手动重建：

```bash
# 步骤 1：从 openFDA API 拉取约 74 种老年常用药英文数据（需联网）
py -3.12 fetch_openfda_full.py

# 步骤 2：合并英文权威库与手写中文药卡，生成 drugs.db
py -3.12 build_drugs_db_v32.py --en drugs_en.db --compress
```

重建完成后 `drugs.db` 会出现在 `chiyaome_app/` 目录下，可本地运行或打包。

### 打包为 exe

```bash
# 双击 build.bat，或命令行执行：
chiyaome_app\build.bat
```

**重要提示（打包踩坑记录）：**

- 必须使用 **Python 3.12**（`py -3.12`），3.13/3.14 的 `onnxruntime` 无 wheel
- PyInstaller 必须显式包含 pywebview 运行时依赖：`proxy_tools`、`bottle`、`pythonnet`、`pywin32`（`build.bat` 已包含）
- `build.bat` 每次自动清理 `build/`、`dist/`、`*.spec` 缓存，避免脏构建
- 输出：`dist\MedicationReminder.exe`（约 150–200 MB，含离线 OCR 模型，正常）

---

## 关于药品数据库 · About the Drug Database

### 为什么 drugs.db 不进 git？

`drugs.db` 由 openFDA API 数据合并生成，体积约 60 MB，不适合放入 git 历史。  
**正式发布版**的 `drugs.db` 已内置于 exe，同时作为 [Release 附件](https://github.com/SteveBohanMa/chiyaome/releases) 单独提供，供开发者使用。

### 为什么用手写中文药卡，而非直译美国标签？

美国 FDA 标签面向美国医疗体系的英语读者，直译后对中国老年患者存在安全隐患：

1. **适应症差异**：美国标签可能包含中国未批准的适应症，直译会产生误导
2. **警告措辞歧义**：某些警告在中国临床实践中优先级不同，逐字翻译反而危险
3. **剂量习惯不同**：美国常用 mg/kg 等体重换算，老人难以理解和使用
4. **可读性差**：美国标签内容冗长，不适合老年用户直接阅读

因此每种药品配有**人工审定的简洁中文卡片**，包含：用途、老年人专项警示、禁忌、建议服药时机。  
**请勿将此改为自动翻译美国标签。**

### 数据来源 · Data Sources

- 英文权威数据：[openFDA Drug API](https://open.fda.gov/apis/drug/)（美国 FDA，公有领域数据）
- 中文药卡：人工审定整理，仅供提醒参考，不构成医疗建议

---

## 技术架构 · Tech Stack

| 组件 | 技术 |
|------|------|
| 后端 | Python 3.12 + pywebview |
| 前端 | 原生 HTML / CSS / JS（无框架） |
| 离线 OCR | RapidOCR + onnxruntime |
| 语音提醒 | pyttsx3（调用 Windows SAPI5，完全离线） |
| 数据存储 | SQLite（药品库 `drugs.db`）+ JSON（用户数据 `~/.chiyaome/`） |
| 模糊中文匹配 | rapidfuzz |
| 系统托盘 | pystray |
| 打包 | PyInstaller → Windows exe |
| 开机自启 | Windows 注册表 HKCU（无需管理员） |

---

## 许可证 · License

[Apache License 2.0](LICENSE)

本项目使用来自 [openFDA](https://open.fda.gov/) 的公开数据（公有领域）。  
*This project uses public domain data from the [openFDA API](https://open.fda.gov/).*

---

> ⚠️ **再次声明：本工具仅做提醒，不构成医疗建议。用药请遵医嘱。**
