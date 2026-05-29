# Vibe Research Framework TODO.md

## 0. 任务定位

本 TODO 用于继续完善当前已经基本实现的 repo-specific Vibe Research Framework。请先完整阅读当前实现，再对照本 TODO 制定 plan 或直接实现缺失功能。不要从零重写整个框架，不要重复实现已有功能。当前目标不是引入 Write Agent，也不是生成论文或科研图片，而是把框架补成可安装、可迁移、可配置、可观察、可 dogfood 的版本。

框架的基本定位保持不变：每个工作 repo 内有一个 `.vibe/` 目录，所有 repo-specific 的状态、配置、cycle、run、scheduler、paper DB、wiki、deep research request、idea pool、dashboard、report 和 artifact 都应保存在 `.vibe/` 下。CLI 或框架代码可以作为独立工具安装，但研究状态不能散落在项目根目录或用户 home 目录中。

Codex CLI 负责思考、计划、review、patch、reflect、revised plan、deep research request、wiki update 和 idea pool update；deterministic runner/scheduler 负责真实执行，包括 dry-run、Slurm submit、monitor、collect、provenance、dashboard build、meeting export 和文件状态维护。Codex 不应成为长任务执行和 job provenance 的唯一来源。

## 1. 先做实现审计

在开始补功能前，先检查当前代码已经实现了哪些模块，哪些只是空壳，哪些行为与本 TODO 冲突。审计结果写入：

```text
.vibe/reports/dev/current_alignment_audit.md
```

审计至少覆盖以下内容：

```text
init / config / scheduler / Slurm / cycle / run / revised_plan / deep research / dashboard / idea pool / meeting export / tests / root portal / AGENTS snippet
```

审计报告格式建议如下：

```markdown
# Current Alignment Audit

## 已实现且可用
列出已实现功能、对应文件、已验证命令。

## 已实现但需要加固
列出功能、存在的问题、建议修复方式。

## 尚未实现
列出缺失功能、优先级、依赖关系。

## 与本 TODO 冲突的行为
特别标记 root 写文件、状态不在 `.vibe/`、长任务由 Codex 直接执行、缺少 revised_plan gate、缺少 provenance 等问题。

## 推荐实现顺序
按阶段给出后续开发计划。
```

## 2. 安装和部署形态

需要支持“框架代码”和“repo-specific 状态”分离。推荐采用两层结构：框架 CLI 可以通过 `pipx install git+...`、`pip install -e ...` 或本地 clone 安装；目标工作 repo 只保存 `.vibe/` 目录作为研究状态和 artifact 根目录。

需要实现或补齐以下能力：

```text
vibe init
vibe init --auto
vibe init --minimal
vibe init --root-portal copy
vibe init --root-portal symlink
vibe init --root-portal none
vibe init --no-root-portal
vibe vendor-runtime
vibe portal build
```

默认安装策略可以创建根目录可见入口，但这些入口必须只是 portal 或 dashboard 的生成视图，不是权威状态文件。也就是说，默认可以生成：

```text
RUN.md
VIBE_STATUS.md
VIBE_TODO.md
VIBE_TIMELINE.md
VIBE_LEADERBOARD.md
```

但这些文件必须满足以下条件：

```text
1. 内容由 `.vibe/portal/` 或 `.vibe/dashboard/` 生成；
2. 文件开头明确标注 generated / mirror / portal；
3. 删除这些根目录文件不会丢失任何状态；
4. `vibe portal build` 可以重新生成；
5. 用户可以在 init 时关闭它们。
```

如果用户选择 `--no-root-portal` 或 `--root-portal none`，则除 `.vibe/` 外，不应在 repo 根目录写任何文件。

不要默认修改根目录已有的 `AGENTS.md`。应生成：

```text
.vibe/AGENTS.md
.vibe/AGENTS_SNIPPET.md
```

如果需要把 snippet 加入根目录 `AGENTS.md`，必须由用户显式选择，例如：

```text
vibe init --install-agents-snippet
```

或者在 interactive init 中确认。

### Init 时的项目目标 / 背景 / 初始想法

初始化不应该只创建空状态。每个 repo-specific VibeResearch 项目都必须有一个大致的研究目标和项目背景，作为后续 Leader、Reviewer、deep research request、dashboard 和 meeting export 的基础上下文。

需要支持：

```text
vibe init --goal "..." --background "..."
vibe init --brief-file PROJECT_BRIEF.md
vibe init --idea "..."
vibe init --idea-file initial_ideas.md
```

规则：

```text
1. 普通 init 必须得到项目目标 / 背景。interactive init 应询问用户；non-interactive init 应通过 `--goal`、`--background` 或 `--brief-file` 提供。
2. `--minimal` 可以只创建 `.vibe/` 骨架，但必须把 project brief 标记为 missing，并让 `vibe next` 或 dashboard 显示需要补充目标 / 背景。
3. 项目目标 / 背景应写入 `.vibe/project/brief.md`，并同步到 config 的 project metadata；不要只写在根目录 README 或聊天记录里。
4. 初始想法是 optional。用户可以通过一个或多个 `--idea`，或通过 `--idea-file` 提供。
5. 初始想法必须进入 raw inbox；在 Idea Pool 阶段还要进入 `.vibe/ideas/` 并标注 source=`init`.
6. 这些内容必须被 Codex planning、Reviewer、deep research request、dashboard 和 meeting export 读取。
```

## 3. 配置系统

需要实现或加固以下配置文件：

```text
.vibe/config.yaml
.vibe/config.schema.json
.vibe/config.local.yaml
.vibe/scheduler/budget.yaml
```

`config.yaml` 存 repo-specific 的可提交默认配置。`config.local.yaml` 存本机路径、账号、私有环境变量、个人偏好，默认应被 git ignore。`budget.yaml` 存 scheduler 和资源预算。需要提供 schema 校验，避免配置字段漂移。

推荐配置内容包括：

```yaml
project:
  name:
  root:
  vibe_dir: .vibe

portal:
  root_portal: copy        # copy / symlink / none
  create_root_entries: true
  generated_notice: true

codex:
  provider: codex_cli
  command:
  model:
  approval_mode:
  sandbox:
  quota_display: manual    # manual / unknown / detected

slurm:
  enabled: auto
  account:
  qos:
  preferred_partitions: []
  fallback_partitions: []
  partition_priority: {}
  default_time:
  default_cpus:
  default_mem_gb:
  default_gpus:

scheduler:
  max_parallel_jobs:
  max_gpu_jobs:
  max_total_gpus:
  max_walltime_hours_per_cycle:
  max_failed_runs_before_pause:
  queue_policy:
  allow_parallel_runs:

portfolio:
  mode: exploration        # exploration / balanced / exploitation
  max_runs_per_cycle:
  min_distinct_directions:
  max_same_direction_runs:
  require_portfolio_review:

deep_research:
  enabled: true
  default_blocking: false
  allow_pdf_ingest: true
  allow_markdown_ingest: true

ideas:
  enabled: true
  max_active_ideas:
  stale_after_days:
  require_cleanup_each_cycle: true

dashboard:
  enabled: true
  static_site_dir: .vibe/site
  serve_host: 127.0.0.1
  serve_port: 8765
```

需要实现：

```text
vibe config detect
vibe config validate
vibe config show
vibe config edit
```

`vibe config detect` 应尽量自动探测：

```text
git 状态
python / venv / conda 环境
Slurm 是否存在
sinfo partition 能力
squeue 当前队列压力
sacct 是否可用
nvidia-smi 是否可用
GPU 型号和数量
当前 repo root
常见数据/结果目录
```

partition 探测不能只靠 `squeue`。应优先用 `sinfo` 看 partition 能力，用 `squeue` 看排队情况，用 `sacct` 看历史完成状态。自动建议可以写入 `.vibe/config.detected.yaml`，再由用户确认合并到 `config.yaml` 或 `config.local.yaml`。

## 4. Root Portal 规则

根目录可见入口是方便用户查看，不是状态存储。需要实现 root portal 的测试和 guard。

需要支持：

```text
默认创建 root portal；
安装时可关闭 root portal；
root portal 可重新生成；
root portal 不保存唯一状态；
所有 authoritative state 均在 `.vibe/` 中。
```

测试要求：

```text
1. `vibe init --no-root-portal` 后，根目录只新增 `.vibe/`；
2. 默认 `vibe init` 只新增允许的 portal 文件；
3. 删除 root portal 后，`vibe portal build` 可重建；
4. `.vibe/` 中有 portal 源文件；
5. dashboard build 不应意外写入根目录。
```

## 5. Idea Pool / 想法池

需要新增或加固一个显式 idea pool。它不同于 raw inbox。inbox 捕获用户原始输入，idea pool 是经过维护的工作池，用于承载用户、Leader、Reviewer、revised plan、literature refresh、deep research ingest 和 cycle reflection 产生的想法。

初始化阶段提供的 optional 初始想法也应进入 idea pool，source 标记为 `init`，并保留与 `.vibe/project/brief.md` 的关联。这样项目一开始就有目标背景和初始假设，而不是等第一轮 chat 之后才产生上下文。

建议结构：

```text
.vibe/ideas/
  pool.md
  active.md
  deep_research_candidates.md
  backlog.md
  rejected.md
  archive.md
  registry.jsonl
```

每个 idea 应有稳定 ID，例如：

```text
idea_001
idea_002
idea_003
```

idea 至少应包含：

```markdown
## idea_001: short title

### Source
来自用户 / Leader / Reviewer / revised_plan / literature_refresh / deep_research / cycle_reflect。

### Status
new / triaged / actionable_next_run / queued_for_cycle / needs_literature_refresh / needs_deep_research / waiting_user_decision / implemented / rejected / archived / superseded

### Priority
high / medium / low

### Confidence
high / medium / low

### Linked evidence
关联 cycle、run、direction、paper、wiki page、deep research request。

### Why it matters
为什么这个想法重要。

### Current evidence
已有证据是什么。

### Next action
下一步应该直接实验、查文献、做 deep research、等待用户、还是拒绝。

### Rejection or archive reason
如果拒绝或归档，说明原因。
```

需要实现或规划以下命令：

```text
vibe ideas list
vibe ideas triage
vibe ideas promote <idea_id>
vibe ideas reject <idea_id>
vibe ideas archive <idea_id>
vibe ideas clean
vibe ideas build-deep-request <idea_id>
vibe deep-request-from-idea <idea_id>
```

每个 run-level revised plan 和 cycle-level revised plan 都必须显式维护 idea pool。也就是说，每次 revise plan 后应回答：

```markdown
## Idea pool update
本轮是否产生新想法？
哪些旧想法变成 actionable？
哪些想法需要 literature refresh？
哪些想法需要 deep research？
哪些想法应该 rejected / archived / superseded？
```

需要有清理机制，避免 idea pool 变成垃圾堆。`vibe ideas clean` 应检查：

```text
过期 idea
重复 idea
已实现但未归档 idea
已被实验否定但仍在 active 的 idea
deep research candidates 中过于泛泛的 idea
没有 linked evidence 的 idea
```

## 6. Deep Research 与 Idea Pool 的关系

Deep research 不应自动凭空触发。Agent 可以标记某个 idea `needs_deep_research`，但是否真正生成 deep research request，应由用户在 dashboard 或 CLI 中决定。

推荐逻辑：

```text
1. Codex 每轮会产生想法；
2. 能直接实现的想法进入下一轮 portfolio 或 run；
3. 重要但难以实现、路线级不确定、需要外部系统性判断的想法进入 `.vibe/ideas/deep_research_candidates.md`；
4. dashboard 显示这些 deep research candidates；
5. 用户判断是否对某个 idea 生成 deep research request；
6. 用户点击 dashboard 按钮或运行 CLI；
7. Codex 基于 idea pool + 当前 repo 架构 + 实验状态 + wiki + leaderboard 生成 deep research prompt；
8. 用户把 markdown/pdf deep research 结果放回 `.vibe/research/raw/deep_reports/`；
9. `vibe ingest-deep-research` 解析报告并更新 paper DB、wiki、idea pool、TODO 和 revised plan。
```

需要支持：

```text
vibe deep-request-from-idea idea_012
vibe deep-request --run-id r001 "route selection" --blocking
vibe deep-request-cycle c001 "route selection" --blocking
vibe ingest-deep-research dr001
```

生成 deep research request 时，不要只根据 idea 本身写泛泛 prompt。必须读取：

```text
idea 内容
相关 cycle / run evidence
当前 leaderboard
best_by_direction
相关 wiki 页面
paper DB
当前 repo 架构或代码摘要
scheduler/resource 约束
open questions
Reviewer 意见
revised plan
```

request 文件放在：

```text
.vibe/research/deep_requests/drXXX_short_topic.md
```

deep research request 应包含：

```markdown
# Deep Research Request: drXXX_short_topic

## Project context
说明当前 repo、长期目标、当前 leaderboard、资源限制和实验阶段。

## Current architecture / workflow
说明当前代码结构、pipeline、runner、scheduler、数据流和关键模块。

## Selected idea
说明 idea ID、来源、为什么重要、为什么不能直接靠普通实验解决。

## Current experimental evidence
总结相关 run/cycle 的成功、失败、guardrail、subgroup/OOD 和 Reviewer 判断。

## Existing local knowledge
列出已入库论文、wiki 页面、相关 repo、已下载权重和当前 hypotheses。

## Core research question
明确这轮 deep research 要回答的问题。

## Required comparisons
列出必须比较的方法族、baseline、数据集、benchmark、repo 或权重。

## What counts as useful output
要求输出可执行结论，例如推荐路线、停止路线、可复现实验、需要 clone 的 repo、需要读的论文、潜在风险。

## What to avoid
禁止泛泛综述、无来源建议、只列论文不综合、忽略当前 repo 约束。

## Expected deliverable
要求最终报告包含 evidence table、method map、repo/weight list、risk assessment、recommended next experiments 和 citations。
```

`vibe ingest-deep-research` 需要支持 markdown 和 PDF。PDF 用 PyMuPDF 抽文本，不需要 OCR。ingest 时支持 `--kind science|workflow|repo|benchmark`，其中 `workflow` 用于审计当前 `.vibe` 框架本身。

ingest 后应更新：

```text
paper DB
raw repos / repo queue
wiki/papers
wiki/concepts
wiki/entities
wiki/comparisons
wiki/gaps
wiki/synthesis
idea pool
inbox triage
dashboard
timeline
revised_plan 或 cycle_revised_plan，如果报告改变了决策
```

## 7. Portfolio / Cycle / Run

框架必须支持 cycle-level portfolio，而不是每轮只设计一个实验。早期 exploration mode 应允许多个方向并行探索；中期 balanced mode 应减少到 2-3 个方向；后期 exploitation mode 可以收敛到 1-2 个 focused runs。

需要检查并加固以下结构：

```text
.vibe/cycles/c001/
  portfolio_plan.md
  portfolio_review.md
  resource_plan.yaml
  cycle_reflect.md
  cycle_revised_plan.md
  runs.txt

.vibe/runs/r001_short_name/
  proposal.md
  review.md
  manifest.yaml
  patch.diff
  dryrun.json
  launch.json
  metrics.json
  reflect.md
  revised_plan.md
```

`portfolio_plan.md` 应说明：

```markdown
## Stage
exploration / balanced / exploitation

## Current leaderboard summary
当前 best trusted、best candidate、各 direction 最好结果，以及上一轮主要失败原因。

## User ideas and directives considered
本轮读取了哪些用户新想法、哪些被采纳、哪些延后、哪些拒绝。

## Candidate directions
列出本轮考虑的方向，每个方向说明动机、已有证据、风险和成本。

## Selected runs
列出本 cycle 要执行的 run。

## Dependency graph
说明哪些 run 可以并行，哪些 run 依赖前置 smoke 或数据准备。

## Resource budget
说明 GPU、CPU、内存、时间、Slurm partition、最大并行数和取消条件。

## Portfolio success criteria
这一整个 cycle 成功的标准是什么。

## Stop or shrink criteria
什么情况下停止某个方向，什么情况下从 exploration 收敛到 balanced 或 exploitation。

## Idea pool update
本轮从 idea pool 中选择了哪些 idea，哪些 idea 被延后、拒绝或标记为 deep research candidate。
```

`cycle_revised_plan.md` 应说明：

```markdown
## Cycle-level interpretation
这一轮 portfolio 中哪些 run 有价值，哪些失败，哪些结果互相矛盾。

## Direction decisions
对每个 direction 给出 promote / continue / pause / stop / needs_evidence。

## Portfolio mode update
下一轮是 exploration / balanced / exploitation。说明为什么扩大、保持或缩小并行实验数量。

## Next portfolio sketch
下一轮建议包含几个 run，分别来自哪些 direction，哪些可以并行，哪些有依赖。

## Resource update
下一轮最大并行 job、GPU 数、partition 偏好和取消规则。

## Literature and deep research decision
说明是否需要普通 literature refresh 或 deep research request。若需要，说明服务于哪个 direction 或哪个 idea。

## Idea pool maintenance
更新 idea pool：哪些 idea 变为 actionable、needs_deep_research、rejected、archived 或 superseded。

## User decision needed
如果需要用户判断，明确写出问题和可选项。

## Stop condition
明确什么情况下停止整个方向或结束本阶段探索。
```

## 8. Scheduler 和 Slurm

需要检查并加固 scheduler。它必须支持多个 run 排队和并行，但不能无限提交 job。需要有：

```text
.vibe/scheduler/queue.json
.vibe/scheduler/budget.yaml
.vibe/scheduler/active_jobs.json
.vibe/scheduler/completed_jobs.jsonl
```

`budget.yaml` 应支持：

```yaml
max_parallel_jobs:
max_gpu_jobs:
max_total_gpus:
max_walltime_hours_per_cycle:
max_failed_runs_before_pause:
queue_policy:
partition_priority:
fallback_partitions:
cancel_rules:
```

scheduler 必须尊重：

```text
dry-run 未通过，不得 submit；
manifest schema 未通过，不得 submit；
Portfolio Reviewer block，不得 submit；
Run Reviewer block，不得 submit；
dependency 未满足，不得 submit；
超过 budget，不得 submit；
同一 direction 连续失败超过阈值，应 pause；
expensive training 依赖 cheap smoke 时，不得提前 submit；
```

Slurm 支持应包括：

```text
sinfo partition 探测
squeue queue 状态
sacct completed job 查询
nvidia-smi GPU 可见性
partition fallback
job id 记录
log path 记录
OOM / timeout / NaN / ImportError / permission / quota 失败分类
```

## 9. Dashboard / Website

需要实现或加固静态 dashboard。dashboard 放在：

```text
.vibe/site/
```

或：

```text
.vibe/dashboard/site/
```

默认 read-only，可用：

```text
vibe dashboard build
vibe dashboard serve
```

dashboard 应从以下文件构建：

```text
.vibe/dashboard/status.json
.vibe/dashboard/timeline.jsonl
.vibe/leaderboard/*.json
.vibe/cycles/*
.vibe/runs/*
.vibe/ideas/*
.vibe/research/deep_requests/registry.jsonl
.vibe/scheduler/*
```

页面至少包括：

```text
Cycle cards
Run cards
Direction board
Scheduler / Slurm status
Leaderboard
Timeline
Idea pool panel
Deep research candidate panel
Wiki / paper queue
Artifact browser
Meeting report links
```

点击 run block 应显示：

```text
proposal.md
review.md
manifest.yaml
metrics.json
reflect.md
revised_plan.md
launch.json
logs
artifacts
```

点击 cycle block 应显示：

```text
portfolio_plan.md
portfolio_review.md
resource_plan.yaml
cycle_reflect.md
cycle_revised_plan.md
```

点击 idea block 应显示：

```text
source
status
priority
confidence
linked evidence
why it matters
current evidence
next action
CLI command
```

对 `needs_deep_research` 的 idea，dashboard 应显示：

```text
vibe deep-request-from-idea idea_012
```

如果实现 dashboard 按钮，则必须本地只读或本地 token 保护。默认不要开放 public writable server。用户有 cloudflared 域名，但框架默认不应假设公网安全。

Codex quota display：如果没有可靠来源，不要伪造。dashboard 可以显示：

```text
Codex quota: unknown/manual
```

或读取：

```text
.vibe/state/codex_budget.md
```

不得声称真实剩余额度，除非有可靠可验证来源。

## 10. Research Wiki 和 Paper DB

保持 agent-facing wiki 结构：

```text
.vibe/research/wiki/
  index.md
  log.md
  overview.md
  papers/
  concepts/
  entities/
  comparisons/
  gaps/
  synthesis/
```

raw materials 放在：

```text
.vibe/research/raw/
  papers_pdf/
  papers_md/
  deep_reports/
  repos/
  weights/
  notes/
  assets/
```

paper DB 放在：

```text
.vibe/research/papers.sqlite
```

每篇论文至少记录：

```text
paper_id
title
authors
year
venue
arxiv_id
doi
source_url
pdf_url
local_pdf_path
sha256
downloaded_at
ingested_at
status
confidence
tags
related_cycle_ids
related_run_ids
related_idea_ids
related_deep_request_ids
repo_urls
weight_urls
dataset_names
notes
```

wiki 更新规则：

```text
论文 ingest 后不能只写孤立 paper note；
必须更新相关 concepts / entities / comparisons / gaps / synthesis；
index.md 每次更新；
log.md append-only；
有价值的问答、对比分析、deep research 结论和组会故事线应写回 wiki。
```

## 11. Meeting Export / 组会汇报

暂时不要引入 Write Agent，但需要支持组会汇报材料导出：

```text
vibe export-meeting
vibe export-meeting --date YYYYMMDD
```

输出到：

```text
.vibe/reports/meeting/YYYYMMDD/
```

内容包括：

```text
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

`export-meeting` 不负责写完整论文，也不负责生成正式 PPT。它的任务是从已有 wiki、run logs、results、leaderboard、idea pool 和 deep research status 中整理出组会可用 story pack，方便后续用 Codex 或其他工具生成 PDF/PPT。

## 12. Revised Plan Invariants

每个 run 在 collect 后必须有：

```text
reflect.md
revised_plan.md
```

每个 cycle 在关键 run 完成后必须有：

```text
cycle_reflect.md
cycle_revised_plan.md
```

没有 revised plan 的 run：

```text
不能标记 completed；
不能 merge；
不能进入 trusted leaderboard；
不能作为下一轮唯一依据。
```

没有 cycle revised plan 的 cycle：

```text
不能进入下一轮 portfolio；
不能自动扩大或收缩实验方向；
不能归档为 completed cycle。
```

`revised_plan.md` 应包含：

```markdown
## Result interpretation
上一轮实验的核心结果是什么，是否支持原始 hypothesis，哪些指标可信，哪些指标需要谨慎解释。

## Decision
continue_same_plan / modify_experiment / run_ablation / repeat_seed / collect_more_metrics / literature_refresh_needed / deep_research_needed / stop_branch / merge_candidate / ask_user

## Plan update
下一步具体做什么。如果计划不变，也必须说明为什么不变，以及继续执行的最小下一步。

## Required changes
需要修改哪些代码、配置、数据处理、评估脚本、Slurm 资源或日志结构。如果没有修改，也写明 none，并解释原因。

## Evidence needed
下一步是否需要外部证据。如果需要，列出需要查询的论文、repo、issue、benchmark、leaderboard、权重来源或 deep research 问题。如果不需要，说明为什么当前证据已经足够推进。

## Literature refresh decision
明确写 yes / no。如果 yes，说明检索目标、关键词、优先来源和预期如何影响下一步。如果 no，说明为什么当前阶段不需要检索。

## Deep research decision
明确写 yes / no。如果 yes，说明关联 idea、deep research request id、核心研究问题、为什么普通联网检索不足、预期输出格式、是否阻塞当前 pipeline。如果 no，说明为什么当前问题不需要路线级深度研究。

## Idea pool update
本轮是否产生新想法？哪些旧想法变为 actionable？哪些想法需要 literature refresh？哪些想法需要 deep research？哪些想法应 rejected / archived / superseded？

## Next experiment proposal
如果可以直接进入下一轮实验，写出下一轮 run 的 hypothesis、baseline、success criteria、guardrails、resource budget 和 expected learning。

## Stop condition
明确什么结果会导致停止这个方向，避免无限小修小补。
```

## 13. CLI 需求

检查并补齐以下 CLI：

```text
vibe init
vibe status
vibe next
vibe idea
vibe directive
vibe ideas list
vibe ideas triage
vibe ideas promote
vibe ideas reject
vibe ideas archive
vibe ideas clean
vibe ideas build-deep-request
vibe config detect
vibe config validate
vibe config show
vibe config edit
vibe portal build
vibe plan-cycle
vibe review-cycle
vibe generate-runs
vibe review
vibe branch
vibe patch
vibe dryrun
vibe queue
vibe submit-queue
vibe monitor
vibe collect
vibe reflect
vibe revise-plan
vibe reflect-cycle
vibe revise-cycle
vibe lit-refresh
vibe deep-request
vibe deep-request-cycle
vibe deep-request-from-idea
vibe ingest-deep-research
vibe wiki-ingest
vibe dashboard build
vibe dashboard serve
vibe export-meeting
vibe leaderboard
vibe timeline
vibe merge
vibe abandon
```

`vibe next` 应综合判断：

```text
是否有未 triage 的 user idea；
是否有 portfolio review pending；
是否有 run review pending；
是否有 dry-run pending；
是否有 job running；
是否有 collect pending；
是否有 reflect pending；
是否有 revised_plan missing；
是否有 cycle_revised_plan missing；
是否有 literature refresh requested；
是否有 deep research candidate waiting for user；
是否 blocking deep research 未 ingest；
是否 idea pool 需要 clean；
是否可进入下一轮 cycle。
```

## 14. 测试要求

测试必须能在无 Slurm、无网络、无 GPU 的环境下运行。不要在测试中提交真实 job，不要调用外部 API，不要启动 cloudflared，不要跑长训练。

需要添加或补齐测试：

```text
fake sinfo / squeue / sacct fixture
config schema tests
config detect tests with mocked commands
root portal default creation test
--no-root-portal test
portal rebuild test
idea pool creation / triage / promote / reject / archive / clean tests
deep-request-from-idea test
deep research markdown ingest test
deep research PDF ingest test
dashboard generation test with synthetic data
scheduler budget test
dependency / cancel rule test
revised-plan invariant test
cycle revised-plan invariant test
CLI smoke tests
meeting export test
```

验收标准：

```text
1. `vibe init --minimal --no-root-portal` 只创建 `.vibe/`；
2. 默认 init 可创建 root portal，但 root portal 可重建且不保存唯一状态；
3. config 可 validate；
4. fake Slurm 环境下 config detect 可生成推荐配置；
5. idea pool 可维护，不只是 append-only dump；
6. revised plan 会更新 idea pool；
7. deep research request 可从 idea 生成；
8. deep research markdown/pdf 可 ingest；
9. dashboard 可用 synthetic data 构建；
10. meeting export 可生成 story pack；
11. 无 revised_plan 的 run 不能 trusted/merge；
12. 无 cycle_revised_plan 的 cycle 不能进入下一轮。
```

## 15. 推荐实现阶段

### Phase 1：实现审计和配置边界

完成 current alignment audit，明确已有功能和缺口。补齐 config schema、config detect、root portal policy、AGENTS snippet 生成。确保 `.vibe/` 是权威状态根目录。

### Phase 2：安装和 portal

完善 `vibe init` 的 interactive / auto / minimal 模式。支持默认 root portal 和 `--no-root-portal`。实现 `vibe portal build`。

### Phase 3：Idea Pool

实现 `.vibe/ideas/` 结构和 CLI。让 revised plan 和 cycle revised plan 能维护 idea pool。dashboard 先以静态方式显示 idea pool。

在本阶段补上 init intake enhancement：让已有 `vibe init` 支持必需的项目目标 / 背景和 optional 初始想法。由于 0.4.0 可能已经实现了 init/config/portal 基础能力，本增强可以作为 0.5.0 的兼容补丁加入，不要求重写 0.4.0。

### Phase 4：Deep Research from Idea

实现 `vibe deep-request-from-idea`。让 deep research request 能读取 idea pool、leaderboard、wiki、run/cycle evidence 和 repo architecture。支持 markdown/pdf ingest，并更新 idea pool。

### Phase 5：Dashboard

实现静态 dashboard，展示 cycle、run、direction、leaderboard、scheduler、idea pool、deep research candidate、wiki/paper queue 和 artifact。默认 read-only。

### Phase 6：Meeting Export

实现 `vibe export-meeting`，生成组会 story pack。不要生成正式论文或 PPT，只整理证据和 slides outline。

### Phase 7：Dogfood

完成上述功能后，跑一个 cheap local/mock cycle。不要直接提交长 Slurm job。dogfood 目标是验证：

```text
init
config
idea pool
plan-cycle
portfolio review
mock run
collect
reflect
revised plan
cycle revised plan
dashboard
deep-request-from-idea
meeting export
```

## 16. 最终交付要求

完成后需要生成：

```text
.vibe/reports/dev/alignment_after_changes.md
.vibe/reports/dev/test_summary.md
.vibe/portal/INSTALL.md
.vibe/portal/USAGE.md
.vibe/portal/AGENTS_SNIPPET.md
.vibe/dashboard/status.md
.vibe/dashboard/TODO.md
.vibe/dashboard/TIMELINE.md
.vibe/site/index.html
```

最后请给出一段简短总结，说明：

```text
哪些功能已完成；
哪些功能仍是 TODO；
如何安装到一个新 repo；
如何关闭 root portal；
如何配置 Slurm；
如何维护 idea pool；
如何从 idea 生成 deep research request；
如何构建 dashboard；
如何导出组会材料；
下一轮 dogfood 应该怎么跑。
```
