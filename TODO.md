# Vibe Research Framework 设计日志 v0.5

## 0. 总体定位

这套框架的目标不是复刻一个通用 AutoResearcher，而是在任意具体 repo 内部建立一个 repo-specific 的持续研究工作层。用户提供长期目标、新想法、资源边界和最终判断；Codex Pro 负责主要思考、实验设计、代码修改、文献阅读、反思和下一轮计划；本地 deterministic runner 负责所有真实执行，包括 dry-run、Slurm submit、监控、结果收集、metric provenance、PDF 下载、repo clone、weight 下载和日志落盘。核心原则是：Codex 可以是 Leader、Reviewer、Patch Generator、Reflect Agent、Revised Plan Agent 和 Paper-Ingest Agent，但不能成为唯一可信执行源；所有会影响实验状态的行为必须写入本地结构化文件。

这套系统不是每轮只能设计一个实验。真实研究，尤其是早期探索阶段，通常会同时存在多个可能方向。以 CARE 这种任务为例，可能同时有后处理方向、阈值搜索方向、外部模型方向、数据清洗方向、Cine 路线修复方向和 Slurm/评估可靠性方向。框架必须允许 early exploration 阶段并行设计多个实验，并在资源预算内同时提交多个 Slurm job；到了 late exploitation 阶段，才根据 leaderboard、Reviewer 判断和 revised plan 收敛到少数主线甚至单一实验。因此，核心单位不只是单个 run，而是 cycle 或 portfolio。一个 cycle 可以包含多个 run，每个 run 有独立 branch、proposal、review、manifest、metrics、reflect 和 revised plan；cycle 层面则有 portfolio plan、portfolio review、资源调度和跨实验总结。

原 repo 最值得保留的是 THINK → EXECUTE → MONITOR → REFLECT 的循环、训练期间零 LLM 成本监控、长期目标与临时指令分离、滚动 memory、progress report 和本地 fallback。需要改写的是 worker 执行方式：我们仍然使用 Codex CLI，因为 Codex Pro token 多，OpenAI API 额外计费不适合当前目的；但 Codex CLI 只产出 portfolio plan、proposal、review、patch、manifest、reflect、revised plan、literature request 和 wiki update，真实执行由本地 runner 接管。这样可以避免 Codex CLI 内置 agent loop 绕开外部框架，导致 PID、Slurm job id、log path、metric path 等关键 provenance 丢失。

这套系统必须支持用户随时插入新想法。用户可以直接在聊天里输入，也可以写进 `.vibe/inbox/ideas.md`，也可以通过 CLI 命令 `vibe idea "..."` 写入。任何新想法都不能只停留在聊天记录里，必须进入 inbox，经过 triage 后变成 hypothesis、experiment proposal、literature question、deep research request、TODO、long-term goal update 或 rejected note。

这套系统还必须明确区分“反思上一轮”和“计划下一轮”。`reflect.md` 的职责是解释上一轮实验结果，判断原始 hypothesis 是否被支持，分析成功或失败原因；`revised_plan.md` 的职责是把这些判断转化成下一轮可执行方案。每个 run 结束后，`reflect.md` 和 `revised_plan.md` 都是强制产物。即使计划几乎不变，也必须写出为什么不变、下一步继续执行什么、观察哪些指标、何时停止或转向。不能因为“没什么改动”就省略 revised plan。对于一个包含多个 run 的 cycle，还必须生成 `cycle_reflect.md` 和 `cycle_revised_plan.md`，总结多个实验之间的相对价值，并决定下一轮 portfolio 如何收敛或扩展。

文献检索和深度研究要区分。日常 `literature_refresh` 是轻量、及时、可自动执行的联网查询，服务于当前 revised plan 或 portfolio plan；`deep_research_request` 是路线级不确定时的升级接口，用于生成一份可交给 ChatGPT Deep Research、Gemini Deep Research、Perplexity、Claude Research 或人工检索的系统性研究请求。普通检索回答“下一步实验怎么改”；深度研究回答“这个方向是否值得继续、应该转向哪条路线、当前文献与 repo 生态支持什么判断”。两者都不能机械执行，必须由 `revised_plan.md` 或 `cycle_revised_plan.md` 显式决定。

## 1. Repo-specific 文件结构

每个目标 repo 内放一个 `.vibe/` 目录。这个目录是研究控制层、日志层、知识库层和 dashboard 层，但不替代原 repo 的代码结构。根目录还必须保留几个可见入口文件，让用户不需要进入 `.vibe/` 深处也能知道当前进展。

推荐结构如下：

```text
target-repo/
├── RUN.md
├── VIBE_STATUS.md
├── VIBE_LEADERBOARD.md
├── VIBE_TODO.md
├── VIBE_TIMELINE.md
├── requirements-vibe.txt
├── .vibe/
│   ├── PROJECT_BRIEF.md
│   ├── HUMAN_DIRECTIVE.md
│   ├── README_FOR_AGENTS.md
│   ├── config.yaml
│   ├── inbox/
│   │   ├── ideas.md
│   │   ├── user_prompts.md
│   │   ├── questions.md
│   │   └── triage.jsonl
│   ├── state/
│   │   ├── state.json
│   │   ├── lock.json
│   │   ├── memory.md
│   │   ├── decisions.jsonl
│   │   └── open_questions.jsonl
│   ├── cycles/
│   │   └── c001/
│   │       ├── portfolio_plan.md
│   │       ├── portfolio_review.md
│   │       ├── resource_plan.yaml
│   │       ├── cycle_reflect.md
│   │       ├── cycle_revised_plan.md
│   │       └── runs.txt
│   ├── runs/
│   │   └── r001_short_name/
│   │       ├── proposal.md
│   │       ├── review.md
│   │       ├── manifest.yaml
│   │       ├── patch.diff
│   │       ├── branch.txt
│   │       ├── launch.json
│   │       ├── monitor.jsonl
│   │       ├── metrics.json
│   │       ├── result.md
│   │       ├── reflect.md
│   │       ├── revised_plan.md
│   │       ├── literature_refresh.json
│   │       ├── deep_research_request.md
│   │       ├── next_manifest.yaml
│   │       └── artifacts/
│   ├── directions/
│   │   ├── registry.jsonl
│   │   ├── d001_postprocess.md
│   │   ├── d002_architecture.md
│   │   ├── d003_external_repo.md
│   │   └── d004_data_eval.md
│   ├── branches/
│   │   ├── active.json
│   │   ├── merged.jsonl
│   │   └── abandoned.jsonl
│   ├── leaderboard/
│   │   ├── goals.yaml
│   │   ├── metrics_schema.yaml
│   │   ├── best.json
│   │   ├── best_by_direction.json
│   │   ├── history.jsonl
│   │   └── snapshots/
│   ├── scheduler/
│   │   ├── queue.json
│   │   ├── budget.yaml
│   │   ├── active_jobs.json
│   │   └── completed_jobs.jsonl
│   ├── executor/
│   │   ├── vibe.py
│   │   ├── runner.py
│   │   ├── slurm.py
│   │   ├── scheduler.py
│   │   ├── monitor.py
│   │   ├── metrics.py
│   │   ├── provenance.py
│   │   ├── git_ops.py
│   │   ├── idea_inbox.py
│   │   ├── dashboard.py
│   │   ├── literature.py
│   │   ├── deep_research.py
│   │   └── templates/
│   │       ├── slurm_default.sbatch.j2
│   │       ├── slurm_gpu_short.sbatch.j2
│   │       ├── slurm_gpu_long.sbatch.j2
│   │       ├── run_status.md.j2
│   │       └── deep_research_request.md.j2
│   ├── research/
│   │   ├── papers.sqlite
│   │   ├── sources.jsonl
│   │   ├── deep_requests/
│   │   │   ├── dr001_short_topic.md
│   │   │   └── registry.jsonl
│   │   ├── raw/
│   │   │   ├── papers_pdf/
│   │   │   ├── papers_md/
│   │   │   ├── deep_reports/
│   │   │   ├── repos/
│   │   │   ├── weights/
│   │   │   ├── notes/
│   │   │   └── assets/
│   │   └── wiki/
│   │       ├── index.md
│   │       ├── log.md
│   │       ├── overview.md
│   │       ├── papers/
│   │       ├── concepts/
│   │       ├── entities/
│   │       ├── comparisons/
│   │       ├── gaps/
│   │       └── synthesis/
│   ├── dashboard/
│   │   ├── status.md
│   │   ├── status.json
│   │   ├── TODO.md
│   │   ├── TIMELINE.md
│   │   ├── timeline.jsonl
│   │   └── timeline.html
│   └── prompts/
│       ├── leader.md
│       ├── portfolio_planner.md
│       ├── reviewer.md
│       ├── portfolio_reviewer.md
│       ├── literature.md
│       ├── deep_research_request.md
│       ├── deep_research_ingest.md
│       ├── paper_ingest.md
│       ├── reflect.md
│       ├── cycle_reflect.md
│       ├── revised_plan.md
│       ├── cycle_revised_plan.md
│       └── codex_patch.md
```

文件夹名必须短。cycle 文件夹用 `c001`、`c002`；run 文件夹用 `r001_short_name`、`r002_short_name`，不要用特别长的 timestamp 加完整实验名。timestamp 写进 `manifest.yaml`、`launch.json`、`timeline.jsonl` 和 `resource_plan.yaml`，不强塞进目录名。这样用户用终端查看时不会被超长路径淹没。若需要时间排序，可以用 `c001`、`r001` 这种编号保证顺序，具体创建时间放在结构化 metadata 里。

根目录入口文件的职责要固定。`RUN.md` 是用户最常打开的交互入口，里面写当前推荐 prompt、常用 CLI 命令、新想法 inbox 和下一步操作。`VIBE_STATUS.md` 是当前状态摘要。`VIBE_LEADERBOARD.md` 是长期目标和最佳结果。`VIBE_TODO.md` 是可读 TODO。`VIBE_TIMELINE.md` 是压缩时间线。它们都由 `.vibe/dashboard/` 自动生成或同步，用户不需要记住内部路径。

## 2. 用户新想法入口

用户随时可以提供新想法，这是系统必须支持的一等功能。新想法入口有三种：第一种是直接作为 prompt 输入给 Codex 或 ChatGPT；第二种是用户手写到 `.vibe/inbox/ideas.md`；第三种是通过 CLI，例如 `vibe idea "try MedSAM2 as QC prior, not direct segmentation"`。所有入口最终都写入 `.vibe/inbox/triage.jsonl`，每条记录包含 `idea_id`、`created_at`、`source`、`raw_text`、`status`、`linked_cycle_id`、`linked_run_id`、`linked_direction_id`、`linked_paper_id`、`linked_deep_request_id`、`triage_decision`。

idea triage 不应该每次都立刻变成实验。Leader 在 portfolio planning 前必须先读 inbox，并把新想法分类为 `experiment_candidate`、`direction_candidate`、`literature_question`、`deep_research_candidate`、`wiki_update`、`implementation_task`、`long_term_goal_update`、`blocked_until_user_decision` 或 `rejected_low_value`。如果一个想法暂时不执行，也必须写清楚原因，而不是从上下文里消失。

`RUN.md` 里应该有一个固定区域，方便用户粘贴新想法：

```text
## New Ideas Inbox

在这里追加新想法。下一轮 `vibe plan-cycle` 会自动读取并 triage。

- [ ] idea:
- [ ] idea:
```

CLI 也应该支持快速交互：

```bash
vibe idea "..."
vibe ask "..."
vibe directive "prioritize no-training sweep this week"
vibe status
vibe next
vibe plan-cycle
vibe reflect r001
vibe revise-plan r001
vibe reflect-cycle c001
vibe timeline
vibe leaderboard
```

这样用户不必每次手写长 prompt，也不必复制复杂模板。当前阶段仍然可以保留 `RUN.md` 作为人工 prompt 入口，但后续要逐步转成 CLI 化。

## 3. Python 环境和 requirements

根目录必须有 `requirements-vibe.txt`，用于创建这个 vibe research 框架的虚拟环境。它不应该污染项目原本的训练环境，也不应该强行安装深度学习框架。训练环境由项目自己管理，vibe 环境只负责 orchestration、日志、PDF、数据库、MCP 或 web 查询、Slurm、scheduler 和 dashboard。

第一版 `requirements-vibe.txt` 可以包含：

```text
pydantic
pyyaml
jinja2
rich
typer
requests
httpx
beautifulsoup4
feedparser
python-dotenv
sqlite-utils
pandas
tabulate
GitPython
psutil
jsonschema
tqdm
arxiv
semanticscholar
pymupdf
markdownify
networkx
```

如果要做 HTML dashboard，可以再加 `plotly`，也可以先不用重依赖，直接生成静态 HTML。MVP 阶段不建议加入过多 agent framework 依赖，避免为了框架抽象消耗时间。MCP 可以作为可选依赖，放进 `requirements-vibe-mcp.txt` 或 extras，不要让整个系统因为 MCP server 配置失败而不能跑基本实验闭环。

建议环境创建方式：

```bash
python -m venv .venv-vibe
source .venv-vibe/bin/activate
pip install -r requirements-vibe.txt
```

Windows/WSL 下也可以保持同样结构。不要把 `.venv-vibe/` 放进 git。

## 4. Branch 和 Git 工作流

每个实验 run 都必须新建 branch，像真实开发一样管理。run id 和 branch 必须绑定。默认 branch 命名规则为 `vibe/r001-short-name`。一个 cycle 可以包含多个 run，因此一个 cycle 通常会对应多个 branch。`vibe plan-cycle` 生成 portfolio plan 后，`vibe patch` 前必须检查当前 git 状态；如果 main 不干净，必须让用户或 runner 先处理，不能在脏 main 上直接开实验。

标准流程是：Leader 生成 `portfolio_plan.md`；Reviewer 生成 `portfolio_review.md`；portfolio 中每个被批准的 run 生成自己的 `proposal.md`；runner 为每个 run 创建 branch；Codex 在对应 branch 上改代码；runner 保存 `patch.diff`；dry-run 通过后进入 scheduler；scheduler 根据资源预算提交一个或多个 Slurm job；collect、reflect 和 revised plan 完成后，如果某个 run 成功且 Reviewer 认可，才允许 merge 回 main。merge 不是自动默认行为，必须经过 `vibe merge r001`，并且写入 `.vibe/branches/merged.jsonl`。失败或无价值实验用 `vibe abandon r001` 标记，保留 branch 或删除 branch 的选择也要记录。

如果多个 run 需要共享基础设施改动，不能让每个 branch 各自重复修改同一套基础代码。推荐做法是先创建一个短期 infra branch，例如 `vibe/infra-c001-evaluator`，只放通用评估器、日志或 runner 支持；通过 review 后先 merge 到 main，再从 main 分出各个实验 branch。实验性模型、后处理、训练配置、阈值策略等仍然保持 per-run branch。这样可以避免多个并行实验互相污染。

合并标准不能只看主指标上升。至少要满足：dry-run 和完整 run 都有记录；metric provenance 完整；没有破坏 guardrail；对照清楚；`reflect.md` 解释了结果；`revised_plan.md` 给出了后续决策；若属于某个 cycle，还必须在 `cycle_reflect.md` 中比较过该 run 和同 cycle 的其他 run；Reviewer 给出 `MERGE_OK` 或用户显式 override。否则就算某个数字看起来提高，也不能进入 main。

## 5. Direction、Portfolio 和并行实验策略

框架必须区分 direction、cycle 和 run。Direction 是研究方向，例如 postprocessing、architecture、external repo、data/evaluator、foundation model QC、Cine route repair。Cycle 是一轮 portfolio planning，可以包含多个方向和多个 run。Run 是具体实验，必须有独立 branch、manifest、job、metrics 和 revised plan。

早期阶段应采用 exploration portfolio。这个阶段不应该只押注一个实验，而是让 Leader 设计一个小型实验组合，例如 3 到 6 个 run，覆盖不同假设和不同成本层级。一个合理 portfolio 可能包括一个 no-training postprocess sweep、一个 softmax threshold search、一个小训练 ablation、一个 external repo smoke、一个 evaluator audit。它们不一定都很大，但必须互补，不能只是同一想法换几个参数重复跑。

中期阶段应采用 balanced portfolio。系统根据 leaderboard 和 previous cycle reflect，把资源集中到 2 到 3 个最有希望方向，同时保留少量低成本探索。这个阶段可以允许一个主线训练实验、一个 postprocess/threshold 实验、一个文献或外部 repo 准备任务并行。

后期阶段应采用 exploitation mode。此时方向已经比较清楚，portfolio 应缩小到 1 到 2 个 run，主要做 seed repeat、full fold、消融、稳定性测试、merge 前验证和提交前 QA。后期不应再随意开很多方向，除非 revised plan 或 deep research 明确说明当前主线失效。

`.vibe/config.yaml` 中应有 portfolio mode 配置：

```yaml
portfolio:
  mode: exploration          # exploration / balanced / exploitation
  max_runs_per_cycle: 6
  min_distinct_directions: 3
  max_same_direction_runs: 2
  require_low_cost_baseline: true
  allow_parallel_runs: true
  require_portfolio_review: true

scheduler:
  max_parallel_jobs: 3
  max_parallel_gpu_jobs: 2
  max_total_gpus: 4
  max_walltime_hours_per_cycle: 48
  max_failed_runs_before_pause: 3
  queue_policy: priority_then_resource_fit
```

每个 `portfolio_plan.md` 必须说明本 cycle 处于 exploration、balanced 还是 exploitation。它还必须说明为什么设计这些 run，为什么不是只跑一个实验，哪些 run 可以并行，哪些 run 有依赖关系，哪些 run 是 cheap diagnostic，哪些 run 是 expensive training，以及如果前面的 cheap run 失败，后面的 expensive run 是否应该自动取消。

## 6. Portfolio Plan 和 Portfolio Review

`portfolio_plan.md` 是 cycle 层面的核心计划文件。它不是单个实验 proposal 的替代品，而是负责回答“这一轮为什么要同时跑这些实验”。固定格式建议如下：

```text
# Portfolio Plan for c001

## Stage
exploration / balanced / exploitation

## Current leaderboard summary
当前 best trusted、best candidate、各 direction 最好结果，以及上一轮主要失败原因。

## User ideas and directives considered
本轮读取了哪些用户新想法、哪些被采纳、哪些延后、哪些拒绝。

## Candidate directions
列出本轮考虑的方向，每个方向说明动机、已有证据、风险和成本。

## Selected runs
列出本 cycle 要执行的 run：
- r001: direction, hypothesis, cost, expected learning
- r002: direction, hypothesis, cost, expected learning
- r003: direction, hypothesis, cost, expected learning

## Dependency graph
说明哪些 run 可以并行，哪些 run 依赖前置 smoke 或数据准备。

## Resource budget
说明 GPU、CPU、内存、时间、Slurm partition、最大并行数和取消条件。

## Portfolio success criteria
这一整个 cycle 成功的标准是什么。可以是找到至少一个有希望方向，也可以是排除若干失败方向。

## Stop or shrink criteria
什么情况下停止某个方向，什么情况下从 exploration 收敛到 balanced 或 exploitation。
```

`portfolio_review.md` 由 Portfolio Reviewer 生成。它要检查整个实验组合是否合理，而不只是单个 run 是否能跑。Reviewer 必须判断：组合是否覆盖了足够不同的假设；是否全是同质化参数搜索；是否资源过量；是否缺少 cheap diagnostic；是否把 expensive training 放在不充分证据之前；是否需要先做 literature refresh 或 deep research；是否存在多个 run 改同一文件导致 branch 冲突；是否需要限制并行度；是否有明确的 cycle-level stop criteria。

Portfolio Reviewer 的结论可以是 `APPROVE_PORTFOLIO`、`APPROVE_WITH_RESOURCE_GUARDS`、`REVISE_PORTFOLIO` 或 `BLOCK_PORTFOLIO`。如果 portfolio 被 block，scheduler 不得提交任何 run。

## 7. Scheduler 和并行 Slurm 策略

允许多个实验同时跑，但不能无限并发。`.vibe/scheduler/budget.yaml` 定义全局资源预算，包括最大并行 job 数、最大 GPU 数、每个 cycle 最大 walltime、每个方向最大同时 run 数、失败阈值和优先级策略。scheduler 读取 `resource_plan.yaml` 和各 run 的 `manifest.yaml`，决定哪些 job 立即 submit，哪些排队，哪些等待前置 smoke。

并行规则应遵循几个原则。cheap diagnostic 优先，因为它们能快速减少不确定性。不同方向优先于同方向重复参数搜索。dry-run 必须先过，没过的 run 不能进入 scheduler。expensive training 如果依赖某个 smoke 的结论，不能提前 submit。连续失败超过阈值时，scheduler 应暂停该 direction，而不是继续消耗资源。若 Slurm partition 繁忙，scheduler 可以切换 fallback partition，但必须记录原因。

`resource_plan.yaml` 示例：

```yaml
cycle_id: c001
mode: exploration
max_parallel_jobs: 3
max_gpu_jobs: 2
runs:
  r001_postprocess_sweep:
    priority: 1
    cost: low
    can_parallel: true
    depends_on: []
  r002_softmax_threshold:
    priority: 1
    cost: low
    can_parallel: true
    depends_on: []
  r003_small_train_ablation:
    priority: 2
    cost: medium
    can_parallel: true
    depends_on: ["r001_postprocess_sweep"]
  r004_external_repo_smoke:
    priority: 1
    cost: low
    can_parallel: true
    depends_on: []
cancel_rules:
  - if: "r001_postprocess_sweep fails due evaluator bug"
    cancel: ["r003_small_train_ablation"]
  - if: "three runs in same direction fail guardrails"
    pause_direction: true
```

scheduler 必须生成 `queue.json`、`active_jobs.json` 和 `completed_jobs.jsonl`。`VIBE_STATUS.md` 中要能显示哪些 run 正在跑、哪些排队、哪些被取消、哪些因为依赖未满足而等待。

## 8. 长期目标和 Leaderboard

系统不能只服务某一次 challenge，也不能只看单次 run。必须有长期目标和 leaderboard，用于快速判断是否真的改进。`.vibe/leaderboard/goals.yaml` 定义项目长期目标、primary metrics、secondary metrics、guardrails、baseline、比较协议和是否允许外部 leaderboard feedback。

示例：

```yaml
project: "Generic Research Repo"
primary_goal: "Improve robust validation performance under fixed protocol"
baselines:
  trusted_baseline:
    run_id: "baseline001"
    description: "official local baseline"
metrics:
  primary:
    - name: "val_dice_mean"
      direction: "max"
  guardrails:
    - name: "hd95"
      direction: "min"
    - name: "failure_rate"
      direction: "min"
subgroups:
  - "center"
  - "modality"
  - "ood"
comparison_policy:
  require_same_split: true
  require_same_evaluator: true
  require_metric_provenance: true
  allow_leaderboard_feedback: false
```

`best.json` 记录当前全局最佳 run，不只是最大主指标，还要记录为什么它可信。`best_by_direction.json` 记录每个 direction 的最佳结果，用于 early exploration 阶段判断哪些方向值得继续。`history.jsonl` 每次 collect 后追加一行。`VIBE_LEADERBOARD.md` 自动渲染成用户可读表格，至少包括 cycle id、run id、direction、branch、主指标、guardrail、状态、是否 merged、是否 trusted、失败原因、reflect 摘要和 revised plan 摘要。

Leaderboard 还要支持不同研究类型。分类任务可以是 accuracy、AUC、F1；分割任务可以是 Dice、HD95；统计模拟可以是 bias、MSE、coverage；文献研究项目可以是 resolved questions、hypothesis status、paper coverage 和 contradiction count。关键不是指标固定，而是所有指标必须有 schema、方向和比较规则。

## 9. 根目录可见进展日志

根目录必须能清楚看到 cycle 和 run 的进展。`VIBE_STATUS.md` 应该先显示 cycle-level portfolio，再显示每个 run 的状态。

```text
=== Cycle c001 | mode: exploration ===

[PORTFOLIO_THINK] Reading PROJECT_BRIEF.md, HUMAN_DIRECTIVE.md, memory, inbox, leaderboard...
                  Goal: improve robust validation metric under fixed protocol
                  Best trusted: baseline001, primary=0.763, guardrail OK
                  New user ideas: 4 found, 3 triaged into candidate directions
                  Plan: run 4 complementary experiments across 3 directions

[PORTFOLIO_REVIEW] Verdict: APPROVE_WITH_RESOURCE_GUARDS
                   Guards: max 2 GPU jobs; cheap diagnostics first; cancel r003 if evaluator audit fails

[SELECTED_RUNS]
  r001_postprocess_sweep       direction=d001_postprocess     cost=low      status=ready
  r002_softmax_threshold       direction=d001_postprocess     cost=low      status=ready
  r003_small_train_ablation    direction=d002_training        cost=medium   status=waiting_on_r001
  r004_external_repo_smoke     direction=d003_external_repo   cost=low      status=ready

[SCHEDULER] max_parallel_jobs=3, max_gpu_jobs=2
            submitted: r001, r002, r004
            waiting: r003

=== Run r001_postprocess_sweep ===

[BRANCH] Created branch: vibe/r001-postprocess-sweep
[DRYRUN] passed
[SUBMIT] Slurm job submitted, Job ID: 12345, Partition: gpu_short
[MONITOR] zero LLM cost monitoring
[COLLECT] metrics collected
[REFLECT] topology rule improved HD95 but slightly reduced Dice
[REVISED_PLAN] continue direction with stricter guardrail

=== Run r002_softmax_threshold ===

[BRANCH] Created branch: vibe/r002-softmax-threshold
[DRYRUN] passed
[SUBMIT] local job launched
[COLLECT] metrics collected
[REFLECT] threshold search found no robust improvement
[REVISED_PLAN] stop this sub-branch unless new softmax source appears

=== Cycle c001 Summary ===

[CYCLE_REFLECT] Best candidate: r001_postprocess_sweep
                Stopped: r002_softmax_threshold
                Continue: d001_postprocess, d003_external_repo
                Pause: d002_training until r001 guardrail confirmed

[CYCLE_REVISED_PLAN] Next cycle mode: balanced
                     Reduce portfolio from 4 runs to 2-3 runs
                     Literature needed: yes, targeted topology false-positive suppression
                     Deep research needed: no
```

如果 revised plan 判断需要 deep research，则 cycle-level 日志要显示：

```text
[CYCLE_REVISED_PLAN] Decision: deep_research_needed
                     Reason: three directions failed and ordinary literature refresh gave contradictory signals
                     Deep request: dr001_route_selection
                     Blocking: partial
                     Continue while waiting: run cheap evaluator audit only
```

这种日志要同时写入 `.vibe/dashboard/TIMELINE.md`、`.vibe/dashboard/timeline.jsonl` 和根目录 `VIBE_TIMELINE.md`。timeline 的事件名固定，便于后续生成 fancy HTML 页面。事件包括 `cycle_planned`、`portfolio_reviewed`、`run_selected`、`run_queued`、`run_submitted`、`run_finished`、`run_reflected`、`run_revised_plan_written`、`cycle_reflected`、`cycle_revised_plan_written`、`direction_paused`、`direction_promoted`、`portfolio_mode_changed`、`deep_research_request_created` 等。

## 10. 核心循环

单 run 的循环定义为：

```text
PROPOSAL → REVIEW → BRANCH → PATCH → DRYRUN → QUEUE → SUBMIT → MONITOR → COLLECT → REFLECT → REVISED_PLAN
```

cycle 层面的循环定义为：

```text
PORTFOLIO_THINK → PORTFOLIO_REVIEW → RUN_GENERATION → SCHEDULER → RUN_EXECUTION → CYCLE_REFLECT → CYCLE_REVISED_PLAN → OPTIONAL_LITERATURE_REFRESH → OPTIONAL_DEEP_RESEARCH_REQUEST → WIKI_UPDATE → LEADERBOARD_UPDATE → NEXT_CYCLE
```

THINK 阶段不再默认只生成一个实验，而是先生成 portfolio plan。Portfolio plan 根据当前阶段、leaderboard、inbox、memory、wiki 和资源预算，设计一个实验组合。只有在 exploitation mode 或用户明确要求单实验时，portfolio 才可以只包含一个 run。

REVIEW 阶段分两层。Portfolio Reviewer 先审查整个组合是否合理；Run Reviewer 再审查每个具体 run 是否值得执行。portfolio 没过，不能生成 run；run 没过，不能进入 branch 和 patch。

BRANCH 阶段由 runner 为每个 run 创建 git branch。所有代码改动必须发生在 run branch。若有 shared infra 改动，应先走独立 infra branch。

PATCH 阶段 Codex 写代码和 manifest。Codex 可以改 repo 文件，但必须由 runner 记录 diff、检查 protected files、检查 manifest schema。

DRYRUN 阶段 runner 执行短任务，不由 Codex 自述完成。dry-run 不通过不能进入 scheduler。

QUEUE 和 SUBMIT 阶段由 scheduler 控制。scheduler 根据 resource_plan、依赖关系、Slurm 状态和预算决定并行提交哪些 run。

MONITOR 阶段零 LLM 成本。runner 定时记录 squeue/sacct、GPU、日志 heartbeat、checkpoint heartbeat、磁盘空间和错误模式。

COLLECT 阶段统一收集 metrics、artifacts、logs、checkpoint、predictions 和 evaluator provenance。没有 provenance 的结果不能进入 trusted leaderboard。

REFLECT 阶段每个 run 生成自己的 `reflect.md`。它只回答上一轮发生了什么、结果意味着什么。

REVISED_PLAN 阶段每个 run 生成自己的 `revised_plan.md`。它说明该 run 的下一步是继续、修改、停止、repeat、merge candidate，还是需要外部证据。

CYCLE_REFLECT 阶段比较同一 cycle 内所有 run，判断哪些 direction 值得继续、哪些应该停止、哪些需要更多证据。

CYCLE_REVISED_PLAN 阶段决定下一轮 portfolio 是扩张、保持、收缩还是转向。它必须明确 portfolio mode 是否从 exploration 转为 balanced，或从 balanced 转为 exploitation。

OPTIONAL_LITERATURE_REFRESH 和 OPTIONAL_DEEP_RESEARCH_REQUEST 由 run-level 或 cycle-level revised plan 显式决定。普通检索服务于局部实验修改；deep research 服务于路线级不确定。

WIKI_UPDATE 阶段把有价值的论文、概念、对比、gap、假设、deep research 结果和讨论写回 agent-facing wiki。

LEADERBOARD_UPDATE 阶段把本轮结果和长期目标比较。若不满足 trusted 条件，只能进入 candidate，不得覆盖 best trusted。

NEXT_CYCLE 阶段决定下一轮行动。下一步可能是设计新 portfolio、等待并行 job、补充文献、请求用户执行 deep research、请求用户决策、merge、abandon 或停止某方向。

## 11. Revised Plan 作为强制产物

每个 run 目录中，`reflect.md` 和 `revised_plan.md` 都是强制文件。`reflect.md` 可以得出“当前假设失败”，但 `revised_plan.md` 必须进一步说明是停止该 branch、修改实验、缩小 scope、做 ablation、补充文献、改 evaluator、做 seed repeat，还是回滚代码。不能直接从 reflect 跳到 next experiment，也不能因为“结果没什么变化”省略计划修订。

如果一个 cycle 包含多个 run，则 cycle 层面也必须有 `cycle_reflect.md` 和 `cycle_revised_plan.md`。单个 run 的 revised plan 只能决定该 run 或该 branch 的下一步；cycle revised plan 才能决定下一轮 portfolio 的资源分配、方向收敛和并行策略。没有 `cycle_revised_plan.md` 的 cycle 不能进入 NEXT_CYCLE。

`revised_plan.md` 的固定格式建议如下：

```text
# Revised Plan for r001_short_name

## Result interpretation
上一轮实验的核心结果是什么，是否支持原始 hypothesis，哪些指标可信，哪些指标需要谨慎解释。

## Decision
本轮之后的决策只能是以下几类之一：
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
明确写 yes / no。如果 yes，说明 deep research request id、核心研究问题、为什么普通联网检索不足、预期输出格式、是否阻塞当前 pipeline。如果 no，说明为什么当前问题不需要路线级深度研究。

## Portfolio implication
这个 run 的结果对所在 direction 和下一个 cycle 有什么影响。是推广、保留、降级、暂停，还是停止该方向。

## Next experiment proposal
如果可以直接进入下一轮实验，写出下一轮 run 的 hypothesis、baseline、success criteria、guardrails、resource budget 和 expected learning。

## Stop condition
明确什么结果会导致停止这个方向，避免无限小修小补。
```

`cycle_revised_plan.md` 的固定格式建议如下：

```text
# Cycle Revised Plan for c001

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
说明是否需要普通 literature refresh 或 deep research request。若需要，说明服务于哪个 direction 或哪个路线级问题。

## User decision needed
如果需要用户判断，明确写出问题和可选项。

## Stop condition
明确什么情况下停止整个方向或结束本阶段探索。
```

如果 literature refresh 执行后改变了计划，必须更新相应 revised plan，并标注 `updated_after_literature_refresh: true`。如果 deep research report 被用户放回系统并改变了计划，也必须更新 revised plan，并标注 `updated_after_deep_research: true`。

## 12. Literature Refresh 规则

`LITERATURE_REFRESH` 不再被写成 reflect 后的机械下一步，而是由 `revised_plan.md` 或 `cycle_revised_plan.md` 显式决定。若回答 yes，则必须执行；若回答 no，则必须给出理由。这样可以避免两种问题：一是 agent 每次形式主义搜索几篇无关论文；二是 agent 在明显需要外部证据时闭门造车。

触发 literature refresh 的典型条件包括：实验失败原因不清楚；连续两轮没有改进；出现疑似实现路线错误；需要找更强 baseline；需要确认某个方法是否已有论文做过；需要 clone 外部 repo 或下载权重；Reviewer 认为实验价值不足但可能通过新文献重新设计；Leader 准备改变研究方向；当前 revised plan 中出现新的 method family、dataset、benchmark、foundation model、loss function 或 postprocessing idea。

不触发 literature refresh 的合理条件包括：下一步只是 seed repeat；下一步只是修复明确的实现 bug；下一步只是补跑 dry-run；下一步只是收集已有 metrics；下一步只是把已完成候选交给 Reviewer 做 merge 审查；当前文献证据已经在同一方向上一轮刚刚更新，且没有新的科学问题出现。

如果执行 literature refresh，必须生成 `literature_refresh.json`，记录 queries、sources、results、selected papers、rejected papers、downloaded files、wiki updates，以及这些新证据如何修改 revised plan。没有新结果也要写清楚查了什么。若 literature refresh 改变了下一步实验，必须回写 revised plan。

## 13. Deep Research Interface

Deep research interface 应该加入系统，但不能作为每轮默认步骤，也不能替代普通联网查询。它的定位是 escalation module。普通 `literature_refresh` 负责快速、及时、针对性的联网检索，主要服务于当前 revised plan；`deep_research_request` 负责当框架发现自己进入路线级不确定时，生成一份高质量、可复用、可交给外部 deep research 工具或人工检索的研究请求。

触发 deep research 的典型条件包括：连续若干轮实验没有实质改进；多个 direction 同时失败；Reviewer 判断当前路线价值不足但缺少外部证据；Leader 准备大幅改变研究方向；当前问题需要跨论文、跨 repo、跨 benchmark 的系统性判断；普通 literature refresh 找到的信息互相矛盾；需要比较多个 method family 的长期潜力；需要评估某个 challenge 或项目是否继续投入；用户主动要求做一轮 deep research。

不触发 deep research 的条件包括：下一步只是 seed repeat、bug fix、metric collection、Slurm 修复、短 ablation、one-case smoke 或明确的 postprocessing sweep。这些情况用普通实验循环和 literature refresh 足够，不应升级成 deep research。

实现上，不要假设框架可以自动调用某个 Deep Research API。更稳妥的做法是让框架生成一份标准化请求文件：

```text
.vibe/research/deep_requests/
├── dr001_cardiac_fm_value.md
├── dr002_topology_false_positive.md
├── dr003_external_repo_strategy.md
└── registry.jsonl
```

每个 deep research request 里写清楚背景、当前实验状态、已有结果、已读论文、需要回答的问题、必须比较的路线、希望输出的格式、禁止泛泛而谈、需要给出可执行实验建议。用户可以把这份 markdown 复制给 ChatGPT Deep Research、Gemini Deep Research、Perplexity、Claude Research 或人工检索。等结果回来后，用户把报告放进：

```text
.vibe/research/raw/deep_reports/
└── dr001_result.md
```

然后运行：

```bash
vibe ingest-deep-research dr001
```

框架再把报告拆解成 wiki 页面、paper queue、repo queue、hypotheses、revised plan update 和 TODO。这样 deep research 成为系统的一部分，但不会让系统依赖某个外部产品接口。

`deep_research_request.md` 的建议格式如下：

```text
# Deep Research Request: dr001_short_topic

## Project context
说明当前 repo、长期目标、已有 baseline、当前 leaderboard 状态和资源限制。

## Current experimental evidence
总结最近若干 run 和 cycle 的关键结果，包括成功、失败、guardrail、subgroup/OOD 和 Reviewer 判断。

## Existing local knowledge
列出已入库论文、wiki 页面、相关 repo、已下载权重和当前 hypotheses。

## Core research question
明确这轮 deep research 要回答的路线级问题，而不是泛泛搜索。

## Required comparisons
列出必须比较的方法族、baseline、数据集、benchmark、repo 或权重。

## What counts as useful output
要求输出可执行结论，例如推荐路线、停止路线、可复现实验、需要 clone 的 repo、需要读的论文、潜在风险。

## What to avoid
禁止泛泛综述、无来源建议、只列论文不综合、忽略当前 repo 约束。

## Expected deliverable
要求最终报告包含 evidence table、method map、repo/weight list、risk assessment、recommended next experiments 和 citations。
```

Deep research 的状态要进入 `registry.jsonl`，字段包括 `request_id`、`created_at`、`reason`、`blocking`、`status`、`request_path`、`result_path`、`linked_cycle_ids`、`linked_run_ids`、`linked_revised_plan`、`ingested_at`、`wiki_updates` 和 `decision_impact`。如果 deep research 是 hard dependency，`vibe next` 应显示 `blocked_waiting_deep_research`；如果只是增强背景，当前 pipeline 可以继续跑便宜诊断或已明确实验。

## 14. Research Wiki 和 Paper DB

论文系统必须保存本地 PDF，并记录来源。不能只在 wiki 里写一句“看过某论文”。`.vibe/research/papers.sqlite` 是 Zotero-like metadata 层；`.vibe/research/raw/papers_pdf/` 保存 PDF；`.vibe/research/raw/papers_md/` 保存 PDF 转 markdown；`.vibe/research/raw/deep_reports/` 保存用户从外部 deep research 工具带回的报告；`.vibe/research/wiki/` 保存 agent 整理后的知识。

每篇论文至少记录 `paper_id`、`title`、`authors`、`year`、`venue`、`arxiv_id`、`doi`、`source_url`、`pdf_url`、`local_pdf_path`、`sha256`、`downloaded_at`、`ingested_at`、`status`、`confidence`、`tags`、`related_cycle_ids`、`related_run_ids`、`related_deep_request_ids`、`repo_urls`、`weight_urls`、`dataset_names` 和 `notes`。

wiki 目录沿用科研知识库思想：`papers/` 放单篇论文理解，`concepts/` 放方法和理论，`entities/` 放作者组、数据集、benchmark 和系统，`comparisons/` 放方法对比，`gaps/` 放研究空白、假设和开放问题，`synthesis/` 放跨论文综合。`index.md` 每次更新，`log.md` append-only。论文 ingest 后必须更新相关 concept、gap 或 synthesis 页面，而不是只写一篇孤立 paper note。

论文 ingest 流程是：联网搜索得到候选；Leader 或 Literature Agent 选中候选；downloader 下载 PDF 和页面元数据；parser 生成 markdown；paper_ingest agent 读 markdown；写 `wiki/papers/<paper_id>.md`；更新相关 `concepts/`、`entities/`、`gaps/questions.md`、`gaps/hypotheses.md`、`synthesis/field-map.md` 或 `synthesis/shared-assumptions.md`；最后更新 `wiki/index.md` 和 `wiki/log.md`。

Deep research ingest 流程是：用户放入 `raw/deep_reports/drXXX_result.md`；`vibe ingest-deep-research drXXX` 读取报告；抽取论文、repo、数据集、方法、假设、反例、建议实验和风险；更新 `wiki/synthesis/`、`wiki/comparisons/`、`wiki/gaps/`；把新增论文加入 paper queue；把建议实验写入 inbox triage 或 revised plan update；最后更新 dashboard 和 timeline。

## 15. Reviewer Agent

Reviewer 是系统区别于“写一堆脚本然后乱跑”的关键。Reviewer 默认只读，不直接改代码。它分为两层：Portfolio Reviewer 和 Run Reviewer。Portfolio Reviewer 审查整个 cycle 的实验组合是否合理；Run Reviewer 审查单个 run 是否值得执行。

Portfolio Reviewer 的输出是 `portfolio_review.md`，结论只有 `APPROVE_PORTFOLIO`、`APPROVE_WITH_RESOURCE_GUARDS`、`REVISE_PORTFOLIO`、`BLOCK_PORTFOLIO`。它必须检查组合是否覆盖不同方向、是否全是同质化参数搜索、是否资源过量、是否缺少 cheap diagnostic、是否把 expensive training 放在证据不足之前、是否存在 branch 冲突、是否需要限制并行度、是否需要 literature refresh 或 deep research。

Run Reviewer 的输出是 `review.md`，结论只有 `APPROVE`、`APPROVE_WITH_GUARDS`、`REVISE_OR_BLOCK`。它必须检查实验是否有明确 hypothesis、是否有公平 baseline、是否有最小可验证实验、是否需要 one-case smoke、是否会污染验证集、是否违反长期目标、是否缺少 subgroup/OOD/guardrail 检查、是否缺少 metric provenance、是否有论文反例、是否只是重复失败方向。

Reviewer 还负责 merge 前审查。一个 run 只有在 Reviewer 给出 `MERGE_OK` 或用户显式 override 后，才能 merge 回 main。merge 前 Reviewer 必须读取 `proposal.md`、`review.md`、`manifest.yaml`、`patch.diff`、`metrics.json`、`reflect.md`、`revised_plan.md`、所属 cycle 的 `cycle_reflect.md` 和 leaderboard 记录。没有 revised plan 的 run 不能 merge。

Reviewer 还可以建议触发 literature refresh 或 deep research。如果 Reviewer 认为某个实验路线价值不足但证据不够，不能只写“不要跑”，而应该说明是否需要普通联网检索、deep research request、one-case smoke、或用户决策。

## 16. Slurm 支持

Slurm 必须是一等公民。`.vibe/executor/slurm.py` 要支持固定 header template、partition 探测、fallback partition、squeue/sacct 监控、OOM/timeout/NaN/ImportError/permission/quota 失败分类和日志路径统一管理。`config.yaml` 里要能配置不同集群的 partition profile，例如 `gpu_short`、`gpu_long`、`a100`、`general_gpu`，并记录每个 partition 的时间限制、GPU 类型、account/qos 需求和优先级。

runner submit 前应先查询可用 partition。若首选 partition 不可用、排队过长或资源不匹配，可以自动切换 fallback，但必须把切换原因写入 `launch.json`。这比让 Codex 临时写 `sbatch` 稳定得多。

Slurm header 模板建议包含这些变量：`job_name`、`partition`、`account`、`qos`、`nodes`、`ntasks`、`cpus_per_task`、`mem`、`gres`、`time`、`output`、`error`、`mail_type`、`workdir`、`env_setup`、`command`。runner 在 submit 前先查可用 partition，如果首选 partition 不可用或排队过长，就按 fallback 切换，但必须把选择原因写进 `launch.json`。

## 17. CLI 设计

用户不能长期靠复制 `RUN.md` 里的大 prompt 工作。`RUN.md` 可以保留为人类可读入口，但必须逐步提供 CLI。推荐命令如下：

```bash
vibe init
vibe status
vibe idea "..."
vibe directive "..."
vibe plan-cycle
vibe review-cycle c001
vibe generate-runs c001
vibe review r001
vibe branch r001
vibe patch r001
vibe dryrun r001
vibe queue r001
vibe submit-queue
vibe monitor
vibe collect r001
vibe reflect r001
vibe revise-plan r001
vibe reflect-cycle c001
vibe revise-cycle c001
vibe lit-refresh r001
vibe lit-refresh-cycle c001
vibe deep-request r001
vibe deep-request-cycle c001
vibe ingest-deep-research dr001
vibe wiki-ingest <paper_id>
vibe leaderboard
vibe timeline
vibe merge r001
vibe abandon r001
vibe next
```

`vibe next` 是最重要的人机交互命令。它应该读取当前状态后告诉用户下一步推荐做什么，例如 “portfolio review pending”、“r003 waiting on r001”、“two jobs running”、“r001 finished but not reflected”、“c001 needs cycle_revised_plan”、“revised plan requests literature refresh”、“cycle plan requests deep research”、“new user ideas need triage”。这比让用户自己翻 `.vibe/` 目录更适合长期使用。

`vibe plan-cycle` 是多实验版本的核心命令。它生成 portfolio plan，而不是只生成一个 run。`vibe submit-queue` 由 scheduler 根据资源预算提交多个 run，但不能超过 `budget.yaml`。`vibe reflect-cycle` 和 `vibe revise-cycle` 负责把多个 run 的结果合并成下一轮 portfolio 决策。

## 18. Manifest 和 Runner 接口

Codex 和 runner 的接口应该是 `manifest.yaml`，而不是让 Codex 直接执行长任务。Codex 可以写 manifest，但 runner 必须验证 manifest schema、路径、资源预算、protected files 和危险命令。

示例：

```yaml
run_id: r001_mixup
cycle_id: c001
direction_id: d002_training
branch: vibe/r001-mixup
hypothesis: "Mixup improves robust validation under fixed evaluator."
change_summary: "Add mixup augmentation and cosine schedule."
expected_learning: "Whether augmentation improves primary metric without guardrail regression."
entrypoint:
  type: slurm
  script: jobs/train_r001.sh
  command: "python train.py --config configs/r001.yaml"
dryrun:
  command: "python train.py --config configs/r001.yaml --max_steps 2 --dry_run"
  max_minutes: 20
resources:
  gpu: 1
  gpu_mem_gb_min: 24
  cpus: 8
  mem_gb: 64
  time: "08:00:00"
  preferred_partitions: ["gpu_short", "gpu", "a100"]
  fallback_partitions: ["general_gpu"]
dependencies:
  run_after: []
  cancel_if_failed: []
inputs:
  split_file: "..."
  dataset_roots: ["..."]
  baseline_run_id: "baseline001"
outputs:
  metric_files: ["..."]
  checkpoint_glob: "..."
  prediction_dir: "..."
evaluation:
  command: "python scripts/eval.py --pred ... --gt ..."
  primary_metric: "..."
  guardrail_metrics: ["..."]
success_criteria:
  primary: "..."
  guardrails: ["..."]
provenance_required:
  git_diff: true
  env_export: true
  slurm_record: true
  metric_schema: true
```

runner 对 manifest 的检查必须在 dry-run、queue 和 submit 前执行。检查失败不能继续。

## 19. Dashboard 和 Timeline

`.vibe/dashboard/status.md` 应该始终能回答：当前 cycle 是什么、portfolio mode 是什么、有哪些 run 正在跑、为什么跑、job id、预计输出、当前最佳结果、最近失败原因、下一步 TODO、是否需要用户决定、是否需要用户执行 deep research。`.vibe/dashboard/TODO.md` 应该按 `NOW`、`NEXT`、`BLOCKED`、`DONE` 分区，所有 item 都带 cycle id、run id、idea id、paper id 或 deep request id。`.vibe/dashboard/timeline.jsonl` 是机器源，`TIMELINE.md` 和 `timeline.html` 由它生成。

timeline 事件类型建议固定为：

```text
idea_received
idea_triaged
cycle_planned
portfolio_reviewed
run_generated
run_reviewed
branch_created
patch_created
dryrun_passed
run_queued
job_submitted
job_started
job_finished
metrics_collected
run_reflect_written
run_revised_plan_written
cycle_reflect_written
cycle_revised_plan_written
portfolio_mode_changed
direction_promoted
direction_paused
direction_stopped
literature_refresh_decided
literature_refreshed
deep_research_decided
deep_research_request_created
deep_research_ingested
paper_found
paper_downloaded
paper_ingested
wiki_updated
leaderboard_updated
merge_review_done
merged
abandoned
blocked
user_input_needed
```

`timeline.html` 初版可以是无依赖静态 HTML，用时间轴展示每个 cycle、run、metric、论文、deep research request 和决策。后续再接 Obsidian 或 Notion 都可以，但本地静态文件必须是第一优先级。

## 20. Write Agent 暂不纳入核心

Write Agent 暂时不做核心功能。第一阶段只需要能写 `portfolio_plan.md`、`proposal.md`、`result.md`、`reflect.md`、`revised_plan.md`、`cycle_reflect.md`、`cycle_revised_plan.md`、`deep_research_request.md`、wiki 页面、dashboard 和 progress report。论文写作、投稿报告、manuscript drafting 可以以后解耦成独立 agent。当前核心是 portfolio 实验闭环、计划修订闭环、文献闭环、deep research 升级接口、provenance、leaderboard 和快速交互，不要过早加入写作 agent 增加复杂度。

## 21. MVP 实现顺序

第一阶段实现骨架：`.vibe init`、目录结构、`requirements-vibe.txt`、根目录入口文件、config、state、inbox、cycle registry、run registry、direction registry、leaderboard schema、Slurm template、scheduler budget 和 dashboard 生成。

第二阶段实现用户交互：`vibe idea`、`vibe directive`、`vibe status`、`vibe next`、`RUN.md` 自动更新、`VIBE_STATUS.md`、`VIBE_TODO.md`、`VIBE_TIMELINE.md`、`VIBE_LEADERBOARD.md`。

第三阶段实现 portfolio planning：`vibe plan-cycle`、`portfolio_plan.md`、`portfolio_review.md`、direction registry、multi-run generation、resource_plan.yaml 和 portfolio mode。

第四阶段实现 Codex 协作：Portfolio Planner prompt、Portfolio Reviewer prompt、Leader prompt、Run Reviewer prompt、Patch prompt、Reflect prompt、Cycle Reflect prompt、Revised Plan prompt、Cycle Revised Plan prompt。Codex 只写计划、review、patch、manifest、reflect 和 revised plan，不直接 submit 长任务。

第五阶段实现执行闭环：branch 创建、manifest schema、dry-run、queue、Slurm submit、monitor、collect、metric provenance、failure classification、branch merge/abandon。

第六阶段实现并行 scheduler：max_parallel_jobs、max_gpu_jobs、dependencies、cancel rules、direction pause、partition fallback、active_jobs.json 和 completed_jobs.jsonl。

第七阶段实现 revised-plan 闭环：每个 run 在 `collect` 后强制 `reflect` 和 `revise-plan`；每个 cycle 在所有关键 run 完成后强制 `reflect-cycle` 和 `revise-cycle`；没有 revised plan 不能进入 NEXT；cycle revised plan 决定下一轮 portfolio mode 和并行数量。

第八阶段实现文献闭环：arXiv、Semantic Scholar、OpenAlex、PubMed、GitHub search backend、本地 PDF 下载、papers.sqlite、PDF to markdown、paper ingest、wiki update、wiki lint、forced or justified literature refresh。

第九阶段实现 deep research 升级接口：`vibe deep-request` 和 `vibe deep-request-cycle` 生成标准化 request；用户把外部 deep research report 放入 `raw/deep_reports/`；`vibe ingest-deep-research` 抽取论文、repo、方法、假设、反例和建议实验；更新 wiki、TODO、paper queue、hypotheses 和 revised plan。

第十阶段实现长期优化：HTML timeline、leaderboard ranking、best_by_direction、subgroup/OOD metric schema、seed repeat、parallel job budget、partition scoring、repo clone provenance、weight provenance、external repo smoke test。

## 22. 硬规则

用户新想法必须进入 inbox，不能只留在聊天记录里。每个 cycle 必须有 `portfolio_plan.md`、`portfolio_review.md`、`resource_plan.yaml`、`cycle_reflect.md` 和 `cycle_revised_plan.md`。每个 run 必须有 run id、direction id、branch、proposal、review、manifest、patch、dry-run、launch、monitor、metrics、reflect 和 revised plan。每个 run 必须新建 branch，成功且通过 review 后才能 merge。没有 metric provenance 的结果不能进入 trusted leaderboard。没有 PDF 来源和 checksum 的论文不能算正式入库。Codex 不能直接 submit 长任务；submit 必须由 runner 和 scheduler 执行。Slurm job 必须记录 job id、partition、log path 和 resource request。根目录必须始终能看到 status、TODO、timeline 和 leaderboard。Write Agent 暂缓，不进入 MVP 核心。

早期探索阶段必须允许多实验 portfolio。默认情况下，exploration mode 不应只生成一个 run，除非用户明确要求或资源预算极低。portfolio 中的 run 必须覆盖多个方向或多个互补假设，不能只是同一个参数的无脑网格。后期 exploitation mode 可以收敛到单一实验，但必须由 cycle revised plan 说明为什么收敛。

每个 run 在 `COLLECT` 后必须先生成 `reflect.md`，再生成 `revised_plan.md`。每个 cycle 在关键 run 完成后必须生成 `cycle_reflect.md`，再生成 `cycle_revised_plan.md`。`reflect.md` 不能替代 `revised_plan.md`。没有 `revised_plan.md` 的 run 不能进入 NEXT、不能 merge、不能被标记为 completed。没有 `cycle_revised_plan.md` 的 cycle 不能进入下一轮 portfolio planning。`literature_refresh` 是否执行由 run 或 cycle revised plan 显式决定，每次都必须说明需要或不需要的理由。如果执行 literature refresh，并且新证据改变了判断，必须回写并更新 revised plan。

Deep research 不能作为每轮默认步骤，也不能替代普通 literature refresh。它只能由 revised plan、cycle revised plan 或 Reviewer 显式触发，主要用于路线级不确定、连续失败、准备转向、跨论文/跨 repo/跨 benchmark 综合判断或用户主动要求。生成 deep research request 后，如果它是 hard dependency，NEXT 状态必须标记为 blocked；如果不是 hard dependency，可以继续跑便宜诊断或已明确实验。外部 deep research report 回到系统后必须经过 ingest，不能直接把整篇报告当成可信结论，必须拆解成 wiki、paper queue、hypotheses、TODO 和 revised plan update。

不能直接从 reflect 跳到 next experiment，也不能因为“结果没什么变化”省略计划修订。不能因为 deep research 还没回来就永久等待；如果还有明确的 cheap diagnostic，应该允许继续推进，但必须标明战略决策仍待 deep research 结果。不能因为允许并行实验就无控制地提交大量 Slurm job；所有并行必须经过 scheduler budget、dependency graph 和 portfolio review。

## 23. 后续给 Codex 的任务定义

在任意目标 repo 内实现 `.vibe/` repo-specific sustained vibe research framework。使用 Codex CLI 作为 Portfolio Planner、Leader、Reviewer、Patch Generator、Reflect Agent、Revised Plan Agent、Literature Agent、Deep Research Request Generator 和 Paper-Ingest Agent，但所有真实执行由 deterministic Python runner 和 scheduler 完成。实现用户 idea inbox、requirements-vibe.txt、短目录 cycle/run registry、direction registry、git branch per run、Slurm-aware runner、parallel scheduler、root-level progress files、long-term leaderboard、best_by_direction、reflect 后强制 revised plan、本地 PDF/Zotero-like paper DB、agent-facing wiki、deep research 升级接口、TODO/timeline/status dashboard 和 CLI 快速交互。

核心循环必须支持两层结构。单 run 循环是：

```text
PROPOSAL → REVIEW → BRANCH → PATCH → DRYRUN → QUEUE → SUBMIT → MONITOR → COLLECT → REFLECT → REVISED_PLAN
```

cycle-level portfolio 循环是：

```text
PORTFOLIO_THINK → PORTFOLIO_REVIEW → RUN_GENERATION → SCHEDULER → RUN_EXECUTION → CYCLE_REFLECT → CYCLE_REVISED_PLAN → OPTIONAL_LITERATURE_REFRESH → OPTIONAL_DEEP_RESEARCH_REQUEST → WIKI_UPDATE → LEADERBOARD_UPDATE → NEXT_CYCLE
```

第一阶段不要实现 Write Agent，不要追求通用 agent 框架抽象，优先保证状态清晰、日志完整、可复现、可持续推进。早期必须允许多个实验方向并行探索，后期再根据 leaderboard、Reviewer 和 cycle revised plan 收敛到少数方向或单一实验。普通联网检索用于日常及时更新，deep research interface 用于路线级不确定和战略升级，两者必须由 revised plan 明确区分。
