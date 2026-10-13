<template>
  <div class="welcome">
    <HeaderBar />

    <div class="page-content kids-parent">
      <div class="kids-header">
        <div>
          <h1 class="main-title">{{ $t('kidsParent.title') }}</h1>
          <p class="sub-title">{{ $t('kidsParent.subTitle') }}</p>
        </div>
        <el-select
          v-model="selectedAgentId"
          :placeholder="$t('kidsParent.selectAgent')"
          class="agent-select"
          @change="handleAgentChange"
        >
          <el-option
            v-for="agent in agents"
            :key="agent.id"
            :label="agent.agentName"
            :value="agent.id"
          />
        </el-select>
      </div>

      <template v-if="selectedAgentId">
        <!-- 孩子档案 -->
        <el-card class="section-card" shadow="never">
          <div slot="header" class="section-header">
            <span>{{ $t('kidsParent.profile.title') }}</span>
            <span class="section-hint">{{ $t('kidsParent.profile.effectHint') }}</span>
          </div>
          <el-form ref="profileForm" :model="profile" :rules="profileRules" label-width="120px">
            <el-form-item :label="$t('kidsParent.profile.enabled')">
              <el-switch v-model="profile.enabled" />
            </el-form-item>
            <el-form-item :label="$t('kidsParent.profile.nickname')" prop="nickname">
              <el-input v-model="profile.nickname" maxlength="20" />
            </el-form-item>
            <el-form-item :label="$t('kidsParent.profile.birthYm')" prop="birth_ym">
              <el-date-picker
                v-model="profile.birth_ym"
                type="month"
                :placeholder="$t('kidsParent.profile.birthYmPlaceholder')"
                value-format="yyyy-MM"
                :clearable="false"
              />
            </el-form-item>
            <el-form-item :label="$t('kidsParent.profile.personality')">
              <el-input v-model="profile.personality" maxlength="50" />
            </el-form-item>
            <el-form-item :label="$t('kidsParent.profile.hobbies')">
              <el-input v-model="profile.hobbies" maxlength="50" />
            </el-form-item>
            <el-form-item :label="$t('kidsParent.profile.instructions')">
              <el-input v-model="profile.instructions" type="textarea" :rows="3" maxlength="200" />
            </el-form-item>
            <el-form-item :label="$t('kidsParent.profile.taboos')">
              <el-input
                v-model="profileTaboosText"
                type="textarea"
                :rows="3"
                :placeholder="$t('kidsParent.profile.taboosTip')"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveProfile">
                {{ $t('kidsParent.profile.save') }}
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <!-- 拦截日志 -->
        <el-card class="section-card" shadow="never">
          <div slot="header" class="section-header">
            <span>{{ $t('kidsParent.log.title') }}</span>
            <el-button size="mini" icon="el-icon-refresh" circle @click="loadLogs" />
          </div>
          <el-table
            v-loading="logsLoading"
            :data="logs"
            :row-class-name="logRowClass"
            size="small"
          >
            <el-table-column
              :label="$t('kidsParent.log.time')"
              width="170"
            >
              <template slot-scope="{ row }">{{ formatTime(row.occurredAt) }}</template>
            </el-table-column>
            <el-table-column :label="$t('kidsParent.log.category')" width="110">
              <template slot-scope="{ row }">
                <el-tag :type="categoryTagType(row.category)" size="small">
                  {{ row.category }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column
              :label="$t('kidsParent.log.userText')"
              prop="userText"
              min-width="160"
              show-overflow-tooltip
            />
            <el-table-column
              :label="$t('kidsParent.log.modelReply')"
              prop="modelReply"
              min-width="160"
              show-overflow-tooltip
            />
            <el-table-column
              :label="$t('kidsParent.log.actualReply')"
              prop="actualReply"
              min-width="160"
              show-overflow-tooltip
            />
          </el-table>
        </el-card>

        <!-- 长期记忆 -->
        <el-card class="section-card" shadow="never">
          <div slot="header" class="section-header">
            <span>{{ $t('kidsParent.memory.title') }}</span>
            <div>
              <el-button size="mini" icon="el-icon-refresh" circle @click="loadMemories" />
              <el-button
                size="mini"
                type="danger"
                :disabled="!memories.length"
                @click="confirmClear"
              >
                {{ $t('kidsParent.memory.clearAll') }}
              </el-button>
            </div>
          </div>
          <el-table v-loading="memoriesLoading" :data="memories" size="small">
            <el-table-column :label="$t('kidsParent.memory.time')" width="170">
              <template slot-scope="{ row }">{{ formatTime(row.ts) }}</template>
            </el-table-column>
            <el-table-column
              :label="$t('kidsParent.memory.content')"
              prop="text"
              min-width="220"
              show-overflow-tooltip
            />
            <el-table-column :label="$t('kidsParent.memory.operation')" width="90">
              <template slot-scope="{ row }">
                <el-button size="mini" type="text" class="danger-text" @click="deleteMemory(row)">
                  {{ $t('kidsParent.memory.delete') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </template>

      <el-empty v-else-if="!agentsLoading" :description="$t('kidsParent.noAgent')" />
    </div>
  </div>
</template>

<script>
import i18n from '@/i18n';
import Api from '@/apis/api.js';
import HeaderBar from '@/components/HeaderBar.vue';

const DEFAULT_PROFILE = {
  enabled: false,
  nickname: '',
  birth_ym: '',
  personality: '',
  hobbies: '',
  instructions: '',
  taboos: [],
};

export default {
  name: 'KidsParentManagement',
  components: { HeaderBar },
  data() {
    return {
      agents: [],
      agentsLoading: false,
      selectedAgentId: '',
      profile: { ...DEFAULT_PROFILE },
      profileTaboosText: '',
      logs: [],
      logsLoading: false,
      memories: [],
      memoriesLoading: false,
    };
  },
  computed: {
    profileRules() {
      // 开儿童模式时称呼与出生年月必填（spec 用户故事 11）
      if (!this.profile.enabled) {
        return {};
      }
      return {
        nickname: [
          { required: true, message: i18n.t('kidsParent.profile.nicknameRequired'), trigger: 'blur' },
        ],
        birth_ym: [
          { required: true, message: i18n.t('kidsParent.profile.birthYmRequired'), trigger: 'change' },
        ],
      };
    },
  },
  mounted() {
    this.fetchAgents();
  },
  methods: {
    fetchAgents() {
      this.agentsLoading = true;
      Api.agent.getAgentList(({ data }) => {
        this.agentsLoading = false;
        const list = (data && data.data) || [];
        this.agents = list;
        const fromQuery = this.$route.query.agentId;
        this.selectedAgentId =
          (fromQuery && list.some((a) => a.id === fromQuery) && fromQuery) ||
          (list.length ? list[0].id : '');
        if (this.selectedAgentId) {
          this.loadAll();
        }
      });
    },
    handleAgentChange() {
      this.loadAll();
    },
    loadAll() {
      this.loadProfile();
      this.loadLogs();
      this.loadMemories();
    },
    loadProfile() {
      Api.agent.getDeviceConfig(this.selectedAgentId, ({ data }) => {
        const agent = (data && data.data) || {};
        let profile = { ...DEFAULT_PROFILE, taboos: [] };
        if (agent.kidProfile) {
          try {
            profile = { ...profile, ...JSON.parse(agent.kidProfile) };
          } catch (e) {
            console.error('kidProfile 解析失败:', e);
          }
        }
        this.profile = profile;
        this.profileTaboosText = (profile.taboos || []).join('\n');
      });
    },
    saveProfile() {
      this.$refs.profileForm.validate((valid) => {
        if (!valid) {
          return;
        }
        const taboos = this.profileTaboosText
          .split('\n')
          .map((t) => t.trim())
          .filter(Boolean);
        const kidProfile = JSON.stringify({ ...this.profile, taboos });
        // 与 roleConfig 同通道：PUT /agent/{id} 保存 kidProfile，
        // 经快照机制即时下发；业务错误由全局 httpHandlerError 提示
        Api.agent.updateAgentConfig(this.selectedAgentId, { kidProfile }, ({ data }) => {
          if (data && data.code === 0) {
            this.$message.success({
              message: i18n.t('kidsParent.profile.saveSuccess'),
              showClose: true,
            });
          }
        });
      });
    },
    loadLogs() {
      this.logsLoading = true;
      Api.agent.getInterceptionLogList(this.selectedAgentId, (res) => {
        this.logsLoading = false;
        const body = res && res.data;
        if (body && body.code === 0) {
          this.logs = body.data || [];
        } else if (body) {
          this.$message.error(body.msg || i18n.t('kidsParent.loadFailed'));
        }
      }, () => {
        this.logsLoading = false;
        this.$message.error(i18n.t('kidsParent.loadFailed'));
      });
    },
    loadMemories() {
      this.memoriesLoading = true;
      Api.agent.getKidsMemoryList(this.selectedAgentId, (res) => {
        this.memoriesLoading = false;
        const body = res && res.data;
        if (body && body.code === 0) {
          this.memories = body.data || [];
        } else if (body) {
          this.$message.error(body.msg || i18n.t('kidsParent.loadFailed'));
        }
      }, () => {
        this.memoriesLoading = false;
        this.$message.error(i18n.t('kidsParent.loadFailed'));
      });
    },
    deleteMemory(row) {
      Api.agent.deleteKidsMemory(this.selectedAgentId, row.id, (res) => {
        const body = res && res.data;
        if (body && body.code === 0) {
          this.$message.success({
            message: i18n.t('kidsParent.memory.deleteSuccess'),
            showClose: true,
          });
          this.loadMemories();
        } else if (body) {
          this.$message.error(body.msg || i18n.t('kidsParent.memory.deleteFailed'));
        }
      }, () => {
        this.$message.error(i18n.t('kidsParent.memory.deleteFailed'));
      });
    },
    confirmClear() {
      this.$confirm(i18n.t('kidsParent.memory.clearConfirm'), i18n.t('kidsParent.memory.clearAll'), {
        confirmButtonText: i18n.t('kidsParent.memory.confirm'),
        cancelButtonText: i18n.t('kidsParent.memory.cancel'),
        type: 'warning',
      })
        .then(() => {
          Api.agent.clearKidsMemory(this.selectedAgentId, (res) => {
            const body = res && res.data;
            if (body && body.code === 0) {
              this.$message.success({
                message: i18n.t('kidsParent.memory.clearSuccess'),
                showClose: true,
              });
              this.loadMemories();
            } else if (body) {
              this.$message.error(body.msg || i18n.t('kidsParent.memory.clearFailed'));
            }
          }, () => {
            this.$message.error(i18n.t('kidsParent.memory.clearFailed'));
          });
        })
        .catch(() => {});
    },
    logRowClass({ row }) {
      // care（自残/受虐暗示）与 redline（红线话题）标红，便于家长优先介入
      return row.category === 'care' || row.category === 'redline' ? 'red-row' : '';
    },
    categoryTagType(category) {
      if (category === 'care' || category === 'redline') {
        return 'danger';
      }
      if (category === 'danger' || category === 'profanity') {
        return 'warning';
      }
      return 'info';
    },
    formatTime(value) {
      if (!value) {
        return '';
      }
      const d = new Date(value);
      if (Number.isNaN(d.getTime())) {
        return '';
      }
      const pad = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    },
  },
};
</script>

<style lang="scss" scoped>
.kids-parent {
  max-width: 1080px;
  margin: 0 auto;
  padding: 24px 16px 48px;
}

.kids-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;

  .main-title {
    font-size: 22px;
    font-weight: 600;
    color: #303133;
    margin: 0 0 4px;
  }

  .sub-title {
    font-size: 13px;
    color: #909399;
    margin: 0;
  }

  .agent-select {
    width: 240px;
  }
}

.section-card {
  margin-bottom: 20px;
  border-radius: 8px;

  ::v-deep .el-card__header {
    padding: 12px 20px;
  }
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  color: #303133;

  .section-hint {
    font-size: 12px;
    font-weight: 400;
    color: #909399;
  }
}

::v-deep .red-row {
  color: #f56c6c;

  .cell {
    color: #f56c6c;
  }
}

.danger-text {
  color: #f56c6c;
}
</style>
