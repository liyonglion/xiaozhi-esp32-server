# 调研：小智带屏设备的会话屏幕呈现（票 #22）

日期：2026-10-26 · 分支：`research/screen-session-display` · 服务端：本仓库 main · 固件：`78/xiaozhi-esp32` main HEAD（浅克隆核实，行号以当日为准）

> 票中写"xinnan-tech/xiaozhi-esp32 固件仓库"有误：该仓库不存在。固件上游是 **78/xiaozhi-esp32**（虾哥），xinnan-tech 只有 server。下文固件证据均出自 78/xiaozhi-esp32。

## 结论速览

| 票中问题 | 一句话答案 |
|---|---|
| 1. 题目发上去长什么样 | 取决于固件风格：气泡板=追加一条 assistant 气泡（≤20 条历史）；**默认经典风格=底部单行字幕条，整条替换 + 跑马灯滚动**；OLED 同为单行；无任何截断 |
| 2. 答题期间题目常驻？ | **念完常驻**（tts stop 不清屏），但默认风格/OLED 只有一个文本槽：孩子开口回答的 stt 上屏会**整条顶掉题目**；气泡板不顶（历史保留） |
| 3. 单条文本长度上限 | 协议层**无上限、无截断**；可读性上限：经典彩屏单行 ≈15 汉字 / 30 个数字符号位（跑马灯），OLED 单行更窄。**题面（含题号/进度）建议 ≤20 字符** |
| 4. 固件/屏幕差异 | 四类：气泡彩屏（追加）/ 经典彩屏（单槽替换，默认）/ OLED 单行 / emote 动画屏（无常驻文本）。App 是第三方独立项目，自行渲染，不在固件仓库 |

## 服务端侧事实（本仓库，已逐行核实）

三个（且只有三个）服务端→屏幕的通道，全部汇到固件同一个 `SetChatMessage` 文本槽：

| 通道 | 函数 | 消息 | 文本处理 |
|---|---|---|---|
| 聊天上屏 | `send_display_message` — `core/handle/sendAudioHandle.py:351` | `{"type":"stt","text":…}` | **原样发送**，不去标点。唯一调用方：`unified_tool_handler.py:173`，工具执行前发 `% 函数名` |
| 用户回显 | `send_stt_message` — `sendAudioHandle.py:320` | `{"type":"stt","text":…}` + `{"type":"tts","state":"start"}` | 先 `get_string_no_punctuation_or_emoji` **去首尾标点/emoji**（textUtils.py:42，集合不含 `+ = ? × ÷`），然后置 `client_is_speaking=True` |
| TTS 字幕 | `send_tts_message` — `sendAudioHandle.py:284` | `{"type":"tts","state":"sentence_start","text":…}`；start/stop 无 text | text 过 `check_emoji`（textUtils.py:115，**去全部 emoji 和换行**）。仅 sentence_start 带文本 |
| 表情 | `textUtils.get_emotion` — `core/utils/textUtils.py:80` | `{"type":"llm","text":emoji,"emotion":"happy"}` | 每轮对话一次，LLM 首个非空分片触发（`connection.py:1201-1208`），受 hello `features.emoji` 门控（默认开） |

时序（一轮对话，服务端视角）：

```
ASR 终稿 → type=stt(用户文本) → type=tts start
        → LLM 流式首个分片 → type=llm(表情，一次)
        → 逐句 type=tts sentence_start(该句文本) + opus 音频帧
          （句子按 。！？!?；;\n 切分，core/providers/tts/base.py:295）
        → 末句后 type=tts stop（等音频发完、清 speaking 状态，sendAudioHandle.py:293-314）
工具调用：执行前 type=stt "% 函数名"（unified_tool_handler.py:173）
打断：    只发 type=tts stop + 清服务端队列（core/handle/abortHandle.py），无清屏消息
```

关键服务端事实：

- **服务端没有任何"清屏"消息**；也从不发送 `type=listen`（那是设备→服务端方向）。
- 本服务端（xinnan fork）**未实现** `glyph_push`（缺字补字形）与 `notify`（audio_url+subtitles）通道——已全仓 grep 确认为空。固件侧的这两条接收通道对我们不可用。
- `send_display_message` 与 `send_tts_message(conn,"sentence_start",text)` 都可以**无音频、即时**上屏——后者就是"无声字幕"，是服务端可自由调用的纯显示原语。

## 固件侧事实（78/xiaozhi-esp32）

### 消息分发（main/application.cc:604-748）

- `stt` → `SetChatMessage("user", text)`（:680-694，**仅当 text 字段是 string 才上屏**）
- `tts sentence_start` → `SetChatMessage("assistant", text)`（:664-678）
- `tts start/stop` → 只切设备状态（speaking/listening/idle），不碰文本（:644-663）
- `llm` → **只读 emotion 字段** → `SetEmotion(emotion)`（:695-701）；消息里的 emoji unicode 固件忽略
- `custom` → `SetChatMessage("system",…)`，需编译期 `CONFIG_RECEIVE_CUSTOM_MESSAGE`，**默认关**（:728-744）
- 入站 `listen` 消息不存在解析分支；固件不处理 `sentence_end`

### 渲染形态四类（由显示类 + `DISPLAY_STYLE` 编译选项决定，Kconfig.projbuild:923-947）

1. **微信气泡风格**（`CONFIG_USE_WECHAT_MESSAGE_STYLE`，如 atk-dnesp32s3-box；lcd_display.cc:388-743）：顶栏 + 可滚动聊天列。`MAX_MESSAGES` ESP32 系保留 **20 条**（P4 40 条），超出删最旧；气泡宽 ≤85% 屏宽，`LV_LABEL_LONG_WRAP` 自动换行，高度自适应——**无字符截断**；新消息自动滚到可见。role 区分左右对齐与底色（user 右绿 / assistant 左 / system 居中灰）；连续 system 消息折叠（新删旧）。
2. **经典风格（默认）**（lcd_display.cc:886-1150）：居中大表情 + **底部单行字幕条**。`SetChatMessage` **只有一个文本槽，整条替换**，role 不区分；默认 `LV_LABEL_LONG_SCROLL_CIRCULAR` 单行跑马灯（:1035-1065），可选多行编译项 `CONFIG_USE_MULTILINE_CHAT_MESSAGE`（:1011-1033）。空串隐藏底栏。
3. **OLED（SSD1306 128x64/32，如面包板）**（oled_display.cc:149-170）：同样**单槽替换**，`\n` 替换成空格，单标签循环滚动；14px 字号单行约 16 个数字位/6-7 个汉字。
4. **Emote 动画屏**（esp32-s3-box、桌面机器人 stackchan 等；emote_display.cc:202-217）：`SetChatMessage` 转成说话事件，文本只在说话动画里短暂出现，**无常驻聊天区**。另有纯表情/无屏板（electron-bot 等）无文本能力。

典型硬件：korvo2 v3 彩屏实测配置为 **ILI9341 320x240**（boards/espressif/esp32-s3-korvo-2-v3.0/config.h:47-48），默认经典风格，20px 字号。

### 常驻与清屏

- **tts stop 不清屏**：题目念完一直留在屏上。
- 清屏只发生在**回 Idle**（application.cc:1036-1046 `ClearChatMessages()`）与**进省电模式**（lvgl_display.cc:309-318）。自动对话模式 tts stop → Listening，**不清屏**——孩子整个答题期间上一条文本可见。
- 单槽板的致命交互：孩子回答 → 服务端 `send_stt_message` → `SetChatMessage("user",答案)` **整条替换掉题目**。气泡板则是追加，题目气泡保留在历史里。
- 空闲超时：服务端 `no_voice_close_connect`（receiveAudioHandle.py:119-146）默认 120s 无声即关连接 → 设备回 Idle → 清屏。练习会话若指望题目长期常驻，120s 内必须有语音活动。

### 字符集（关键风险）

- 文本字体 Noto Sans，字符集分 basic（ASCII+Latin-1+UI 静态串）/ common（+大字库）。**数字 0-9、`+ - = ? × ÷` 全部安全**（ASCII/Latin-1，basic 必有）。
- **汉字**在只带 basic 字库的固件上缺字，需服务端 `glyph_push` 补字形——本服务端未实现。装了 assets 分区大字库的设备（报告 common）则安全。**目标真机是否缺汉字必须在真机上验证一次**（让设备说/显示一句含"第题等于"的话看屏）。
- 文本无彩色 emoji 回退链，**题目文本里禁用 emoji**（且服务端 tts 文本本来就会被 `check_emoji` 剥掉）。
- 服务端没有任何画屏/GUI 帧/富文本通道（二进制帧仅 opus 音频；MCP 屏幕工具只有亮度/主题/快照）——与地图 #20 已查证结论一致。

### "小智 App"

固件仓库无 App 代码。README 相关项目列出第三方客户端（TOM88812/xiaozhi-android-client、py-xiaozhi 等），各自实现聊天渲染，走同一 WebSocket 协议；其 UI 差异不在本次一手源码范围内（未深挖，列为不确定点）。

## 对"题目上屏"的硬约束

1. **通道**：题面只能进 `stt`（send_display_message，原样文本）或 `tts sentence_start`（无声字幕原语）。不要指望 custom/notify/glyph_push/llm/画屏。
2. **题面格式**：`第3题 12+5=?` 这类"数字+`+ - = ? × ÷`+少量汉字"。**总长 ≤20 字符**（含题号与进度）；一行写完，不用换行（OLED/经典板换行会被压成空格或跑马灯）。进度别占太多位：建议 `3/10` 而非"第3题，共10题"。
3. **汉字缺字风险**：真机验证目标设备 assets 字库；若缺，题面退化为纯符号式 `3/10 12+5=?`（ASR 判题不受影响，读题音频走 TTS 不经屏幕）。
4. **常驻策略**：题目念完即常驻（sentence_start 天然"读题与上屏并行"——朗读的句子就是字幕）。但默认风格板会被**孩子的 stt 回显顶掉**：要么接受"答题时题目被答案替换"，要么服务端在答案上屏后**补发一条无声 `sentence_start`（紧凑题面）**恢复常驻——服务端完全可控，成本一条消息。练习工具（start_practice/submit_answer）内可实现，不改固件。
5. **时序建议**（单槽板视角，按序）：
   ```
   start_practice 工具执行 → stt "% start_practice"（工具先例自动上屏）
   → 朗读引导+题面（TTS 队列，逐句字幕）
   → 末句 = 紧凑题面（"3/10 12+5=?"）→ 念完常驻
   → 孩子答题（stt 回显顶掉题面，可接受/或）
   → 判题+反馈朗读（字幕=反馈句）
   → 反馈完补发无声 sentence_start 紧凑题面（题目回屏，等下一答）
   ```
6. **表情**：可与题面并用（不同控件）。练习中可让 LLM 首句带 thinking/encouraging 表情，但注意每轮只发一次、且 emotion 只认固件内置枚举名。
7. **会话保活**：默认 120s 无声即关连接并清屏。练习会话要么保证节奏（读题+等待答案 < 120s，一般成立），要么调大 `close_connection_no_voice_time`。

## 剩余不确定点

- **目标真机是哪块板/哪种风格未定**：若为气泡板，第 4 条"顶掉"问题不存在；若为 OLED/emote 屏，题面可读性大幅下降。建议真机演示前用一条 `send_display_message` 实测。
- **真机汉字字库**（basic vs common）未验证，见约束 3。
- App 端（第三方客户端）渲染差异未查——协议相同，App 多为完整聊天列表，题目常驻性预计好于单槽板，未一手核实。
- 固件行号随上游演进会漂移；引用按 2026-10-26 main HEAD。

## 关联

- 票 #22（本调研）· 地图 #20 · 后继 #23（实施切片）
- 服务端证据：本仓库 `main/xiaozhi-server/core/handle/sendAudioHandle.py`、`core/connection.py`、`core/providers/tools/unified_tool_handler.py`、`core/utils/textUtils.py`、`core/handle/abortHandle.py`、`core/providers/tts/base.py`
- 固件证据：78/xiaozhi-esp32 `main/application.cc`、`main/boards/common/lcd_display.cc`、`oled_display.cc`、`emote_display.cc`、`lvgl_display.cc`、`main/Kconfig.projbuild`
