package xiaozhi.modules.agent.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.sys.service.SysParamsService;

/**
 * 儿童长期记忆代理服务测试（工单 #10）。
 *
 * 被测行为：manager-api 把家长页的记忆请求转发到 Python 8003
 * （/xiaozhi/kids/memory/*），携带 Bearer server.secret；Python 返回
 * {"success":..,"data":..} 统一解包；Python 不可达/业务失败转 RenException。
 */
class AgentKidsMemoryServiceImplTest {

    private static final String BASE = "http://127.0.0.1:8003";

    private final SysParamsService sysParamsService = mock(SysParamsService.class);
    private final RestTemplate restTemplate = mock(RestTemplate.class);
    private final AgentKidsMemoryServiceImpl service =
            new AgentKidsMemoryServiceImpl(sysParamsService, restTemplate, BASE);

    private void stubSecret() {
        when(sysParamsService.getValue(Constant.SERVER_SECRET, true)).thenReturn("the-secret");
    }

    private static JsonNode payload(Object data) {
        return new ObjectMapper().valueToTree(Map.of("success", true, "data", data));
    }

    @Test
    void listCallsPythonWithSecretHeaderAndUnwrapsData() {
        stubSecret();
        when(restTemplate.exchange(eq(BASE + "/xiaozhi/kids/memory/list"), eq(HttpMethod.GET),
                any(HttpEntity.class), eq(JsonNode.class)))
                .thenReturn(ResponseEntity.ok(
                        payload(List.of(Map.of("id", 1, "ts", 100, "text", "喜欢恐龙")))));

        JsonNode data = service.list();

        assertEquals(1, data.size());
        assertEquals("喜欢恐龙", data.get(0).path("text").asText());
        @SuppressWarnings("unchecked")
        ArgumentCaptor<HttpEntity<Void>> captor = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).exchange(eq(BASE + "/xiaozhi/kids/memory/list"), eq(HttpMethod.GET),
                captor.capture(), eq(JsonNode.class));
        assertEquals("Bearer the-secret",
                captor.getValue().getHeaders().getFirst("Authorization"));
    }

    @Test
    void deletePostsIdBodyWithSecretHeader() {
        stubSecret();
        when(restTemplate.postForObject(eq(BASE + "/xiaozhi/kids/memory/delete"),
                any(HttpEntity.class), eq(JsonNode.class)))
                .thenReturn(payload(true));

        assertEquals(Boolean.TRUE, service.delete(7L));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<HttpEntity<String>> captor = ArgumentCaptor.forClass(HttpEntity.class);
        verify(restTemplate).postForObject(eq(BASE + "/xiaozhi/kids/memory/delete"),
                captor.capture(), eq(JsonNode.class));
        assertEquals("Bearer the-secret",
                captor.getValue().getHeaders().getFirst("Authorization"));
        assertEquals("{\"id\":7}", captor.getValue().getBody());
    }

    @Test
    void clearPostsToPython() {
        stubSecret();
        when(restTemplate.postForObject(eq(BASE + "/xiaozhi/kids/memory/clear"),
                any(HttpEntity.class), eq(JsonNode.class)))
                .thenReturn(payload(true));

        assertEquals(Boolean.TRUE, service.clear());
    }

    @Test
    void pythonUnreachableBecomesFriendlyRenException() {
        stubSecret();
        when(restTemplate.exchange(any(String.class), eq(HttpMethod.GET), any(),
                eq(JsonNode.class)))
                .thenThrow(new RestClientException("connect refused"));

        RenException e = assertThrows(RenException.class, () -> service.list());
        assertEquals("儿童记忆服务不可达，请确认小智服务已启动（" + BASE + "）", e.getMsg());
    }

    @Test
    void pythonBusinessFailureBecomesRenExceptionWithMessage() {
        stubSecret();
        when(restTemplate.postForObject(eq(BASE + "/xiaozhi/kids/memory/delete"),
                any(HttpEntity.class), eq(JsonNode.class)))
                .thenReturn(new ObjectMapper().valueToTree(
                        Map.of("success", false, "message", "删除儿童记忆失败")));

        RenException e = assertThrows(RenException.class, () -> service.delete(1L));
        assertEquals("删除儿童记忆失败", e.getMsg());
    }
}
