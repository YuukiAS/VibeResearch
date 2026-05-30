# Codex 一句话接入 VibeResearch 的操作提示

把下面整段提示交给 Codex。Codex 应负责安装 VibeResearch、初始化目标仓库、运行 bootstrap、向用户提问、把答案写入目标仓库，并持续 `resume`，而不是要求用户自己照 README 一步步执行。

```text
你现在是 VibeResearch onboarding operator。请不要让我手动读 README 后一步步操作；你负责读取当前 clone 的 AGENTS.md 和 docs/bootstrap/CODEX_ONBOARDING_PROMPT_CN.md，然后在目标研究仓库中安装并接入 VibeResearch。

目标：
1. 从 https://github.com/YuukiAS/VibeResearch.git 安装 VibeResearch，而不是复制某个本地开发目录。
2. 在我指定的目标 repo 中创建或更新 `.vibe/` 控制层。
3. 运行 v0.8.1 bootstrap：init、run、status、doctor。
4. 如果 bootstrap 生成 blocker questions，你要总结成 1-3 个短问题问我；我回答后，你把答案写入目标 repo 的 `.vibe/adapter_questions.yaml`、`.vibe/policies/*.yaml`、`.vibe/research/research_brief.md` 或 memo config，然后执行 `vibe bootstrap resume`。
5. 只激活通过 lint 和 contract test 的最低风险 capability。没有 budget、autonomy、stage gate、protected metrics、trusted baseline、metrics schema 或脚本 contract 时，不要自动提交高成本实验、GPU/Slurm job、validation zip 或 leaderboard upload。
6. 如果目标 repo 已有旧 `.vibe/` 或旧自动化状态，先做 read-only audit，再 archive 或询问我是否改名保留；不要删除旧 evidence，也不要把旧 metrics 自动当 trusted evidence。
7. 最终给我中文总结：安装来源和 commit、目标 repo 状态、readiness level、active/blocked capability、需要我继续回答的问题、下一条安全命令。

如果我还没有提供目标 repo 路径、项目目标/背景、预算或自治边界，请先问我。项目目标/背景是必须项；初始想法是可选项。回答问题时不要一次问太多，优先问会阻塞 readiness 或高风险自动化的内容。
```

## Codex 执行细则

Codex 应按下面顺序工作。

1. 确认目标 repo 路径；如果用户没有给，先问。
2. 确认项目目标和背景；这是初始化必填信息。
3. 可选收集初始想法、memo 语言、timezone、预算偏好和自治等级。
4. 在目标 repo 附近或用户指定位置 clone：

```bash
git clone https://github.com/YuukiAS/VibeResearch.git VibeResearch
cd VibeResearch
git pull --ff-only
python -m pip install -e .
python -m vibe_research.cli bootstrap --help
git rev-parse HEAD
```

5. 在目标 repo 做只读检查：README、AGENTS.md、git status、已有 `.vibe/`、已有结果和脚本。
6. 如果已有旧 `.vibe/`，先生成 archive 或请求用户确认改名；不要覆盖。
7. 初始化：

```bash
python -m vibe_research.cli init \
  --target /path/to/target-repo \
  --goal "<user goal>" \
  --background "<user background>" \
  --no-root-portal

python -m vibe_research.cli bootstrap init \
  --target /path/to/target-repo \
  --goal "<user goal>" \
  --background "<user background>" \
  --memo-language zh-CN \
  --autonomy-level analysis_only \
  --mode fresh

python -m vibe_research.cli bootstrap run --target /path/to/target-repo
python -m vibe_research.cli bootstrap doctor --target /path/to/target-repo
```

8. 读取 readiness 和 questions：

```bash
python -m vibe_research.cli bootstrap status --target /path/to/target-repo
cat /path/to/target-repo/.vibe/bootstrap/readiness_report.md
```

9. 把 blocker 合并成少量用户问题。优先级：

- primary metric、protected metrics、trusted baseline；
- metrics schema 和 evaluation/smoke entrypoint；
- budget：daily、per-experiment、per-hypothesis、unknown cost、long-run confirmation；
- autonomy：是否允许自动改脚本、自动提交 job、自动 archive、自动 stop hypothesis；
- Slurm/GPU 权限和高风险动作边界；
- memo language 和 timezone。

10. 用户回答后，Codex 写入目标 repo 的 `.vibe/` 文件，然后运行：

```bash
python -m vibe_research.cli bootstrap resume --target /path/to/target-repo
python -m vibe_research.cli bootstrap doctor --target /path/to/target-repo
```

11. 只有在 readiness 和 contract test 允许时，才执行：

```bash
python -m vibe_research.cli adapter lint --target /path/to/target-repo
python -m vibe_research.cli adapter doctor --target /path/to/target-repo
python -m vibe_research.cli adapter contract-test <capability_id> --target /path/to/target-repo
python -m vibe_research.cli adapter activate <capability_id> --target /path/to/target-repo --confirm "minimum safe capability"
```

12. 最终总结必须说明哪些动作没有做，尤其是未提交 GPU/Slurm、未创建 validation zip、未上传 leaderboard、未信任旧 evidence。

## 用户只需要提供的最少信息

- 目标 repo 路径。
- 项目目标或研究目标。
- 项目背景和主要约束。

后续信息可以由 Codex 在 readiness blocker 出现后逐步询问。
