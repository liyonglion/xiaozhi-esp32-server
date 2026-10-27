package xiaozhi.modules.todo.service;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.LongSupplier;

import org.springframework.stereotype.Component;

/**
 * 设备在线状态注册表（spec #30 T2 / #32）：xiaozhi-server 每 60s 全量上报在线 mac 集合，
 * 每次上报整体替换；超过一个 TTL 未续报视为离线（xiaozhi-server 重启/宕机的兜底）。
 *
 * ponytail: 进程内 map，仅单实例 manager-api 部署下成立；多实例时改存 Redis（Java 侧已有客户端）。
 */
@Component
public class TodoOnlineRegistry {

    /** 上报周期 60s，TTL 150s（2.5 个周期）容忍一轮上报抖动 */
    public static final long TTL_MILLIS = 150_000L;

    private volatile Map<String, Long> lastSeen = new ConcurrentHashMap<>();
    private volatile LongSupplier clock = System::currentTimeMillis;

    /** 测试接缝：注入可控时钟 */
    public void setClock(LongSupplier clock) {
        this.clock = clock;
    }

    /** 全量上报：本轮未报的 mac 立即视为离线（集合即权威答案）。
     *  原子换新引用（不可变模式）：clear+putAll 的窗口期会让并发 isOnline 短暂看到全员离线。 */
    public void reportOnline(List<String> macs) {
        long now = clock.getAsLong();
        Map<String, Long> fresh = new ConcurrentHashMap<>();
        if (macs != null) {
            for (String mac : macs) {
                if (mac != null && !mac.isBlank()) {
                    fresh.put(mac, now);
                }
            }
        }
        lastSeen = fresh;
    }

    public boolean isOnline(String mac) {
        Long seenAt = lastSeen.get(mac);
        return seenAt != null && clock.getAsLong() - seenAt <= TTL_MILLIS;
    }
}
