package xiaozhi.modules.mathpractice.service;

import java.util.Map;

import xiaozhi.common.page.PageData;
import xiaozhi.modules.mathpractice.dto.MathPracticeConfigSaveDTO;
import xiaozhi.modules.mathpractice.dto.MathPracticeReportDTO;
import xiaozhi.modules.mathpractice.vo.MathPracticeConfigVO;
import xiaozhi.modules.mathpractice.vo.MathPracticeProgressVO;

public interface MathPracticeService {

    /** 按设备 MAC 取配置（xiaozhi-server 内部接口用，无用户态） */
    MathPracticeConfigVO getConfigByMac(String macAddress);

    /** 家长页取配置：校验设备归属当前用户 */
    MathPracticeConfigVO getConfigForUser(String macAddress);

    /** 保存设备配置（家长页用，校验设备归属当前用户） */
    MathPracticeConfigVO saveConfig(MathPracticeConfigSaveDTO dto);

    /** 上报一次练习会话结果（xiaozhi-server 内部接口用） */
    void reportRecord(MathPracticeReportDTO dto);

    /** 学习进度全量聚合（P2 屏：固件开机首拉 + xiaozhi-server 推送前数据源，#29） */
    MathPracticeProgressVO getProgress(String macAddress);

    /** 分页查询设备练习记录（家长页用，校验设备归属当前用户） */
    PageData<Map<String, Object>> listRecords(Map<String, Object> params);
}
