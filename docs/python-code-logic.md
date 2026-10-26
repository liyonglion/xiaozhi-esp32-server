# xiaozhi-server（Python 服务端）代码逻辑详解

> 路径约定：除特别标注外，所有 `文件:行号` 引用均相对于 `main/xiaozhi-server/`；涉及 Java 端时使用仓库根相对路径 `main/manager-api/...`。
> 本文基于 2026-10 的 main 分支代码（SERVER_VERSION 0.9.7）。

## 目录

1. [总览：一句话生命周期](#1-总览)
2. [启动流程（app.py）](#2-启动流程)
3. [配置体系](#3-配置体系)
4. [WebSocket 服务端与鉴权](#4-websocket-服务端)
5. [Connection 生命周期](#5-connection-生命周期)
6. [消息处理与一句话完整调用链](#6-消息处理)
7. [providers 抽象与加载机制](#7-providers-抽象)
8. [与 manager-api 的全部交互（重点）](#8-与-manager-api-的交互)
9. [HTTP 服务（OTA / 视觉分析）](#9-http-服务)
10. [插件机制 plugins_func](#10-插件机制)
11. [MQTT 模式](#11-mqtt-模式)
12. [关键文件总表](#12-关键文件总表)

---

## 1. 总览

设备（ESP32）开机 → 向 HTTP 服务（8003 端口）请求 OTA 接口拿到 WebSocket 地址和 token → 连接 WebSocket（8000 端口 `/xiaozhi/v1/`）→ Python 为每个连接创建 `ConnectionHandler`，按设备 MAC 从 manager-api 拉取该设备专属的 agent 配置（LLM/TTS/ASR/提示词等）→ 之后语音对话全在这条 WebSocket 上进行：Opus 音频上行 → VAD 断句 → ASR 转文字 → 意图/LLM → TTS 合成 → Opus 音频下行。对话内容异步上报回 manager-api 供管理后台展示。

进程级组件（VAD/共享 ASR/LLM/Intent/Memory）在启动时创建一次；**TTS 永远是每连接独立实例**。

## 2. 启动流程

### 2.1 入口

- 入口 `app.py:148-152`：`asyncio.run(main())`，捕获 KeyboardInterrupt。启动命令就是 `python app.py`。
- **没有 `-a` / `--api` 命令行参数**（全仓 grep 仅 `performance_tester/` 测试工具有 argv 处理）。是否走 API（智控台）模式完全由配置文件决定：`data/.config.yaml` 中是否存在 `manager-api.url`。

### 2.2 main() 启动序列（app.py:46-145）

1. `check_ffmpeg_installed()`（app.py:47，实现在 core/utils/util.py:157）。
2. `config = await load_config()`（app.py:48）。注意模块级 `logger = setup_logging()`（app.py:15）在 import 时就会触发一次配置检查（config/logger.py:49-57 → config/settings.py:10-34）。
3. **auth_key 三级优先级**（app.py:53-62）：`server.auth_key` > `manager-api.secret` > `uuid4().hex` 随机生成；写回 `config["server"]["auth_key"]`。该 key 用于 HMAC token 签发（WebSocket 鉴权、OTA 下发的 token）。
4. `monitor_stdin` 任务（app.py:40-44, 65）：消费回车，防止 stdin 阻塞。
5. 全局 GC 管理器：`get_gc_manager(interval_seconds=300).start()`（app.py:68-69）。
6. **启动两个 server**：
   - `WebSocketServer(config)` + `asyncio.create_task(ws_server.start())`（app.py:72-73）；
   - `SimpleHttpServer(config)` + `ota_task`（app.py:75-76）。
7. 日志输出：非 API 模式才打印 OTA 地址（app.py:78-85）；打印视觉分析地址（app.py:86-90）；校验并改写 `mcp_endpoint`（`ws://.../mcp/?token=` → `/call/`，app.py:91-101，校验函数 util.py:576-598）；打印 WebSocket 地址 `ws://ip:port/xiaozhi/v1/`（app.py:104-113）。
8. `await wait_for_exit()`（app.py:125；信号处理 app.py:18-37，Unix 用 `loop.add_signal_handler`）。
9. finally 清理：停 GC → cancel stdin/ws/ota 任务 → `asyncio.wait(..., timeout=3.0)`（app.py:129-145）。

### 2.3 端口

| 服务 | 绑定 | 默认端口 | 代码位置 |
|---|---|---|---|
| WebSocket | `server.ip`（默认 0.0.0.0） | `server.port` = **8000** | core/websocket_server.py:73-74；config.yaml:11-12 |
| HTTP（OTA/视觉） | `server.ip` | `server.http_port` = **8003** | core/http_server.py:39-40；config.yaml:13-14 |
| manager-api（被调用方） | — | 8002，context path `/xiaozhi` | config_from_api.yaml:23 |

## 3. 配置体系

### 3.1 三份配置文件的关系

- `config.yaml`（项目根，1176 行）：全量默认配置。含 server（:9-43）、log（:44-56）、exit_commands（:84）、`xiaozhi` hello 报文模板（:88-97，即服务端发给设备的 server hello）、wakeup_words（:107-117）、mcp_endpoint（:121）、context_providers（:126-129）、plugins（:132-187）、voiceprint（:189-199）、prompt 角色提示词（:204）、prompt_template（:220）、system_error_response（:223）、end_prompt（:226-230）、selected_module（:233-251）、Intent（:254-291）、Memory（:293-356）、ASR（:358-604）、VAD（:605-611）、LLM（:613-744）、VLLM（:746-769）、TTS（:770-1175）。
- `config_from_api.yaml`：API（智控台）模式的最小模板，只有 `server`（:8-19）+ `manager-api.url/secret`（:20-25）+ `prompt_template`（:26）。用法：复制到 `data/` 改名 `.config.yaml`（文件头注释 :1-7）。
- `data/.config.yaml`：**真正生效的用户配置**，必须存在（config/settings.py:17-21 否则 FileNotFoundError）。

### 3.2 加载逻辑（config/config_loader.py）

`load_config()`（:26-52）：

1. 先查全局缓存 `cache_manager.get(CacheType.CONFIG, "main_config")`（:31-33）。
2. 读默认 `config.yaml`（:35,39）与 `data/.config.yaml`（:36,40）。
3. **模式判定**（:42-46）：`custom_config["manager-api"]["url"]` 非空 → `get_config_from_api_async()`（API 模式）；否则 `merge_configs()`（本地模式，深合并、custom 优先，:154-182）。
4. `ensure_directories()`（:47-48）创建 log/tmp/models 目录；结果写缓存（:51）。

**API 模式**（`get_config_from_api_async`，:55-88）：

1. `init_service(config)`（:58）→ `ManageApiClient(config)` 单例（config/manage_api_client.py:29-35）。
2. `await get_server_config()`（:61）→ **POST `{manager-api.url}/config/server-base`**（manage_api_client.py:224-227），拿回全局 server 配置（含 selected_module、各模块密钥、prompt 等）。
3. 置 `read_config_from_api=True`（:65）；保留本地 `manager-api` url/secret（:66-69）。
4. **server 块以本地为准**（:72-83）：ip/port/http_port/vision_explain/auth_key 用本地覆盖，且本地显式配置的 `server.websocket` 可覆盖智控台下发值（:81-83）。
5. `prompt_template` 若服务端没下发则用本地（:86-87）。

**每设备差异化配置**（`get_private_config_from_api`，:91-110）：`asyncio.gather` 并发 `get_agent_models`（POST `/config/agent-models`，body `{macAddress, clientId, selectedModule}`）+ `get_correct_words`（POST `/config/correct-words`，body `{macAddress}`）；`DeviceNotFoundException`/`DeviceBindException` 原样抛出（:102-105），correct_words 附加进结果（:108-109）。

混用检查：`check_config_file()`（config/settings.py:10-34）发现 `.config.yaml` 既像智控台配置又含 selected_module 时直接报错（:27-33）。

### 3.3 logging 及可选开关

- logging（config/logger.py）：loguru，`SERVER_VERSION = "0.9.7"`（:9）；格式/级别/目录全部来自 `config.log`（:70-87）；控制台 + 文件双输出（:93, 100-112），文件 10MB 轮转、保留 30 天；`create_connection_logger` 按模块串绑定（:118-121，模块串由 `build_module_string` :26-36 生成，如 VAD+ASR+LLM+TTS 各取前两字符）。
- **Python 端没有 prometheus**；指标体系在 manager-api 侧。
- 常用可选开关（config.yaml）：`enable_wakeup_words_response_cache`（:66）、`enable_greeting`（:68）、`enable_stop_tts_notify`（:70）、`enable_websocket_ping`（:74）、`tts_audio_send_delay`（:78-82）、`close_connection_no_voice_time`（:60）、`tts_timeout`（:62）、`tool_call_timeout`（:64）、`delete_audio`（:59）。

## 4. WebSocket 服务端

### 4.1 WebSocketServer 构造（core/websocket_server.py:42-69）

- `initialize_modules(...)`（:47-56；实现 core/utils/modules_initialize.py:9-98）按 `selected_module` 是否含 VAD/ASR/LLM/Memory/Intent 创建**进程级共享实例**；`init_tts=False`（:53）——**TTS 永远每连接实例**。
- 鉴权配置（:63-69）：`server.auth.enabled`、`allowed_devices` 白名单、`AuthManager(secret_key=auth_key, expire_seconds)`。

### 4.2 监听与握手

- `start()`（:71-83）：`websockets.serve(self._handle_connection, host, port, process_request=self._http_response, ping_interval=None)`。非升级请求（浏览器直接访问）返回 200 "Server is running"（:150-157）。

### 4.3 连接处理 `_handle_connection`（:85-148）

1. **device-id 提取**（:87-110）：优先 header `device-id`；缺失则解析 URL query（`device-id`/`client-id`/`authorization` 均可放 query）。无 device-id → 发提示文本并关闭。
2. **鉴权** `_handle_auth`（:114-115；实现 :210-231）：
   - `auth_enable=False` 直接放行（:212）；
   - 白名单设备跳过 token 校验（:216-218）；
   - 否则要求 `Authorization: Bearer <token>`（:221-225），`AuthManager.verify_token(token, client_id, username=device_id)`（:227-229）；失败抛 `AuthenticationError` → 回复"认证失败"并 close（:116-119）。
   - **这一步不调用 manager-api**。token 是 OTA 接口用同一 auth_key 签发的（见 §9）；设备是否注册/绑定，在后续拉 agent 配置时由业务码 10041/10042 判定。
3. **AuthManager**（core/auth.py:13-72）：HMAC-SHA256 签名 `"{client_id}|{username}|{ts}"`，token 形如 `sig.ts`（:36-50）；verify 拆分、比对过期时间与 `hmac.compare_digest`（:52-72）。MQTT 场景同一三元组映射为 client_id/username/password（类注释 :14-19）。
4. **创建 ConnectionHandler**（:121-129）：传入 config + 共享的 `_vad/_asr/_llm/_memory/_intent` + server 自身引用（用于 serverMessageHandler 触发 update_config）。
5. `await handler.handle_connection(websocket)`（:131）；finally 三重兜底强制 close（:134-148）。

### 4.4 配置热更新 `update_config`（:159-208）

重新 `get_config_from_api_async`（:168）→ `check_vad_update`/`check_asr_update`（:174-175，比较 type 是否变化）→ 替换 config → `initialize_modules` 重建共享组件（:182-203）。由 WebSocket 文本消息 `{"type":"server","action":"update_config"}` 触发（core/handle/textHandler/serverMessageHandler.py:38-77）。

## 5. Connection 生命周期

core/connection.py（1853 行）是整个服务的中枢。

### 5.1 构造（:80-201）

- `self.config = copy.deepcopy(config)`（:91）——每连接独立配置副本，供 per-device 覆盖；
- `session_id = uuid4`（:92）；`read_config_from_api`（:102）；
- 绑定状态 `need_bind/bind_completed_event/bind_code`（:96-100）；
- 客户端状态 `client_abort/client_is_speaking/client_listen_mode/client_aec`（:116-119）；
- `ThreadPoolExecutor(max_workers=5)`（:124）；
- 上报队列 `report_queue` + 上报开关 `report_asr_enable/report_tts_enable`（:127-131，API 模式默认开）；
- VAD/ASR 私有缓冲（:147-164）；`dialogue`（:166）；IoT 描述符表（:174）；`cmd_exit`（:177）；`timeout_seconds = close_connection_no_voice_time + 60`（:184-186）；`PromptManager`（:196）；通话状态 `calling/incoming_call`（:199-201）。
- 模块导入时即 `auto_import_modules("plugins_func.functions")`（:52）加载全部插件。

### 5.2 handle_connection（:203-276）

- 保存事件循环 `self.loop`（:206）；headers 与真实 IP（`x-real-ip`/`x-forwarded-for` 优先，:209-216）；`device_id`（:221）。
- **MQTT 网关识别**：请求路径以 `?from=mqtt_gateway` 结尾则 `conn_from_mqtt_gateway=True`（:227-230）。
- 启动两个后台协程：超时检查 `_check_timeout`（:237；实现 :1720-1749，每 10s 检查静默超时并 close）、AEC 缓存清理（:240；:1751-1769，30s 周期 / 120s TTL）。
- `welcome_msg = config["xiaozhi"]`（server hello 模板）并注入 `session_id`（:242-243）；`sample_rate` 默认取该块 `audio_params.sample_rate`（:246）。
- **`asyncio.create_task(self._background_initialize())`（:250）**：异步初始化不阻塞主循环。
- 主循环 `async for message in websocket: await self._route_message(message)`（:253-254）。
- finally → `_save_and_close(ws)`（:265-269）。

### 5.3 消息路由 `_route_message`（:348-383）

- **绑定门闩**：`bind_completed_event` 未置位时最多等 1s（:351-355），超时或 `need_bind=True` 则丢弃消息并周期性（60s）播报绑定提示（`_discard_message_with_bind_prompt` :337-346 → `check_bind_device`，receiveAudioHandle.py:144-179，用 `config/assets/bind_code*.wav` 逐位播报绑定码）。
- 文本消息 → `handleTextMessage`（:368-369）。
- 二进制音频：
  - MQTT 网关包（≥16 字节）先 `_process_mqtt_audio_message`（:375-378；实现 :385-415：解析 8-12 字节 timestamp、去 16 字节头、AEC 处理 `_apply_aec` :417-530——互相关延迟估计 + Wiener/谱减法的频域回声消除）；
  - 统一在入口做 Opus→PCM 解码（`_decode_opus_packet` :532-551，每连接独立 `opuslib_next.Decoder(16000, 1)`），PCM 入 `asr_audio_queue`（:383）。

### 5.4 后台初始化：拉取哪些配置

`_background_initialize`（:790-798）= `_initialize_private_config_async` + 线程池 `_initialize_components`。

**`_initialize_private_config_async`（:800-957）**——本地模式直接置 `need_bind=False` 放行（:802-805）；API 模式：

1. `get_private_config_from_api(config, device-id, client-id||device-id)`（:808-812）→ POST /config/agent-models + POST /config/correct-words。
2. 业务码异常映射：10041 设备不存在 / 10042 未绑定（带 bind_code）→ `need_bind=True`（:820-826）。
3. **per-device 覆盖合并**到 `self.config`：VAD（:839-846）、ASR（:847-851）、TTS（:852-857）、LLM（:858-863）、VLLM（:864-868）、Memory（:869-874）、Intent + 插件配置（:875-905：智控台下发的 `plugins` 字典反序列化、模块名经 `module_func_map` 展开为函数名、写回 `Intent[...].functions`）、`prompt`（:906-907，agent 的 system prompt）、`voiceprint`（:909-910）、`summaryMemory`（:911-912，长期记忆摘要）、`device_max_output_size`（:913-914）、`chat_history_conf`（:915-916，0=不上报/1=仅文本/2=文本+音频）、`mcp_endpoint`（:917-918）、`context_providers`（:919-920）、`correct_words` 注入 TTS 配置（:922-927）。
4. 线程池中 `initialize_modules`（:931-942）按需重建实例并赋值（:946-957）。

**`_initialize_components`（:606-657，跑在线程池）**：

- TTS 初始化（:608-609；失败兜底 `DefaultTTS`，core/providers/tts/default.py）；`tts.open_audio_channels(self)`（:611-613）启动 TTS 两个消化线程。
- `need_bind` 时到此为止（:614-616）。
- 快速 system prompt（:623-630）；VAD/ASR 赋值（:633-636；`_initialize_asr` :757-772——公共 ASR 是 LOCAL 类型则共享，远程（如 websocket 流式）则每连接新实例）；声纹 `VoiceprintProvider`（:639）；`asr.open_audio_channels`（:641-643）；`_initialize_memory`（:646；:959-999——`memory.init_memory(role_id=device_id, llm, summary_memory, save_to_file=not read_config_from_api)`，可配专用总结 LLM :979-995）；`_initialize_intent`（:648；:1001-1048——判定 `intent_type`（function_call/intent_llm/nointent）、intent_llm 可配专用 LLM、创建 `UnifiedToolHandler` 并异步 `_initialize()`）；`_init_report_threads`（:650；:733-744 启动聊天上报线程）；`_init_prompt_enhancement`（:652；:659-671——注入时间/日期/农历/位置/天气/上下文源后重建增强 system prompt，模板为 `agent-base-prompt.txt` + jinja2，core/utils/prompt_manager.py:249-315）；`_inject_tool_call_fewshot`（:654；:673-731，仅 function_call 模式注入 few-shot）。

### 5.5 服务端 → 设备的消息类型

| 消息 | 位置 |
|---|---|
| `{"type":"hello", ...xiaozhi块+session_id}`（server hello） | helloHandle.py:61（收到客户端 hello 后回） |
| `{"type":"stt","text":...}`（回显识别文本） | sendAudioHandle.py:320-348 |
| `{"type":"tts","state":"start"/"sentence_start"/"stop","text":...}` | sendAudioHandle.py:284-317 |
| 二进制 Opus 帧（裸包或 MQTT 网关 16 字节头包） | sendAudioHandle.py:263-281 |
| `{"type":"iot","commands":[{name,method,parameters}]}` | iot_executor.py:111-133 |
| `{"type":"server","status":...,"content":{"action":...}}` | serverMessageHandler.py / connection.py:558-604 |
| `{"type":"pong","timestamp":...}` | pingMessageHandler.py:36-42 |
| MCP payload（`{"type":"mcp",...}`） | core/providers/tools/device_mcp（mcp_handler.py:238） |

### 5.6 关闭路径

- `_save_and_close`（:278-335）：两个守护线程——① `chat_history_conf != 0` 时调 `generate_and_save_chat_title(session_id)`（:285-301；**POST /agent/chat-title/{session_id}/generate**）；② memory 非空时 `memory.save_memory(dialogue, session_id)`（:303-325；mem_local_short 在 API 模式下转调 **POST /agent/chat-summary/{session_id}/save**，mem_local_short.py:190-193）。随后立即 `close()`。
- `close()`（:1543-1656）：释放 VAD 连接态、opus 解码器、超时/AEC 任务、`func_handler.cleanup()`（关 server_mcp 与 mcp_endpoint 连接）、`stop_event.set()`、`clear_queues()`（:1662-1690）、关 websocket、`tts.close()/asr.close()`、线程池 shutdown。
- `handle_restart`（:558-604）：回确认消息后 `subprocess.Popen([sys.executable, "app.py"], start_new_session=True)` + `os._exit(0)`（:581-588）。

## 6. 消息处理

### 6.1 文本消息分发（注册表 + 策略模式）

- 入口 `handleTextMessage(conn, message)`（textHandle.py:17-19）→ 全局 `TextMessageProcessor.process_message`（textMessageProcessor.py:17-44）：JSON dict 按 `type` 查注册表；纯数字/非 JSON 原样回显。
- 注册表（textMessageHandlerRegistry.py:22-47）注册 7 个 handler：`hello / abort / listen / iot / mcp / server / ping`。抽象基类 textMessageHandler.py:9-21（`handle()` + `message_type` 属性）。

各 handler 职责：

| 文件 | 职责 |
|---|---|
| helloMessageHandler.py:10-18 | → helloHandle.handleHelloMessage：采纳客户端 audio_params（helloHandle.py:44-49）、features（mcp→建 MCPClient；aec→client_aec :57-59）、发送 server hello（:61）、异步发 MCP initialize（:63-65）。另有唤醒词缓存回复 checkWakeupWords（:68-126）与后台刷新（:129-161） |
| abortMessageHandler.py:8-16 | → abortHandle：`client_abort=True`、`clear_queues()`、发 `tts stop` |
| listenMessageHandler.py:22-116 | 拾音状态机：`mode`；`state=start`→`reset_audio_states`；`state=stop`→流式 ASR 发 stop / 非流式直接 `handle_voice_stop`；`state=detect`+`text`→`[device_call]` 来电接听分支（:65-94）、唤醒词分支（enable_greeting 控制，:96-110）、普通文本→`enqueue_asr_report`+`startToChat`（:111-116） |
| iotMessageHandler.py:11-22 | descriptors→注册 IoT 工具（iot_handler.py:15-87）；states→更新属性值 |
| mcpMessageHandler.py:11-23 | payload→device_mcp.handle_mcp_message（mcp_handler.py:118） |
| serverMessageHandler.py:11-92 | API 模式下用 `manager-api.secret` 验签（:20-36）；`action=update_config`→`conn.server.update_config()`；`action=restart`→`conn.handle_restart` |
| pingMessageHandler.py:11-45 | `enable_websocket_ping` 开启才回 pong |

### 6.2 一句话完整调用链（说 → 听到回答）

1. **Opus 解码入队**：connection.py:381-383。
2. **VAD**：`handleAudioMessage`（receiveAudioHandle.py:17-34）→ `conn.vad.is_vad`（silero.py:55-114：512 样本窗 ONNX 推理、双阈值 + 3 帧滑动窗确认、静默超 `min_silence_duration_ms` 置 `client_voice_stop=True`）；`just_woken_up` 时短暂忽略（:21-26）；服务端 AEC 下检测到人声自动打断（:28-30）；`no_voice_close_connect` 空闲告别（:32；:106-130）。
3. **ASR 缓存**：`conn.asr.receive_audio`（asr/base.py:61-81），非流式模式在 `client_voice_stop` 时凑够 15 帧调 `handle_voice_stop`。
4. **识别**：`handle_voice_stop`（asr/base.py:84-175）并发声纹识别（:103-113），`speech_to_text_wrapper`（:268-320，落盘/临时文件/直传三策略）→ 子类 `speech_to_text`。结果若含说话人则包成 `{"speaker":...,"content":...}` JSON（:145, :177-184）。
5. **进入对话**：`enqueue_asr_report` + `await startToChat(conn, enhanced_text)`（:168-170）。
6. **startToChat**（receiveAudioHandle.py:43-103）：解析 speaker JSON（:48-72）→ need_bind 分流（:74-76）→ `max_output_size` 字数限流（:79-84）→ 自动模式下先打断（:87-88）→ **意图识别 `handle_user_intent`**（:91）→ 未被意图消费则 `send_stt_message`（回显 stt，:98）→ `conn.executor.submit(conn.chat, actual_text)`（:103）。
7. **意图**：intentHandler.py:20-50：`check_direct_exit`（exit_commands 命中直接 close）；`checkWakeupWords`；`function_call` 模式直接返回 False 走主 LLM；`intent_llm` 模式 `analyze_intent_with_llm`（intent_llm.py:142-296，带 md5 缓存、函数清单 prompt、音乐/HA 设备注入）→ `process_intent_result`（:83-230：`continue_chat` 放行 / `result_for_context` 用时间地点上下文直接答 / 真实工具经 `func_handler.handle_llm_function_call` 在线程池执行，REQLLM 结果再由 `intent.replyResult` 生成口语回复）。
8. **LLM 主循环 `conn.chat`**（connection.py:1055-1395）：
   - depth==0 生成 `sentence_id`、写入 user 消息、向 TTS 队列投 `FIRST/ACTION` DTO（:1062-1073）；
   - 记忆查询 `memory.query_memory`（:1113-1119）；说话人首次注入 system（:1121-1127）；
   - function_call 模式取 `func_handler.get_functions()` 并追加 `direct_answer` 虚拟工具（:1098-1107，定义 :60-76）；
   - `llm.response_with_functions`（openai 实现 llm/openai/openai.py:138 起，流式 tools）或 `llm.response`（:92-137，流式、自动剥 `<think>`、按域名禁思考模式 :13-19, 82-90）；
   - 流循环（:1156-1220）：文本增量直接进 TTS 队列（:1210-1220）；工具调用增量合并（`_merge_tool_calls` :1826-1852）；`direct_answer` 参数流式提取实时送 TTS（:1177-1197，提取器 :1771-1802、清 JSON 垃圾 :1804-1824）；首轮抓 emoji 情绪（:1201-1208）；
   - 工具执行（:1241-1372）：兼容 `<tool_call>` 文本协议（:1244-1268）；多工具并行 `run_coroutine_threadsafe(func_handler.handle_llm_function_call)`，超时 `tool_call_timeout`（:1329-1368）；工具调用与结果均 `enqueue_tool_report`（:1336, :1356）；
   - `_handle_function_result`（:1397-1503）：RESPONSE/NOTFOUND/ERROR→直接 `tts_one_sentence` 播报（:1402-1415）；REQLLM→写 assistant(tool_calls)+tool 消息后 `self.chat(None, depth+1)` 递归（:1469-1503，MAX_DEPTH=5 强制总结 :1082-1093）；RECORD→只记历史不调 LLM（:1423-1467）；
   - 收尾：assistant 文本入 dialogue、`store_tts_text`（:1374-1378），投 `LAST/ACTION` DTO（:1380-1387）。
9. **TTS 文本线程**：`TTSProviderBase.tts_text_priority_thread`（tts/base.py:371-412）：过滤旧 sentence_id（:379-380）；FIRST 重置状态（:381-387）；TEXT 按 `_get_segment_text` 标点分段（:486-523，首句用逗号级标点提速）；`to_tts_stream`（:126-194，Markdown 清理 + correct_words 替换 + 重试 5 次）→ 子类 `text_to_speak` → `audio_bytes_to_data_stream` 转 Opus → `handle_opus` 入 `tts_audio_queue`；LAST 冲刷剩余文本（:400-404）。
10. **TTS 音频线程**：`_audio_play_priority_thread`（:414-472）：非 MIDDLE 帧做 TTS 上报切档（:439-454）；`run_coroutine_threadsafe(sendAudioMessage(...))`（:461-465）。
11. **音频下发**：sendAudioHandle.py:21-55 → FIRST 发 `tts/sentence_start`（:30-43）→ `sendAudio`（:119-147）经 `AudioRateController` 精确 60ms/包节流（:150-260，前 5 包预缓冲直发）→ `_do_send_audio`（:263-281）：普通连接裸 `websocket.send(opus)`；MQTT 网关连接打 16 字节头（:84-116，含 AEC 参考帧缓存）→ LAST 发 `tts/stop` 并视情况 close（:52-55）。
12. **上报**：TTS 文本/音频由 `enqueue_tts_report`（reportHandle.py:160-185）经 `report_queue` → `_report_worker`（connection.py:1505-1526）→ `_process_report`（:1528-1537）→ `report()`（reportHandle.py:25-56，PCM/Opus 转 WAV base64）→ **POST /agent/chat-history/report**。

## 7. providers 抽象

### 7.1 抽象基类

| 类 | 文件 | 关键契约 |
|---|---|---|
| `ASRProviderBase` | core/providers/asr/base.py:31 | `speech_to_text`（:322-336 抽象）；`interface_type` STREAM/NON_STREAM/LOCAL；基类自带线程/断句/落盘/声纹并发 |
| `TTSProviderBase` | core/providers/tts/base.py:34 | `text_to_speak`（:263-265 抽象）；`interface_type` DUAL_STREAM/SINGLE_STREAM/NON_STREAM；基类自带双队列双线程、分段、替换词、上报 |
| `LLMProviderBase` | core/providers/llm/base.py:7 | `response`（流式生成器）+ 默认 `response_with_functions`（不支持工具时退化为纯文本） |
| `MemoryProviderBase` | core/providers/memory/base.py:8 | `save_memory`/`query_memory`、`init_memory` |
| `IntentProviderBase` | core/providers/intent/base.py:9 | `detect_intent`、`set_llm` |
| `VADProviderBase` | core/providers/vad/base.py:5 | `is_vad` |

### 7.2 实例化机制（约定优于配置的工厂）

各自的 `create_instance(class_name, *args)` 拼模块路径后 `importlib.import_module` 取固定类名：

- TTS：`core.providers.tts.<type>.TTSProvider`（core/utils/tts.py:33-41）
- LLM：`core.providers.llm.<type>.<type>.LLMProvider`（core/utils/llm.py:15-23）
- ASR：`core.providers.asr.<type>.ASRProvider`（core/utils/asr.py:16-24）
- VLLM：`core.providers.vllm.<type>.VLLMProvider`（core/utils/vllm.py:15-23）
- intent/memory/vad 同理（core/utils/intent.py、memory.py、vad.py）

`<type>` 取自配置项的 `type` 字段（没有则用配置键名本身），见 modules_initialize.py:39-109；统一入口 `initialize_modules`（:9-98）。

### 7.3 支持的 provider 清单（按 type 字段）

- **ASR**（16）：fun_local、fun_server、sherpa_onnx_local、doubao、doubao_stream、tencent、aliyun、aliyun_stream、baidu、openai、vosk、qwen3_asr_flash、xunfei_stream、aliyunbl_stream
- **LLM**（9）：openai、AliBL、coze、dify、fastgpt、gemini、homeassistant、ollama、xinference
- **TTS**（21）：edge、doubao、huoshan_double_stream、siliconflow、cozecn、openai、fishspeech、gpt_sovits_v2、gpt_sovits_v3、minimax_httpstream、aliyun、aliyun_stream、tencent、custom、paddle_speech、index_stream、alibl_stream、alibl、xunfei_stream、default
- **VAD**（1）：silero
- **Memory**（5）：nomem、mem_local_short、mem0ai、powermem、mem_report_only
- **Intent**（3）：nointent（恒 continue_chat）、function_call（恒 continue_chat，工具选择交给主 LLM 的 tools）、intent_llm（前置小模型 JSON 意图分类）
- **VLLM**（1）：openai

## 8. 与 manager-api 的交互

### 8.1 HTTP 客户端（config/manage_api_client.py）

- `ManageApiClient` 线程安全单例（:22-35）；`_init_client` 校验 `manager-api.url/secret`（:38-56），`max_retries=6`、`retry_delay=10s`。
- `_ensure_async_client`（:58-92）：**每个事件循环一个 `httpx.AsyncClient`**（keep-alive 置 0），base_url=manager-api.url，固定头 `Authorization: Bearer <secret>`、`User-Agent: PythonClient/2.0 (PID)`（:78-88）。
- `_async_request`（:94-120）：`raise_for_status` → JSON 业务码处理——`10041`→`DeviceNotFoundException`、`10042`→`DeviceBindException(bind_code)`、`code!=0`→Exception，成功返回 `data` 字段（:107-116）。
- `_should_retry`（:123-136）：连接/超时/网络错误与 408/429/500/502/503/504 重试；`_execute_async_request`（:138-160）指数等待重试。
- `api_guard` 装饰器（:192-221）：统一取单例局部引用；启动路径未初始化即抛错，守护线程路径静默返回 None。
- Java 端对应：这些路径挂在 Shiro `server` 过滤器后（Bearer server.secret），main/manager-api/src/main/java/xiaozhi/modules/security/config/ShiroConfig.java:93-98；controller 在 modules/config/controller/ConfigController.java:32,39,48 与 modules/agent/controller/AgentController.java:149,171。

### 8.2 交互总表（python → manager-api）

所有 ManageApiClient 请求：base_url = `manager-api.url`（如 `http://127.0.0.1:8002/xiaozhi`），Header `Authorization: Bearer <manager-api.secret>`，JSON 响应 `{code, msg, data}`，code 10041/10042 特殊语义。

| # | 方法+URL | 用途 | 发起方（python 文件:行） | 返回 data 的消费方式 |
|---|---|---|---|---|
| 1 | POST `/config/server-base` | 拉全局配置（智控台参数） | config/manage_api_client.py:225-227；调用点 config/config_loader.py:61（启动）、core/websocket_server.py:168（热更新） | 作为整个运行 config（read_config_from_api=True），server 块被本地覆盖（config_loader.py:70-84） |
| 2 | POST `/config/agent-models`，body `{macAddress, clientId, selectedModule}` | 拉某设备的 agent/voice 差异化配置 | manage_api_client.py:231-243；调用点 config_loader.py:94 → core/connection.py:808（每连接）、core/api/vision_handler.py:107（视觉） | 覆盖 TTS/LLM/VAD/ASR/Memory/Intent/prompt/voiceprint/summaryMemory/chat_history_conf/plugins 等（connection.py:839-927） |
| 3 | POST `/config/correct-words`，body `{macAddress}` | 拉替换词 | manage_api_client.py:247-252 | 注入 `config.TTS[selected].correct_words`（connection.py:922-927；tts/base.py:52-80 正则替换） |
| 4 | POST `/agent/chat-summary/{session_id}/save` | 会话记忆总结（保存长记忆） | manage_api_client.py:256-261；调用点 mem_local_short.py:193（仅 API 模式） | Java 侧生成总结，下轮以 `summaryMemory` 随 #2 下发 |
| 5 | POST `/agent/chat-title/{session_id}/generate` | 断开时生成会话标题 | manage_api_client.py:265-270；调用点 connection.py:291（守护线程） | 仅写库 |
| 6 | POST `/agent/chat-history/report`，body `{macAddress, sessionId, chatType, content, reportTime, audioBase64}` | 聊天记录上报（1=用户ASR/2=智能体TTS/3=工具调用） | manage_api_client.py:274-293；调用点 reportHandle.py:47（队列消费 connection.py:1505-1537） | 仅写库；受 `chat_history_conf`（0/1/2）控制是否含音频 |
| 7 | GET `/device/address-book/lookup` | 按昵称查目标设备 | manage_api_client.py:297-302（**当前无调用方，死代码**；Java 端也无此路由） | — |
| 8 | GET `/device/address-book/call?callerMac=&nickname=[&answer=true]`（**不走 ManageApiClient，插件内 httpx 直连，同样 Bearer secret**） | 设备间语音通话/接听 | plugins_func/functions/call_device.py:64-78 | code!=0 或 data.status=="error" 转为语音回复（:84-95） |

Java 端对应：ConfigController.java:32/39/48（#1-3）、AgentController.java:149/171（#4-5）、chat-history/report（ShiroConfig.java:95 放行 + server 过滤器）、DeviceController.java:180-189（#8）。

### 8.3 反向通道（manager-api → python）

无 HTTP 直调。控制指令经 WebSocket 文本 `{"type":"server","action":"update_config"|"restart"}` 下发（serverMessageHandler.py:18-92），需携带 `manager-api.secret` 验签。

### 8.4 vision 接口的间接使用

core/api/vision_handler.py:104-111：API 模式下每次视觉请求都 `get_private_config_from_api` 拉该设备的 VLLM 配置再实例化（:113-130）。

## 9. HTTP 服务

core/http_server.py：`SimpleHttpServer.start()`（:35-92）aiohttp `web.Application`，绑定 `server.ip:http_port`（:39-40, 79-82）。

- 路由：
  - 仅本地模式注册 OTA（:45-64）：`GET/POST/OPTIONS /xiaozhi/ota/`、`GET/OPTIONS /xiaozhi/ota/download/{filename}`。
  - 任何模式注册视觉（:66-76）：`GET/POST/OPTIONS /mcp/vision/explain`。
- **OTAHandler**（core/api/ota_handler.py）：
  - `handle_post`（:143-353）：从 header/body 判定 `device-model` 与 `device-version`（:184-221）；返回 `server_time`、`firmware{version,url}`；配置了 `server.mqtt_gateway` 时下发 MQTT 三元组（endpoint/client_id/username/password，密码 = HMAC-SHA256(mqtt_signature_key) 签名，:235-280，签名函数 :105-123）；否则下发 `websocket{url,token}`，token 由 AuthManager 用 auth_key 现场签发（:282-298）——**这就是 §4.3 鉴权所验 token 的来源**；固件检查：扫描 `data/bin/{model}_{version}.bin`（TTL 30s 缓存，:66-104），版本更高则给下载 URL（:300-335）。
  - `handle_get`（:355-370）：连通性测试，回显 websocket 地址。
  - `handle_download`（:372-415）：仅允许 `data/bin` 下合法命名的 .bin（basename + realpath 双重防穿越，:384-398），`web.FileResponse` 流式下载。
- **VisionHandler**（core/api/vision_handler.py:20-183）：POST 为 multipart（question + 图片 ≤5MB，魔数校验 util.py:540-567）→ JWT 鉴权 `AuthToken.verify_token`（:30-45；core/utils/auth.py:13-126，JWT-HS256 外层 + AES-GCM 加密内层 payload，1 小时过期）→ API 模式拉私有配置 → VLLM `response(question, image_base64)`（:126-136）。
- **BaseHandler**（core/api/base_handler.py:5-24）：统一 CORS 头（`*`、允许 client-id/device-id/authorization 头）。
- API 模式下 OTA 由 manager-api 自己提供（`/ota/**` anon，ShiroConfig.java:79），python 端不再暴露 OTA。

## 10. 插件机制

- **注册**：`@register_function(name, desc_json, ToolType)`（plugins_func/register.py:85-96）把 `FunctionItem` 写入全局 `all_function_registry`，并记录 `module_func_map[模块名].append(函数名)`（:81-92）——支撑"配置里写模块名展开为多个函数"（connection.py:887-905；plugin_executor.py:57-80）。
- **发现**：`auto_import_modules("plugins_func.functions")`（loadplugins.py:9-27，pkgutil 遍历 import）；在 connection.py:52（import 时）与 unified_tool_handler.py:61（连接初始化）各执行一次。
- **动作契约**：`Action` 枚举 ERROR/NOTFOUND/NONE/RESPONSE/REQLLM/RECORD（register.py:25-31）+ `ActionResponse(action, result, response)`（:38-42）；`ToolType`（插件层）NONE/WAIT/CHANGE_SYS_PROMPT/SYSTEM_CTL/IOT_CTL/MCP_CLIENT（:9-22）。
- **参数 schema**：每个插件文件自带 OpenAI function-calling 格式 JSON（如 handle_exit_intent.py:11-27）。
- **执行**：`ServerPluginExecutor.execute`（core/providers/tools/server_plugins/plugin_executor.py:19-55）按 ToolType 决定是否传 conn（SYSTEM_CTL/IOT_CTL/CHANGE_SYS_PROMPT 传），兼容 async 函数。
- **统一工具体系**（core/providers/tools/）：`UnifiedToolHandler`（unified_tool_handler.py:22-56）挂 5 类执行器（SERVER_PLUGIN/SERVER_MCP/DEVICE_IOT/DEVICE_MCP/MCP_ENDPOINT，tool_types.py:10-17）；`ToolManager` 聚合描述并按类型分发执行（unified_tool_manager.py:30-47, 73-102）；server_mcp 读 `data/.mcp_server_settings.json`；device_iot 由设备 descriptors 动态生成 `get_XX_属性` / `XX_方法` 工具并回发 iot 命令（iot_executor.py:17-100, 111-133, 135-230）；`handle_exit_intent`、`get_lunar` 为必备强制加载（plugin_executor.py:99）。
- **内置插件**（plugins_func/functions/）：call_device、change_role、get_news_from_chinanews、get_news_from_newsnow、get_time、get_weather、handle_exit_intent、hass_init、hass_play_music、hass_state、play_music、search_from_ragflow、web_search。

## 11. MQTT 模式

- 本 Python 服务**不内置 MQTT broker/客户端**；MQTT 由独立部署的 mqtt_gateway 网关承担（docs/mqtt-gateway-integration.md），网关把 MQTT 设备流量转成 **WebSocket 连到本服务，路径带 `?from=mqtt_gateway`**（connection.py:227-230）。
- 与普通 WebSocket 连接的差异：
  1. OTA 下发 MQTT 参数而非 websocket url（ota_handler.py:235-280）：endpoint、`GID_{model}@@@{mac}@@@{mac}` 形式 client_id、base64 用户名、HMAC 签名密码、publish/subscribe topic。
  2. 上行音频带 16 字节头（type/len/sequence/timestamp），connection.py:385-415 解析；timestamp>0 且 client_aec 时做服务端 AEC（:405-407）。
  3. 下行音频同样打 16 字节头（sendAudioHandle.py:84-116），并缓存 PCM 供 AEC 参考帧。
  4. 鉴权语义复用同一 HMAC 三元组：MQTT 的 client_id/username/password 对应 WS 的 client-id/device-id/authorization（auth.py:14-19）。
  5. config.yaml 侧开关：`server.mqtt_gateway`、`server.mqtt_signature_key`（config.yaml:38-41）。

## 12. 关键文件总表

| 文件 | 职责 | 重要度 |
|---|---|---|
| app.py | 启动编排、auth_key、双 server、信号处理 | 高 |
| config/config_loader.py | 双模式配置加载/合并/API 差异化 | 高 |
| config/manage_api_client.py | manager-api HTTP 客户端（8 个端点） | 高 |
| config/settings.py / config/logger.py | 配置检查 / loguru 日志 | 中 |
| core/websocket_server.py | WS 监听、握手、鉴权、共享模块、热更新 | 高 |
| core/auth.py / core/utils/auth.py | HMAC token（WS/OTA）/ JWT+AES（vision） | 高 |
| core/connection.py | 连接全生命周期、chat 主循环、TTS/ASR 编排 | 最高 |
| core/handle/*（11 文件 + textHandler/ 7 文件） | 消息路由与各类型处理 | 高 |
| core/providers/{asr,tts,llm,memory,intent,vad}/base.py | 六大抽象基类 | 高 |
| core/utils/modules_initialize.py + core/utils/{llm,tts,asr,intent,memory,vad,vllm}.py | 模块初始化与 importlib 工厂 | 高 |
| core/http_server.py + core/api/* | OTA/固件下载/视觉分析 HTTP | 高 |
| core/providers/tools/*（unified_tool_handler/manager + 5 执行器） | 统一工具（插件/MCP/IoT）体系 | 高 |
| plugins_func/register.py + loadplugins.py + functions/* | 插件注册/发现/13 个内置插件 | 高 |
| core/utils/dialogue.py / prompt_manager.py | 对话历史组装 / 系统提示词增强 | 中 |

## 外部依赖

websockets（WS 服务）、aiohttp（HTTP/OTA/vision）、httpx（manager-api/LLM）、openai SDK（LLM/VLLM）、opuslib_next（Opus 编解码）、onnxruntime（SileroVAD）、loguru、jinja2（提示词模板）、PyJWT + cryptography（vision 鉴权）、mcp（服务端 MCP）、funasr/sherpa-onnx 等按需 provider 依赖。

## 开发提示

- 新增 ASR/TTS/LLM/Memory/Intent 供应器：在 `core/providers/<类>/<type>.py` 写 `XxxProvider` 类并保持工厂命名约定（TTS/ASR 单层目录、LLM 双层目录），config.yaml 加 type 即可被发现，无需改工厂代码。
- 新增设备能力/工具：优先做成 `plugins_func/functions/` 插件（@register_function + OpenAI schema），自动进入 UnifiedToolHandler；涉及回发设备消息时参考 iot_executor 的 `{"type":"iot",...}`。
- 涉及 manager-api 的新请求：统一加到 config/manage_api_client.py 的 `@api_guard` 函数族，勿自建 httpx 客户端（call_device.py 是历史例外；manage_api_client.py:296-302 的 lookup 已是死代码，清理时可删）。
- 易踩的坑：无命令行参数（勿找 -a/--api）；TTS 每连接实例而 VAD/本地 ASR/LLM/Intent/Memory 是进程级共享；`read_config_from_api=True` 时 server 块以本地 .config.yaml 为准（含 websocket 覆盖，config_loader.py:72-83）。
