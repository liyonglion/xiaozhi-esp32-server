"""儿童长期记忆 HTTP 面（工单 #10，家长页能力）。

家长页不直连本服务：manager-api 代理 controller（oauth2 + 智能体归属
校验）携带 server secret 到这里，本层只校验 Bearer 密钥 ==
server.auth_key（默认部署下 auth_key 回退 manager-api.secret，两侧一致）。

路由挂在 SimpleHttpServer（8003）：
- GET  /xiaozhi/kids/memory/list
- POST /xiaozhi/kids/memory/delete   body {"id": <int>}
- POST /xiaozhi/kids/memory/clear

数据操作走 mem_kids 模块级 list_for_role/delete_for_role/clear_for_role
（活跃实例优先，文件 fallback）。单家庭单孩子设备假设见 mem_kids 注释。
"""
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
        return bool(self.auth_key) and header == f"Bearer {self.auth_key}"

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

    async def handle_list(self, request):
        if not self._authorized(request):
            return self._unauthorized()
        try:
            return self._ok(mem_kids.list_for_role())
        except Exception as e:
            return self._fail(f"读取儿童记忆失败: {e}")

    async def handle_delete(self, request):
        if not self._authorized(request):
            return self._unauthorized()
        try:
            body = await request.json()
            entry_id = int(body["id"])
        except Exception:
            return self._fail("请求体应为 {\"id\": <整数>}")
        try:
            return self._ok(mem_kids.delete_for_role(entry_id))
        except Exception as e:
            return self._fail(f"删除儿童记忆失败: {e}")

    async def handle_clear(self, request):
        if not self._authorized(request):
            return self._unauthorized()
        try:
            mem_kids.clear_for_role()
            return self._ok(True)
        except Exception as e:
            return self._fail(f"清除儿童记忆失败: {e}")
