# 儿童陪伴模式部署与验证（家长页收官，工单 #10）

单家庭自用部署。三个可部署件：`main/xiaozhi-server`（Python，WS 8000 +
HTTP 8003）、`main/manager-api`（Java，8002）、`main/manager-web`（Vue2）。
功能总览见 `GLOSSARY.md` 儿童陪伴模式块。

## 1. read_config_from_api：文件模式 ↔ 智控台模式切换

开关就是 `main/xiaozhi-server/data/.config.yaml` 里的 `manager-api.url`
（分支行为由 `tests/config/test_config_loader.py` 锁定）：

- **文件模式（默认）**：`data/.config.yaml` 不填 `manager-api` 块（或只
  留 `log.log_dir` 等本地项）。全部配置走 `config.yaml` + `data/.config.yaml`
  合并；儿童模式配置 = config.yaml 顶层 `kids` 块 + `Memory.mem_kids`。
- **智控台模式（read_config_from_api）**：把
  `main/xiaozhi-server/config_from_api.yaml` 复制为
  `main/xiaozhi-server/data/.config.yaml`，填 `manager-api.url` 与
  `manager-api.secret`（参数管理页里 `server.secret` 的值）。此模式下：

  | 儿童模式配置 | 智控台落点 |
  |---|---|
  | 孩子档案 + 儿童模式开关 | 智能体编辑（家长页「孩子档案」区块）→ `ai_agent.kid_profile`，随 per-agent 配置下发（键名 `kids`） |
  | 长期记忆 provider | 模型管理建 `mem_kids` 类型记忆模型，智能体绑定 |
  | 后台任务小模型（安全分类/记忆抽取/压缩） | 智能体的 SLM 槽位（小模型） |
  | 童声音色 | 音色管理（如 cosyvoice-v2 + longhuhu） |

切换后重启 xiaozhi-server 生效。

## 2. 家长页

入口：manager-web 顶栏「家长页」（`/kids-parent`，支持 `?agentId=` 直达）。
一个页面三块：

- **孩子档案**：`enabled` 开关、称呼、出生年月（必填项，开儿童模式时校验）、
  性格/爱好/嘱托/个性化禁忌（可选）。保存走 `PUT /agent/{id}` 的
  `kidProfile` 字段，经配置快照通道即时下发（无需重启、无需重连）。
- **拦截日志**：`GET /agent/interception-log/list/{agentId}`，时间倒序、
  环形 500 条（care/redline 永不挤出）；care/redline 行标红。
- **长期记忆**：`GET /agent/kids-memory/list/{agentId}` 列表，
  `DELETE /agent/kids-memory/{agentId}/{entryId}` 逐条删除，
  `POST /agent/kids-memory/clear/{agentId}` 全量清除（条目+滚动摘要）。

## 3. 记忆 HTTP 面与密钥一致性

家长页的长期记忆请求由 manager-api 代理（浏览器不直连小智服务）：

```
manager-web ──oauth2──> manager-api /agent/kids-memory/*
                          │  Bearer <server.secret>（参数管理）
                          ▼
              xiaozhi-server :8003 /xiaozhi/kids/memory/{list,delete,clear}
```

- manager-api 侧转发地址：`application.yml`
  `xiaozhi.kids-memory.base-url`（默认 `http://127.0.0.1:8003`，与
  xiaozhi-server `server.http_port` 一致；分机部署改成对应内网地址）。
- Python 侧校验 `Authorization: Bearer <server.auth_key>`。默认部署
  `server.auth_key` 未单独配置时回退 `manager-api.secret`，两侧天然一致；
  若在 `data/.config.yaml` 显式配置了 `server.auth_key`，它必须等于
  manager-api 参数管理里的 `server.secret`。
- 记忆按「活跃连接实例优先，文件 fallback」定位（单家庭单孩子设备假设，
  多孩子设备需扩展 deviceId 透传）。

## 4. 验证清单

已本地模拟验证（无真实设备/密钥）：

- [x] Python：记忆 HTTP 面鉴权与三端点（真实 aiohttp 路由冒烟 +
  `tests/core/api/test_kids_memory_handler.py`）
- [x] Python：`load_config` 两模式分支（`tests/config/test_config_loader.py`）
- [x] Python：mem_kids 家长页操作活跃实例/文件 fallback、API 模式持久化
  （`tests/core/providers/memory/test_mem_kids.py`、
  `tests/core/test_kids_config.py`）
- [x] manager-api：代理 URL/密钥头/解包/不可达错误映射
  （`AgentKidsMemoryServiceImplTest`）

真部署人工验收项：

1. 切 read_config_from_api（§1），重启 xiaozhi-server，设备对话正常。
2. 家长页改档案（如称呼）→ 保存 → 设备下一轮对话立即用新称呼（快照即时
   生效）。
3. 让设备触发一次拦截（如问红线话题）→ 家长页拦截日志出现该条且标红。
4. 家长页删除一条记忆 → 设备下轮对话不再「记得」该条；全量清除同理。
5. care 类（自残/受虐暗示）日志在 500 条环形挤出后仍在（豁免）。

手工冒烟（服务起来后）：

```bash
# 密钥用参数管理里的 server.secret
curl -H "Authorization: Bearer <server.secret>" \
  http://127.0.0.1:8003/xiaozhi/kids/memory/list
```
