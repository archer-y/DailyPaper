# GitHub Actions 配置指南

本文档说明如何配置 GitHub Actions 实现每日自动运行论文推荐。

## 一、配置 Secrets

进入仓库的 **Settings → Secrets and variables → Actions → New repository secret**

### 必需 Secrets

| Secret Name | 说明 | 示例值 |
|---|---|---|
| `ZOTERO_ID` | Zotero 用户 ID（纯数字） | `8327135` |
| `ZOTERO_KEY` | Zotero API Key（只读权限） | `AB5tZ877P2j7Sm2Mragq041H` |
| `OPENAI_API_KEY` | OpenAI 或兼容服务 API Key | `sk-xxx` 或 `sk-sp-xxx` |
| `OPENAI_BASE_URL` | API 地址 | `https://api.lkeap.cloud.tencent.com/coding/v3` |
| `FEISHU_WEBHOOK` | 飞书群机器人 Webhook | `https://open.feishu.cn/open-apis/bot/v2/hook/xxx` |

### 可选 Secrets

| Secret Name | 说明 |
|---|---|
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar API Key，提高请求限额 |
| `WECHAT_WORK_WEBHOOK` | 企业微信群机器人 Webhook |

---

## 二、配置 Variables（可选）

进入 **Settings → Secrets and variables → Actions → Variables tab**

默认使用 `config/custom.yaml` 中的配置，如需覆盖可通过 Variables 设置：

| Variable Name | 说明 | 默认值 |
|---|---|---|
| `NAME` | Git 提交者名称 | `github-actions[bot]` |
| `EMAIL` | Git 提交者邮箱 | `41898282+github-actions[bot]@users.noreply.github.com` |

---

## 三、运行方式

### 自动运行

每天北京时间 **09:00**（UTC 01:00）自动运行。

修改运行时间：编辑 `.github/workflows/main.yml` 中的 `cron` 表达式。

```
cron: '0 1 * * *'  # UTC 时间
# 北京时间 09:00 = UTC 01:00
```

### 手动触发

1. 进入仓库 **Actions** 页面
2. 选择 **Daily Paper Digest** workflow
3. 点击 **Run workflow** → **Run workflow**

---

## 四、配置文件说明

### config/custom.yaml 核心配置

```yaml
source:
  arxiv:
    category: ["cs.AI","cs.LG","cs.RO","cs.SY","cs.MA","eess.SY"]
    include_cross_list: true
    date_range: "1month"  # 时间范围: 1day/3days/1week/1month
  openalex:
    enabled: true  # 启用 OpenAlex 数据源
    keywords: ["agent","scheduling","satellite","optimization"]
    date_range: "1month"
    max_results: 100

executor:
  debug: false  # 生产环境设为 false
  max_paper_num: 10
  source: ['arxiv', 'openalex']
  keywords: ["Agent","multi-agent","autonomous agent","tool-use","planning",
             "scheduling","optimization","spacecraft","satellite","mission planning",
             "orbital","observation","Earth observation","positioning","RAG"]
  keyword_score_weight: 0.3
  filter_mode: "parallel"  # 并行筛选模式
  similarity_threshold: 2.0
  candidate_pool_size: 50

llm:
  generation_kwargs:
    model: glm-5  # 或 hunyuan-turbos
  language: Chinese

notifications:
  enabled: true
```

---

## 五、验证配置

### 检查 Secrets 是否正确

1. 进入 **Actions** 页面
2. 手动触发 workflow
3. 查看运行日志，确认无错误

### 常见问题

#### Q: 报错 `ZOTERO_ID not found`

**A**: 检查 Secrets 名称是否正确，区分大小写

#### Q: 报错 `Invalid ARXIV_QUERY`

**A**: 检查 arXiv 类别是否正确，参考 https://arxiv.org/category_taxonomy

#### Q: 飞书未收到消息

**A**: 
- 检查 `FEISHU_WEBHOOK` 是否正确
- 确认机器人未被移出群
- 查看 Actions 日志中的错误信息

#### Q: TLDR 生成失败

**A**: 
- 检查 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL` 是否匹配
- 确认模型名称在 `config/custom.yaml` 中正确配置

---

## 六、配置清单

### 必需配置

- [ ] 创建 Zotero API Key
- [ ] 获取 OpenAI/兼容服务 API Key
- [ ] 创建飞书群机器人
- [ ] 配置所有必需 Secrets
- [ ] 手动触发测试

### 可选配置

- [ ] 配置 Semantic Scholar API Key
- [ ] 配置企业微信群机器人
- [ ] 调整 arXiv 类别和关键词
- [ ] 调整运行时间

---

## 七、GitHub 仓库设置步骤

### 步骤 1: Fork 或 Clone 仓库

确保你有仓库的管理员权限。

### 步骤 2: 配置 Secrets

```
Settings → Secrets and variables → Actions → New repository secret
```

依次添加：
- `ZOTERO_ID`
- `ZOTERO_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `FEISHU_WEBHOOK`

### 步骤 3: 提交配置文件

将本地修改的 `config/custom.yaml` 提交到仓库：

```bash
git add config/custom.yaml
git commit -m "Update custom config"
git push
```

### 步骤 4: 测试运行

```
Actions → Daily Paper Digest → Run workflow → Run workflow
```

### 步骤 5: 验证结果

- 检查 Actions 日志无错误
- 飞书群收到消息
- `reports/` 目录有新文件

---

## 八、参考链接

- [Zotero API 文档](https://www.zotero.org/support/dev/web_api/v3/basics)
- [arXiv 类别列表](https://arxiv.org/category_taxonomy)
- [OpenAlex API 文档](https://docs.openalex.org)
- [GitHub Actions 文档](https://docs.github.com/en/actions)
