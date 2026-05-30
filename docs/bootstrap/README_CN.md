# Bootstrap / Dogfood / Readiness 指南

本文把 v0.8.1 的 bootstrap、dogfood、legacy archive、policy gate 和 script readiness
说明集中到一个中文入口。目标是让新项目能安全接入 VibeResearch，而不是把下游仓库的
训练、评估或提交逻辑写死进主框架。

## 端到端 Bootstrap

在目标研究仓库里先初始化 `.vibe/`，再运行可恢复的 bootstrap 编排：

```bash
vibe init --goal "..." --background "..."
vibe bootstrap init --goal "..." --background "..." --memo-language zh-CN
vibe bootstrap run
vibe bootstrap status
vibe bootstrap doctor
```

bootstrap 阶段包括：

- `intake`：收集目标、背景、memo 语言和自治等级。
- `discovery`：读取 README、AGENTS、配置、脚本和已有 `.vibe/` 状态。
- `draft`：生成 adapter、script、policy 和 question 草案。
- `questions`：把缺失的项目答案显式写成 blocker。
- `validation`：运行 adapter lint、policy completeness 和 script readiness 检查。
- `activation`：只激活通过 contract test 的低风险 capability。
- `report`：输出 readiness report 和机器可读状态。

中断后使用：

```bash
vibe bootstrap resume
```

resume 会保留用户已经修改过的 adapter、script、question 和 policy 文件；如果需要合并，
会记录 merge warning，不会静默覆盖人工修改。

## 主要输出

bootstrap 相关状态默认写在目标仓库的 `.vibe/` 下：

```text
.vibe/bootstrap/state.json
.vibe/bootstrap/latest.json
.vibe/bootstrap/sessions/<session_id>.json
.vibe/bootstrap/readiness_report.md
.vibe/bootstrap/readiness.json
.vibe/script_readiness.json
.vibe/dashboard/readiness_export.json
.vibe/memos/YYYY-MM-DD.md
```

readiness 不是简单的 pass/fail。它需要说明当前哪些 capability 可以安全执行、哪些被阻塞、
哪些信息不完整，以及最小下一步是什么。

## 本地 Ignored Dogfood Sandbox

本地 dogfood sandbox 位于 `.vibe_dogfood/`，默认被 git 忽略，不应该提交。

创建或运行内置 profile：

```bash
vibe bootstrap sandbox --profile 0.8.1-happy-path
vibe bootstrap dogfood --profile 0.8.1-happy-path
vibe bootstrap dogfood --profile 0.8.1-missing-metrics
vibe bootstrap dogfood --profile 0.8.1-policy-conflict
vibe bootstrap dogfood --profile 0.8.1-placeholder-script
vibe bootstrap dogfood --profile 0.8.1-resume-after-failure
```

`0.8.1-happy-path` 包含 README、AGENTS、最小 evaluation script、sample metrics 和
bootstrap answers，用来验证一个低风险 evaluation capability 能够被激活。其它 profile
用于验证缺 metrics、policy 冲突、placeholder wrapper 和初始化中断会进入 state、questions
和 readiness blocker，而不是被误报为已完成。

## 外部 Dogfood 与 Legacy Archive

外部 repo dogfood 用来验证通用 bootstrap 流程是否能服务真实下游仓库。主框架不能硬编码
外部项目路径、脚本名、指标或答案；项目特异信息应留在外部 repo、brief 或输出 report 里。

推荐流程：

```bash
vibe bootstrap dogfood \
  --external-repo /path/to/repo \
  --brief-file /path/to/problem.md \
  --dry-run \
  --output-report /tmp/dogfood.json

vibe bootstrap archive \
  --source /path/to/repo \
  --note "legacy automation before fresh bootstrap"

vibe bootstrap import-legacy .vibe/archives/<archive_id>/manifest.json
```

如果目标仓库已有 `.vibe/` 或旧自动化，先 archive 再 fresh bootstrap。旧结果导入后默认是
`imported_unverified` 历史上下文。只有当前 adapter revision、capability id、metrics schema、
artifact rules 和 provenance 都能验证时，旧结果才可能成为 trusted evidence。

## Policy Completeness Gate

v0.8.1 的 readiness 检查会阻止不安全自动化：

- 缺 budget policy 时，不能 queue submission。
- 缺 autonomy policy 时，不能 automatic execution。
- 缺 stage-gate policy 时，不能 promotion。
- 缺 memo config 时，只 warning，不阻塞低风险初始化。
- 缺 protected metrics 时，不能自动进入更高阶段 promotion。

这些 blocker 应进入 `.vibe/bootstrap/readiness_report.md`、`.vibe/bootstrap/readiness.json`
和 dashboard readiness export，便于用户回答或补齐配置。

## Script Readiness Hardening

script readiness 导出到：

```text
.vibe/script_readiness.json
```

由 VibeResearch 生成的 wrapper 默认只能是 draft 或 untrusted。它必须通过 contract test，
并证明自己做了真实接口动作，才可以支持 active capability。真实接口动作包括但不限于：

- 解析配置。
- 检查输入路径。
- 调用项目 entrypoint。
- 生成 sample metrics。
- 校验 artifact 或 metrics schema。

placeholder wrapper、只打印字符串的命令、缺 expected output、sample metrics schema 无效的
脚本，都不能成为 active capability。

## 推荐操作原则

- 不删除旧 evidence；先 archive，再重新 bootstrap。
- 不把外部 repo 的项目细节写进 VibeResearch 主框架。
- 项目特异 blocker 应在下游 repo 中回答或修复。
- 先激活最小安全 capability，通常是 evaluation 或 metrics export。
- policy、contract test 和 readiness 未通过前，不自动进入 GPU、Slurm 或 long-run 执行。
