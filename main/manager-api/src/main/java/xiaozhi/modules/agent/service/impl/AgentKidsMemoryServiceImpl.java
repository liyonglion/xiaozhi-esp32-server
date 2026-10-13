package xiaozhi.modules.agent.service.impl;

import java.util.List;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;

import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.user.UserDetail;
import xiaozhi.modules.agent.service.AgentKidsMemoryService;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.security.user.SecurityUser;
import xiaozhi.modules.sys.service.SysParamsService;

/**
 * 儿童长期记忆代理服务实现（工单 #10）
 *
 * <p>
 * 转发到 Python 8003（xiaozhi.kids-memory.base-url），鉴权用与
 * 小智服务上报相同的 server.secret（Python 侧校验 server.auth_key，
 * 默认部署两者一致——都来自 manager-api.secret，见 docs/kids-companion.md）。
 *
 * <p>
 * 记忆按 role_id 精确定位：agentId → 该智能体名下设备的 mac_address
 * （即 Python 连接的 device-id 与 mem_kids 存储键），逐台转发；不落到
 * Python 侧的全局「最近活跃实例」回退（那是跨家庭越权面）。
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
@Slf4j
@Service
public class AgentKidsMemoryServiceImpl implements AgentKidsMemoryService {

    private final SysParamsService sysParamsService;
    private final DeviceService deviceService;
    private final RestTemplate restTemplate;
    private final String baseUrl;

    public AgentKidsMemoryServiceImpl(SysParamsService sysParamsService, DeviceService deviceService,
            RestTemplate restTemplate,
            @Value("${xiaozhi.kids-memory.base-url:http://127.0.0.1:8003}") String baseUrl) {
        this.sysParamsService = sysParamsService;
        this.deviceService = deviceService;
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl;
    }

    @Override
    public JsonNode list(String agentId) {
        DeviceEntity device = kidsDeviceOf(agentId);
        if (device == null) {
            return JsonNodeFactory.instance.arrayNode();
        }
        return unwrap(call(() -> restTemplate.exchange(
                roleUrl("/xiaozhi/kids/memory/list", device.getMacAddress()),
                HttpMethod.GET, new HttpEntity<>(authHeaders()), JsonNode.class).getBody()));
    }

    @Override
    public Boolean delete(String agentId, Long entryId) {
        DeviceEntity device = kidsDeviceOf(agentId);
        if (device == null) {
            return Boolean.FALSE;
        }
        // entryId 来自路径变量（Long），无注入面
        String body = "{\"id\":" + entryId + "}";
        JsonNode data = unwrap(call(() -> restTemplate.postForObject(
                roleUrl("/xiaozhi/kids/memory/delete", device.getMacAddress()),
                jsonEntity(body), JsonNode.class)));
        return data.asBoolean(false);
    }

    @Override
    public Boolean clear(String agentId) {
        DeviceEntity device = kidsDeviceOf(agentId);
        if (device == null) {
            return Boolean.FALSE;
        }
        JsonNode data = unwrap(call(() -> restTemplate.postForObject(
                roleUrl("/xiaozhi/kids/memory/clear", device.getMacAddress()),
                jsonEntity("{}"), JsonNode.class)));
        return data.asBoolean(false);
    }

    /**
     * 智能体名下的孩子设备（归属已在 controller 校验）。
     * ponytail: 单家庭单孩子假设——一个智能体取第一台设备；多孩子设备时
     * 需按 device 逐台定位（entry id 按 role 独立编号），届时再扩展。
     */
    private DeviceEntity kidsDeviceOf(String agentId) {
        UserDetail user = SecurityUser.getUser();
        List<DeviceEntity> devices = deviceService.getUserDevices(user.getId(), agentId);
        return devices.isEmpty() ? null : devices.get(0);
    }

    /** 端点 URL + role_id 查询参数（mem_kids 存储键 = 设备 mac） */
    private String roleUrl(String path, String macAddress) {
        return baseUrl + path + "?role_id=" + macAddress;
    }

    private HttpHeaders authHeaders() {
        String secret = sysParamsService.getValue(Constant.SERVER_SECRET, true);
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Bearer " + secret);
        return headers;
    }

    private HttpEntity<String> jsonEntity(String body) {
        HttpHeaders headers = authHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        return new HttpEntity<>(body, headers);
    }

    /** Python 统一返回 {"success":..,"data":..,"message":..}：失败抛 RenException */
    private JsonNode unwrap(JsonNode root) {
        if (root == null) {
            throw new RenException("儿童记忆服务无响应");
        }
        if (!root.path("success").asBoolean(false)) {
            throw new RenException(root.path("message").asText("儿童记忆服务返回失败"));
        }
        // path() 防契约漂移（data 缺失时 MissingNode 安全降级，不 NPE）
        return root.path("data");
    }

    private <T> T call(PythonCall<T> call) {
        try {
            return call.get();
        } catch (HttpStatusCodeException e) {
            // 4xx/5xx 是「服务在但拒绝了」（如 401 密钥不符），别误报成「服务未启动」
            log.error("儿童记忆服务返回错误状态 {}: {}", e.getStatusCode(), e.getResponseBodyAsString());
            throw new RenException("儿童记忆服务返回错误（HTTP " + e.getStatusCode().value() + "）", e);
        } catch (RestClientException e) {
            log.error("儿童记忆服务调用失败: {}", e.getMessage());
            throw new RenException("儿童记忆服务不可达，请确认小智服务已启动（" + baseUrl + "）", e);
        }
    }

    @FunctionalInterface
    private interface PythonCall<T> {
        T get();
    }
}
