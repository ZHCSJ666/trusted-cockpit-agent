# 评测与验证材料

本目录随 GitHub 整理版保留历史证据，方便复核。历史成绩不代表已对本次发布副本重新调用模型评测，也不代表全部扩展功能的总体准确率。

| 文件或目录 | 内容 |
|---|---|
| `summary.json`、`summary_main_250.json` | 五类可靠性主评测摘要；前端读取 `summary.json` |
| `trials_main_250.jsonl`、`trials_kimi.jsonl` | 主评测逐例记录 |
| `archive_250_source/` | 主评测冻结源码、数据、结果与指纹；保持原始字节 |
| `archive_120/` | 早期 120 例阶段的报告和证据；不混入当前 250 例成绩 |
| `trials_offline.jsonl` | 历史规则回归；不是模型能力成绩；重跑会生成 `summary_offline.json` |
| `model_capabilities.json` | 原服务模型探测记录；新服务请显式配置视觉模型 |
| `expansion_*`、`chat_routing*`、`navigation_question*` | 历史扩展功能及助手路由验收 |
| `screenshots/`、`expansion_ui/` | 历史演示截图 |
| `release_redactions.json` | 发布副本对历史日志中本机路径的替换记录与前后指纹 |
| `release_checks.json` | 本次整理后的安装、测试、构建与启动验证；与历史模型评测分开 |

主评测为每类 50 个、合计 250 个开发可见用例，每例重复 3 次；方案前后各 750 次执行，两组共享模型候选。结果为 62.80% → 91.73%，提升 28.93 个百分点。它是自建回归集上的配对比较，不能解释为第三方盲测成绩。

只有少量历史日志和进程元数据中的本机绝对路径被改为占位符；逐例评分与冻结目录未改。重新跑评测可能覆盖同标签文件，请使用独立 `--tag` 并保留源码、模型版本、语料、评分器和原始输出。
