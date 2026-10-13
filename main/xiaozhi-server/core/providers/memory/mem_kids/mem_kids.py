"""儿童长期记忆 + 滚动摘要 provider（工单 #7，对齐小布（源工程）L3/L4 规则）。

- 长期记忆（L3）：条目列表 {id, ts, text}，上限 100 条，ts 升序注入
  <memory>（【小智记住的事】格式）。
- 记忆抽取：LLM（连接上为 conn.slm）按抽取指令输出 JSON add/delete
  操作；住址/证件号/电话号码本地硬排除（正则兜底，指令排除之外的保险）。
- 滚动摘要（L4）：每 20 轮把旧摘要+近窗压成 ≤300 字三要素摘要（事实、
  未完话题、情绪基调），注入 <summary>（【前面聊过的】格式）。
- 家长页能力：list_memories / delete_memory / clear_memory（实例方法）+
  模块级 list_for_role / delete_for_role / clear_for_role（HTTP 面经
  core/api/kids_memory_handler.py 到达，工单 #10：活跃实例优先、文件
  fallback）。

存储：data/.memory_kids.yaml，按 role_id（device_id）隔离，条目跨连接
持久；滚动摘要一并持久，跨连接滚动。provider 实例为进程内共享（先例：
mem_local_short），按「单家庭单活跃连接」假设运行。

# ponytail: 实例状态（entries/摘要/水位）无锁共享，多连接同角色并发
# 会互相覆盖；单家庭部署够用，多租户时改按 role_id 加锁或每连接一实例。
"""
from ..base import MemoryProviderBase, logger
import json
import os
import re
import time

import yaml

from config.config_loader import get_project_dir

TAG = __name__

# 与小布（源工程）xb_core.c 的常量对齐
MEM_MAX = 100          # 长期记忆条数上限
MEM_TEXT_MAX = 30      # 单条记忆字数上限（按字符计）
SUMMARY_MAX = 300      # 滚动摘要字数上限
COMPACT_TURNS = 20     # 每 20 轮触发一次抽取+窗口压缩

# 抽取指令（xb_core.c EXTRACT_INSTR 逐字）
EXTRACT_INSTR = """你是孩子长期记忆的管理器。根据下面的材料维护记忆清单，输出要执行的操作。
规则：
1. 只记孩子亲口说过的稳定事实（喜好、上学的班、家里的事、提到的人），一条一行简短事实，不超过 30 个字。
2. 对话里出现新事实就新增；换个说法重述已有事实不要新增，不产生重复条目。
3. 孩子的话和现有记忆矛盾（比如不再喜欢某个东西了），删除对应旧条目，需要的话再新增一条新的。
4. 家庭住址、证件号、电话号码这类敏感信息绝对不记录。
5. 现有记忆满 100 条时，每新增一条就要同时删除一条最不重要的旧条目。
6. 没有要变更的就输出空数组。
只输出一个 JSON 数组，不要解释、不要用代码块。元素形如 {"op":"add","text":"喜欢恐龙"} 或 {"op":"delete","id":3}"""

# 压缩指令（xb_core.c COMPACT_INSTR 逐字）
COMPACT_INSTR = """你是对话记录压缩器。把旧摘要和对话记录合并成一段不超过 300 字的新摘要，保留三要素：一、孩子讲过的事实（喜好、家事、提到的人）；二、正在聊的话题和没聊完的线索；三、孩子的情绪基调。只总结对话记录里孩子和小智说过的话，系统设定、人设、孩子档案都不进摘要。直接输出新摘要正文，不要客套开头。"""

# 敏感信息硬排除（指令第 4 条之外的本地兜底；宁可错杀不可漏过）
SENSITIVE_PATTERNS = [
    re.compile(r"1[3-9]\d{9}"),        # 手机号
    re.compile(r"\d{3,4}-\d{7,8}"),    # 座机
    re.compile(r"\d{17}[0-9Xx]"),      # 18 位证件号
    re.compile(r"(?<!\d)\d{15}(?!\d)"),  # 15 位证件号
    re.compile(r"家住|住在|地址"),       # 住址表述
    re.compile(r"\d+号楼|\d+单元|\d+室"),  # 门牌
]


def _is_sensitive(text: str) -> bool:
    return any(p.search(text) for p in SENSITIVE_PATTERNS)


# ---- 家长页 HTTP 面支撑（工单 #10）----
# 活跃实例登记：role_id -> 最近一次 init_memory 的实例。不主动注销——
# 单家庭下死实例残留无害，同 role 新连接会覆盖登记。
_INSTANCES: dict = {}

_STORE_PATH = get_project_dir() + "data/.memory_kids.yaml"


def _read_role_store(role_id, path=None) -> dict:
    path = path or _STORE_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            all_roles = yaml.safe_load(f) or {}
        return all_roles.get(role_id) or {}
    except Exception as e:
        logger.bind(tag=TAG).error(f"读儿童记忆文件失败: {e}")
        return {}


def _write_role_store(role_id, data: dict, path=None) -> None:
    path = path or _STORE_PATH
    try:
        all_roles = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                all_roles = yaml.safe_load(f) or {}
        all_roles[role_id] = data
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(all_roles, f, allow_unicode=True)
    except Exception as e:
        logger.bind(tag=TAG).error(f"写儿童记忆文件失败: {e}")


def _read_all_roles(path=None) -> dict:
    path = path or _STORE_PATH
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.bind(tag=TAG).error(f"读儿童记忆文件失败: {e}")
        return {}


def _newest_role_id(all_roles: dict):
    """文件里最近活跃的 role（按条目最大 ts）。"""

    def newest_ts(v):
        return max((e.get("ts", 0) for e in (v or {}).get("entries", [])), default=0)

    return max(all_roles, key=lambda k: newest_ts(all_roles[k]), default=None)


def _active_instance(role_id=None):
    if role_id is not None:
        return _INSTANCES.get(role_id)
    # ponytail: 单家庭单孩子设备——无 role 时取最近登记的实例；
    # 多孩子设备时家长页需带 deviceId 精确定位（HTTP 面预留 role_id 参数）。
    return next(reversed(list(_INSTANCES.values())), None)


def list_for_role(role_id=None) -> list:
    """家长页列表：优先活跃实例（内存态即时），否则读文件。"""
    inst = _active_instance(role_id)
    if inst is not None:
        return inst.list_memories()
    if role_id is None:
        all_roles = _read_all_roles()
        role_id = _newest_role_id(all_roles)
        if role_id is None:
            return []
    entries = _read_role_store(role_id).get("entries", []) or []
    return sorted(entries, key=lambda e: e["ts"])


def delete_for_role(entry_id: int, role_id=None) -> bool:
    """家长页逐条删除：走活跃实例（内存/文件同步），否则直改文件。"""
    inst = _active_instance(role_id)
    if inst is not None:
        return inst.delete_memory(entry_id)
    if role_id is None:
        role_id = _newest_role_id(_read_all_roles())
        if role_id is None:
            return False
    data = _read_role_store(role_id)
    entries = [e for e in data.get("entries", []) or [] if e.get("id") != entry_id]
    removed = len(entries) < len(data.get("entries", []) or [])
    if removed:
        _write_role_store(role_id, {"entries": entries, "summary": data.get("summary", "")})
    return removed


def clear_for_role(role_id=None) -> None:
    """家长页全量清除：条目与滚动摘要一起清（隐私边界）。"""
    inst = _active_instance(role_id)
    if inst is not None:
        inst.clear_memory()
        return
    if role_id is None:
        role_id = _newest_role_id(_read_all_roles())
        if role_id is None:
            return
    _write_role_store(role_id, {"entries": [], "summary": ""})


class MemoryProvider(MemoryProviderBase):
    def __init__(self, config, summary_memory):
        super().__init__(config)
        self.memory_path = _STORE_PATH
        self.save_to_file = True
        self.entries = []      # [{id, ts, text}]，ts 升序
        self.summary = ""      # 滚动摘要（L4）
        self._next_id = 1
        self._last_ts = 0
        # 近窗水位（已处理的消息数，按 user/assistant 非临时消息计）
        self._extracted_upto = 0
        self._compacted_upto = 0
        self._turn_count = 0  # 距上次压缩的回合数
        self.load_memory(summary_memory)

    def init_memory(
        self, role_id, llm, summary_memory=None, save_to_file=True, **kwargs
    ):
        super().init_memory(role_id, llm, **kwargs)
        self.save_to_file = save_to_file
        if role_id is not None:
            _INSTANCES[role_id] = self
        self.load_memory(summary_memory)

    def load_memory(self, summary_memory):
        self.entries = []
        self.summary = ""
        self._next_id = 1
        self._last_ts = 0
        # 新连接（共享实例再次 init_memory）对话窗口从零起算，水位必须重置
        self._extracted_upto = 0
        self._compacted_upto = 0
        self._turn_count = 0
        data = self._read_store()
        if data:
            self.entries = sorted(data.get("entries", []), key=lambda e: e["ts"])
            self.summary = data.get("summary", "") or ""
        if not self.summary and summary_memory:
            # API 模式种子（先例：mem_local_short）：无本地摘要时用下发摘要
            self.summary = summary_memory
        if self.entries:
            self._next_id = max(e["id"] for e in self.entries) + 1
            self._last_ts = max(e["ts"] for e in self.entries)

    def _read_store(self) -> dict:
        return _read_role_store(self.role_id, path=self.memory_path)

    def _write_store(self):
        if not self.save_to_file:
            return
        _write_role_store(
            self.role_id,
            {"entries": self.entries, "summary": self.summary},
            path=self.memory_path,
        )

    async def query_memory(self, query: str) -> str:
        """L3 注入串：全量条目 ts 升序，id/ts 不进 prompt；空集为空串。"""
        if not self.entries:
            return ""
        lines = ["【小智记住的事】"]
        lines += [f"- {e['text']}" for e in self.entries]
        return "\n".join(lines)

    def get_rolling_summary(self) -> str:
        """L4 注入串：【前面聊过的】+ 摘要正文；无摘要为空串。"""
        if not self.summary:
            return ""
        return f"【前面聊过的】\n{self.summary}"

    async def save_memory(self, msgs, session_id=None):
        """连接关闭触发：对剩余未抽取窗口跑一次记忆抽取。"""
        try:
            self._extract(msgs)
        except Exception as e:
            logger.bind(tag=TAG).error(f"儿童记忆抽取失败（连接关闭）: {e}")
        return None

    # ---- 家长页能力（HTTP 接口归后续票）----

    def list_memories(self) -> list:
        """逐条列出长期记忆（含 id/ts/text，家长页删除时用 id 定位）。"""
        return [dict(e) for e in self.entries]

    def delete_memory(self, entry_id: int) -> bool:
        """逐条删除；返回是否确实删了一条。"""
        before = len(self.entries)
        self.entries = [e for e in self.entries if e["id"] != entry_id]
        if len(self.entries) < before:
            self._write_store()
            return True
        return False

    def clear_memory(self) -> None:
        """全量清除：条目与滚动摘要一起清（隐私边界）。"""
        self.entries = []
        self.summary = ""
        self._write_store()

    # ---- 回合收尾后台趟（chat() depth==0 末尾挂点调用）----

    def on_turn_end(self, messages) -> None:
        """回合收尾：满 20 轮触发记忆抽取+窗口压缩；任何失败不抛出。"""
        try:
            self._turn_count += 1
            if self._turn_count < COMPACT_TURNS:
                return
            # 先抽取再压缩（小布（源工程）maybe_compact 顺序）
            self._extract(messages)
            self._compact(messages)
            self._turn_count = 0
        except Exception as e:
            # 失败退化：摘要/条目/水位不动，下个触发点自然重试
            logger.bind(tag=TAG).error(f"儿童记忆后台趟失败（下轮重试）: {e}")

    # ---- 内部 ----

    @staticmethod
    def _plain_content(content) -> str:
        """剥掉 ASR 说话人 JSON 包装，取 content 字段（先例 mem_local_short）。"""
        try:
            if content and content.strip().startswith("{") and content.strip().endswith("}"):
                data = json.loads(content)
                if "content" in data:
                    return data["content"]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
        return content or ""

    def _extract(self, messages) -> None:
        """对未抽取窗口跑一次 LLM 记忆抽取并应用操作；成功才推进水位。"""
        if self.llm is None:
            return
        window = self._window(messages, self._extracted_upto)
        if not window:
            return
        lines = []
        if self.summary:
            lines.append(f"【旧摘要】\n{self.summary}\n")
        lines.append("【对话记录】")
        for m in window:
            who = "孩子" if m.role == "user" else "小智"
            lines.append(f"{who}：{self._plain_content(m.content)}")
        lines.append("【现有记忆】")
        if self.entries:
            lines += [f"{e['id']}. {e['text']}" for e in self.entries]
        else:
            lines.append("（还没有记忆）")

        result = self.llm.response_no_stream(
            EXTRACT_INSTR, "\n".join(lines), max_tokens=2000, temperature=0.2
        )
        self._apply_ops(self._parse_ops(result))
        self._extracted_upto += len(window)
        self._write_store()

    @staticmethod
    def _parse_ops(result: str) -> list:
        """容错解析：取首个 [ 到末个 ] 的片段（小布（源工程）mem_apply 同款）。"""
        if not result:
            return []
        start, end = result.find("["), result.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            ops = json.loads(result[start : end + 1])
        except json.JSONDecodeError:
            return []
        return [o for o in ops if isinstance(o, dict) and o.get("op") in ("add", "delete")]

    def _apply_ops(self, ops: list) -> None:
        """先 delete 后 add；新增条目过四道闸：敏感/超长/去重/百条封顶。"""
        delete_ids = {
            o["id"] for o in ops if o.get("op") == "delete" and isinstance(o.get("id"), int)
        }
        if delete_ids:
            self.entries = [e for e in self.entries if e["id"] not in delete_ids]
        for o in ops:
            if o.get("op") != "add":
                continue
            text = str(o.get("text", "")).strip()
            if not text or len(text) > MEM_TEXT_MAX:
                continue
            if _is_sensitive(text):
                logger.bind(tag=TAG).info(f"拒收敏感记忆条目: {text}")
                continue
            if any(e["text"] == text for e in self.entries):
                continue
            if len(self.entries) >= MEM_MAX:
                # 小布（源工程）策略：满百未淘汰则拒新条目（最不重要归模型判断，不本地按 ts 丢）
                logger.bind(tag=TAG).warning("记忆满 100 条且模型未淘汰，拒新条目")
                continue
            ts = max(int(time.time() * 1000), self._last_ts + 1)
            self._last_ts = ts
            self.entries.append({"id": self._next_id, "ts": ts, "text": text})
            self._next_id += 1
        self.entries.sort(key=lambda e: e["ts"])

    def _compact(self, messages) -> None:
        """旧摘要+未压缩窗口 → ≤300 字三要素新摘要；成功才清水位。"""
        if self.llm is None:
            return
        window = self._window(messages, self._compacted_upto)
        if not window:
            return
        lines = []
        if self.summary:
            lines.append(f"【旧摘要】\n{self.summary}\n")
        lines.append("【对话记录】")
        for m in window:
            who = "孩子" if m.role == "user" else "小智"
            lines.append(f"{who}：{self._plain_content(m.content)}")

        result = self.llm.response_no_stream(
            COMPACT_INSTR, "\n".join(lines), max_tokens=800, temperature=0.2
        )
        summary = (result or "").strip()[:SUMMARY_MAX]
        if not summary:
            return  # 空输出视为失败：保留旧摘要与水位，下个触发点重试
        self.summary = summary
        self._compacted_upto += len(window)
        self._write_store()

    @staticmethod
    def _window(messages, upto: int) -> list:
        """过滤出 user/assistant 非临时消息中，第 upto 条之后的部分（快照）。"""
        chat_msgs = [
            m
            for m in messages
            if getattr(m, "role", None) in ("user", "assistant")
            and not getattr(m, "is_temporary", False)
            and getattr(m, "content", None)
        ]
        return chat_msgs[upto:]
