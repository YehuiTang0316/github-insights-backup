# GitHub Insights Backup

把 GitHub Insights 持续保存到你自己的私有仓库，保留超过 14 天的历史数据。支持多个项目，无需部署服务器。

## 开始使用

1. 在项目首页点击 **Use this template → Create a new repository**，创建一个 **Private** 仓库。不要 Fork 成公开仓库。
2. 在新仓库的 **Settings → Secrets and variables → Actions → Variables** 添加 `TARGET_REPOSITORIES`，填写 `owner/repo`；多个仓库用逗号或换行分隔。也可以编辑 `config.json` 的 `repositories` 数组。
3. 创建一个 fine-grained GitHub Token：资源所有者选择被采集仓库所属的账号或组织，仅选择需要的仓库，权限为 **Administration: Read-only、Contents: Read-only、Metadata: Read-only**。账号本身也需要能够读取对应仓库的 Traffic。
4. 在新仓库的 **Actions → Secrets** 添加 `INSIGHTS_TOKEN`，值为这个 Token。不要将 Token 填进 Variables 或代码。
5. 在 **Actions → Back up Insights → Run workflow** 手动运行一次。完成后查看 `data/README.md` 和各仓库的 `traffic-daily.csv`。

之后默认每天 **北京时间 09:00（UTC 01:00）** 执行，电脑无需开机。GitHub 调度可能延迟；可以随时手动补跑。组织可能要求审批 Token，需要在过期前更换。

这是公开代码、私有部署的模板：公开项目不包含任何真实 Insights 数据；自动备份会拒绝在公开仓库中执行。它不能绕过权限，获取任意公开项目的访问量或克隆量。

## 多个账号或组织

一个 fine-grained Token 对应一个资源所有者。跨多个组织时，添加 `INSIGHTS_TOKENS_JSON` **Secret**，用 JSON 把组织名映射到各自的 Token，也支持针对 `owner/repo` 指定 Token：

```json
{
  "your-org": "TOKEN_FOR_YOUR_ORG",
  "another-org": "TOKEN_FOR_ANOTHER_ORG"
}
```

匹配优先级：具体仓库 → 所有者 → `INSIGHTS_TOKEN`。

## 数据与统计口径

- 保存访问、克隆、UV、unique cloners、来源、热门页面、Star/Fork 明细、发布和贡献统计。
- 原始 JSON 按 UTC 日期保存为不可覆盖的快照；CSV 按 UTC 日更新，同一天的重复抓取不会重复累加。
- **Unique visitors / cloners 不能跨天或跨窗口直接相加得到累计去重人数。**
- GitHub Traffic 仅提供最近 14 天；开始备份前已经过期的数据无法凭空恢复。
- 当天数据可能未结束；缺失数据保留为未知，不补零。
- GitHub 尚未生成的提交统计会标记为 pending，已成功的数据仍然保存。

本地也可以运行：安装 Python 3.9+ 和 GitHub CLI，执行 `gh auth login`，然后：

```bash
python3 -m insights_backup --repositories your-org/your-repo
```

完整配置、故障排查和限制见 [英文 README](../README.md)，数据结构见 [data.md](data.md)。
