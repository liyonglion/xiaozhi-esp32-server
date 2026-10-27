<template>
  <div class="welcome">
    <HeaderBar />

    <div class="operation-bar">
      <h2 class="page-title">{{ $t("todoList.title") }}</h2>
    </div>

    <div class="main-wrapper">
      <div class="content-panel">
        <div class="content-area">
          <el-card class="config-card" shadow="never">
            <div class="selector-row">
              <el-select
                v-model="selectedAgentId"
                :placeholder="$t('todoList.selectAgent')"
                class="selector"
                @change="handleAgentChange"
              >
                <el-option v-for="agent in agents" :key="agent.id" :label="agent.agentName" :value="agent.id" />
              </el-select>
              <el-select
                v-model="selectedMac"
                :placeholder="$t('todoList.selectDevice')"
                class="selector"
                :disabled="!selectedAgentId"
                @change="handleDeviceChange"
              >
                <el-option
                  v-for="device in devices"
                  :key="device.macAddress"
                  :label="device.alias || device.macAddress"
                  :value="device.macAddress"
                />
              </el-select>
              <span v-if="selectedMac" class="badges">
                <el-tag :type="mirror.deviceOnline ? 'success' : 'info'" size="small">
                  {{ mirror.deviceOnline ? $t("todoList.statusOnline") : $t("todoList.statusOffline") }}
                </el-tag>
                <el-tag v-if="mirror.pending" type="warning" size="small">{{ $t("todoList.statusPending") }}</el-tag>
              </span>
            </div>

            <div v-if="selectedMac" v-loading="loading" class="todo-layout">
              <div class="editor-pane">
                <div class="daily-section">
                  <div class="pane-head">
                    <span class="pane-title">{{ $t("todoList.dailyTitle") }}</span>
                    <span class="count-hint">{{ dailyCount }} / 30</span>
                  </div>
                  <div class="daily-hint">{{ $t("todoList.dailyHint") }}</div>
                  <div v-for="group in dailyGroups" :key="group.key" class="daily-group">
                    <span class="template-group-label">{{ group.label }}</span>
                    <div class="daily-rows">
                      <div v-for="(row, idx) in group.rows" :key="idx" class="daily-row">
                        <el-input
                          v-model="row.text"
                          size="small"
                          class="daily-text"
                          :maxlength="30"
                          @input="markDailyDirty"
                        />
                        <el-time-picker
                          v-model="row.deadline"
                          size="small"
                          class="daily-deadline"
                          :clearable="true"
                          value-format="HH:mm"
                          format="HH:mm"
                          :placeholder="$t('todoList.deadlinePlaceholder')"
                          @change="markDailyDirty"
                        />
                        <el-button
                          type="text"
                          class="item-remove"
                          :title="$t('todoList.removeItem')"
                          @click="removeDailyRow(group, idx)"
                        >✕</el-button>
                      </div>
                      <el-button size="small" type="text" class="daily-add" @click="addDailyRow(group)">
                        + {{ $t("todoList.dailyAdd") }}
                      </el-button>
                      <span v-if="!group.rows.length" class="daily-empty">{{ $t("todoList.dailyEmpty") }}</span>
                    </div>
                  </div>
                  <div class="daily-save-row">
                    <el-button size="small" type="primary" plain :loading="dailySaving" @click="saveDaily">
                      {{ $t("todoList.dailySave") }}
                    </el-button>
                    <span class="save-hint">{{ $t("todoList.dailySaveHint") }}</span>
                  </div>
                </div>

                <div class="section-divider"></div>

                <div class="pane-head">
                  <span class="pane-title">{{ $t("todoList.editorTitle") }}</span>
                  <span class="count-hint">{{ items.length }} / 30</span>
                </div>
                <div class="due-hint">{{ $t("todoList.dueHint") }}</div>

                <div class="item-rows">
                  <div v-for="(item, idx) in items" :key="idx" class="item-row">
                    <el-checkbox v-model="item.done" @change="markDirty" />
                    <el-input
                      v-model="item.text"
                      class="item-text"
                      size="small"
                      :maxlength="30"
                      show-word-limit
                      @input="markDirty"
                    />
                    <el-time-picker
                      v-model="item.due"
                      size="small"
                      class="item-due"
                      :clearable="true"
                      value-format="HH:mm"
                      format="HH:mm"
                      :placeholder="$t('todoList.deadlinePlaceholder')"
                      @change="markDirty"
                    />
                    <el-button
                      type="text"
                      class="item-remove"
                      :title="$t('todoList.removeItem')"
                      @click="removeItem(idx)"
                    >✕</el-button>
                  </div>
                  <div v-if="!items.length" class="empty-hint">{{ $t("todoList.editorEmpty") }}</div>
                </div>

                <div class="add-row">
                  <el-input
                    v-model="newTaskText"
                    size="small"
                    class="add-input"
                    :maxlength="30"
                    :placeholder="$t('todoList.addTask')"
                    @keyup.enter.native="addTask"
                  />
                  <el-button size="small" type="primary" plain @click="addTask">{{ $t("todoList.addButton") }}</el-button>
                </div>

                <div class="templates">
                  <div class="pane-title templates-title">{{ $t("todoList.templateTitle") }}</div>
                  <div v-for="group in templateGroups" :key="group.key" class="template-group">
                    <span class="template-group-label">{{ group.label }}</span>
                    <el-tag
                      v-for="t in group.items"
                      :key="t"
                      class="template-chip"
                      size="small"
                      effect="plain"
                      @click="addTemplate(t)"
                    >+ {{ t }}</el-tag>
                  </div>
                </div>

                <div class="device-config">
                  <span class="pane-title">{{ $t("todoList.deviceConfigTitle") }}</span>
                  <div class="config-row">
                    <span class="config-label">{{ $t("todoList.syncEnabled") }}</span>
                    <el-switch v-model="config.syncEnabled" @change="markDirty" />
                    <span class="config-hint">{{ $t("todoList.syncEnabledHint") }}</span>
                  </div>
                  <div class="config-row">
                    <span class="config-label">{{ $t("todoList.quietPeriod") }}</span>
                    <el-time-picker
                      v-model="config.quietStart"
                      size="small"
                      class="config-time"
                      value-format="HH:mm"
                      format="HH:mm"
                      @change="markDirty"
                    />
                    <span class="config-sep">–</span>
                    <el-time-picker
                      v-model="config.quietEnd"
                      size="small"
                      class="config-time"
                      value-format="HH:mm"
                      format="HH:mm"
                      @change="markDirty"
                    />
                    <span class="config-hint">{{ $t("todoList.quietHint") }}</span>
                  </div>
                  <div class="config-row">
                    <span class="config-label">{{ $t("todoList.maxItemsLabel") }}</span>
                    <el-input-number v-model="config.maxItems" size="small" :min="1" :max="30" @change="markDirty" />
                    <span class="config-hint">{{ $t("todoList.maxItemsHint") }}</span>
                  </div>
                </div>

                <div class="save-row">
                  <el-button type="primary" :loading="saving" @click="save">{{ $t("todoList.save") }}</el-button>
                  <span class="save-hint">{{ $t("todoList.saveHint") }}</span>
                </div>
              </div>

              <div class="preview-pane">
                <div class="pane-head">
                  <span class="pane-title">{{ $t("todoList.previewTitle") }}</span>
                </div>
                <div class="board" aria-hidden="true">
                  <div class="board-badge">
                    <span class="dot" :class="{ offline: !mirror.deviceOnline }"></span>
                    {{ mirror.deviceOnline ? $t("todoList.statusOnline") : $t("todoList.statusOffline") }}
                    <span v-if="mirror.pending">· {{ $t("todoList.statusPending") }}</span>
                  </div>
                  <h4>{{ $t("todoList.boardTitle") }}<span class="chalk-underline"></span></h4>
                  <ul class="board-items">
                    <li v-for="(item, idx) in items" :key="idx" :class="{ done: item.done }">
                      <span class="box"></span>
                      <span class="txt">{{ item.text }}</span>
                    </li>
                    <li v-if="!items.length" class="empty-line">{{ $t("todoList.editorEmpty") }}</li>
                  </ul>
                </div>
                <div class="preview-foot">{{ $t("todoList.previewFoot") }}</div>
              </div>
            </div>

            <div v-else class="empty-hint">{{ $t("todoList.selectDeviceHint") }}</div>
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

// 模板四组（spec #30：晨间/学习/家务/睡前）；文案随界面语言——任务文本即孩子看到的黑板内容
const TEMPLATE_KEYS = {
  morning: ["tplBrushTeeth", "tplWashFace", "tplBreakfast", "tplMakeBed"],
  study: ["tplReadBook", "tplHomework", "tplMathPractice", "tplRecitePoem"],
  chores: ["tplTidyToys", "tplWaterPlants", "tplWipeTable", "tplTakeOutTrash"],
  bedtime: ["tplBath", "tplBrushTeethNight", "tplBedtimeStory", "tplPackBag"],
};

// 每日任务四组（与后端 DAILY_GROUPS 白名单保持同步）
const DAILY_GROUP_KEYS = ["morning", "study", "chores", "bedtime"];

const MAX_ITEMS = 30; // 与设备契约一致（服务端同口径拒绝）

const emptyDailyGroups = () =>
  DAILY_GROUP_KEYS.map((key) => ({ key, rows: [] }));

const defaultConfig = () => ({ syncEnabled: true, quietStart: "21:00", quietEnd: "07:00", maxItems: 30 });

export default {
  name: "TodoListConfigPage",
  components: { HeaderBar },
  data() {
    return {
      agents: [],
      devices: [],
      selectedAgentId: "",
      selectedMac: "",
      loading: false,
      saving: false,
      items: [],
      newTaskText: "",
      mirror: { deviceOnline: false, pending: false },
      config: defaultConfig(), // 设备级配置（#33 评论补充）：随整表保存一并提交
      dailyGroups: emptyDailyGroups(), // 上区「每日任务」四组
      dailyDirty: false,
      dailySaving: false,
      dirty: false, // 本地有未保存编辑：轮询只刷徽标，不覆盖 items/config
      fetchSeq: 0,
      dailySeq: 0, // 独立于 fetchSeq：两路请求各自比对，互不丢弃对方响应
      loadedMac: "", // 当前已加载到编辑器的设备：切换取消时回退用
      pollTimer: null,
    };
  },
  computed: {
    templateGroups() {
      return Object.keys(TEMPLATE_KEYS).map((key) => ({
        key,
        label: this.$t(`todoList.group_${key}`),
        items: TEMPLATE_KEYS[key].map((k) => this.$t(`todoList.${k}`)),
      }));
    },
    dailyCount() {
      return this.dailyGroups.reduce((n, g) => n + g.rows.length, 0);
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
      this.stopPolling();
      if (!agentId) {
        return;
      }
      Api.device.getAgentBindDevices(agentId, ({ data }) => {
        if (data?.code === 0) {
          this.devices = data.data || [];
        } else {
          this.$message.error(data?.msg || i18n.t("todoList.fetchFailed"));
        }
      });
    },
    handleDeviceChange() {
      if (!this.selectedMac) {
        this.stopPolling();
        return;
      }
      if (this.dirty || this.dailyDirty) {
        const from = this.loadedMac;
        this.$confirm(i18n.t("todoList.switchConfirm"))
          .then(() => this.loadDevice())
          .catch(() => {
            this.selectedMac = from || ""; // 放弃切换，回到已加载设备
          });
        return;
      }
      this.loadDevice();
    },
    loadDevice() {
      this.dirty = false;
      this.dailyDirty = false;
      this.fetchMirror();
      this.fetchDaily();
      this.startPolling();
    },
    fetchMirror(silent = false) {
      const seq = ++this.fetchSeq;
      if (!silent) {
        this.loading = true;
      }
      Api.todoList.getTodoList(this.selectedMac, ({ data }) => {
        if (seq !== this.fetchSeq) {
          return; // 已切到其他设备，丢弃滞后响应
        }
        this.loading = false;
        if (data?.code !== 0) {
          this.$message.error(data?.msg || i18n.t("todoList.fetchFailed"));
          return;
        }
        const m = data.data || {};
        if (!this.dirty) {
          this.items = (m.items || []).map((i) => ({ text: i.text || "", done: !!i.done, due: i.due || null }));
          this.config = {
            syncEnabled: m.syncEnabled !== false,
            quietStart: m.quietStart || "21:00",
            quietEnd: m.quietEnd || "07:00",
            maxItems: m.maxItems || 30,
          };
        }
        this.mirror = { deviceOnline: !!m.deviceOnline, pending: !!m.pending };
        this.loadedMac = this.selectedMac;
      });
    },
    fetchDaily() {
      const seq = ++this.dailySeq; // 独立序号：只丢弃 daily 自己的滞后响应
      Api.todoList.getDailyTemplates(this.selectedMac, ({ data }) => {
        if (seq !== this.dailySeq) {
          return;
        }
        if (data?.code !== 0) {
          this.$message.error(data?.msg || i18n.t("todoList.fetchFailed"));
          return;
        }
        if (this.dailyDirty) {
          return; // 本地有未保存编辑，不覆盖
        }
        const groups = emptyDailyGroups();
        (data.data || []).forEach((t) => {
          const group = groups.find((g) => g.key === t.group);
          if (group) {
            group.rows.push({ text: t.text || "", deadline: t.deadline || null });
          }
        });
        this.dailyGroups = groups;
      });
    },
    startPolling() {
      // 徽标是动态状态（上线送达、离线保留），轻量轮询让「待下发」清除可见；
      // 本地有未保存编辑（dirty）时只刷徽标，不覆盖编辑器内容
      this.stopPolling();
      this.pollTimer = setInterval(() => {
        if (!this.saving) {
          this.fetchMirror(true); // 静默轮询：不闪 loading 遮罩
        }
      }, 15000);
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },
    markDirty() {
      this.dirty = true;
    },
    appendTask(text) {
      if (this.items.length >= MAX_ITEMS) {
        this.$message.warning(i18n.t("todoList.maxItems"));
        return false;
      }
      this.items.push({ text, done: false, due: null });
      this.dirty = true;
      return true;
    },
    addTask() {
      const text = this.newTaskText.trim();
      if (!text) {
        return;
      }
      if (this.appendTask(text)) {
        this.newTaskText = "";
      }
    },
    addTemplate(text) {
      this.appendTask(text);
    },
    removeItem(idx) {
      this.items.splice(idx, 1);
      this.dirty = true;
    },
    markDailyDirty() {
      this.dailyDirty = true;
    },
    addDailyRow(group) {
      if (this.dailyCount >= MAX_ITEMS) {
        this.$message.warning(i18n.t("todoList.maxItems"));
        return;
      }
      group.rows.push({ text: "", deadline: null });
      this.dailyDirty = true;
    },
    removeDailyRow(group, idx) {
      group.rows.splice(idx, 1);
      this.dailyDirty = true;
    },
    saveDaily() {
      const items = [];
      this.dailyGroups.forEach((g) =>
        g.rows.forEach((r) => {
          const text = (r.text || "").trim();
          if (text) {
            items.push({ group: g.key, text, deadline: r.deadline || null });
          }
        })
      );
      if (items.length > MAX_ITEMS) {
        this.$message.warning(i18n.t("todoList.maxItems"));
        return;
      }
      this.dailySaving = true;
      Api.todoList.saveDailyTemplates({ macAddress: this.selectedMac, items }, ({ data }) => {
        this.dailySaving = false;
        if (data?.code === 0) {
          this.$message.success(i18n.t("todoList.dailySaveSuccess"));
          this.dailyDirty = false;
        } else {
          this.$message.error(data?.msg || i18n.t("todoList.saveFailed"));
        }
      });
    },
    save() {
      const items = this.items
        .map((i) => ({ text: (i.text || "").trim(), done: !!i.done, due: i.due || null }))
        .filter((i) => i.text);
      if (items.length > MAX_ITEMS) {
        this.$message.warning(i18n.t("todoList.maxItems"));
        return;
      }
      this.saving = true;
      // 设备级配置块随整表保存一并提交（#33 评论补充；后端 null=不修改，这里全量带上）
      const payload = {
        macAddress: this.selectedMac,
        items,
        syncEnabled: !!this.config.syncEnabled,
        quietStart: this.config.quietStart || null,
        quietEnd: this.config.quietEnd || null,
        maxItems: this.config.maxItems || null,
      };
      Api.todoList.saveTodoList(payload, ({ data }) => {
        this.saving = false;
        if (data?.code === 0) {
          this.$message.success(i18n.t("todoList.saveSuccess"));
          this.dirty = false;
          const m = data.data || {};
          this.mirror = { deviceOnline: !!m.deviceOnline, pending: !!m.pending };
        } else {
          this.$message.error(data?.msg || i18n.t("todoList.saveFailed"));
        }
      });
    },
  },
  mounted() {
    this.fetchAgents();
  },
  beforeDestroy() {
    this.stopPolling();
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
  align-items: center;
  margin-bottom: 12px;
}

.selector {
  width: 260px;
}

.badges {
  display: inline-flex;
  gap: 8px;
}

.todo-layout {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}

.editor-pane {
  flex: 1;
  min-width: 0;
}

.preview-pane {
  width: 340px;
  flex-shrink: 0;
}

.pane-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 10px;
}

.pane-title {
  font-size: 15px;
  font-weight: 600;
  color: #3d4566;
}

.count-hint {
  font-size: 12px;
  color: #979db1;
}

.item-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow-y: auto;
  padding: 8px 10px;
  border: 1px solid #e8f0ff;
  border-radius: 8px;
}

.item-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.item-text {
  flex: 1;
}

.item-due {
  width: 110px;
  flex-shrink: 0;
}

.due-hint {
  font-size: 12px;
  color: #979db1;
  margin: -4px 0 8px;
}

.item-remove {
  color: #979db1;
  padding: 4px 6px;

  &:hover {
    color: #f56c6c;
  }
}

.add-row {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}

.add-input {
  width: 280px;
}

.templates {
  margin-top: 18px;
  padding: 10px 12px;
  border: 1px solid #e8f0ff;
  border-radius: 8px;
}

// ── 上区「每日任务」（#33，原型变体 D 两区结构） ──
.daily-section {
  padding: 12px 14px;
  border: 1px solid #e8f0ff;
  border-radius: 8px;
  background: #fbfdff;
}

.daily-hint {
  font-size: 12px;
  color: #979db1;
  margin-bottom: 10px;
}

.daily-group {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 6px 0;
  border-top: 1px dashed #e8f0ff;

  &:first-of-type {
    border-top: none;
  }
}

.daily-rows {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-start;
}

.daily-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.daily-text {
  width: 240px;
}

.daily-deadline {
  width: 120px;
}

.daily-add {
  padding: 2px 0;
}

.daily-empty {
  font-size: 12px;
  color: #979db1;
}

.daily-save-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
}

.section-divider {
  height: 1px;
  margin: 18px 0 12px;
  background: #e8f0ff;
}

// ── 设备级配置块（#33 评论补充：同步开关/静默时段/条数上限，随整表保存提交） ──
.device-config {
  margin-top: 18px;
  padding: 10px 12px;
  border: 1px solid #e8f0ff;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;

  .pane-title {
    font-size: 14px;
  }
}

.config-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.config-label {
  font-size: 13px;
  color: #3d4566;
  width: 64px;
  flex-shrink: 0;
}

.config-time {
  width: 110px;
}

.config-sep {
  color: #979db1;
}

.config-hint {
  font-size: 12px;
  color: #979db1;
}

.templates-title {
  margin-bottom: 8px;
}

.template-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 4px 0;
}

.template-group-label {
  font-size: 13px;
  color: #3d4566;
  width: 64px;
  flex-shrink: 0;
}

.template-chip {
  cursor: pointer;
  user-select: none;

  &:hover {
    color: #409eff;
    border-color: #409eff;
  }
}

.save-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 16px;
}

.save-hint {
  font-size: 12px;
  color: #979db1;
}

// ── 设备黑板屏预览（视觉照原型变体 D） ──
.board {
  background: #2b4a3f;
  border-radius: 10px;
  padding: 16px 18px 12px;
  color: #f4f1e6;
  min-height: 280px;
  position: relative;
  border: 3px solid #223b33;
  box-shadow: inset 0 0 24px rgba(0, 0, 0, 0.35);
  font-family: "Kaiti SC", STKaiti, "楷体", "Songti SC", serif;
}

.board h4 {
  margin: 0 0 12px;
  font-size: 19px;
  text-align: center;
  letter-spacing: 2px;
  font-weight: 500;
}

.chalk-underline {
  display: block;
  width: 64px;
  height: 2px;
  background: rgba(244, 241, 230, 0.55);
  margin: 6px auto 0;
  border-radius: 2px;
}

.board-items {
  list-style: none;
  margin: 0;
  padding: 0 2px;
  font-size: 16px;
  max-height: 212px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(244, 241, 230, 0.4) transparent;

  li {
    display: flex;
    gap: 10px;
    align-items: baseline;
    padding: 7px 2px;
  }

  .box {
    width: 15px;
    height: 15px;
    min-width: 15px;
    border: 1.6px solid rgba(244, 241, 230, 0.85);
    border-radius: 3px;
    position: relative;
    top: 2px;
  }

  li.done .box::after {
    content: "✓";
    position: absolute;
    left: 1px;
    top: -5px;
    font-size: 15px;
    color: #ffe08a;
  }

  li.done .txt {
    text-decoration: line-through;
    opacity: 0.55;
  }

  .empty-line {
    color: rgba(244, 241, 230, 0.4);
    font-size: 14px;
    padding-top: 10px;
  }
}

.board-badge {
  position: absolute;
  top: 10px;
  right: 12px;
  font-size: 11px;
  color: #ffd77e;
  display: flex;
  gap: 5px;
  align-items: center;

  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #ffd77e;
    animation: board-pulse 1.6s infinite;

    &.offline {
      background: rgba(244, 241, 230, 0.5);
      animation: none;
    }
  }
}

@keyframes board-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}

@media (prefers-reduced-motion: reduce) {
  .board-badge .dot {
    animation: none;
  }
}

.preview-foot {
  color: #979db1;
  font-size: 12px;
  text-align: center;
  padding-top: 8px;
}

.empty-hint {
  color: #979db1;
  text-align: center;
  padding: 48px 0;
}
</style>
