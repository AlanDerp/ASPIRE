# ASPIRE Sim 动态 FG 重构施工规划

状态：实施中；P0–P7 的 CPU/伪环境工程链已落地，P8 真实仿真与性能实验仍待按协议选择 suite、完成 preflight 后执行。
日期：2026-09-11
主设计：[FG-redesign.md](FG-redesign.md)
范围：`aspire/sim` 的任务协议、公开感知验证、私有审计、验证 Skill 和试验工具。

## 1. 施工基线与交付目标

### 1.1 分支核对

本次核查得到：

| 项目 | 实际状态 | 对施工的影响 |
| --- | --- | --- |
| 当前工作分支 | `FGRebuild`，HEAD `0a36d7a02abad08943f2124146d783fb253677b7` | 本文文件“新增/修改”以此基线为准 |
| 用户拟用分支名称 | `FGBuild`；本地未发现同名分支 | 本次仅编写规划，不创建、重命名或切换分支；开始实施时核对最终名称 |
| 旧 FG 参考分支 | `codex/merge`，`42df97b12669335c293d21abe79abe8d6dac96dc` | 通过 Git 只读检查其实现，作为行为对照 |
| 当前基线已有 | `cap/knowledge/*`、`cap/envs/trial.py`、`cap/envs/tasks/base.py`、视觉服务 | 复用知识证据基础和试验主入口 |
| 当前基线没有 | `cap/factual_grounding/*`、`cap/agent_protocol/*`、`cap/perception/*`、`cap/integrations/franka/g17/*` | 不能把这些写成当前分支已有模块；新 FG 在本分支主要是新增 |

`codex/merge` 比当前基线包含更多调度、服务启动、G17 hooks 和文档变化。不以整体 merge 作为本计划的前置动作；需要的通用能力逐项审查后移植。旧分支中的固定任务事实、关键词任务白名单和硬编码恢复判定不进入 dynamic-v2 主链。

补充参考为 `codex/merge` 上的 `doc/aspire-sim-fg-v2-design-review-2026-09-11.md`，用于发现时序、隔离和目标覆盖问题；协议字段以主设计和本计划 P0 冻结的契约为准，不混用两稿的 `decision/turn_kind` 命名。

### 1.2 最终应实现的效果

1. Actor 从任务语言和公开能力清单生成 PLAN 与动态 FG 目标；相同 predicate 可以绑定不同对象、阶段和时间要求，无任务 ID→固定 facts 表。
2. Harness 严格解析、审查并冻结目标，通过真实公开传感器及注册验证方法产生证据和 observed verdict。
3. Actor 收到有版本、证据、时效和 UNKNOWN 原因的反馈；无效响应不能执行，缺少完成证据不能通过结束门。
4. Audit 对相同目标产生独立私有判断；正式 held-out 中不影响动作、prompt、重试、结束判断或 Skill 状态。
5. Development 可诊断差异、执行获准探测并积累验证方法候选；经过配对验证、审核和冻结后，方法能在没有 audit 的任务中调用。
6. 通过完整功能测试证明流程真实连通；通过独立受控实验判断泛化和性能，不能用 mock 测试通过代替性能结论。

本文不选择或启动仿真实验，不变更既有 seed 分区、预算、结果或机器人服务。真实仿真阶段按根 `AGENTS.md`、suite constitution 和选定 experiment runbook 完成 preflight 后另行执行。

## 2. 开工前必须冻结的设计补充

以下是对主设计歧义的施工决策，P0 应以 schema、配置及测试固化。

| 问题 | 施工决定 | 防止的失败 |
| --- | --- | --- |
| 模型挑选容易成功的锚点 | 引入独立 Spec Critic；目标关联 task requirement，审查覆盖、必要性和可观测性。Critic 不能读 audit 或按 task ID 返回固定目标表 | 仅有动态 JSON 外壳，实质仍是假成功或人工编排 |
| required 目标替换 | 不只禁止删除/降级，还检查放宽阈值、替换实体、缩短窗口等语义弱化；保存理由与重新审核结果 | 通过 replace 绕过完成门 |
| 长任务历史要求 | 区分 milestone、terminal、invariant；finish 检查被接受的完成公式。已完成的“曾抓取”不要求放下后仍 held_by | 要求所有历史锚点在最后一帧同时成立 |
| continuous N steps | 绑定 simulator/control tick，不是 LLM turn；规定采样间隔、最大缺口和覆盖窗口。无法证明窗口覆盖时 UNKNOWN | 用动作结束两帧推断全程无接触 |
| 接触判断 | 公共几何只能报告可观测间隙及不确定性；低于分辨率、遮挡或身份不确定时 UNKNOWN。审计 contact 定义与容差单独锁定 | 把两张“看起来未接触”的图当可靠真值 |
| 阈值来源 | 明确 unit、tolerance、threshold_source、assumption；任务给定值优先，模型提议值需 Critic 审查与记录 | 模型任意降低任务标准 |
| development 的 audit 影响 | mismatch 触发的探测标记 `audit_influenced=true`，单独统计；不能把该轨迹称为 observed-only | audit 经探测选择间接改变策略却未报告 |
| 学到的 Skill 触发条件 | 冻结 Skill 只能依赖公开状态、遮挡、不确定性或公开冲突；audit mismatch 仅作开发证据标签 | 新 Skill 上线后仍依赖真值才能触发 |
| 动作修复与验证修复 | 区分 `task_repair`、`probe`、`verifier_revision`；移动物体后 mismatch 消失不证明 verifier 改善 | 将完成任务的恢复动作错误晋升为感知方法 |
| shadow 语义 | `legacy-code-v1` 保持原执行入口；v2 shadow 严格解析，FG 不反馈也不门控，但协议错误始终不执行。shadow 不宣称与 legacy 的模型行为相同 | “错误响应不执行”与“任何行为完全不变”互相矛盾 |
| audit 隔离 | 仅删 prompt 字段不足够；生成代码 worker 不持有 simulator/audit 对象，也不能读私有文件或调用私有 IPC | 把进程可靠性隔离误当权限隔离 |
| public hash | Public snapshot/projection hash 只覆盖公开内容；含 audit 的完整索引仅存在私有存储 | 即使内容隐藏，audit 改变仍经 hash、路径或控制流泄漏 |

主设计示例 JSON 省略了部分模型必需字段。P0 必须明确必填项及确定性默认值，并给出完全可通过 parser 的示例；不能在 runtime 中自由猜测。

## 3. 阶段顺序与范围

```text
P0 基线与契约
 → P1 AgentTurn / PLAN / 目标审核
 → P2 事件、持久化与公开感知边界
 → P3 observed verifier 与时序证据
 → P4 trial 主循环、公开反馈及 finish gate
 → P5 私有 audit、对齐比较和隔离验收
 → P6 development 诊断与主动探测
 → P7 Verification Skill 验证、审核、冻结、调用
 → P8 完整功能性验收与受控实验
```

第一可用切片为 P0–P5，加 P6 的公开 alternate-view probe：具备动态目标、真实 observed 验证、Actor 反馈和私有离线比较。P7 是完整学习闭环，不能以“已有候选接口”宣布完成。各阶段先通过自身测试及前序回归，再启用下一阶段配置。

以下路径除 `doc/` 外均相对 `aspire/sim/`。新增包同时创建 `__init__.py`；测试默认使用 pytest 执行，兼容现有 unittest 测试。

## 4. P0：基线、迁移契约与配置冻结

**目的：** 明确旧路径兼容性、新路径所有权、配置来源和可证明的验收标准。

**创建或修改文件：**

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `docs/fg-v2-contracts.md` | 协议合法组合、版本规则、时序语义、public/private 边界、完成公式和错误码 |
| 新增 | `cap/factual_grounding/config.py` | 严格 v2 配置、模式互斥、目标/模型/探测/时长预算、checkpoint 锁 |
| 修改 | `cap/envs/tasks/base.py` | `CodeExecEnvConfig` 新增类型化 `runtime_features`，不在 env 内创建 FG coordinator |
| 修改 | `cap/envs/configs/loader.py` | 校验配置合并路径，未知字段和冲突配置报错 |
| 新增 | `env_configs/fg/dynamic_v2_template.yaml` | 不绑定任务、种子、GPU 的模板；未完成 suite 配置时不能直接启动 |
| 新增 | `tests/fg/test_config.py`、`tests/fg/test_legacy_compatibility.py` | 新配置校验与关闭 FG 的基线行为 |

**实现功能：**

- 明确 `protocol` 与 `runtime_mode`、`feedback=shadow/visible` 是不同维度；enabled=false 时不初始化感知、模型、audit 或 Skill 更新服务。
- `runtime_features` 经配置 composer 进入 `env.cfg`，同时保留当前 `knowledge` 配置的唯一来源，禁止双份互相覆盖。
- 禁止 dynamic-v2 同时启用旧 G17 capture、sim_gt actor feedback 或按函数出现次数自动晋升验证 Skill。
- 保存 baseline commit、配置 hash、API 清单和公开输入 fixture；旧 FG 对照在独立 checkout/结果目录中重现。

**运行测试及退出条件：**

- `tests/fg/test_config.py`：三种 runtime mode、非法混配、缺少 adapter/checkpoint、预算越界、未知字段。
- `tests/fg/test_legacy_compatibility.py`：FG 关闭时 prompt/动作序列及结果字段不变；不加载可选重依赖。
- 回归现有 `test_knowledge_runtime.py`、`test_preregistration.py`。
- 产出可机器读取的配置契约，分支基线和所有未定实验参数有显式记录。

## 5. P1：结构化 AgentTurn、动态目标与覆盖审核

**目的：** 从输入源头替换自由文本猜测，保证执行前已有合法 PLAN 和有用的目标。

**创建或修改文件：**

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `cap/agent_protocol/models.py`、`parser.py`、`validator.py`、`prompt.py` | AgentTurn、Plan、Action、FGPatch、严格解析和错误恢复 |
| 新增 | `cap/agent_protocol/spec_critic.py` | 隔离上下文的 requirement coverage 审核接口与结构化评审结果 |
| 新增 | `cap/factual_grounding/targets.py`、`registry.py` | 动态目标 revision、实体引用、算子类型/单位和 patch 规则 |
| 新增 | `cap/agent_protocol/legacy.py` | 旧代码/REGENERATE/FINISH 协议的显式适配 |
| 修改 | `cap/utils/launch_utils.py` | 将 `_extract_code`、`_parse_multi_turn_decision` 限定在 legacy 调用链 |
| 新增 | `tests/fg/test_agent_protocol.py`、`test_targets.py`、`test_spec_critic.py` | 协议、覆盖和规避测试 |
| 新增 | `tests/fixtures/fg_v2/protocol/` | 合法/非法 envelope、不同任务语言及长任务 PLAN fixtures |

**实现功能：**

- 首轮与多轮共用一个 parser；只接受一个 JSON envelope，拒绝多 JSON、重复键、未知字段、NaN/Infinity、类型不符和夹杂文本；限长度与嵌套深度。
- `decision` 使用主设计五种值；冻结 `turn_kind` 与 decision/plan/action 的合法组合。finish/abort 不得夹带执行代码。
- plan_action 原子校验：任一 target、patch、动作字段无效，整个 turn 不提交也不执行。
- 初始至少一个 required anchor；绑定公开实体与 requirement；unsupported 明确返回，要求修订，不能转 False 或静默略过。
- 对陈旧 revision、重复 turn ID、required 降级、阈值弱化及循环定义给出明确错误。Critic 超时/无效输出不得默认批准。
- 限制错误修复轮数和模型预算，防止无效响应死循环。Critic 不承诺语义全知，后续另评估覆盖准确率。

**运行测试及退出条件：**

- 三个新增测试文件；用执行 spy 断言所有拒绝场景动作调用数为 0、revision 未变化。
- 测试遗漏否定词/指定夹爪/持续条件、同义改写、替换实体、放宽阈值和历史 milestone。
- 同一任务不同合法 PLAN 可通过；不同对象可复用同 predicate，不依赖任务关键词白名单。
- 完整 envelope 示例通过 parser，所有错误能返回下一轮结构化反馈。

## 6. P2：事件、持久化、ObservationBroker 与执行权限边界

**目的：** 建立可追溯的实际证据来源，并在 audit 引入前划清生成代码权限。

**创建或修改文件：**

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `cap/factual_grounding/observations.py`、`persistence.py`、`runtime.py` | 双通道契约、append-only ledger、公开/私有索引、恢复状态 |
| 新增 | `cap/perception/observation_broker.py`、`capability_registry.py` | 同事件 sensor bundle、能力协商、标定和时钟元数据 |
| 新增 | `cap/perception/entity_binding.py`、`evidence.py` | 公开实例绑定、证据内容寻址和来源标识 |
| 新增 | `cap/envs/execution_boundary.py`、`generated_worker.py` | allowlist RPC facade、生成代码隔离 worker、消息 schema 和超时 |
| 修改 | `cap/envs/tasks/base.py`、`cap/envs/runner.py` | v2 通过受控边界执行；legacy 保留原路径；传感器和事件由 harness 订阅 |
| 新增 | `tests/fg/test_persistence.py`、`test_observation_broker.py`、`test_execution_boundary.py` | 事件、存储、采样和权限测试 |

**实现功能：**

- action/probe 有唯一 event ID；bundle 包含 capture ID、spec revision、tick 范围、相机时间戳、标定/实体版本；相机不同步明确记录。
- 同 target 的 observed/audit 可以共存；false、unknown、unsupported、error 分开编码。
- 原始大图使用内容寻址；记录真实方法版本、参数和输入引用。保存采用追加与提交标记，prompt 只引用已提交完整事件。
- worker 仅收到公开数据及注册控制 API 的代理；无 env/simulator 对象、audit 句柄、私有目录、凭据或私有 IPC 权限。重定向错误/日志也走公开过滤。
- `agent/`、`plan/`、`fg/`、`execution/`、`evidence/`、`skill_proposals/` 按主设计落盘；audit/comparison/full snapshot 存在独立私有根，公共 trial 仅保留许可引用。
- 使用 OS/container 权限落实边界；AST 检查只是补充。平台未配置该边界时，带任意生成 Python 的 v2 audit 模式应拒绝启动。
- 重启遇到已确认动作不重放；动作已发出但完成状态未知时标记 indeterminate 并停止/重建试验，不宣称物理副作用 exactly-once。

**运行测试及退出条件：**

- 三个新增测试文件：跨 trial 隔离、重复 event、追加中断、损坏/缺失 blob、陈旧结果、同名双通道、确定性重放。
- 对 worker 做真实子进程/权限测试：公开 API 可用，私有路径、audit socket 和 simulator 引用不可达；仅测试对象字典不够。
- 测试输出 hash 不受 audit 内容影响；完整私有 hash 仍可验证双通道关联。
- 事件链可重建；不覆盖旧实验目录。权限测试不能运行的环境标记 blocked，而非通过。

## 7. P3：公开验证方法与持续时间判断

**目的：** 让动态目标获得真实 observed producer，替换“字段存在但无测量”的旧 FG。

**创建或修改文件：**

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `cap/perception/verification_plan.py`、`probe_runner.py` | 受约束的 VerificationPlan、方法依赖、公共证据 runner |
| 新增 | `cap/factual_grounding/verifier.py`、`temporal.py` | 测量合成 verdict、时效、冲突及连续窗口覆盖 |
| 新增 | `cap/factual_grounding/verifiers/held_by.py`、`above.py`、`contact.py` | 首批三种动态 predicate 的公开验证器 |
| 新增 | `cap/perception/components.py` | 将现有 SAM/深度/几何接口注册为组件，保持服务实现复用 |
| 按需修改 | `cap/integrations/vision/sam3.py`、选定 suite 的公开 observation/控制边界文件 | 补齐结果元数据、帧内采样 hook；禁止读取对象真值 |
| 新增 | `tests/fg/test_verifiers.py`、`test_temporal.py`、`test_capability_resolution.py` | 三种 predicate、组合和资源测试 |
| 新增 | `tests/fixtures/fg_v2/sensors/` | 标明 synthetic/recorded 来源、标定和标签的多视角时序 fixtures |

**实现功能：**

- 目标映射为注册的方法和输入，不接受模型生成的任意验证 Python；缺方法或相机返回 unsupported。
- `held_by` 使用实例身份、跨帧相对运动及夹爪观测，夹爪闭合本身不能证明抓对物体。
- `above` 计算公共深度/点云支持的方向、间隙、单位与误差界；`contact` 对不可见接触区域、零间隙模糊和共享遮挡返回 UNKNOWN。
- 两视角独立性依据相机/视线/输入 provenance，而不是调用次数；同图两次模型调用不能充当两个独立视角。
- `stable_for` 包装组合命题；采用 action 内 tick 采样或受控 action 分段。缺帧、越过最大间隔、过期或冲突按契约中断/失去窗口证明。
- Verifier/VLM 与 Actor 使用独立 prompt 和状态；输出必须引用已存在证据。stdout、执行无错误、LLM 自称成功均不是 measurement。
- 方法、模型、prompt、采样策略和预算锁版本；可确定性重放保存结果，在线模型重复调用不要求字节一致。

**运行测试及退出条件：**

- 三个新增测试文件：遮挡、身份交换、同图重复、深度缺失、标定错误、服务超时、非法测量、相互冲突及过期。
- 单帧满足不完成 N-step；首尾满足但中途接触必须失败或 UNKNOWN，不能 satisfied。
- 在公开 sensor fixture 上至少各有正例、负例、UNKNOWN 和错误例；结果具备 evidence hash。
- 真实组件连接测试列为 integration；fake 感知输出通过不等于真实视觉验证完成。

## 8. P4：Trial Coordinator、Actor 反馈与结束门

**目的：** 将前述模块接入真正的首轮和多轮执行主链，形成 observed-only 可用闭环。

**创建或修改文件：**

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `cap/factual_grounding/coordinator.py`、`prompt_projection.py`、`finish_gate.py` | 状态机、预算、公开反馈及完成公式 |
| 新增 | `cap/envs/agent_turn_loop.py` | v2 loop；统一首轮、后续 turn、错误恢复及结果提交 |
| 修改 | `cap/envs/trial.py`、`cap/utils/launch_utils.py` | `_query_initial_code`/多轮解析分流；v2 交给新 loop |
| 修改 | `cap/envs/tasks/base.py`、`cap/envs/runner.py` | env 只发布执行/传感器结果；超时和失败也保存已提交 FG trace |
| 修改 | `cap/envs/launch.py`、`cap/utils/launch_utils.py` 中的 `TrialSummary` | 结果字段贯通及兼容导出，不复用模糊 success 标志 |
| 新增 | `tests/fg/test_coordinator.py`、`test_trial_v2.py`、`test_prompt_projection.py`、`test_finish_gate.py` | 真正 trial 入口集成和完成门 |

**实现功能：**

- 实现主设计状态机，所有模式共用明确 dispatch；禁止无有效 PLAN 的第一动作。配置不支持的 ensemble/oracle 路径应明确拒绝，而非绕过 v2 校验。
- `observe` 只运行获准 probe，`revise_plan` 只提交已审核 patch，finish_request 只进入完成门。
- 长任务按 milestone/terminal/invariant 完成公式判定；terminal freshness 和 required UNKNOWN/CONFLICTED/EXPIRED 不能被 FINISH 绕过。
- 公开投影包含目标/阶段、证据、置信度来源、UNKNOWN 原因、时效和允许探测；token 截断不能隐藏阻止 finish 的 required 目标。
- 四种结果独立保存：`execution_status`、`agent_finish_requested`、`fg_finish_verdict`、`environment_task_completed`。环境 reward 不提升 observed verdict，也不提前向 Actor 泄漏目标满足状态。
- FG 与现有 Knowledge Portfolio 明确分区，一次 prompt 构建各注入一次。既有业务技能加载不赋予其 audit 或 FG 写权限。
- 全局预算包含 Actor、Critic、Verifier、修复轮数和 probe；错误/超时/abort 都有可审计的终止原因。

**运行测试及退出条件：**

- 四个新增测试文件；用 fake model/environment/perception 替换外部依赖，但调用生产 `_run_single_trial` 的 v2 分流，不只直接调用 coordinator。
- 完整验证 plan→action→unknown→observe→satisfied→finish，以及 invalid→repair、replan、abort、timeout。
- 测试代码执行成功但任务失败、Actor 请求结束但 FG 不满足、FG 满足但环境任务失败，三者不互相覆盖。
- legacy/knowledge 相关回归通过；shadow 不暴露 FG，visible prompt 引用全部可解析。

## 9. P5：私有 Audit、Comparator 与无泄漏验收

**目的：** 获得可比较的双来源判断，同时证明正式路径不会获得 audit 帮助。

**创建或修改文件：**

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `cap/factual_grounding/audit_protocol.py`、`comparator.py` | 私有 adapter 协议、类型/单位/语义/时间对齐和 mismatch 分类 |
| 新增 | `cap/integrations/<selected_suite>/fg_audit_adapter.py` | 选定 suite 后确定实际路径，真实实现获准 audit producer |
| 新增 | `scripts/fg/compare_trace.py` | 私有离线对照与指标导出 |
| 修改 | `cap/factual_grounding/coordinator.py`、`persistence.py`、`config.py` | 三模式分流、私有保存、audit 错误隔离 |
| 新增 | `tests/fg/test_comparator.py`、`test_audit_modes.py`、`test_audit_noninterference.py` | 语义对齐、模式和差分隔离测试 |

**实现功能：**

- 先有 fake adapter 契约测试，再实现选定 suite 的真实 adapter；旧 G17 仅调用 `get_factual_grounding_audit`，不能当作真值 producer 已存在。
- 对齐 target/spec/semantic hash、实体版本、unit、event 和时间窗口；错位 stale、不支持 indeterminate；支持 audit_ambiguity。
- 私有 adapter 必须符合 suite constitution；若现行规则未授权私有评估入口，先明确扩展协议，禁止在 fix/skill/debug 代码中读取真值替代。
- held-out 的 audit 只追加私有结果；关闭、改变、延迟或失败均不改变公开动作调度、prompt、FG verdict、预算终止和 Skill 更新。私有审计资源不得挤占公开路径截止预算。
- comparisons、Coach 原文、私有对象 ID/路径/阈值/异常栈均不能进入 Actor 或 generated worker；审计指标只在离线报告中展示。

**运行测试及退出条件：**

- 三个新增测试文件；同目标不同 channel 相反值保存后产生 mismatch，observed 原记录不变。
- 对固定公开证据和 scripted Actor，分别注入 audit true/false/unsupported/timeout：要求 public prompt/hash、动作/探测序列、finish verdict、Skill manifest 完全一致。
- 在 P2 真实权限边界下运行访问攻击 fixture，验证 private 文件/IPC 不可读；检验 public 日志和错误文本无泄漏。
- fake 隔离验收通过后才能启用真实 held_out_audit；真实 adapter 未验收不得宣称双通道仿真完整可用。

## 10. P6：Development Audit Coach 与主动探测

**目的：** 让 UNKNOWN、公开冲突和开发差异转化为有预算的证据获取，而不是硬编码动作恢复表。

**创建或修改文件：**

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `cap/factual_grounding/audit_coach.py`、`diagnostics.py` | 独立私有上下文、结构化假设、修正类别和 proposal |
| 新增 | `cap/perception/probe_planner.py` | 基于公开能力的探测候选、代价/预期信息增益和安全前置条件 |
| 修改 | `cap/perception/probe_runner.py`、`cap/factual_grounding/coordinator.py` | probe 事件、重验证、预算和停止条件 |
| 新增 | `tests/fg/test_active_probes.py`、`test_audit_coach.py` | alternate-view 流程和开发权限 |

**实现功能：**

- UNKNOWN/公开冲突可触发公共 probe；仅 development_compare 可以消费 mismatch。两种触发来源分别记录，不混淆评估。
- Coach 提案经 allowlist/schema/预算校验，不能把 audit=true 翻译成 observed=true；重新观察产生新 event/evidence。
- 优先无运动视角切换；有运动 probe 需要安全前置条件、动作预算和中止策略；没有左腕相机时明确 unsupported，不伪造双臂能力。
- 失败、无信息、重复及超预算 probe 有确定停止规则；迟到结果不能更新已替换目标。
- 输出候选学习证据，保存原始 mismatch 和新观测；不自动注册或晋升任何 Skill。

**运行测试及退出条件：**

- 两个新增测试文件；主/腕视角共享遮挡→可用第三视角→新证据，和无第三视角→UNKNOWN/replan。
- held-out 使用会在调用时失败的 Coach spy，保证调用次数为 0；候选输出目录没有写入。
- task_repair 改变场景不能充当 verifier 改善证据；探测回路在预算内终止。
- 第一切片到此可以完成 contact 消歧候选流程，尚不宣称具备已学习的验证 Skill。

## 11. P7：Verification Skill 验证、审核、冻结与实际调用

**目的：** 将多次有效的验证方法沉淀为可迁移技能，复用现有知识门禁而不绕过其证据要求。

**创建或修改文件：**

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `cap/knowledge/verification_skill.py`、`verification_evidence.py`、`verification_review.py` | 方法 schema、公共触发条件、配对证据和专用 review 适配 |
| 按需修改 | `cap/knowledge/models.py`、`repository.py`、`integrity.py`、`cli.py` | 新类型不可变存储、引用验证、候选/审核/冻结 CLI |
| 按需修改 | `cap/knowledge/checkpoints.py`、`review_artifacts.py` | 复用 development 分区、哈希锁和审核工件；不放宽 principle gate |
| 新增 | `scripts/fg/evaluate_verification_skill.py` | 同冻结输入上的旧/新方法配对重放与跨任务评估 |
| 修改 | `cap/perception/capability_registry.py`、`verification_plan.py` | 从锁定 manifest 加载 approved 方法，实际调度其 verifier |
| 新增 | `tests/fg/test_verification_skill_gate.py`、`test_verification_skill_runtime.py` | 证据门禁和冻结后的实际调用 |

**实现功能：**

- VerificationSkill 是版本化验证方法，不是新 principle；candidate→reviewed→frozen/active 全部绑定准确内容和证据。
- 对相同冻结 sensor 输入配对评估，覆盖正例、负例、遮挡/UNKNOWN、多视角和不同场景；leave-one-task/family-out 属于 development 内部验证。
- 同时检查 false_satisfied、UNKNOWN、coverage、延迟和成本，不能用“全部返回 UNKNOWN”刷准确率。
- 冻结 Skill 不含私有 ID、真值常量、audit 触发器或 forbidden API；新方法若需新程序，必须先离线审查后注册，不能现场执行任意候选代码。
- 在线 trial 只读冻结 checkpoint；更新产生新 manifest 并用于后续开发/评估 campaign，既有 held-out 运行不刷新。
- 原有按函数频次的 `cap/skills/library.py` 不参与该晋升路径；业务技能演化与验证 Skill 证据分开。

**运行测试及退出条件：**

- 两个新增测试文件，以及现有 knowledge、knowledge CLI、preregistration、promotion 记录测试。
- 拒绝单例证据、held-out 来源、缺反例、缺配对比较、篡改报告、仅改变任务状态、无公开触发器和未审核 revision。
- 在 audit 完全关闭的新 development 输入上，冻结 Skill 被 resolver 命中并执行；证据中记录正确 method/version/checkpoint。
- 人工构造证据只证明 gate 机械行为；真实改善必须有独立记录的开发验证报告。未取得报告时保持 candidate，不能为完成施工伪造晋升。

## 12. P8：最终完整功能性测试与受控实验

**目的：** 用生产入口证明端到端功能，并将工程完成与真实性能收益分开验收。

**创建或修改文件：**

| 操作 | 文件 | 内容 |
| --- | --- | --- |
| 新增 | `tests/fg/test_end_to_end.py`、`test_trace_integrity.py` | 生产入口全流程及所有产物引用闭合 |
| 新增 | `tests/integrations/test_fg_v2_sim.py` | 选定 suite 的真实环境、感知、Actor 与 audit 集成测试 |
| 新增 | `scripts/fg/acceptance.py`、`report.py` | 验收清单执行、缺项失败、指标聚合、结论工件 |
| 新增 | `docs/fg-v2-acceptance-runbook.md` | preflight、命令、输出、失败恢复与逐项验收说明 |
| 新增 | `fg/experiment/preregistration-template.yaml`、`acceptance-matrix.yaml` | 待选择的 suite/task/seed、模型和方法版本、阈值及完整试验矩阵 |
| 修改 | `pyproject.toml` | 为 offline/权限/真实仿真测试增加明确 markers，避免默认启动 GPU |

### 12.1 L1：CPU / fake 全链功能矩阵

使用生产 trial v2 入口，替换外部模型、sensor、simulator adapter；不用 GPU 或真实 API key。至少覆盖以下用例，每项有可复查断言：

| ID | 输入/触发 | 必须看到的结果 |
| --- | --- | --- |
| F01 | 合法 PLAN→动态 held_by/above/contact→持续保持→finish | 首动作前 spec 已冻结；证据和时间窗口满足后完成 |
| F02 | 文本、破损/多 JSON、非法 decision 或坏 target | ProtocolError；零动作；无默认 FINISH；修复预算耗尽后终止 |
| F03 | 漏掉“不接触”、删 required、放宽阈值或换对象 | Critic/patch 拒绝；旧要求和证据保留 |
| F04 | 同一 predicate 更换合法实体/同义任务表达 | 可以生成不同合法目标，无任务 ID 查表依赖 |
| F05 | 缺能力、遮挡、false、方法异常 | unsupported/unknown/known-false/error 分别保留，不相互降级 |
| F06 | 首尾满足、中途违反或缺帧 | 连续目标不能 satisfied；显示窗口进度/缺口 |
| F07 | 抓取后放置的长任务 | 历史 milestone 保留；终态不要求继续抓持 |
| F08 | UNKNOWN/冲突→公共 probe→新证据 | 新 event 和 evidence；原测量不覆盖；预算内结束 |
| F09 | observed=false、audit=true | 双记录和 mismatch；公开 verdict 不被改写 |
| F10 | revision/单位/实体/tick 对不齐 | stale/indeterminate，不纳入有效 mismatch 分母 |
| F11 | held-out 切换 audit 值/延迟/失败 | 公开 hash、prompt、动作、探测、finish 和 Skill 状态不变 |
| F12 | development mismatch→Coach→probe→candidate | 标记 audit 影响；不自动晋升；公开输入无私有原文 |
| F13 | 合格开发证据→review→freeze→audit-off 新任务 | 固定方法真实被 resolver 调用；runtime 无在线更新 |
| F14 | 单例、held-out、篡改或 task_repair 证据 | promotion 拒绝，active manifest 不变 |
| F15 | 服务超时、迟到观测、abort、动作中断、重启 | 不污染新 revision；不重复未知动作；保存部分 trace 与明确状态 |
| F16 | 执行 rc=0、Agent finish、FG satisfied、环境成功互相不一致 | 四类结果独立，报告不把任何一项替代其余项 |
| F17 | legacy/off 与已有 Knowledge Portfolio | 旧路径回归通过；FG/knowledge 不重复注入或争夺配置 |
| F18 | trace 删除/篡改一个 evidence、错误 public hash | 验收器失败并指出断链；不得输出完整成功结论 |

### 12.2 L2：真实隔离边界测试

使用 P2 最终部署形式，不用 fake 权限对象代替 OS 隔离：

- 生成代码尝试读取 audit 文件、列出私有根、获取 env 引用、访问私有 IPC、经异常/日志外传；全部不能获得 audit 数据。
- 允许的 robot/sensor facade 仍正常工作；禁止测试通过只是因为所有 API 都不可用。
- audit 不影响公开资源截止时间、public hash 和终止原因；固定公开输入做 F11 差分重放。
- 记录 OS/container 配置、mount/network policy 和测试日志。任何依赖缺失为 blocked；泄漏事件数必须为 0。

### 12.3 L3：真实仿真完整功能测试

此级是“完整功能可用”的必要条件，不以 scripted Actor/fake vision 替代。执行前由用户选定 suite 和 experiment，依 runbook 固定任务、development/held-out seeds、模型、感知服务、阈值、预算、checkpoint、输出根并完成 preflight。双臂/左腕示例只作为能力需求，不能默认 LIBERO Franka 支持。

一个选定任务未覆盖所有机制时，使用明确冻结的机制任务集合，至少覆盖 holding/wrong-object、above/placement、contact/no-contact、遮挡/多视角、continuous window、UNKNOWN、audit mismatch。实际 suite 不支持的机制须增加适合的测试环境或标为未验收，不能静默跳过。

按以下顺序运行，每步单独保存结果：

1. 真实公开感知重放：记录 RGB/depth/calibration/robot state，复验 held_by/above/contact；人工盲标证据充分性及 UNKNOWN 合理性。
2. live Actor observed_only：Actor 自主生成 PLAN/目标，经 Critic 后执行、观察、probe、反馈和 finish；关闭 audit 也必须独立运行。
3. held_out_audit：加载同一冻结方法，以私有 audit 测量差异；Actor 不接收结果，不更新 Skill。
4. development_compare：在 development 事件上验证 mismatch→诊断→probe→candidate；保留失败和无信息 probe。
5. Skill 闭环：真实配对开发证据→独立审核→冻结→新的 development 场景 audit-off 调用→正式 held-out 只评价。
6. 离线完整性审计：逐一重建 turn→spec→event→sensor→measurement→verdict→projection；私有比较可另行追溯，公共链不依赖私有内容。

真实模型输出不要求跨运行完全一致；对已记录模型响应和 sensor bundle 的重放应可确定性复现公开状态与 verdict。

### 12.4 L4：泛化与性能评估

功能完整不代表性能恢复。至少比较：旧 `codex/merge` 固定 FG、v2 shadow（协议变化对照）、dynamic observed FG、development-learned frozen FG；需要时加 FG-off。旧分支的其它代码差异需记录，优先在相同 harness 下通过隔离 legacy adapter 形成匹配对照，避免将无关代码变更当 FG 收益。

在开始采集前冻结任务族划分、场景/物体变化、模型/prompt/API 版本、总 token/动作/探测预算、持续时间和容差、Skill checkpoint、统计方法及 non-inferiority margin；当前不填任意 seed 或性能阈值冒充预注册。

必须分别报告：

- 目标质量：parse success、required coverage、unsupported、Critic 误拒/漏拒；coverage 不能只用 Actor 自报的目标数作分母，需独立任务要求标签。
- 判断质量：precision/recall、false_satisfied、UNKNOWN、conflict、stale、可比较样本覆盖和 mismatch；unknown/unsupported 不算正确负例。
- 任务表现：独立环境 success、Agent finish、FG finish、false finish、不同 task family/场景的迁移差异。
- 成本：Actor/Critic/Verifier/Coach 的 token、感知延迟、probe 动作成本、总时长和超时。
- 方法迁移：旧/新 verifier 同输入配对差异、无 audit 触发能力、跨任务/场景表现和开发构建成本。
- 结论：置信区间、按任务聚类统计、样本缺失；开发 audit-influenced 轨迹与 held-out observed-only 结果分开。

若新方案增加 UNKNOWN/探测成本或降低成功率，应如实给出部分支持/不支持结论，不能通过删除困难任务或改变 held-out 标准使其通过。

## 13. 测试命令与运行约定

下列命令在对应测试文件/工具完成后执行；本次文档施工没有运行这些尚不存在的命令。从 `aspire/sim` 工作根运行，使用已按 README 配置的环境，不为文档工作安装依赖。

```bash
# 每阶段：选择本阶段 tests/fg/test_*.py，同时回归全部已有 fg 测试。
PYTHONPATH=../.. .venv/bin/python -m pytest tests/fg -m 'not integration' -q

# 保持已有知识工具链兼容。
PYTHONPATH=../.. .venv/bin/python -m pytest \
  tests/test_knowledge.py tests/test_knowledge_cli.py \
  tests/test_preregistration.py tests/test_knowledge_runtime.py \
  tests/test_record_skill_promotion.py -q

# 最终离线全链及工件完整性。
PYTHONPATH=../.. .venv/bin/python -m pytest \
  tests/fg/test_end_to_end.py tests/fg/test_trace_integrity.py -q

# 在实际隔离部署环境执行；P8 注册该 marker。
PYTHONPATH=../.. .venv/bin/python -m pytest \
  tests/fg/test_execution_boundary.py tests/fg/test_audit_noninterference.py \
  -m integration -q

git diff --check
```

真实仿真命令由 P8 runbook 根据选定 suite 的 Python、启动配置和已批准矩阵生成；不提供会暗中选择默认任务的“一键运行”。`scripts/fg/acceptance.py` 应要求显式 manifest、全新 output root 和 test level；缺少必要参数直接失败。

所有验收输出进入新的 `outputs/fg_v2/<campaign-id>/`，私有 audit root 独立授权。工件至少包含 `acceptance_manifest.json`、`acceptance_report.json`、`acceptance_report.md`、测试报告、逐任务 trace、配置/代码/方法 hash。每项状态为 passed/failed/blocked/not_run，禁止把 skipped 计为 passed。

## 14. 最终 Definition of Done

**第一切片完成：** P0–P5 和公共 alternate-view probe 通过；真实 selected-suite observed pipeline 与 Actor loop 连通；audit 只私有对照；不要求已产生可晋升 Skill。

**完整工程功能完成：**

- [ ] 所有阶段指定文件、生产接入点和对应测试存在；没有未接入主循环的孤立接口冒充交付。
- [ ] L1 F01–F18、L2 权限隔离和 L3 真实仿真机制覆盖全部通过，无必要项被跳过。
- [ ] Agent 动态产生目标，Critic 检查任务覆盖；系统不依赖任务级事实表。
- [ ] observed 来自可迁移公开证据，连续目标具备足够采样覆盖。
- [ ] 私有 audit 不进入 held-out 策略或知识更新；audit leakage 为 0。
- [ ] finish、FG、代码执行和环境成功独立保存，错误与 UNKNOWN 不会假完成。
- [ ] Verification Skill 在真实开发证据上完成审核和冻结，并在 audit-off 新场景实际调用。
- [ ] append-only trace、恢复、版本锁、预算和失败路径均可审计；旧代码路径回归通过。

**性能/研究验收完成：** L4 完整矩阵、独立标签、成本和统计报告已产出，明确判断动态 FG 是否改善泛化及任务表现。若真实证据或晋升条件未满足，应继续记录未完成项，不能用工程测试替代。

## 15. 提交与评审建议

每阶段作为独立可回滚提交单元，提交说明写清新增行为、验证命令和未通过项。默认保持新功能显式 opt-in；阶段完成后才逐项开放模式。回滚切换代码/配置和 frozen manifest，不删除历史 trace。

P0/P1 重点评审协议与目标规避，P2/P5 重点评审隔离，P3 重点评审测量语义和时序覆盖，P4 重点评审所有执行入口，P6/P7 重点评审 audit 间接影响和技能迁移，P8 重点评审真实机制覆盖与对照公平性。
