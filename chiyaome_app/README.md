# 吃药么 · 新界面版（离线 / 响铃 / 语音）

> ⚠️ 重要：请使用 **Python 3.12**（到 python.org 下载，安装第一屏勾选 “Add Python to PATH”）。
> 不要用 Python 3.14：离线 OCR 依赖的 onnxruntime 暂无 3.14 安装包，会装不上。
> 已安装多个版本也没关系，run.bat / build.bat 会自动优先选用 3.12。


把设计稿 UI 应用到你的应用，并新增：**离线拍照识别、到点系统响铃、离线语音播报、后台提醒（最小化也能弹出）**。
保留原数据格式：settings.json / medications.json / history.json。

## 文件
- app.py            后端 + 窗口 + 后台提醒线程
- ocr_parse.py      离线 OCR(RapidOCR) + 规则解析
- web/index.html    界面（与设计稿一致，数据驱动）
- alarm.wav         提示音
- chiyaome.ico      图标
- build.bat / requirements.txt

## 本机试运行（Windows，Python 3.12）
```
pip install -r requirements.txt
python app.py
```
首次自带示例药品。到「自定义」页可：开关声音/语音、点“测试提醒”看效果。

## 打包成 exe
双击 build.bat。生成 dist\MedicationReminder.exe（含离线 OCR 模型，约 150–200MB 属正常）。

## 离线拍照识别
默认离线：本地 RapidOCR 识别文字 + 规则解析出药名/剂量/服用时间，**完全不需要联网**，
适合老人无网络的场景。识别为自动推测，建议子女核对后再确认。
（可选）在「自定义」开启“联网识别”并填 Anthropic Key，可用 Claude 提高准确度。

## 响铃与语音（离线）
- 响铃：Windows 自带 winsound 播放 alarm.wav，循环直到老人点“已吃/没吃”。
- 语音：pyttsx3 调用 Windows 自带 SAPI5 语音（离线）。中文播报需系统装有中文语音
  （Win10/11 多数自带“Microsoft Huihui”，没有可在 设置→时间和语言→语音 添加中文）。
- 后台线程驱动，程序最小化时也会把窗口弹到最前并响铃播报。

## 沿用旧数据
把旧的 medications.json/settings.json/history.json 复制到 C:\Users\你\.chiyaome\ 即可。

## 用回你自己的 Claude 提示词
改 app.py 的 parse_online() 即可，返回字段：name/dose/type(pill|skin)/timings[]/note。
