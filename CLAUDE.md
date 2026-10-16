# xiaozhi-esp32-server

## Agent skills

### Issue tracker

Issues 跟踪在本仓库的 GitHub Issues（liyonglion/xiaozhi-esp32-server，用 gh CLI）。See `docs/agents/issue-tracker.md`.

### Triage labels

使用五个默认 triage 标签（needs-triage / needs-info / ready-for-agent / ready-for-human / wontfix）。See `docs/agents/triage-labels.md`.

### Domain docs

单上下文布局：根目录 `GLOSSARY.md` + `docs/adr/`。See `docs/agents/domain.md`.

## Deployment

生产部署信息（服务器地址、连接方式、systemd 单元、云 MySQL/Redis）在 `~/.xiaozhi-kids.env`（不在仓库内，勿提交、勿粘贴内容到 issue/PR）。
