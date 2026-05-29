<h1 align="center">VibeResearch</h1>
<h3 align="center">面向 Codex、Slurm、Idea Pool、Dashboard 和组会汇报的 repo-local 研究编排框架</h3>

<p align="center">
  <strong>把长期研究状态集中保存在目标仓库的 <code>.vibe/</code> 目录中，让规划、执行、监控、复盘和汇报形成闭环。</strong>
</p>

<p align="center">
  <a href="../README.md">English</a> |
  <a href="README_CN.md">中文</a>
</p>

<p align="center">
  <a href="#快速开始"><img src="https://img.shields.io/badge/-快速开始-blue?style=for-the-badge" alt="快速开始"/></a>
  <a href="#dashboard-和报告"><img src="https://img.shields.io/badge/-Dashboard-orange?style=for-the-badge" alt="Dashboard"/></a>
  <a href="#slurm-和-scheduler"><img src="https://img.shields.io/badge/-Slurm-green?style=for-the-badge" alt="Slurm"/></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/Codex_CLI-compatible-green.svg" alt="Codex CLI"/>
  <img src="https://img.shields.io/badge/state-.vibe%2F-informational.svg" alt=".vibe state"/>
  <img src="https://img.shields.io/badge/default-read--only_dashboard-lightgrey.svg" alt="Read-only dashboard"/>
</p>

---

## 这是什么

VibeResearch 是一个 repo-specific 的持续研究编排框架。它会在目标仓库中创建 `.vibe/` 控制层，并把权威研究状态集中保存在这里：项目 brief、配置、cycle、run、scheduler 队列、paper DB、wiki、idea pool、deep research request、dashboard、report 和 artifact。

Codex 可以负责编写 plan、review、patch、reflection、revised plan、wiki update 和 deep research request；确定性的 Python 代码负责 dry-run、排队、Slurm 提交、监控、结果收集、provenance、dashboard 和组会材料导出。

## 快速开始

先从本仓库安装 CLI：

```bash
cd /path/to/VibeResearch
python -m pip install -e .
```

然后进入你的目标研究仓库：

```bash
cd /path/to/your/research-repo
vibe init \
  --goal "在固定协议下提升 robust validation 表现" \
  --background "项目背景、数据、指标、算力约束和当前 baseline"
```

检查状态和下一步：

```bash
vibe config validate
vibe status
vibe next
```

如果不希望目标仓库根目录生成 `RUN.md` / `VIBE_*.md` 镜像文件：

```bash
vibe init --no-root-portal --goal "..." --background "..."
```

## 跑一个本地 Mock Cycle

下面这条路径适合无 Slurm、无 GPU、无网络、无 Codex 登录的机器：

```bash
vibe idea "先跑一个便宜的 baseline diagnostic，再考虑昂贵训练"
vibe ideas triage
vibe plan-cycle --offline
vibe review-cycle c001 --offline
vibe generate-runs c001 --count 1
vibe review r001_baseline_check --offline
vibe patch r001_baseline_check --offline
vibe dryrun r001_baseline_check
vibe queue r001_baseline_check
vibe submit-queue --dry
vibe monitor
vibe collect r001_baseline_check --metric 0.1
vibe reflect r001_baseline_check --offline
vibe revise-plan r001_baseline_check --offline
vibe reflect-cycle c001 --offline
vibe revise-cycle c001 --offline
```

也可以直接运行内置 smoke workflow：

```bash
vibe dogfood
```

## 会创建哪些文件

```text
.vibe/
  project/brief.md
  config.yaml
  config.schema.json
  config.local.yaml
  state/
  cycles/
  runs/
  scheduler/
  ideas/
  research/
  dashboard/
  site/
  reports/
  portal/
```

根目录中的 `RUN.md`、`VIBE_STATUS.md`、`VIBE_TODO.md`、`VIBE_TIMELINE.md`、`VIBE_LEADERBOARD.md` 只是生成镜像，不是权威状态。权威状态始终在 `.vibe/` 下。删除根目录镜像后可以随时重建：

```bash
vibe portal build
```

默认不会修改根目录已有的 `AGENTS.md`。只有显式传参时才会安装 snippet：

```bash
vibe init --install-agents-snippet --goal "..." --background "..."
```

## 核心工作流

1. 初始化项目上下文：`vibe init --goal ... --background ...`
2. 捕获想法：`vibe idea "..."`，`vibe ideas triage`
3. 制定 portfolio：`vibe plan-cycle`
4. 审核 portfolio：`vibe review-cycle c001`
5. 生成 runs：`vibe generate-runs c001`
6. 审核并 patch 每个 run：`vibe review`，`vibe patch`
7. dry-run 并入队：`vibe dryrun`，`vibe queue`
8. 提交并监控：`vibe submit-queue`，`vibe monitor`
9. 收集指标：`vibe collect`
10. 复盘并修订计划：`vibe reflect`，`vibe revise-plan`，`vibe revise-cycle`
11. 构建 dashboard 和组会材料：`vibe dashboard build`，`vibe export-meeting`

## Idea Pool / 想法池

raw inbox 负责保存用户原始输入；idea pool 负责维护可工作的研究想法，并分配稳定 ID，例如 `idea_001`。

```bash
vibe idea "比较两条路线级方法"
vibe ideas list
vibe ideas triage
vibe ideas promote idea_001
vibe ideas reject idea_001 --reason "暂时超出范围"
vibe ideas archive idea_001
vibe ideas clean
```

相关文件位于 `.vibe/ideas/`：

```text
registry.jsonl
pool.md
active.md
deep_research_candidates.md
backlog.md
rejected.md
archive.md
```

## 从 Idea 生成 Deep Research

把 idea 标记为 `needs_deep_research` 不会自动生成 deep research request。需要用户或 operator 显式触发：

```bash
vibe deep-request-from-idea idea_001
```

把返回的 deep research 报告放到：

```text
.vibe/research/raw/deep_reports/<request_id>_result.md
.vibe/research/raw/deep_reports/<request_id>_result.pdf
```

然后 ingest：

```bash
vibe ingest-deep-research dr001_idea_001 --kind science
vibe ingest-deep-research dr001_idea_001 --kind workflow
vibe ingest-deep-research dr001_idea_001 --kind repo
vibe ingest-deep-research dr001_idea_001 --kind benchmark
```

支持 Markdown 和 PDF。PDF 优先使用 PyMuPDF 抽取文本，不做 OCR。

## Slurm 和 Scheduler

Scheduler 是确定性的，并且会遵守资源预算。未通过 dry-run、manifest 无效、被 portfolio/run review 阻塞、依赖未满足或超出预算的 run 都不会提交。

探测当前环境：

```bash
vibe config detect
```

集群相关配置主要在：

```text
.vibe/config.yaml
.vibe/config.local.yaml
.vibe/scheduler/budget.yaml
```

使用 Slurm 提交：

```bash
vibe submit-queue --backend slurm
vibe monitor --loop --auto-next
```

开发时可以使用 dry submit：

```bash
vibe submit-queue --dry
```

## Dashboard 和报告

构建静态只读 dashboard：

```bash
vibe dashboard build
```

输出：

```text
.vibe/site/index.html
```

本地启动 dashboard：

```bash
vibe dashboard serve --host 127.0.0.1 --port 8765
```

导出组会 story pack：

```bash
vibe export-meeting
vibe export-meeting --date 20260529
```

输出：

```text
.vibe/reports/meeting/YYYYMMDD/
  story.md
  timeline.md
  leaderboard.md
  key_runs.md
  idea_pool.md
  deep_research_status.md
  paper_summary.md
  evidence_table.csv
  slides_outline.md
  figures/
```

生成最终开发报告和 portal 文档：

```bash
vibe finalize-reports
```

## 常用命令

```bash
vibe status
vibe next
vibe config show
vibe config validate
vibe audit current
vibe validate-hard-rules
vibe scheduler-status
vibe leaderboard
vibe timeline
```

## 设计原则

- `.vibe/` 是权威状态根目录。
- 根目录文件只是生成镜像，不保存唯一状态。
- Codex 只写边界清晰的 artifact；确定性代码负责真实执行。
- Dashboard 默认只读。
- 长任务监控不调用 LLM。
- 真实 Slurm / Codex / 网络行为需要在部署环境中验证。

## 当前状态

本地/offline 验收路径已经实现并有测试覆盖：

```bash
python -m pytest -q
```

测试使用 fake/offline Codex 和 dry Slurm 路径，不需要网络、Codex 登录、GPU 或集群。
