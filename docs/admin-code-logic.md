# 管理端（manager-api + manager-web）代码逻辑详解

> 路径约定：所有 `文件:行号` 引用均相对于仓库根。本文基于 2026-10 的 main 分支代码（版本 0.9.7）。
> Python 端（xiaozhi-server）逻辑见姊妹篇 [python-code-logic.md](./python-code-logic.md)。

## 目录

- [第一部分 关键事实：admin 与 python 如何交互](#第〇部分)
- [第一部分 manager-api（Java Spring Boot）](#第一部分-managerapi)
- [第二部分 manager-web（Vue 前端）](#第二部分-managerweb)
- [附表 A：admin 侧对外接口总表](#附表-a)
- [附表 B：前端页面 → 后端接口映射](#附表-b)

---

# 第〇部分 关键事实：admin 与 python 如何交互

先纠正三个容易误解的点（本版本代码的实际事实）：

1. **manager-api 没有任何 WebSocket 服务端**（全仓库 grep `DeviceWebSocketHandler` 无结果，manager-api 也不监听 WS 端口）。
2. **manager-api 与 python 之间没有 Redis pub/sub**（grep `MessageListener|RedisMessageListenerContainer|convertAndSend` 无命中）。Redis 只做缓存共享：两边读同一批 key（如 `server:config`、`tmp_register_mac:*`、`ota:activation:*`）。
3. 管理页面的"设备在线状态"不是 WebSocket 推送，而是 HTTP 代理外部 MQTT 管理器的一次性拉取。

实际的交互是**三条链路 + 一个共享 Redis**：

| 链路 | 方向 | 机制 | 代码入口 |
|---|---|---|---|
| ① 配置拉取 | python → manager-api | HTTP POST `/config/**`，鉴权 = `Authorization: Bearer <server.secret>`（单串全等比较） | ConfigController.java:32-54 ← python manage_api_client.py |
| ② 设备接入 | 设备 → manager-api → python | 设备先 POST `/ota/` 领取 WebSocket URL + HMAC token，再直连 python 的 WS | OTAController.java:44-60；token 生成 DeviceServiceImpl.java:609-634 |
| ③ 管理指令 | manager-api → python | 智控台"服务端管理"页发起，Java 用 **WebSocket 客户端**反向连 python `/xiaozhi/v1/`，发 `{"type":"server","action":"restart\|update_config"}` | ServerSideManageController.java:66-138 → python serverMessageHandler.py:18-92 |
| ④ 共享缓存 | 双方读写同一 Redis | `server:config`（全局配置）、`tmp_register_mac:{id}`（管理端代查标记）、`ota:activation:*`（激活码）等 | RedisKeys.java:8-197 |

完整时序（设备从激活到对话）：

```
设备 --POST /ota/--> manager-api
        ├─ 设备未注册 → 生成6位激活码存 Redis，返回 frontend_url+code（设备屏幕显示）
        └─ 设备已绑定 → 返回 websocket{url, token(HMAC)} 或 MQTT 三元组；有新版固件则返回下载URL
用户 --在智控台输入激活码 POST /device/bind/{agentId}/{code}--> manager-api
        └─ 写 ai_device（agent_id = 所选智能体）
设备 --WS 连接 python（携带 token）--> xiaozhi-server
python --POST /config/agent-models {macAddress}--> manager-api
        └─ 按 ai_device.agent_id → ai_agent → 8个模型ID → ai_model_config.config_json（含明文密钥）
        返回该设备专属 TTS/LLM/ASR/... + prompt + 插件参数 + MCP endpoint + 声纹
设备 ↔ python 语音对话；python --POST /agent/chat-history/report--> manager-api 写 ai_agent_chat_history
连接断开 --POST /agent/chat-title/{sessionId}/generate + /agent/chat-summary/{sessionId}/save--> manager-api
管理员在智控台改智能体/模型 → 下次设备连接（或 update_config 指令）时 python 重新拉取生效
```

---

# 第一部分 manager-api

## 1. 技术栈与启动

### 1.1 依赖（pom.xml）

- Spring Boot **3.4.3** parent（pom.xml:11-15），Java **21**（pom.xml:20）
- 权限：Apache **Shiro 2.0.2**（jakarta classifier，pom.xml:40-74）。**没有 Spring Security，也没有 JWT 库**——用户 token 是 `MD5(UUID)` 摘要存 MySQL 的 opaque token
- ORM：**MyBatis-Plus 3.5.17**（pom.xml:178-187），注解 + 少量 XML mapper（`src/main/resources/mapper/**/*.xml`）
- 数据库：MySQL（pom.xml:163-167）+ **Druid 1.2.20** 连接池 + **Liquibase 4.20.0**（pom.xml:173-177）
- Redis：`spring-boot-starter-data-redis`（Lettuce，pom.xml:150-153）
- WebSocket：`spring-boot-starter-websocket`（pom.xml:83-86）——**仅用作客户端**（见 §9）
- 其它：knife4j 4.6.0 + springdoc 2.8.8（API 文档 `/xiaozhi/doc.html`，pom.xml:198-215）、easy-captcha 1.6.2、BouncyCastle（SM2 登录密码加密）、阿里云 SMS SDK、hutool 5.8.46、guava

### 1.2 启动类与初始化

- `AdminApplication.java:6-12`：`@SpringBootApplication`，main 打印 `http://localhost:8002/xiaozhi/doc.html`。
- 启动顺序钩子 `SystemInitConfig.java:15-47`：`@DependsOn("liquibase")` + `@PostConstruct init()`：
  1. 校验 Redis 中的版本号与 `Constant.VERSION`（当前 `0.9.7`，Constant.java:327），不一致则 `redisUtils.emptyAll()` 清空全部缓存（SystemInitConfig.java:34-40）——升级发布即全量缓存冷启动。
  2. `sysParamsService.initServerSecret()`：首次启动生成 `server.secret`（UUID）和 SM2 密钥对（SysParamsServiceImpl.java:205-237）。
  3. `configService.getConfig(false)` 预热配置；刷新设备通讯录缓存。

### 1.3 application.yml 关键配置

- `application.yml`：端口 **8002**，context-path **/xiaozhi**（:8-10），Tomcat 最大线程 1000；`spring.profiles.active: dev`；multipart 上限 100MB；knife4j 开启；`renren.xss.enabled: true`；MyBatis-Plus 主键 `ASSIGN_ID`、下划线转驼峰（:47-66）。
- `application-dev.yml`：MySQL `jdbc:mysql://127.0.0.1:3306/xiaozhi_esp32_server`（Druid 池 10~100，:11-38）；Redis `127.0.0.1:6379` db 0（:39-51）。

## 2. 模块总览

`xiaozhi.common`（基础层，renren 脚手架遗留）：`Constant`（全系统参数码表）、`RenException + RenExceptionHandler`（全局异常）、分页、`RedisUtils/RedisKeys`、Json/Convert/HttpContext/SM2/AES/敏感数据掩码等工具、XSS 过滤器、`DataFilterInterceptor`（数据权限）、`RedisAspect`、`AsyncConfig`（@EnableAsync）、`MybatisPlusConfig`（分页插件）。

`xiaozhi.modules.*`（业务层，controller/service/dao/entity/dto/vo 标准分层）：

| 模块 | 职责 |
|---|---|
| `security` | 登录/验证码/短信/用户 token（Shiro Oauth2Filter + ServerSecretFilter 两套过滤器） |
| `sys` | 管理员用户管理、参数管理（sys_params）、字典、**服务端管理（admin↔python WebSocket 指令）**、WebSocket 客户端工具 |
| `agent` | 智能体 CRUD、模板、快照（版本回滚）、插件映射、上下文源、声纹、聊天记录/会话/标题/总结、MCP 接入点 |
| `device` | 设备绑定/激活/解绑、OTA 上报与固件管理、设备通讯录（P2P 呼叫）、设备工具（MQTT 网关代理） |
| `config` | **给 python 拉取的三个配置接口**（server-base / agent-models / correct-words）与启动初始化 |
| `model` | 模型配置（ai_model_config）与模型供应器（ai_model_provider）管理，含敏感字段掩码/缓存 |
| `timbre` | TTS 音色库管理（ai_tts_voice） |
| `voiceclone` | 用户声音克隆（上传音频→外部平台训练→生成 voiceId） |
| `correctword` | 替换词（纠错词）文件与词条管理，按智能体关联 |
| `knowledge` | RAGFlow 知识库（数据集/文档/分块/检索测试）+ 30s 文档状态同步任务 |
| `llm` | OpenAI 风格 LLM 调用封装（用于标题/总结生成） |
| `sms` | 阿里云短信发送 |

## 3. 认证与权限

### 3.1 登录流程（前端用户）

入口 `POST /xiaozhi/user/login`（LoginController.java:89-111）：

1. 前端用 sm-crypto 以 SM2 公钥加密 `captcha+password`；后端 `Sm2DecryptUtil.decryptAndValidateCaptcha`（:95-96）用 `server.private_key`（sys_params）解密并顺带校验图形验证码。
2. `sysUserService.getByUsername`（:101；SysUserServiceImpl.java:52-61）。
3. 密码校验 `PasswordUtils.matches`——BCrypt。**第一个注册的用户自动成为 superAdmin=1**（SysUserServiceImpl.java:85-90）。
4. 生成 token（SysUserTokenServiceImpl.java:35-82）：
   - token = `TokenGenerator.generateValue()` = **MD5(UUID) 的 hex**（TokenGenerator.java:34-44）——不是 JWT；
   - 存 `sys_user_token` 表（user_id 唯一），有效期 **12 小时**，每次登录滑动续期；
   - 返回 `TokenDTO{token, expire, clientHash}`（TokenDTO.java:15-25）。
5. **没有 refresh token 接口**：过期后 Oauth2Realm 抛 TOKEN_INVALID，前端收 401 清 localStorage 重登（httpRequest.js:125-128）。改密/登出把 expire_date 置为过去。

### 3.2 Shiro 过滤器链（ShiroConfig.java:78-102）

两个自定义 filter（:63-68）：

- `oauth2` = `Oauth2Filter`（Oauth2Filter.java:29-108）：从 `Authorization: Bearer xxx` 取 token → `Oauth2Realm.doGetAuthenticationInfo`（Oauth2Realm.java:76-106）：按 token 查 `sys_user_token` → 过期抛 IncorrectCredentials → 查 `sys_user` 转 UserDetail、status=0 抛 LockedAccount。
- `server` = `ServerSecretFilter`（ServerSecretFilter.java:27-105）：Bearer 值与 sys_params 的 `server.secret` **全等比较**（:62-68），匹配即放行且**不创建 Shiro 登录态**，不等返回 401 JSON。这是 python 调 manager-api 的鉴权方式。

过滤链定义（ShiroConfig.java:78-101）：

```
/ota/**                              → anon    （设备 OTA 上报，无鉴权）
/otaMag/download/**                  → anon    （固件下载，UUID 一次性）
/user/captcha|login|register|smsVerification|pub-config|retrieve-password → anon
/agent/chat-history/download/**      → anon    （一次性 UUID 下载）
/agent/play/**、/voiceClone/play/**  → anon    （一次性 UUID 音频播放）
/config/**                           → server  （python 拉配置，secret 鉴权）
/device/address-book/call            → server  （python 呼叫插件）
/agent/chat-history/report           → server  （python 聊天上报）
/agent/chat-summary/**、/agent/chat-title/** → server
/**                                  → oauth2  （其余全部走用户 token）
```

### 3.3 权限模型

- 只有两种权限串：`sys:role:normal`（所有登录用户）与 `sys:role:superAdmin`，由 `Oauth2Realm.doGetAuthorizationInfo` 按 `UserDetail.superAdmin` 授予（Oauth2Realm.java:54-70）。
- 控制器用 `@RequiresPermissions(...)`（如 DeviceController.java:59、OTAMagController.java:69）。**没有菜单表/权限表**，前端菜单由 `userInfo.superAdmin` + `system-web.menu` 参数决定（见第二部分 §1.2）。
- 资源级权限（设备/智能体归属）在 Service 层手写：`AgentServiceImpl.hasAgentPermission`（owner 或 superAdmin，AgentServiceImpl.java:149-163）、`DeviceController.updateDeviceInfo` 校验 `entity.getUserId().equals(user.getId())`（DeviceController.java:123-126）。

### 3.4 python 调用的鉴权细节

- 密钥来源：sys_params `server.secret`，首次启动生成（SysParamsServiceImpl.java:205-215）；管理员可在参数页改。
- 校验链：`/config/** → server` filter → `sysParamsService.getValue("server.secret", true)`（带 Redis 缓存 `sys:params`，ServerSecretFilter.java:102-104）→ 字符串相等即通过。
- ⚠️ secret 泄露 = 全配置泄露（含模型 API key 明文，ConfigServiceImpl.java:452-53 注释明确 python 拉的是原始密钥）。

## 4. 设备相关（device 模块）

### 4.1 DeviceEntity / ai_device 表

DeviceEntity.java:17-67（DDL 202503141346.sql:110-127）：

`id`(PK=激活时的设备ID) / `user_id` / `mac_address` / `last_connected_at` / `auto_update`(0/1 自动固件升级) / `board`(OTA 上报的硬件型号) / `alias` / `agent_id`(**逻辑外键→ai_agent.id**) / `app_version` / `sort` 等。

关联关系：`ai_device.agent_id → ai_agent.id`、`ai_agent.user_id → sys_user.id`、`ai_agent.tts_voice_id → ai_tts_voice.id（或 ai_voice_clone.id）`、各 `*_model_id → ai_model_config.id`——全部是**无外键约束的逻辑关联**（202503141346.sql:105,126）。

### 4.2 设备注册/激活流程（两段式）

**第一段：设备 OTA 上报（未绑定设备生成激活码）**

1. 设备 POST `/xiaozhi/ota/`，Header `Device-Id`(=MAC)、`Client-Id`（OTAController.java:44-60）。
2. MAC 正则校验 `^([0-9A-Za-z]{2}[:-]){5}([0-9A-Za-z]{2})$`（OTAController.java:114-121）。
3. `DeviceServiceImpl.checkDeviceActive(mac, clientId, report)`（DeviceServiceImpl.java:192-282）：
   - 查 ai_device；不存在 → firmware.url 填占位常量 `INVALID_FIRMWARE_URL`（:199-203）。
   - 存在且 auto_update=1 → `buildFirmwareInfo`：按 board.type 查 `ai_ota` 最新记录（OtaServiceImpl.java:78-84），版本比较（:528-548），有新版则生成一次性 uuid 存 Redis `ota:id:{uuid}`，下载 URL = `server.ota` 参数把 `/ota/` 替换为 `/otaMag/download/` + uuid（:493-518）。
   - 组装 WebSocket 配置：`server.websocket` 参数（分号分隔多节点**随机选一**，:234-247）；`server.auth.enabled=true` 时用 `generateWebSocketToken(clientId, mac)` 生成 token（见 §8）。
   - 组装 MQTT 配置（配置了 `server.mqtt_gateway` 时）：clientId=`{board}_{mac}@@@…`、username=Base64(JSON{ip})、password=HMAC-SHA256(clientId|username, `server.mqtt_signature_key`)（:643-688）。
   - 已存在 → **@Async** 更新 last_connected_at/app_version（:82-98）。
   - 不存在 → `buildActivation`（:443-483）：生成 6 位随机码，写两个 Redis key：`ota:activation:data:{mac}` → {id, mac, board, app_version, activation_code}、`ota:activation:code:{code}` → deviceId；响应 `activation.message = server.fronted_url + "\n" + code`（设备屏幕展示给用户）。

**第二段：用户在智控台输码绑定**

4. `POST /device/bind/{agentId}/{deviceCode}`（DeviceController.java:57-63）→ `deviceActivation`（DeviceServiceImpl.java:101-153）：从 `ota:activation:code:{code}` 反查 deviceId → 校验激活码一致 → 未被激活过 → 以当前登录用户身份 insert ai_device（agentId=所选智能体）→ 清理激活 Redis key + `agent:device:count:{agentId}` 缓存。
5. 辅助路径：手动添加 `POST /device/manual-add`（DeviceController.java:134-141，MAC 唯一性校验）；网页生成配对码 `POST /device/register`（:65-84，写 `sys:device:captcha:{code}→mac`）；解绑 `POST /device/unbind`（DeviceServiceImpl.java:313-332，连带删通讯录记录）。

### 4.3 设备与 agent/voice 配置的关联

- 设备只挂一个 `agent_id`；**voice/LLM/ASR 等全部由 agent 决定**：`ai_agent` 持有 `asr/vad/llm/slm/vllm/tts/mem/intent` 八个模型 ID 列 + `tts_voice_id`（AgentEntity.java:31-68）。
- `tts_voice_id` 双态：普通音色→`ai_tts_voice.id`，克隆音色→`ai_voice_clone.id`，ConfigServiceImpl 先查 timbre 查不到再查 voice_clone（ConfigServiceImpl.java:149-167）。
- 管理端改设备（别名/自动升级）`PUT /device/update/{id}`（DeviceController.java:115-132）。

### 4.4 设备在线状态与设备工具的真实路径（重点澄清）

**不存在 admin 端 WebSocket 服务端**。管理页面看设备实时状态的路径是 HTTP 代理外部 MQTT 管理器：

1. 前端调 `POST /device/bind/{agentId}`（DeviceController.java:95-104，「设备在线接口」）→ `getDeviceOnlineData(agentId)`（DeviceServiceImpl.java:159-189）：
   - 读参数 `server.mqtt_manager_api`，拼 `http://{addr}/api/devices/status`；
   - 把该用户该智能体下所有设备拼成 clientId 集合 `{board}:{mac→_}@@@{mac}@@@{mac}`（:173-177）；
   - `postToMqttGateway`：HMAC 签名请求（密钥 `server.mqtt_signature_key`，:690-697），原样返回 MQTT 管理器 JSON。
2. 前端解析 `{clientId: {isAlive, exists}}` 更新在线标签（DeviceManagement.vue:373-421）。一次性拉取，无轮询无推送。
3. 设备工具调用同理：`POST /device/tools/list/{deviceId}`、`/device/tools/call/{deviceId}` 代理到 MQTT 管理器的 `/api/commands/{clientId}`（JSON-RPC `tools/list`/`tools/call`，DeviceServiceImpl.java:700-883）。
4. 真正的 **admin→python WebSocket** 只在「服务端管理」页（§9.1）和 MCP 工具探测（§9.2），方向都是 manager-api **作为客户端连出去**。

## 5. agent 模块

### 5.1 AgentController（基路径 /agent）

- `GET /agent/list?keyword&searchType`（:99-110）→ `getUserAgents`（AgentServiceImpl.java:229-260）：按 user_id 过滤，keyword 可按名称/设备 MAC（先查设备反查 agentId）/标签联合 like-or；每条 DTO 附加 TTS/LLM/VLLM 模型名（Redis `model:name:{id}`）、音色名、最近连接时间（Redis `agent:device:lastConnected:{agentId}`）、设备数（Redis `agent:device:count:{agentId}`，60s TTL，:309-329）、标签。
- `GET /agent/{id}`（:125-131）→ mapper `selectAgentInfoById`（AgentDao.xml:47-83）：`ai_agent LEFT JOIN ai_agent_plugin_mapping`，resultMap 把插件映射聚合为 `functions` 集合；再补上下文源、替换词文件 ID、当前快照版本号。
- `POST /agent`（:133-139）→ `createAgent`（AgentServiceImpl.java:592-694）：从**默认模板**（ai_agent_template 按 sort ASC 第一条）拷贝全部模型 ID/systemPrompt/summaryMemory/chatHistoryConf；模板无 ttsVoiceId 时从 TTS 模型 config_json 的 voice/speaker 反查音色（:606-619）；slm 缺省取第一个 is_default LLM；自动挂三个默认插件（音乐/天气/新闻）；创建 initial 快照。
- `PUT /agent/{id}`（:179-185）→ `updateAgentById`（:365-544）：`SELECT … FOR UPDATE` 锁行（AgentDao.xml:85-90）；**先写保护快照**（initial/current）；非空字段覆盖式更新；插件映射 diff 同步（update/insert/delete）；记忆策略变 nomem 时删全部聊天记录（:509-516）；上下文源/替换词/标签关联更新；`validateLLMIntentParams`：LLM 类型非 openai/ollama 时禁配 Intent_function_call（:576-588）；落库后写 config 快照。
- `DELETE /agent/{id}`（:187-193）→ 级联删设备/聊天/插件/上下文源/替换词映射/标签/快照（:213-226）。
- 会话/聊天：`GET /{id}/sessions`（按 session_id GROUP BY 取 MAX(created_at)+COUNT+标题，AgentChatHistoryServiceImpl.java:48-74）；`GET /{id}/chat-history/{sessionId}`、`GET /{id}/chat-history/user`（最近 50 条）；音频换一次性播放 uuid `POST /audio/{audioId}` + `GET /play/{uuid}`（anon，5 分钟有效，AgentController.java:268-300）。
- 标签 `POST /tag` 等（:302-351）；快照 AgentSnapshotController.java:36-71（列表/详情/restore/delete，快照含脱敏版本号）；模板 AgentTemplateController（superAdmin）；声纹 AgentVoicePrintController.java:38-85（依赖外部声纹服务）；MCP AgentMcpAccessPointController.java:36-54（见 §9.2）。

### 5.2 AgentEntity 字段（事实澄清）

`AgentEntity.java:13-100`——**没有** `model_config`/`voice_config`/`mcp_settings` 这类 JSON 大字段：

- 模型选择是 8 个独立 varchar 列：`asr_model_id / vad_model_id / llm_model_id / slm_model_id / vllm_model_id / tts_model_id / mem_model_id / intent_model_id`（:31-68）。
- 语音参数：`tts_voice_id / tts_language / tts_volume / tts_rate / tts_pitch`。
- 文本：`system_prompt`（TEXT 角色设定）、`summary_memory`（TEXT 总结记忆）、`chat_history_conf`（0 不记/1 文本/2 文本+音频，Constant.java:309-322）。
- MCP/插件 JSON 分散在关联表：`ai_agent_plugin_mapping.param_info`（JSON 字符串 `{插件参数key: value}`）、`ai_agent_context_provider.context_providers`（JSON 列表 `[{"url":..., "headers":{...}}]`）。
- 真正的**模型 config JSON** 在 `ai_model_config.config_json`（JSONObject，含 type/api_key/model 等，由供应器 fields 定义，ModelConfigEntity.java:37-39）。

## 6. config 模块与模型配置（python 拉取的核心）

### 6.1 三个公开接口（ConfigController.java）

| URL | 方法 | 行号 | 作用 |
|---|---|---|---|
| `/config/server-base` | POST | :32-37 | 服务端全局配置（sys_params 全量→嵌套 map） |
| `/config/agent-models` | POST | :39-46 | 按 MAC 返回该设备智能体的全部模型实例+音色+提示词 |
| `/config/correct-words` | POST | :48-54 | 返回该设备智能体的替换词列表 |

### 6.2 server-base 组装（ConfigServiceImpl.getConfig，:68-115）

1. 读 Redis `server:config`（RedisKeys.java:75-77），命中直接返回。
2. 未命中 `buildConfig`（:268-331）：sys_params 全部 param_type=1 的行按 `param_code` 点号拆成嵌套 map（`server.websocket` → `{"server":{"websocket":...}}`），按 value_type 转 number/boolean/array/json。
3. 追加默认模板的 VAD/ASR 模型；`buildModuleConfig` 注入 VAD/ASR 节点与 `selected_module`、`prompt`（`{{assistant_name}}` 替换，:548-551）。
4. 写回 Redis。
5. **失效机制 = 写时重建**：管理员每次改参数/增删模型/设默认模型都手动调 `configService.getConfig(false)` 强制重建（SysParamsController.java:90,123,170；ModelController.java:91,103,162）。⚠️ 遗漏调用处会导致 python 读到旧 `server:config`。

### 6.3 agent-models 组装（getAgentModels，:118-248）——python 每次设备连接调用

1. **管理控制台代查探测**：先查 Redis `tmp_register_mac:{macAddress}`=="true"（ServerSideManageController 发 WS 指令前写入，5 分钟有效）——是则直接返回 getConfig(true) 并删 key（:120-127）。
2. `getDeviceByMacAddress` 查不到 → 查激活缓存抛 OTA_DEVICE_NEED_BIND（带绑定码）/OTA_DEVICE_NOT_FOUND（:130-137；python 侧对应 code 10041/10042）。
3. `getAgentById(device.getAgentId())`。
4. 音色解析：先 `timbreService.get(ttsVoiceId)`（缓存 `timbre:details:{id}`）取 ttsVoice/referenceAudio/referenceText/languages；查不到再查 `ai_voice_clone`（:149-167）。
5. 顶层字段：`device_max_output_size`、`chat_history_conf`（nomem 强制 0；有记忆且为空默认 2，:171-183）。
6. **模型差量下发**：入参 `selectedModule`（python 已实例化的 {VAD: id, ASR: id}），相同则置 null 不再返回（:185-192）。
7. 插件参数：非 `Intent_nointent` 时，查 `ai_agent_plugin_mapping JOIN ai_model_provider` 得 `{provider_code: paramInfo}` 放入 `plugins`（:195-205）。
8. MCP 接入点：生成 `ws://.../mcp/?token=AES(md5(agentId))`，路径 `/mcp/`→`/call/` 后作为 `mcp_endpoint` 下发（:207-211）。
9. 上下文源、声纹配置 `voiceprint{url, speakers[], similarity_threshold=0.4}`（:339-387）。
10. `buildModuleConfig`（:418-553）逐类型组装：
    - 每个模型 ID 经 `getModelByIdFromCache`（Redis `model:data:{id}`）取**含真实密钥**的 config_json；
    - 结果形状：`{"TTS": {"<modelId>": {...config+voice/volume/rate/pitch...}}, "LLM": {...}, ..., "selected_module": {...}, "prompt": ...}`；
    - TTS 特例：火山 `huoshan_double_stream` 且 voice 以 `S_` 开头 → resource_id 换 `seed-icl-1.0`（:479-484）；
    - Intent 特例：intent_llm 取其附加 LLM；functions 分号拆数组（:487-503）；
    - Memory 特例：mem_local_short 附带其 LLM；LLM 节点并入 intentLLM、memLocalShortLLM、所选 SLM（:504-540）。

### 6.4 聊天上报处理链

`AgentChatHistoryController.report`（:62-67，server filter）→ `AgentChatHistoryBizServiceImpl.report`（:52-87）：按 mac 反查默认智能体 → 按 chatHistoryConf 只存文本或文本+音频（Base64→ai_agent_chat_audio）→ 刷新 last_connected 缓存与 ai_device。

## 7. OTA

- 设备侧 `OTAController`（/ota/，全 anon）：`POST /xiaozhi/ota/` 版本检查+激活码+WS/MQTT 配置（:44-60，逻辑见 §4.2）；`POST /ota/activate` 快速探测是否已绑定（202=未激活，:63-75）；`GET /ota/` 自检（校验 server.websocket/server.ota/server.mqtt_gateway 三个参数，:77-93）。
- 管理侧 `OTAMagController`（/otaMag，superAdmin）：分页/详情/保存（同类固件仅保留一条：save 覆盖旧 id，OtaServiceImpl.java:63-75）/修改（type+version 唯一）/删除/`GET /getDownloadUrl/{id}` 生成一次性 uuid（:135-142）/`GET /download/{uuid}`（anon；Redis 取 id，**同 uuid 最多下载 3 次**后删 key 返回 404，:146-163）/`POST /upload`（仅 .bin/.apk，MD5 去重，:247-293）/`POST /uploadAssetsBin`（普通用户 20MB/50 次每天限制，:298-329）。
- 固件表 `ai_ota`（202504251422.sql:14）。

## 8. WebSocket token 的发放

- **发放方是 manager-api 的 OTA 接口**，不是 python。`generateWebSocketToken(clientId, username)`（DeviceServiceImpl.java:609-634）：密钥=sys_params `server.secret`；`content = clientId|username|timestamp(秒)`；HMAC-SHA256 → Base64-URL-safe 去填充；token = `signature.timestamp`。仅在 `server.auth.enabled=true` 时随 OTA 响应下发（:220-232）。
- python 校验方：`core/auth.py:36-72`（同算法，30 天过期，hmac.compare_digest），握手在 `core/websocket_server.py:227`。
- 智控台反向连 python 也用同一算法：ServerSideManageController.java:103 生成 token 后以 `authorization: Bearer` 头连接（§9.1）。

## 9. manager-api ↔ python 的 WebSocket / Redis 交互

### 9.1 智控台→python 指令通道（restart / update_config）

入口 `POST /admin/server/emit-action`（ServerSideManageController.java:66-85，superAdmin）：body `{action: restart|update_config, targetWs}`；`GET /admin/server/server-list`（:55-64）返回 `server.websocket` 分号拆分列表供选择。

`emitServerActionByWs`（:87-138）：

1. 取 `server.secret`；生成随机 deviceId/clientId；**写 Redis `tmp_register_mac:{deviceId}="true"`（300s）**——python 收到指令后回调 `/config/agent-models` 时由此识别这是管理端代查（ConfigServiceImpl.java:120-127）。
2. headers：`device-id`、`client-id`、`authorization: Bearer <HMAC token>`（:99-107）。
3. `WebSocketClientManager`（modules/sys/utils/WebSocketClientManager.java，Builder 模式 WS 客户端；build 握手 :79-94；InternalHandler 收消息入 BlockingQueue+回调 :241-320）连 targetWs（超时 3s/会话 120s）。
4. 发送 `{"type":"server","action":"...","content":{"secret": serverSK}}`（ServerActionPayloadDTO.java:27-33）。
5. `client.listener(...)` 阻塞等响应，判 `status==SUCCESS && type=="server" && content.action` 存在（:121-132）。

python 接收方：`serverMessageHandler.py:18-92`：校验 content.secret 与本地 manager-api.secret 一致 → `update_config` 重拉 `/config/server-base` → `restart` 走 `handle_restart`。

### 9.2 MCP 接入点客户端

`AgentMcpAccessPointServiceImpl`：

- `getAgentMcpAccessAddress(agentId)`（:33-51）：取参数 `server.mcp_endpoint`，token = `AES(key, {"agentId": md5(agentId)})`，拼 `ws(s)://…/mcp/?token=…`。
- `getAgentMcpToolsList(agentId)`（:54-173）：把 `/mcp/` 换 `/call/` 后用 WebSocketClientManager 连 python 的设备 MCP 端点，依次发 JSON-RPC `initialize`→`notifications/initialized`→`tools/list`，收集工具名列表。

### 9.3 Redis 的角色（无 pub/sub，纯共享缓存）

关键 key（RedisKeys.java:8-197）：`server:config`（:75-77，python 也直接读同一 Redis）、`sys:params`（:12-14）、`model:data:{id}`/`model:name:{id}`（:40-49）、`tmp_register_mac:{id}`（:166-168）、`ota:activation:code|data`（:173-189）、`ota:id:{uuid}`/`ota:download:count`（:96-105）、`agent:chat:history:{uuid}`（:145-147）、`agent:audio:id:{uuid}`（:117-119）、`device:address_book:all`（:194-196）。版本变更全清（SystemInitConfig.java:34-40）。

## 10. 定时任务 / 异步

`@EnableScheduling`（RAGTaskConfig.java:11）；`@EnableAsync` + exposeProxy（AsyncConfig.java:13-39，线程池 core2/max4/queue1000，满则 caller-run）。仅两个 @Scheduled：

1. `AgentSnapshotRedactionRunner`（:27-31）：启动 + 每 15s 对历史智能体快照做凭据脱敏补偿。
2. `DocumentStatusSyncTask.syncRunningDocuments`（:30-38）：每 30s 轮询 RAGFlow 把 RUNNING 文档翻转为 SUCCESS/FAIL。

@Async 使用点：设备连接信息更新（DeviceServiceImpl.java:82）。

## 11. 数据库（Liquibase）

- 主 changelog `db/changelog/db.changelog-master.yaml`（按序 include 140+ 个 SQL）；`@DependsOn("liquibase")` 保证先迁移后初始化。
- 主要表：

| 表 | 用途 | 建表位置 |
|---|---|---|
| sys_user / sys_user_token / sys_params | 用户 / token / 参数 | 202503141335.sql:8/:23/:36 |
| sys_dict_type / sys_dict_data | 字典 | :52/:68 |
| ai_model_provider / ai_model_config | 模型供应器 / 模型配置 | 202503141346.sql:3/:20 |
| ai_tts_voice / ai_agent_template / ai_agent / ai_device / ai_voiceprint | 音色 / 模板 / 智能体 / 设备 / 声纹 | :41/:60/:84/:110/:131 |
| ai_chat_history / ai_chat_message | 旧版对话 | :151/:166 |
| ai_ota / ai_agent_plugin_mapping | 固件 / 插件映射 | 202504251422.sql:14 / 202505292203.sql:178 |
| ai_agent_chat_history / ai_agent_chat_audio | 新版聊天 / 聊天音频 | 202505022134.sql:5/:23 |
| ai_voice_clone / ai_agent_chat_title | 声音克隆 / 会话标题 | 202510071522.sql:3 / 202604011545.sql:8 |
| ai_agent_context_provider | 上下文源 | 202512041515.sql:4 |
| ai_rag_dataset / ai_rag_knowledge_document | RAG | 202510251150.sql:3 / 202603111131.sql:41 |
| ai_agent_correct_word_file/item/mapping | 替换词三表 | 202604211515.sql:2/16/26 |
| ai_agent_snapshot / ai_agent_tag / ai_agent_tag_relation | 快照 / 标签 | 202607071530.sql:4 / 202602281000.sql:2/17 |
| ai_device_address_book | 通讯录 | 202605251426.sql:27 |

全库无物理外键，级联删除靠应用层（AgentServiceImpl.java:213-226）。

## 12. 其它横切面

- 全局异常 `RenExceptionHandler`；响应包 `Result{code=0成功, msg, data}`（Result.java:14-60）。
- CORS：WebMvcConfig.java:41-47（allowedOriginPatterns * + allowCredentials）。
- 国际化：Accept-Language → Locale（WebMvcConfig.java:107-154）。
- XSS：`XssFilter` + SqlFilter（`renren.xss.enabled`）。
- Long→String 序列化防前端精度丢失（WebMvcConfig.java:94-98）。
- 模型密钥安全：管理端读路径掩码 `SensitiveDataUtils.maskSensitiveFields`（ModelConfigServiceImpl.java:192-198, 459-472）；编辑时掩码值（含 `***`）不覆盖原密钥（:352-385）；python 拉取用原始密钥。

---

# 第二部分 manager-web

## 1. 技术栈与基础设施

### 1.1 技术栈

- **Vue 2.6.14** + vue-router 3.6.5 + vuex 3.6.2 + **Element-UI 2.15.14** + vue-i18n 8（6 语言，main.js:8,18）（package.json:19-32）。
- HTTP 库：**flyio**（非 axios；请求全走 fly）（src/apis/httpRequest.js:1）。
- 构建：@vue/cli-service 5、sass、vitest + node:test 契约测试（`tests/*Contract.test.mjs`）、Terser drop_console、gzip、PWA Workbox、可选 CDN externals（vue.config.js:95-172）。
- 其它：opus-decoder/opus-recorder（声音克隆试听/录音）、sm-crypto（SM2 登录加密）、v-code-diff（快照 diff）。

### 1.2 请求封装与 token（src/apis/httpRequest.js）

- 链式 DSL：`sendRequest().url().method().data().success().fail().networkFail().send()`（:20-110）；url 中 `$` 替换回 `/`（:78-84）。
- token 注入：每次请求 `Authorization: Bearer <token>`，token 从 vuex 读（来源 localStorage，存 `JSON.stringify(TokenDTO)`）（:41-43；store/index.js:22-27）。
- 业务码约定：HTTP 200 且 `code===0/'success'/undefined` 成功；**401 → `clearAuth` + 跳登录**（:120-139）；其余弹后端 i18n msg。
- 断网重试 `reAjaxFun` 每 2s、10 次上限（:149-168）；agent.js 另有 terminal-failure 重试（10 次/20s，agent.js:4-37）。

### 1.3 状态管理与动态菜单/权限

- store（store/index.js:9-77）：state `token/userInfo/pubConfig`；mutations 同步写 localStorage；actions logout、fetchPubConfig（拉 `/user/pub-config`）。
- 路由守卫（router/index.js:196-217）：匿名白名单 + 无 token 重定向登录。**没有动态路由注册**——所有页面路由静态声明（:6-175），「权限」只是菜单显隐。
- 菜单显隐两因子（HeaderBar.vue:29-150）：
  1. `userInfo.superAdmin`（来自 `/user/info`）控制管理员菜单（模型配置、参数/字典/OTA/用户/模板/服务端管理/功能配置/替换词）；
  2. `featureStatus` 来自 **featureManager**（utils/featureManager.js）：从 `/user/pub-config` 的 `systemWebMenu`（sys_params `system-web.menu` JSON，LoginController.java:239-243 下发）解析 `features.{voiceprintRecognition,voiceClone,knowledgeBase,mcpAccessPoint,vad,asr,addressBook}.enabled`（featureManager.js:92-181）；功能配置页保存时写回参数 id=600（:218-250）。

### 1.4 登录流程（login.vue:318-384）

`sm2Encrypt(sm2PublicKey, captcha+password)`（:343-352，公钥来自 pub-config）→ `POST /user/login` → `setToken(JSON.stringify(data.data))`（:369）→ `getUserInfo`。

## 2. 页面清单（src/views/*.vue）

| 页面 | 路由 | 功能 | 后端对应 |
|---|---|---|---|
| login.vue | /login | 登录（SM2+验证码） | LoginController.java:61-111 |
| register.vue / retrievePassword.vue | /register /retrieve-password | 注册/找回（短信验证码） | LoginController.java:113-155,176-215 |
| home.vue | /home | **控制台 dashboard**：智能体卡片列表、搜索（名称/MAC/标签）、新建/删除智能体、按 featureStatus 显示声纹/克隆/知识库入口 | AgentController.java:99,133,187 |
| roleConfig.vue | /role-config?agentId= | **智能体配置编辑**（§4） | AgentController / ModelController / AgentMcpAccessPointController |
| DeviceManagement.vue | /device-management?agentId= | 设备管理（§3） | DeviceController.java |
| VoicePrint.vue | /voice-print | 智能体声纹管理 | AgentVoicePrintController.java:38-85 |
| VoiceCloneManagement.vue | /voice-clone-management | 用户声音克隆 | VoiceCloneController.java |
| VoiceResourceManagement.vue | /voice-resource-management | 管理员克隆音色资源库 | VoiceResourceController.java |
| ModelConfig.vue | /model-config | **模型（角色）配置管理**：LLM/TTS/ASR/VAD/Intent/Memory/VLLM/SLM/RAG 分 tab，按供应器动态表单，启停/设默认 | ModelController.java:47-173 |
| ProviderManagement.vue | /provider-management | 模型供应器/插件管理 | ModelProviderController.java |
| KnowledgeBaseManagement.vue + Item | /knowledge-base-management | RAGFlow 知识库 | KnowledgeBaseController / KnowledgeFilesController |
| OtaManagement.vue | /ota-management | 固件上传与版本管理 | OTAMagController.java |
| ParamsManagement.vue | /params-management | 系统参数（敏感值掩码） | SysParamsController.java |
| DictManagement.vue | /dict-management | 字典管理 | SysDictType/DataController |
| UserManagement.vue | /user-management | 用户管理 | AdminController.java:46-108 |
| ServerSideManager.vue | /server-side-management | **下发 restart/update_config 到 python**（§9.1 前端侧） | ServerSideManageController.java |
| AgentTemplateManagement.vue / TemplateQuickConfig.vue | /agent-template-management /template-quick-config | 智能体默认模板管理与快速配置 | AgentTemplateController.java |
| FeatureManagement.vue | /feature-management | 功能开关（写 system-web.menu） | SysParamsController.java:94-125 |
| ReplacementWordManagement.vue | /replacement-word-management | 替换词文件管理 | CorrectWordController.java |
| AddressBookManagement.vue | /address-book-management | 设备通讯录 | DeviceController.java:173-215 |

组件层 src/components/：AddDeviceDialog（绑设备/手动添加）、AddWisdomBodyDialog（建智能体）、AddModelDialog/ModelEditDialog（模型动态表单，按 provider fields 渲染）、ChatHistoryDialog（会话/聊天记录/音频播放）、AgentSnapshotDialog（快照 diff/恢复）、ContextProviderDialog、AddressBookDialog、ChangePasswordDialog、CacheViewer 等。

## 3. 设备管理页与"实时状态"（澄清：前端无 WebSocket）

- **manager-web 全目录 grep `new WebSocket|ws://|wss://` 零命中**——前端没有任何 WebSocket 连接。
- 设备列表：`GET /device/bind/{agentId}`（DeviceManagement.vue:332-371）。
- 在线状态：`fetchDeviceStatus` → `POST /device/bind/{agentId}`（apis/module/device.js:119-140）→ 后端代理 MQTT 管理器（§4.4）；前端拼 clientId 匹配响应，按 `isAlive/exists` 置 online/offline 标签（DeviceManagement.vue:396-421）；服务不可用时隐藏状态列（:170-172）。**一次性拉取**。
- 别名/自动升级 `PUT /device/update/{id}`（:265-294,426-440）；解绑 `POST /device/unbind`（:213-258,299-320）；固件类型字典 `Api.dict.getDictDataByType('FIRMWARE_TYPE')`（:188-196）。

## 4. 智能体/模型/音色配置编辑表单

### 4.1 roleConfig.vue（智能体配置）

- form 结构（:515-548）：agentCode/agentName/systemPrompt/summaryMemory/chatHistoryConf/langCode/language/sort + `model.{vad,asr,llm,slm,vllm,mem,intent,tts}ModelId` + ttsVoiceId/ttsVolume/ttsRate/ttsPitch；另维护 currentFunctions（插件+参数）、currentContextProviders、checkedReplacementWordIds、dynamicTags（标签）。
- 模型下拉数据：`GET /models/names?modelType=`（ModelController.java:47-54）；LLM 用 `/models/llm/names`（带 type 区分 intent 兼容性）；音色 `/models/{modelId}/voices`（:166-173）。
- 保存：`saveConfig()` 组装 AgentUpdateDTO（roleConfig.vue:632-684）→ `PUT /agent/{agentId}`（agent.js:116-130）→ `AgentController.update:179-185` → `AgentServiceImpl.updateAgentById:365-544`（§5.1）。
- 读取：`GET /agent/{agentId}`（agent.js:88-114）。快照走 `/agent/{agentId}/snapshots*`（agent.js:132-216）。

### 4.2 ModelConfig.vue（模型配置）

- 列表 `GET /models/list?modelType`、新增 `POST /models/{modelType}/{provideCode}`、编辑 `PUT /models/{modelType}/{provideCode}/{id}`、启停 `PUT /models/enable/{id}/{status}`、默认 `PUT /models/default/{id}`（ModelConfig.vue:366-551；model.js:35-280）——对应 ModelController.java:72-164；动态表单字段来自 `GET /models/{modelType}/provideTypes`（ai_model_provider.fields）。
- 音色管理：`/ttsVoice` CRUD（timbre.js → TimbreController.java:42-90）。

## 5. 构建/代理配置

- `vue.config.js:43-54`：devServer 端口 **8001**，proxy `'/xiaozhi' → http://127.0.0.1:8002`，changeOrigin: true——开发态前端所有 `/xiaozhi/**` 请求（`.env.development` 的 `VUE_APP_API_BASE_URL=/xiaozhi`）都转给 manager-api。
- `.env.production`：`VUE_APP_API_BASE_URL=/xiaozhi`、`VUE_APP_PUBLIC_PATH=/`、`VUE_APP_USE_CDN=false`。
- 生产优化：Terser drop_console、gzip>20KB、splitChunks、文件系统缓存（vue.config.js:96-171）；PWA service-worker（src/service-worker.js）。

---

# 附表 A：admin 侧对外接口总表

## A-1 python 用 server.secret 调用（filter=server）

| URL | 方法 | 用途 | Controller:行号 |
|---|---|---|---|
| /xiaozhi/config/server-base | POST | 全局配置（sys_params 嵌套化+默认模板 VAD/ASR，缓存 server:config） | ConfigController.java:32-37 |
| /xiaozhi/config/agent-models | POST | 按 MAC 的智能体模型实例/音色/提示词/插件/MCP/声纹（差量 selectedModule） | ConfigController.java:39-46 |
| /xiaozhi/config/correct-words | POST | 替换词列表 | ConfigController.java:48-54 |
| /xiaozhi/agent/chat-history/report | POST | 聊天文本+opus 音频上报 | AgentChatHistoryController.java:62-67 |
| /xiaozhi/agent/chat-summary/{sessionId}/save | POST | 生成并保存会话总结（异步） | AgentController.java:149-169 |
| /xiaozhi/agent/chat-title/{sessionId}/generate | POST | 生成会话标题 | AgentController.java:171-177 |
| /xiaozhi/device/address-book/call | GET | 通讯录昵称呼叫/接听（代理 MQTT 管理器） | DeviceController.java:180-189 |

## A-2 设备/匿名调用（filter=anon）

| URL | 方法 | 用途 | Controller:行号 |
|---|---|---|---|
| /xiaozhi/ota/ | POST | OTA 版本检查+激活码+WebSocket(token)/MQTT 配置 | OTAController.java:44-60 |
| /xiaozhi/ota/activate | POST | 快速激活探测（202/200） | OTAController.java:63-75 |
| /xiaozhi/otaMag/download/{uuid} | GET | 固件下载（一次性 uuid，3 次上限） | OTAMagController.java:144-242 |
| /xiaozhi/user/captcha、/login、/register、/smsVerification、/retrieve-password、/pub-config | — | 登录族 | LoginController.java:61-246 |
| /xiaozhi/agent/chat-history/download/{uuid}/current\|previous | GET | 聊天记录 txt 下载 | AgentChatHistoryController.java:103-191 |
| /xiaozhi/agent/play/{uuid}、/voiceClone/play/{uuid} | GET | 一次性音频播放 | AgentController.java:282-300；VoiceCloneController.java:148+ |

## A-3 admin 反向 WebSocket 指令（非 HTTP）

| 通道 | 消息 | 发起 | 实现 |
|---|---|---|---|
| admin→python WS（targetWs 来自 server.websocket） | `{"type":"server","action":"restart\|update_config","content":{"secret":...}}`；python 回 `{"type":"server","status":"success",...}` | POST /xiaozhi/admin/server/emit-action（superAdmin） | ServerSideManageController.java:66-138；python 侧 serverMessageHandler.py:18-92 |
| admin→python MCP 端点 WS | JSON-RPC initialize/tools/list（探测智能体 MCP 工具） | GET /agent/mcp/tools/{agentId} | AgentMcpAccessPointServiceImpl.java:54-173 |

## A-4 admin↔python 共享 Redis key（无 pub/sub）

`server:config`、`tmp_register_mac:{deviceId}`（管理端代查标记）、`sys:params`、`model:data:{id}`、`ota:activation:*`、`agent:device:*` 等（RedisKeys.java:8-197）。

---

# 附表 B：前端页面 → 后端接口映射（主链）

| 前端页面/组件 | 后端接口（均含 /xiaozhi 前缀） | 后端 Controller:行号 |
|---|---|---|
| login/register/retrieve | POST /user/login；POST /user/register；PUT /user/retrieve-password；GET /user/captcha；GET /user/pub-config；POST /user/smsVerification | LoginController.java:89,113,176,61,217,70 |
| home.vue 智能体列表 | GET /agent/list；POST /agent；DELETE /agent/{id} | AgentController.java:99,133,187 |
| roleConfig.vue 智能体编辑 | GET /agent/{id}；PUT /agent/{id}；GET /agent/template；GET /models/names、/models/llm/names、/models/{modelId}/voices；GET\|POST /agent/mcp/address\|tools/{agentId}；GET\|PUT /agent/{id}/tags；GET /agent/{agentId}/snapshots… | AgentController.java:125,179,195；ModelController.java:47,56,166；AgentMcpAccessPointController.java:36,54；AgentController.java:330,339；AgentSnapshotController.java:36-64 |
| DeviceManagement.vue | GET /device/bind/{agentId}；POST /device/bind/{agentId}（在线状态代理）；POST /device/bind/{agentId}/{code}；POST /device/unbind；PUT /device/update/{id}；POST /device/manual-add；GET dict FIRMWARE_TYPE | DeviceController.java:86,95,57,106,115,134 |
| 设备聊天记录（ChatHistoryDialog） | GET /agent/{id}/sessions；GET /agent/{id}/chat-history/{sessionId}；POST /agent/audio/{audioId}；GET /agent/play/{uuid}；POST /agent/chat-history/getDownloadUrl/…；GET /agent/chat-history/download/{uuid}/… | AgentController.java:204,220,268,282；AgentChatHistoryController.java:78,103,136 |
| ModelConfig.vue | GET /models/list；GET /models/{modelType}/provideTypes；POST\|PUT /models/…；PUT /models/enable/{id}/{status}；PUT /models/default/{id}；DELETE /models/{id} | ModelController.java:72,64,84,95,124,143,107 |
| VoiceResource / ttsVoice | GET/POST /ttsVoice；PUT /ttsVoice/{id}；POST /ttsVoice/delete | TimbreController.java:42,64,73,84 |
| VoiceCloneManagement | POST /voiceClone/upload；POST /voiceClone/updateName；POST /voiceClone/audio/{id}；GET /voiceClone/play/{uuid}；POST /voiceClone/cloneAudio；GET /voiceResource/ttsPlatforms | VoiceCloneController.java:64,108,133,148,180；VoiceResourceController.java:109 |
| UserManagement | GET /admin/users；PUT /admin/users/{id}；DELETE /admin/users/{id}；PUT /admin/users/changeStatus/{status} | AdminController.java:46,65,74,82 |
| ParamsManagement / FeatureManagement | GET admin/params/page；GET admin/params/{id}；POST\|PUT admin/params；POST admin/params/delete | SysParamsController.java:56,72,81,94,161 |
| ServerSideManager | GET /admin/server/server-list；POST /admin/server/emit-action | ServerSideManageController.java:55,66 |
| OtaManagement | GET\|POST /otaMag；GET\|PUT\|DELETE /otaMag/{id}；POST /otaMag/upload；GET /otaMag/getDownloadUrl/{id} | OTAMagController.java:63,84,76,119,108,244,135 |
| DictManagement | /admin/dict/type/**、/admin/dict/data/** | SysDictTypeController.java:41-84；SysDictDataController.java:44-97 |
| ProviderManagement | GET /models/provider；POST\|PUT /models/provider；POST /models/provider/delete；GET /models/provider/plugin/names | ModelProviderController.java:28-69 |
| KnowledgeBase | GET\|POST\|PUT\|DELETE /datasets…；GET\|POST /datasets/{id}/documents…；POST /datasets/retrieval-test；GET /datasets/rag-models | KnowledgeBaseController.java:42-156；KnowledgeFilesController.java:57-191 |
| ReplacementWordManagement | POST\|PUT\|GET /correct-word/file…；DELETE /correct-word/file/{id}；POST /correct-word/file/batch-delete | CorrectWordController.java:43-106 |
| AddressBookManagement | GET /device/address-book/{mac}；PUT /device/address-book/alias；PUT /device/address-book/permission | DeviceController.java:173,191,204 |
| AgentTemplateManagement | GET /agent/template/page；GET\|POST\|PUT\|DELETE /agent/template…；POST /agent/template/batch-remove | AgentTemplateController.java:44-147 |

---

# 开发提示（易踩的坑）

1. 写"admin WebSocket 实时看设备"相关功能前，先按 §4.4/§9.1 的事实理解现状：设备实时状态 = HTTP 代理 MQTT 管理器；admin→python 指令 = Java WS 客户端；manager-api 不监听任何 WebSocket 端口。
2. `/config/**` 鉴权只有 `server.secret` 单串全等比较——secret 泄露即等于全配置（含模型 API key 明文）泄露。
3. 配置缓存失效是"写时重建"模式：所有改参数/模型的地方必须手动调 `configService.getConfig(false)`；新增改动点遗漏调用会导致 python 读到旧 `server:config`。
4. 设备激活状态在 Redis（`ota:activation:*`）——Redis 数据丢失 = 未完成激活的设备全部需重新走激活码流程。
5. 版本号 `Constant.VERSION`（Constant.java:327）一变即全量清 Redis，升级发布时所有缓存（含 model:data、timbre:details）冷启动。
