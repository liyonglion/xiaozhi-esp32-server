package xiaozhi.modules.agent.controller;

import java.util.List;

import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.user.UserDetail;
import xiaozhi.common.utils.Result;
import xiaozhi.modules.agent.dto.AgentInterceptionLogReportDTO;
import xiaozhi.modules.agent.service.AgentInterceptionLogService;
import xiaozhi.modules.agent.service.AgentService;
import xiaozhi.modules.agent.vo.AgentInterceptionLogVO;
import xiaozhi.modules.security.user.SecurityUser;

/**
 * 儿童陪伴模式拦截日志
 *
 * <p>
 * 上报端点走 server 过滤器（Python 服务 Bearer server.secret 认证，
 * 见 ShiroConfig）；查询端点走 oauth2 用户认证 + 智能体归属校验，供家长页展示。
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
@Tag(name = "儿童陪伴模式-拦截日志")
@RequiredArgsConstructor
@RestController
@RequestMapping("/agent/interception-log")
public class AgentInterceptionLogController {
    private final AgentInterceptionLogService agentInterceptionLogService;
    private final AgentService agentService;

    /**
     * 小智服务拦截日志上报（回合结束整批上报）
     *
     * @param request MAC地址 + 拦截事件列表
     */
    @Operation(summary = "小智服务拦截日志上报")
    @PostMapping("/report")
    public Result<Boolean> report(@Valid @RequestBody AgentInterceptionLogReportDTO request) {
        return new Result<Boolean>().ok(agentInterceptionLogService.report(request));
    }

    /**
     * 查询智能体拦截日志（按时间倒序）
     *
     * @param agentId 智能体ID
     */
    @Operation(summary = "查询智能体拦截日志（按时间倒序）")
    @RequiresPermissions("sys:role:normal")
    @GetMapping("/list/{agentId}")
    public Result<List<AgentInterceptionLogVO>> list(@PathVariable("agentId") String agentId) {
        UserDetail user = SecurityUser.getUser();
        if (!agentService.checkAgentPermission(agentId, user.getId())) {
            throw new RenException(ErrorCode.CHAT_HISTORY_NO_PERMISSION);
        }
        return new Result<List<AgentInterceptionLogVO>>().ok(agentInterceptionLogService.listByAgentId(agentId));
    }
}
