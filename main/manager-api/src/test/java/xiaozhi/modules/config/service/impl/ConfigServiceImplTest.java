package xiaozhi.modules.config.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import xiaozhi.common.redis.RedisKeys;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.modules.agent.dao.AgentVoicePrintDao;
import xiaozhi.modules.agent.vo.AgentInfoVO;
import xiaozhi.modules.agent.service.AgentContextProviderService;
import xiaozhi.modules.agent.service.AgentMcpAccessPointService;
import xiaozhi.modules.agent.service.AgentPluginMappingService;
import xiaozhi.modules.agent.service.AgentService;
import xiaozhi.modules.agent.service.AgentTemplateService;
import xiaozhi.modules.correctword.service.CorrectWordFileService;
import xiaozhi.modules.device.entity.DeviceEntity;
import xiaozhi.modules.device.service.DeviceService;
import xiaozhi.modules.model.service.ModelConfigService;
import xiaozhi.modules.sys.dto.SysParamsDTO;
import xiaozhi.modules.sys.service.SysParamsService;
import xiaozhi.modules.timbre.service.TimbreService;
import xiaozhi.modules.voiceclone.service.VoiceCloneService;

class ConfigServiceImplTest {

    @Test
    void cachedServerConfigIsCheckedAsAStringKeyedMapWithoutChangingNestedValues() {
        RedisUtils redisUtils = mock(RedisUtils.class);
        Map<String, Object> nested = new HashMap<>();
        nested.put("enabled", true);
        Map<String, Object> cached = new HashMap<>();
        cached.put("features", nested);
        when(redisUtils.get(RedisKeys.getServerConfigKey())).thenReturn(cached);

        ConfigServiceImpl service = newService(mock(SysParamsService.class), redisUtils);

        Map<String, Object> result = service.getConfig(true);

        assertNotSame(cached, result);
        assertSame(nested, result.get("features"));
        assertEquals(true, ((Map<?, ?>) result.get("features")).get("enabled"));
    }

    @Test
    void nestedSystemParametersStillShareAndPopulateTheSameConfigBranch() {
        SysParamsService sysParamsService = mock(SysParamsService.class);
        SysParamsDTO enabled = parameter("server.features.enabled", "true", "boolean");
        SysParamsDTO labels = parameter("server.features.labels", "first;second", "array");
        when(sysParamsService.list(anyMap())).thenReturn(List.of(enabled, labels));
        ConfigServiceImpl service = newService(sysParamsService, mock(RedisUtils.class));
        Map<String, Object> config = new HashMap<>();

        Object returned = ReflectionTestUtils.invokeMethod(service, "buildConfig", config);

        assertSame(config, returned);
        Map<?, ?> server = assertInstanceOf(Map.class, config.get("server"));
        Map<?, ?> features = assertInstanceOf(Map.class, server.get("features"));
        assertEquals(true, features.get("enabled"));
        assertEquals(List.of("first", "second"), features.get("labels"));
    }

    private static SysParamsDTO parameter(String code, String value, String type) {
        SysParamsDTO parameter = new SysParamsDTO();
        parameter.setParamCode(code);
        parameter.setParamValue(value);
        parameter.setValueType(type);
        return parameter;
    }

    private static ConfigServiceImpl newService(SysParamsService sysParamsService, RedisUtils redisUtils) {
        return new ConfigServiceImpl(
                sysParamsService,
                mock(DeviceService.class),
                mock(ModelConfigService.class),
                mock(AgentService.class),
                mock(AgentTemplateService.class),
                redisUtils,
                mock(TimbreService.class),
                mock(AgentPluginMappingService.class),
                mock(AgentMcpAccessPointService.class),
                mock(AgentContextProviderService.class),
                mock(VoiceCloneService.class),
                mock(AgentVoicePrintDao.class),
                mock(CorrectWordFileService.class));
    }

    // ===== 孩子档案 per-agent 下发（工单 #6）=====

    private static ConfigServiceImpl newService(DeviceService deviceService, AgentService agentService) {
        return new ConfigServiceImpl(
                mock(SysParamsService.class),
                deviceService,
                mock(ModelConfigService.class),
                agentService,
                mock(AgentTemplateService.class),
                mock(RedisUtils.class),
                mock(TimbreService.class),
                mock(AgentPluginMappingService.class),
                mock(AgentMcpAccessPointService.class),
                mock(AgentContextProviderService.class),
                mock(VoiceCloneService.class),
                mock(AgentVoicePrintDao.class),
                mock(CorrectWordFileService.class));
    }

    private static DeviceService deviceServiceFor(String agentId) {
        DeviceEntity device = new DeviceEntity();
        device.setAgentId(agentId);
        DeviceService deviceService = mock(DeviceService.class);
        when(deviceService.getDeviceByMacAddress("aa:bb:cc:dd:ee:ff")).thenReturn(device);
        return deviceService;
    }

    private static AgentService agentServiceFor(AgentInfoVO agent) {
        AgentService agentService = mock(AgentService.class);
        when(agentService.getAgentById(agent.getId())).thenReturn(agent);
        return agentService;
    }

    @Test
    void kidsProfileIsDeliveredAsParsedMap() {
        // 档案 JSON（enabled + 档案子字段统一形状）随 agent-models 下发为 kids 块
        AgentInfoVO agent = new AgentInfoVO();
        agent.setId("agent-1");
        agent.setKidProfile("{\"enabled\":true,\"nickname\":\"小豆\",\"birth_ym\":\"2019-05\",\"taboos\":[\"不聊鬼故事\"]}");
        ConfigServiceImpl service = newService(deviceServiceFor("agent-1"), agentServiceFor(agent));

        Map<String, Object> result = service.getAgentModels("aa:bb:cc:dd:ee:ff", new HashMap<>());

        Map<?, ?> kids = assertInstanceOf(Map.class, result.get("kids"));
        assertEquals(true, kids.get("enabled"));
        assertEquals("小豆", kids.get("nickname"));
        assertEquals("2019-05", kids.get("birth_ym"));
        assertEquals(List.of("不聊鬼故事"), kids.get("taboos"));
    }

    @Test
    void blankKidProfileOmitsKidsKey() {
        AgentInfoVO agent = new AgentInfoVO();
        agent.setId("agent-1");
        ConfigServiceImpl service = newService(deviceServiceFor("agent-1"), agentServiceFor(agent));

        Map<String, Object> result = service.getAgentModels("aa:bb:cc:dd:ee:ff", new HashMap<>());

        assertFalse(result.containsKey("kids"));
    }

    @Test
    void invalidKidProfileJsonOmitsKidsKeyWithoutThrowing() {
        // 坏 JSON：跳过 kids 下发（Python 端退化为无档案），不炸整个配置接口
        AgentInfoVO agent = new AgentInfoVO();
        agent.setId("agent-1");
        agent.setKidProfile("{not-json");
        ConfigServiceImpl service = newService(deviceServiceFor("agent-1"), agentServiceFor(agent));

        Map<String, Object> result = service.getAgentModels("aa:bb:cc:dd:ee:ff", new HashMap<>());

        assertFalse(result.containsKey("kids"));
    }
}
