"""儿童长期记忆 HTTP 面（工单 #10，家长页能力）。

家长页不直连本服务：manager-api 代理 controller（oauth2 + 智能体归属
校验）携带 server secret 到这里，本层只校验 Bearer 密钥 ==
server.auth_key（默认部署下 auth_key 回退 manager-api.secret，两侧一致）。

路由挂在 SimpleHttpServer（8003）：
- GET  /xiaozhi/kids/memory/list?role_id=<mac>
- POST /xiaozhi/kids/memory/delete?role_id=<mac>   body {"id": <int>}
- POST /xiaozhi/kids/memory/clear?role_id=<mac>

role_id 必填（manager-api 侧按 agentId 解析出其设备 mac 传入，即
mem_kids 的存储键/连接 device-id）；不带 role_id 的全局「最近活跃实例」
回退是跨家庭越权面，HTTP 面不再暴露。
数据操作走 mem_kids 模块级 list_for_role/delete_for_role/clear_for_role。
"""
import hmac
import json

from aiohttp import web

from config.logger import setup_logging
from core.api.base_handler import BaseHandler
from core.providers.memory.mem_kids import mem_kids

TAG = __name__


class KidsMemoryHandler(BaseHandler):
    def __init__(self, config: dict):
        super().__init__(config)
        self.auth_key = config.get("server", {}).get("auth_key", "")

    def _authorized(self, request) -> bool:
        header = request.headers.get("Authorization", "")
        return bool(self.auth_key) and hmac.compare_digest(
            header.encode("utf-8"), f"Bearer {self.auth_key}".encode("utf-8")
        )

    def _unauthorized(self) -> web.Response:
        return web.Response(
            text=json.dumps({"success": False, "message": "无效的服务器密钥"}),
            content_type="application/json",
            status=401,
        )

    @staticmethod
    def _ok(data) -> web.Response:
        return web.Response(
            text=json.dumps({"success": True, "data": data}, ensure_ascii=False),
            content_type="application/json",
        )

    def _fail(self, message: str) -> web.Response:
        self.logger.bind(tag=TAG).error(f"儿童记忆接口异常: {message}")
        return web.Response(
            text=json.dumps({"success": False, "message": message}, ensure_ascii=False),
            content_type="application/json",
        )

    @staticmethod
    def _role_id(request) -> str:
        return request.query.get("role_id", "").strip()

    async def handle_list(self, request):
        if not self._authorized(request):
            return self._unauthorized()
        role_id = self._role_id(request)
        if not role_id:
            return self._fail("缺少 role_id 参数")
        try:
            return self._ok(mem_kids.list_for_role(role_id))
        except Exception as e:
            return self._fail(f"读取儿童记忆失败: {e}")

    async def handle_delete(self, request):
        if not self._authorized(request):
            return self._unauthorized()
        role_id = self._role_id(request)
        if not role_id:
            return self._fail("缺少 role_id 参数")
        try:
            body = await request.json()
            entry_id = int(body["id"])
        except Exception:
            return self._fail("请求体应为 {\"id\": <整数>}")
        try:
            return self._ok(mem_kids.delete_for_role(entry_id, role_id))
        except Exception as e:
            return self._fail(f"删除儿童记忆失败: {e}")

    async def handle_clear(self, request):
        if not self._authorized(request):
            return self._unauthorized()
        role_id = self._role_id(request)
        if not role_id:
            return self._fail("缺少 role_id 参数")
        try:
            mem_kids.clear_for_role(role_id)
            return self._ok(True)
        except Exception as e:
            return self._fail(f"清除儿童记忆失败: {e}")
