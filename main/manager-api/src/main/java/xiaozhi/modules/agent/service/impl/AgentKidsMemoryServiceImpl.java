package xiaozhi.modules.agent.service.impl;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import com.fasterxml.jackson.databind.JsonNode;

import lombok.extern.slf4j.Slf4j;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.agent.service.AgentKidsMemoryService;
import xiaozhi.modules.sys.service.SysParamsService;

/**
 * 儿童长期记忆代理服务实现（工单 #10）
 *
 * <p>
 * 转发到 Python 8003（xiaozhi.kids-memory.base-url），鉴权用与
 * 小智服务上报相同的 server.secret（Python 侧校验 server.auth_key，
 * 默认部署两者一致——都来自 manager-api.secret，见 docs/kids-companion.md）。
 *
 * @author lion
 * @version 1.0, 2026/10/13
 * @since 1.0.0
 */
@Slf4j
@Service
public class AgentKidsMemoryServiceImpl implements AgentKidsMemoryService {

    private final SysParamsService sysParamsService;
    private final RestTemplate restTemplate;
    private final String baseUrl;

    public AgentKidsMemoryServiceImpl(SysParamsService sysParamsService, RestTemplate restTemplate,
            @Value("${xiaozhi.kids-memory.base-url:http://127.0.0.1:8003}") String baseUrl) {
        this.sysParamsService = sysParamsService;
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl;
    }

    @Override
    public JsonNode list() {
        return unwrap(call(() -> restTemplate.exchange(baseUrl + "/xiaozhi/kids/memory/list",
                HttpMethod.GET, new HttpEntity<>(authHeaders()), JsonNode.class).getBody()));
    }

    @Override
    public Boolean delete(Long entryId) {
        // entryId 来自路径变量（Long），无注入面
        String body = "{\"id\":" + entryId + "}";
        JsonNode data = unwrap(call(() -> restTemplate.postForObject(
                baseUrl + "/xiaozhi/kids/memory/delete", jsonEntity(body), JsonNode.class)));
        return data.asBoolean(false);
    }

    @Override
    public Boolean clear() {
        JsonNode data = unwrap(call(() -> restTemplate.postForObject(
                baseUrl + "/xiaozhi/kids/memory/clear", jsonEntity("{}"), JsonNode.class)));
        return data.asBoolean(false);
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
        return root.get("data");
    }

    private <T> T call(PythonCall<T> call) {
        try {
            return call.get();
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
