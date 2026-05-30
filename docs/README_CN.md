<h1 align="center">VibeResearch</h1>
<h3 align="center">面向长期研究流程的仓库级控制层</h3>

<p align="center">
  <strong>VibeResearch 将项目上下文、执行状态、证据链和报告集中保存在目标仓库的 <code>.vibe/</code> 目录中。</strong>
</p>

<p align="center">
  <a href="../README.md">English</a> |
  <a href="README_CN.md">中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/state-.vibe%2F-informational.svg" alt=".vibe state"/>
  <img src="https://img.shields.io/badge/dashboard-read--only-lightgrey.svg" alt="Read-only dashboard"/>
</p>

---

## 项目概览

VibeResearch 是一个本地优先的研究流程管理框架，面向已经存在的代码仓库。它会在目标仓库中创建 `.vibe/` 工作区，并把项目背景、想法、计划、运行记录、调度状态、实验依据、看板和每日日志保存在这里。

它的核心设计是把“判断”和“执行”分开。研究者或代码助手可以提出计划、假设、审阅意见和分析结论；VibeResearch 负责记录状态、校验接口、调度任务、跟踪来源、收集指标，并在信息不足或风险过高时阻止自动执行。

适合的场景包括：

- 持续多轮推进一个研究项目，并保留每轮决策依据；
- 将项目自己的训练、评估或推理脚本接入统一的编排层；
- 在本地或 Slurm 集群上运行实验，同时保留预算和就绪检查；
- 归档旧失败状态，把它作为历史经验，而不是直接当成可信证据；
- 生成状态看板、每日记录和组会材料。

## 安装

从 GitHub 克隆并安装：

```bash
git clone https://github.com/YuukiAS/VibeResearch.git
cd VibeResearch
python -m pip install -e .
```

确认命令可用：

```bash
vibe --help
vibe bootstrap --help
```

## 快速开始

进入目标研究仓库并初始化：

```bash
cd /path/to/research-repo
vibe init \
  --goal "在固定评估协议下提升验证表现" \
  --background "项目背景、数据、指标、算力限制和当前基线"
```

查看当前状态：

```bash
vibe config validate
vibe status
vibe next
```

如果不希望在目标仓库根目录生成状态镜像文件，可以使用：

```bash
vibe init --no-root-portal --goal "..." --background "..."
```

## 让 Codex 代为接入

如果希望把安装和初始化交给 Codex，而不是手动照 README 执行命令，可以把下面文件中的提示交给 Codex：

```text
docs/bootstrap/CODEX_ONBOARDING_PROMPT_CN.md
```

这份提示会要求 Codex 从 GitHub 克隆 VibeResearch、安装框架、询问目标仓库和项目目标/背景、运行初始化流程、整理阻塞问题、把你的回答写入目标仓库的 `.vibe/` 文件，并继续执行 `bootstrap resume`，直到最小安全能力就绪或明确阻塞。

## 状态目录

VibeResearch 的持久状态都在 `.vibe/` 下：

```text
.vibe/
  project/                 项目 brief 和初始化上下文
  config.yaml              框架配置
  adapter.yaml             项目能力声明
  adapter_questions.yaml   激活前需要回答的问题
  script_bootstrap_plan.md 脚本接入计划
  scripts/                 项目自己维护的封装脚本
  contract_tests/          能力接口测试结果
  policies/                预算、阶段门控和自治策略
  state/                   控制状态
  cycles/                  cycle 级计划和决策
  runs/                    运行清单和来源记录
  scheduler/               队列和预算状态
  ideas/                   想法池
  research/                假设、实验、证据和决策
  memos/                   每日记录
  dashboard/               看板数据导出
  site/                    静态看板
  reports/                 组会和开发报告
  portal/                  根目录镜像文件的来源
```

根目录的 `RUN.md`、`VIBE_STATUS.md`、`VIBE_TODO.md`、`VIBE_TIMELINE.md`、`VIBE_LEADERBOARD.md` 只是生成出来的镜像文件，不是权威状态。权威状态始终在 `.vibe/` 下。

重新生成根目录镜像：

```bash
vibe portal build
```

默认不会修改根目录已有的 `AGENTS.md`。只有显式要求时才会安装片段：

```bash
vibe init --install-agents-snippet --goal "..." --background "..."
```

## 初始化与就绪检查

Bootstrap 是把已有项目接入 VibeResearch 的初始化流程。它会读取项目文件，生成 adapter 草案和脚本接入计划，写入策略文件，记录未回答的问题，运行校验，并且只激活通过接口测试的能力。

```bash
vibe bootstrap init --goal "..." --background "..." --memo-language zh-CN
vibe bootstrap run
vibe bootstrap status
vibe bootstrap doctor
```

如果 bootstrap 因信息不足而停止，先回答或修改 `.vibe/` 下生成的文件，然后继续：

```bash
vibe bootstrap resume
```

主要输出：

```text
.vibe/bootstrap/state.json
.vibe/bootstrap/sessions/<session_id>.json
.vibe/bootstrap/readiness_report.md
.vibe/bootstrap/readiness.json
.vibe/script_readiness.json
.vibe/dashboard/readiness_export.json
```

就绪检查采用保守策略：缺预算策略时不能提交队列；缺自治策略时不能自动执行；缺阶段门控时不能晋升；缺受保护指标时不能自动进入更高阶段。

Bootstrap 和 adapter 发现流程使用有上限的文件遍历器。`.git/`、`.vibe/`、`.vibe_dogfood/`、`data/`、`results/`、`models/`、`logs/`、`envs/`、`external_supervisors/` 等运行期或重目录会在进入前跳过，避免初始化时扫进大量中间产物。项目可以在 `.vibe/config.yaml` 中调整：

```yaml
discovery:
  skip_dirs: [scratch, downloads]
  max_files: 200
  max_dirs: 1000
  max_seconds: 5
```

更完整的接入、本地试运行、旧状态归档和就绪门控说明见 [Bootstrap 指南](bootstrap/README_CN.md)。

## Adapter 接入

Adapter 是项目自己的能力声明，用来说明 VibeResearch 可以做什么。真正的训练、评估、推理和提交逻辑仍然属于下游项目，由 `.vibe/scripts/` 中的薄封装脚本调用。VibeResearch 主框架不保存项目特定执行逻辑。

常用命令：

```bash
vibe adapter discover
vibe adapter draft
vibe adapter ask
vibe script bootstrap --plan
vibe adapter lint
vibe adapter doctor
```

只有 `active` 能力可以被选中执行。`draft`、`candidate` 或阻塞状态的能力只会出现在报告中，不会自动运行。能力必须先通过接口测试才能激活：

```bash
vibe adapter contract-test metrics_export
vibe adapter activate metrics_export --confirm "reviewed by project owner"
```

`.vibe/scripts/` 中生成的封装脚本默认是草案，不能直接视为可信。通常应先建立评估或指标导出能力，再考虑训练自动化；GPU 和长任务能力必须有明确的资源策略。

Instrumentation readiness 和真实实验 readiness 是两件事。环境探针、数据探针和 baseline inventory 可以验证项目表面，但不代表已经可以推进方法或评估实验。真实实验前需要补齐评估命令、指标格式、baseline/proxy、后端策略、collector 和项目安全规则：

```bash
vibe adapter real-gaps
vibe experiment real-progress
```

## 有边界的研究管理

研究管理层用来记录假设、实验、证据、决策、预算和每日记录。它帮助项目持续迭代研究想法，同时保留每个结论背后的证据链。

```bash
vibe research init --goal "..." --background "..." --memo-language zh-CN
vibe hypothesis create "try a calibrated evaluator" --stage analysis
vibe experiment create hyp_001 --design "calibration smoke" --stage analysis --capability metrics_export
vibe experiment analyze exp_001 --trusted --schema-valid --summary "primary improved without guardrail regression"
vibe memory build
vibe portfolio plan
vibe portfolio schedule
vibe budget status
vibe memo daily --language zh-CN
vibe dashboard export-research
```

晋升需要可信且符合指标格式的证据，并且受保护指标不能出现不可接受的回退。停止假设需要可信负证据或明确的用户决定。同构重复实验、未知成本、缺脚本、缺指标格式和缺 `active` 能力都会在执行前被阻止。

## 从决策到执行

VibeResearch 不会直接把自由文本计划变成实验。它先把结构化决策编译为资源计划，再生成运行清单。

```text
revised_plan.md
  -> decision.json
  -> project adapter
  -> resource_plan.yaml
  -> 运行清单
  -> 通过格式和来源检查后才成为可信指标
```

常用命令：

```bash
vibe validate-decision c001
vibe decision show c001
vibe decision write c001 --type launch_gpu_gate --action "run configured adapter task"
vibe decision write-block c001 --reason "adapter missing"
vibe compile-decision c001
vibe validate-resource-plan c001
```

重复收集同类证据、缺失指标或默认 0.0 指标会被标记为阻塞或不可信，不会更新可信排行榜状态。

## 想法池与深入调研

原始输入会进入收件箱；整理后的研究想法会进入想法池，并获得稳定 ID。

```bash
vibe idea "比较两条路线级方法"
vibe ideas list
vibe ideas triage
vibe ideas promote idea_001
vibe ideas reject idea_001 --reason "暂时超出范围"
vibe ideas archive idea_001
```

深入调研需要显式触发。把想法标记为需要深入调研，并不会自动开始调研。

```bash
vibe deep-request-from-idea idea_001
vibe ingest-deep-research dr001_idea_001 --kind science
vibe ingest-deep-research dr001_idea_001 --kind workflow
vibe ingest-deep-research dr001_idea_001 --kind repo
vibe ingest-deep-research dr001_idea_001 --kind benchmark
```

支持 Markdown 和 PDF 报告。PDF 文本抽取优先使用 PyMuPDF，不做 OCR。

## 调度与 Slurm

调度器是确定性的，并且会遵守预算。未通过预演、清单无效、依赖未满足、超预算或被审阅阻塞的任务都不会提交。

探测本地环境：

```bash
vibe config detect
```

集群相关配置通常位于：

```text
.vibe/config.yaml
.vibe/config.local.yaml
.vibe/scheduler/budget.yaml
```

提交并监控：

```bash
vibe submit-queue --backend slurm
vibe monitor --loop --auto-next
```

本地开发可以使用模拟提交：

```bash
vibe submit-queue --dry
```

## 看板与报告

构建静态只读看板：

```bash
vibe dashboard build
```

本地查看：

```bash
vibe dashboard serve --host 127.0.0.1 --port 8765
```

导出组会材料：

```bash
vibe export-meeting
vibe export-meeting --date 20260529
```

输出目录：

```text
.vibe/reports/meeting/YYYYMMDD/
```

## 本地开发

运行测试：

```bash
python -m pytest -q
```

测试使用离线 Codex 和本地模拟调度路径，不需要 Codex 登录、GPU、Slurm 集群或网络。

运行内置冒烟流程：

```bash
vibe dogfood
```

## 设计原则

- `.vibe/` 是权威状态目录。
- 根目录状态文件只是生成镜像。
- 项目特定执行逻辑留在下游仓库。
- 能力必须明确声明、经过审查，并通过接口测试后才能使用。
- 长任务监控不依赖语言模型调用。
- 旧结果只是历史上下文，只有通过当前 adapter、指标格式、产物和来源规则后才可能成为可信证据。
