<template>
  <div class="welcome">
    <HeaderBar />

    <div class="operation-bar">
      <h2 class="page-title">{{ $t("mathPractice.title") }}</h2>
    </div>

    <div class="main-wrapper">
      <div class="content-panel">
        <div class="content-area">
          <el-card class="config-card" shadow="never">
            <div class="selector-row">
              <el-select
                v-model="selectedAgentId"
                :placeholder="$t('mathPractice.selectAgent')"
                class="selector"
                @change="handleAgentChange"
              >
                <el-option
                  v-for="agent in agents"
                  :key="agent.id"
                  :label="agent.agentName"
                  :value="agent.id"
                />
              </el-select>
              <el-select
                v-model="selectedMac"
                :placeholder="$t('mathPractice.selectDevice')"
                class="selector"
                :disabled="!selectedAgentId"
                @change="handleDeviceChange"
              >
                <el-option
                  v-for="device in devices"
                  :key="device.macAddress"
                  :label="(device.alias || device.macAddress)"
                  :value="device.macAddress"
                />
              </el-select>
            </div>

            <div v-if="selectedMac" v-loading="loading">
              <el-tabs v-model="activeTab">
                <el-tab-pane :label="$t('mathPractice.configTab')" name="config">
                  <el-form label-width="90px">
                    <el-form-item :label="$t('mathPractice.preset')">
                      <el-radio-group v-model="form.preset" @change="applyPresetDefaults">
                        <el-radio-button
                          v-for="p in presetOptions"
                          :key="p.value"
                          :label="p.value"
                        >{{ p.label }}</el-radio-button>
                      </el-radio-group>
                    </el-form-item>

                    <el-form-item :label="$t('mathPractice.questionTypes')">
                      <div class="type-groups">
                        <div v-for="group in typeGroups" :key="group.label" class="type-group">
                          <div class="type-group-label">{{ group.label }}</div>
                          <el-checkbox-group v-model="form.typeIds">
                            <el-checkbox
                              v-for="t in group.items"
                              :key="t.id"
                              :label="t.id"
                            >{{ t.id }} {{ t.name }}</el-checkbox>
                          </el-checkbox-group>
                        </div>
                      </div>
                    </el-form-item>

                    <el-form-item :label="$t('mathPractice.questionCount')">
                      <el-slider
                        v-model="form.questionCount"
                        :min="5"
                        :max="20"
                        :step="1"
                        show-input
                        class="count-slider"
                      />
                    </el-form-item>

                    <el-form-item>
                      <el-button type="primary" @click="saveConfig">{{ $t("mathPractice.save") }}</el-button>
                    </el-form-item>
                  </el-form>
                </el-tab-pane>

                <el-tab-pane :label="$t('mathPractice.recordTab')" name="records">
                  <el-table :data="records" style="width: 100%">
                    <el-table-column prop="createdAt" :label="$t('mathPractice.recordTime')" width="180" />
                    <el-table-column :label="$t('mathPractice.recordPreset')" width="120">
                      <template slot-scope="scope">{{ presetName(scope.row.preset) }}</template>
                    </el-table-column>
                    <el-table-column :label="$t('mathPractice.recordScore')">
                      <template slot-scope="scope">{{ scope.row.correct }} / {{ scope.row.total }}</template>
                    </el-table-column>
                    <el-table-column :label="$t('mathPractice.recordStreak')">
                      <template slot-scope="scope">{{ scope.row.streakPeak || 0 }}</template>
                    </el-table-column>
                    <el-table-column :label="$t('mathPractice.recordDuration')">
                      <template slot-scope="scope">{{ formatDuration(scope.row.durationSeconds) }}</template>
                    </el-table-column>
                  </el-table>
                  <el-pagination
                    v-if="recordTotal > recordPageSize"
                    layout="total, prev, pager, next"
                    :total="recordTotal"
                    :page-size="recordPageSize"
                    :current-page.sync="recordPage"
                    class="record-pagination"
                    @current-change="fetchRecords"
                  />
                </el-tab-pane>
              </el-tabs>
            </div>

            <div v-else class="empty-hint">{{ $t("mathPractice.selectDeviceHint") }}</div>
          </el-card>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import Api from "@/apis/api";
import HeaderBar from "@/components/HeaderBar.vue";
import i18n from "@/i18n";

// 题型目录与年级预设默认集合：与 xiaozhi-server mcp_services/math_practice/generator.py 保持同步
const TYPE_CATALOG = [
  { id: "A1", name: "5以内加法" },
  { id: "A2", name: "10以内加法" },
  { id: "A3", name: "20以内不进位加" },
  { id: "A4", name: "20以内进位加" },
  { id: "A5", name: "50以内加法(过渡档)" },
  { id: "A6", name: "两位数+一位数" },
  { id: "A7", name: "两位数+两位数" },
  { id: "S1", name: "5以内减法" },
  { id: "S2", name: "10以内减法" },
  { id: "S3", name: "20以内不退位减" },
  { id: "S4", name: "20以内退位减(难点)" },
  { id: "S5", name: "50以内减法(过渡档)" },
  { id: "S6", name: "两位数-一位数" },
  { id: "S7", name: "两位数-整十数" },
  { id: "S8", name: "两位数-两位数" },
  { id: "M1", name: "表内乘法(口诀≤6)" },
  { id: "M2", name: "表内乘法(全口诀)" },
  { id: "M3", name: "乘数未知" },
  { id: "D1", name: "表内除法(口诀≤6)" },
  { id: "D2", name: "表内除法(全口诀)" },
  { id: "CMP5", name: "比大小(5以内)" },
  { id: "CMP10", name: "比大小(10以内)" },
  { id: "CMP100", name: "比大小(100以内)" },
  { id: "ADJ100", name: "相邻数(100以内)" },
  { id: "PAT20", name: "找规律(20以内)" },
  { id: "DEC", name: "分与合" },
];

// 显式分组（避免前缀匹配把 ADJ100/DEC 归错组）
const TYPE_GROUP_IDS = {
  add: ["A1", "A2", "A3", "A4", "A5", "A6", "A7"],
  sub: ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"],
  mulDiv: ["M1", "M2", "M3", "D1", "D2"],
  sense: ["CMP5", "CMP10", "CMP100", "ADJ100", "PAT20", "DEC"],
};

const PRESET_DEFAULTS = {
  preschool: ["A1", "S1", "CMP5", "DEC", "PAT20"],
  g1a: ["A2", "A3", "S2", "A4", "CMP10", "DEC"],
  g1b: ["S3", "S4", "A5", "S5", "A6", "S7", "ADJ100"],
  g2a: ["M1", "M2", "A7", "S8"],
  g2b: ["D1", "D2", "M2", "M3", "A7", "S8"],
};

const PRESET_LABELS = {
  preschool: "mathPractice.presetPreschool",
  g1a: "mathPractice.presetG1a",
  g1b: "mathPractice.presetG1b",
  g2a: "mathPractice.presetG2a",
  g2b: "mathPractice.presetG2b",
};

export default {
  name: "MathPracticeConfigPage",
  components: { HeaderBar },
  data() {
    return {
      agents: [],
      devices: [],
      selectedAgentId: "",
      selectedMac: "",
      activeTab: "config",
      loading: false,
      form: {
        preset: "g1a",
        typeIds: [...PRESET_DEFAULTS.g1a],
        questionCount: 10,
      },
      records: [],
      recordPage: 1,
      recordPageSize: 10,
      recordTotal: 0,
      configSeq: 0, // 请求序号：快速切换设备时丢弃滞后响应
      recordSeq: 0,
    };
  },
  computed: {
    presetOptions() {
      return Object.keys(PRESET_DEFAULTS).map((value) => ({
        value,
        label: this.$t(PRESET_LABELS[value]),
      }));
    },
    typeGroups() {
      const byId = Object.fromEntries(TYPE_CATALOG.map((t) => [t.id, t]));
      return [
        { label: this.$t("mathPractice.groupAdd"), ids: TYPE_GROUP_IDS.add },
        { label: this.$t("mathPractice.groupSub"), ids: TYPE_GROUP_IDS.sub },
        { label: this.$t("mathPractice.groupMulDiv"), ids: TYPE_GROUP_IDS.mulDiv },
        { label: this.$t("mathPractice.groupSense"), ids: TYPE_GROUP_IDS.sense },
      ].map((g) => ({ label: g.label, items: g.ids.map((id) => byId[id]).filter(Boolean) }));
    },
  },
  methods: {
    fetchAgents() {
      Api.agent.getAgentList(({ data }) => {
        if (data?.code === 0) {
          this.agents = data.data || [];
        }
      });
    },
    handleAgentChange(agentId) {
      this.selectedMac = "";
      this.devices = [];
      if (!agentId) {
        return;
      }
      Api.device.getAgentBindDevices(agentId, ({ data }) => {
        if (data?.code === 0) {
          this.devices = data.data || [];
        } else {
          this.$message.error(data?.msg || i18n.t("mathPractice.fetchFailed"));
        }
      });
    },
    handleDeviceChange() {
      if (!this.selectedMac) {
        return;
      }
      this.fetchConfig();
      this.recordPage = 1;
      this.fetchRecords();
    },
    fetchConfig() {
      const seq = ++this.configSeq;
      this.loading = true;
      Api.mathPractice.getConfig(this.selectedMac, ({ data }) => {
        if (seq !== this.configSeq) {
          return; // 已切到其他设备，丢弃滞后响应
        }
        this.loading = false;
        if (data?.code !== 0) {
          this.$message.error(data?.msg || i18n.t("mathPractice.fetchFailed"));
          return;
        }
        const cfg = data.data;
        if (cfg) {
          this.form = {
            preset: cfg.preset || "g1a",
            typeIds: (cfg.typeIds && cfg.typeIds.length ? cfg.typeIds : [...(PRESET_DEFAULTS[cfg.preset] || PRESET_DEFAULTS.g1a)]),
            questionCount: cfg.questionCount || 10,
          };
        } else {
          // 未配置：展示默认一上档（#24：最终保障默认档）
          this.form = { preset: "g1a", typeIds: [...PRESET_DEFAULTS.g1a], questionCount: 10 };
        }
      });
    },
    applyPresetDefaults(preset) {
      this.form.typeIds = [...(PRESET_DEFAULTS[preset] || [])];
    },
    saveConfig() {
      if (!this.form.typeIds.length) {
        this.$message.warning(i18n.t("mathPractice.noTypes"));
        return;
      }
      Api.mathPractice.saveConfig(
        {
          macAddress: this.selectedMac,
          preset: this.form.preset,
          typeIds: this.form.typeIds,
          questionCount: this.form.questionCount,
        },
        ({ data }) => {
          if (data?.code === 0) {
            this.$message.success(i18n.t("mathPractice.saveSuccess"));
          } else {
            this.$message.error(data?.msg || i18n.t("mathPractice.saveFailed"));
          }
        }
      );
    },
    fetchRecords() {
      const seq = ++this.recordSeq;
      Api.mathPractice.getRecordList(
        { page: this.recordPage, pageSize: this.recordPageSize, macAddress: this.selectedMac },
        ({ data }) => {
          if (seq !== this.recordSeq) {
            return;
          }
          if (data?.code === 0) {
            this.records = data.data?.list || [];
            this.recordTotal = data.data?.total || 0;
          } else {
            this.$message.error(data?.msg || i18n.t("mathPractice.fetchFailed"));
          }
        }
      );
    },
    presetName(preset) {
      return PRESET_LABELS[preset] ? this.$t(PRESET_LABELS[preset]) : preset || "-";
    },
    formatDuration(seconds) {
      if (seconds == null) {
        return "-";
      }
      const m = Math.floor(seconds / 60);
      const s = seconds % 60;
      return m > 0 ? `${m}m ${s}s` : `${s}s`;
    },
  },
  mounted() {
    this.fetchAgents();
  },
};
</script>

<style lang="scss" scoped>
.welcome {
  min-width: 900px;
  height: 100vh;
  display: flex;
  position: relative;
  flex-direction: column;
  background: #eff4ff;
  overflow: hidden;
}

.operation-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
}

.page-title {
  font-size: 24px;
  margin: 0;
  color: #2c3e50;
}

.main-wrapper {
  height: calc(100vh - 63px - 35px - 60px);
  margin: 0 22px;
  border-radius: 15px;
  position: relative;
  display: flex;
  flex-direction: column;
}

.content-panel {
  flex: 1;
  display: flex;
  overflow: hidden;
  height: 100%;
  border-radius: 15px;
  background: transparent;
  border: 1px solid #fff;
}

.content-area {
  flex: 1;
  height: 100%;
  overflow: auto;
  background-color: white;
  display: flex;
  flex-direction: column;
}

.config-card {
  background: white;
  border: none;
  box-shadow: none;
  flex: 1;
  overflow-y: auto;
}

.selector-row {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}

.selector {
  width: 260px;
}

.type-groups {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.type-group {
  padding: 8px 12px;
  border: 1px solid #e8f0ff;
  border-radius: 8px;
}

.type-group-label {
  font-size: 13px;
  font-weight: 600;
  color: #3d4566;
  margin-bottom: 4px;
}

.count-slider {
  max-width: 420px;
}

.empty-hint {
  color: #979db1;
  text-align: center;
  padding: 48px 0;
}

.record-pagination {
  margin-top: 12px;
  text-align: right;
}
</style>
