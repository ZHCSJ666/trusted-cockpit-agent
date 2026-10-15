# 本仓库维护入口

这是基于 `cockpit-agent/` 上游源码制作的独立座舱演示工作台。默认入口是根目录 `start.py`，前端是 `cockpit-agent/hmi/`，后端是 `cockpit-agent/interview/`。来源见 `UPSTREAM.json`、`NOTICE` 和 `LICENSE`。

- 安装、配置与启动以根目录 README 为准；默认运行单进程模拟环境，不启动上游 Compose、云端、Android 或真实车辆服务。
- 修改上游模块前阅读其 `AGENTS.md` / `CLAUDE.md`；不要将上游历史部署状态当作本仓库运行状态。
- 所有实际车控仍是模拟；模型仅提出计划，执行需要经过参数、能力、权限、安全和结果验证。
- `.env`、密钥、`runtime/`、个人上传、下载的第三方 PDF 与本地依赖不入库。
- `results/archive_250_source/` 是历史冻结证据，不修改；新测试记录单独保存，不覆盖历史成绩。
- 常用验证：`python run_tests.py`；前端目录运行 `npm run typecheck`、`npm test`、`npm run build`。
- 不自动推送、部署或修改运行中的原始项目。
