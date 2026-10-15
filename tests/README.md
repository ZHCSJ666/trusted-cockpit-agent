# 如何复现测试

正常运行座舱不需要测试工具。以下命令在仓库根目录执行，前端使用 Node.js 22+。

## 发布版启动检查

先启动 `.venv/bin/python start.py`，再在另一终端运行：

```bash
.venv/bin/python tests/release_smoke.py
```

它通过真实 HTTP 检查模拟车控、歧义澄清、能力拒绝、安全拦截与精选手册证据，不调用模型或外部信息提供商。安装下文 Playwright 后，可加 `--browser` 检查助手交互、四个主页面和手机布局。不同端口使用 `--url http://127.0.0.1:8790`。

## 无网络机制测试

```bash
.venv/bin/python run_tests.py
```

涵盖关键槽位、参数与原话一致性、否定/读态问句、车型能力、权限、安全态、确认过期/重放/状态变化、错目标、ACK丢失、RAG条件和模型错误路径。不会读取真实API凭据或发出模型请求。

扩展后此入口也运行新增车控与T1/T2、任务补槽、服务注册、SQLite、PDF和HTTP/SSE的机制测试。外部提供商使用明确测试替身，真实调用另见下方扩展验收。

## 扩展版真实验收

在独立终端启动 `.venv/bin/python start.py --port 8788`，不要停止其他人运行的服务。再执行：

```bash
.venv/bin/python tests/expansion_api.py --port 8788
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python tests/expansion_browser.py
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python tests/voice_browser_lifecycle.py
```

前两项使用真实本地API、外部地图/信息接口和已配置模型，会产生模型调用。语音生命周期测试使用合成识别事件和播报替身，验证自动发送/继续聆听/显式打断/权限失败路径，不代表真人语音识别或音质已验收。浏览器URL可通过 `STUDIO_TEST_URL` 指定。硬件麦克风和摄像头需要在实际演示设备上检查。

服务独立探针为 `tests/probe_expanded_services.py`；结果在 `results/expanded_services_probe.json`。它只证明记录时刻的接口与检索可用，不是准确率/SLA。完整旅程与页面证据分别在 `results/expansion_acceptance.json`、`results/expansion_ui.json`。

原250例及成绩未改变，源码与结果已保存在 `results/archive_250_source/`；新增功能不得引用旧准确率作为总体成绩。

助手自然语言路由回归（在单独终端启动 `start.py --port 8788`）：

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python tests/chat_routing_browser.py
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python tests/navigation_question_browser.py
```

这项测试直接键入用户报告的导航、新闻原话，继续选择实际起点，并用另一种表达触发真实模型查询；不模拟服务响应。结果为 `results/chat_routing_acceptance.json`，截图在 `results/chat_routing/`。`test_chat_routing.py` 的确定性回归已纳入 `run_tests.py`，另覆盖空计划修复、起终点校验和复合/否定表达。

第二项复现“怎么去杭州市政府”问路、先问手册再改问路、目的地前置问句、车辆手册正例及问路＋天气复合任务；真实数据和模型不设替身。结果为 `results/navigation_question_acceptance.json`，截图在 `results/navigation_question/`。相应的领域划分、补槽与参数授权机制回归在 `test_navigation_questions.py`，政府简称与地图模糊命中回归在 `test_expanded_services.py`，均纳入统一测试入口。

## 配对评测

```bash
.venv/bin/python evaluate.py --provider kimi --repeats 3 --concurrency 8
.venv/bin/python render_reports.py
```

`cases.json`：250条开发可见回归集，每类50；每例重复3次，Kimi方案前/后各750次。模型候选由两组共享，不是1,500次独立模型调用。主页面只展示Kimi两组。

`challenge.json`：旧120例阶段、当时引擎冻结后编写的15条表达。旧挑战/消融成绩保存在 `results/archive_120/`，不是当前250例评测的一部分。以下命令仅用于单独重跑挑战，不会替换主成绩。

```bash
.venv/bin/python evaluate.py --provider offline --repeats 3 \
  --cases tests/challenge.json --tag challenge_offline
.venv/bin/python evaluate.py --provider kimi --repeats 3 --concurrency 2 \
  --cases tests/challenge.json --tag challenge_kimi
```

offline 工程回归可另用 `.venv/bin/python evaluate.py --provider offline --repeats 3`，仅写 `summary_offline.json`；不把规则输出当作真实模型结果。历史消融若重跑，需另行标注新日期、源码及范围。

每次运行覆盖对应标签的原始记录。正式比较前冻结引擎、语料、用例和评分器，运行期间不要修改。`source_changed_during_run` 必须为 `false`。同一Kimi候选共享给两个模式，配对组的模型Token不可重复相加。

## 浏览器检查

先在一个终端启动 `.venv/bin/python start.py`。浏览器测试使用真实本地接口，不mock响应。

安装仅用于QA的依赖：

```bash
.venv/bin/python -m pip install playwright==1.63.0
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python -m playwright install chromium
```

运行：

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python tests/browser_smoke.py
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python tests/kimi_browser.py
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python tests/benchmark_browser.py
```

`kimi_browser.py` 会产生一次真实 Kimi 请求；`benchmark_browser.py` 核对桌面/手机评测页面与已保存结果一致，不调用模型。截图与结果在 `results/`；未验证真实麦克风、音响、实车或上游完整分布式栈。
