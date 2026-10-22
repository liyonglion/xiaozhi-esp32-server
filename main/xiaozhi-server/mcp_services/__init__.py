"""在线服务扩展模块：每个外部服务一个子包（如 netease_mcp）。

注意：目录不能命名为 mcp——项目 core/providers/tools/server_mcp 依赖
pip 的官方 MCP SDK（import mcp.types），顶级 mcp 包会将其遮蔽导致服务无法启动。
"""
