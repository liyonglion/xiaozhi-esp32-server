package xiaozhi.modules.agent.controller;

import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import com.fasterxml.jackson.databind.JsonNode;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.user.UserDetail;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.agent.service.AgentKidsMemoryService;
import xiaozhi.modules.agent.service.AgentService;
import xiaozhi.modules.security.user.SecurityUser;

/**
 * 儿童陪伴模式家长页-长期记忆
 *
 * <p>
 * 家长页经本端点（oauth2 用户认证 + 智能体归属校验）转发到小智服务
 * Python 8003，浏览器不直连小智服务。单家庭单孩子设备假设下记忆按
 * 活跃实例定位（多孩子设备需扩展 deviceId 透传，见 docs/kids-companion.md）。
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
@Tag(name = "儿童陪伴模式-家长页长期记忆")
@RequiredArgsConstructor
@RestController
@RequestMapping("/agent/kids-memory")
public class AgentKidsMemoryController {
    private final AgentKidsMemoryService agentKidsMemoryService;
    private final AgentService agentService;

    /**
     * 查询儿童长期记忆列表
     *
     * @param agentId 智能体ID
     */
    @Operation(summary = "查询儿童长期记忆列表")
    @RequiresPermissions("sys:role:normal")
    @GetMapping("/list/{agentId}")
    public Result<JsonNode> list(@PathVariable("agentId") String agentId) {
        checkPermission(agentId);
        return new Result<JsonNode>().ok(agentKidsMemoryService.list());
    }

    /**
     * 逐条删除儿童长期记忆
     *
     * @param agentId 智能体ID
     * @param entryId 记忆条目ID
     */
    @Operation(summary = "逐条删除儿童长期记忆")
    @RequiresPermissions("sys:role:normal")
    @DeleteMapping("/{agentId}/{entryId}")
    public Result<Boolean> delete(@PathVariable("agentId") String agentId,
            @PathVariable("entryId") Long entryId) {
        checkPermission(agentId);
        return new Result<Boolean>().ok(agentKidsMemoryService.delete(entryId));
    }

    /**
     * 全量清除儿童长期记忆（条目与滚动摘要一起清）
     *
     * @param agentId 智能体ID
     */
    @Operation(summary = "全量清除儿童长期记忆")
    @RequiresPermissions("sys:role:normal")
    @PostMapping("/clear/{agentId}")
    public Result<Boolean> clear(@PathVariable("agentId") String agentId) {
        checkPermission(agentId);
        return new Result<Boolean>().ok(agentKidsMemoryService.clear());
    }

    private void checkPermission(String agentId) {
        UserDetail user = SecurityUser.getUser();
        if (!agentService.checkAgentPermission(agentId, user.getId())) {
            throw new RenException(ErrorCode.CHAT_HISTORY_NO_PERMISSION);
        }
    }
}
