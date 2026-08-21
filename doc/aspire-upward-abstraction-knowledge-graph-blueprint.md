# ASPIRE Skill-Code-First 纵向抽象森林工程蓝图

> 版本：v0.3（Skill-code-first consolidation）
> 日期：2026-08-21
> 状态：Implementation-ready research blueprint
> 研究目标：验证高层抽象是否能有效抑制技能库扩张带来的检索、重复、冲突、剪枝和失效管理退化
> 适用代码：ASPIRE `680bad4df1dabe2463e20069e16f6978630fe1d7`
> 取代：[AKL v0.1 bottom-up blueprint](./aspire-akl-engineering-blueprint.md)

---

## 0. 方向修订

v0.1 的主要问题，是先从 `skill + atomic-op` 向下做结构化，再把 `principle` 放到未来阶段。它可以改善知识的可检索性和 API 失效治理，但不能直接回答本项目真正关心的问题：

> 当技能和经验持续增长时，能否通过向上归纳出少量高层原则，让检索、组合和维护围绕稳定抽象进行，而不是继续在线性膨胀的叶子库中工作？

v0.3 把研究对象改为“先积累、再向上抽象”。顺序是不可交换的：

```text
task-specific skill-code instances
          |
          | 达到 consolidation checkpoint 后评估重复性
          |
          v
    canonical reusable skills
          |
          | 归纳共同不变量、选择准则和失败边界
          v
 principle / sub-principle tree
```

禁止从单条 findings、单段代码或第一次 skill 生成直接产生 principle。Principle 只能由冻结的一批 skill-code instances 经重复性审计后产生。

知识库的主组织单位是“纵向能力树”：

```text
localization tree    grasp tree    transport tree    manipulation tree
       \                |              |                    /
        +---------------+--------------+-------------------+
              cross-tree dependency / sequence / conflict graph
```

每棵树在内部把多个 task-specific code instances 整合为 canonical skills，再向上提炼 principle。树之间才使用 graph edges 表达跨能力协作。

运行时则反向工作：

```text
task context
    |
    v
select relevant vertical trees and retrieve applicable principles
    |
    v
check exceptions / contradictions
    |
    v
selectively descend to a minimal set of skills
    |
    v
task portfolio -> actor
```

权威结构采用“纵向抽象森林 + 跨树 overlay graph”：每个能力族内部是一棵有主父节点的抽象树，树之间用 typed edges 表达依赖、顺序、冲突和例外。这样既保留用户希望的纵向整合，又不强迫跨能力关系塞进单棵树。

---

## 1. 对研究思路的批判性结论

### 1.1 合理之处

高层抽象确实可能改善四类规模化问题：

| 问题 | 高层抽象可能提供的机制 |
|---|---|
| 检索 | 先在较小的 principle surface 上决策，再下钻少量叶子 |
| 去重 | 多个表面不同的 skill 共享一个 common invariant，不必重复把 invariant 注入 prompt |
| 剪枝 | 先判断 principle 是否仍必要，再分析其支持子图；也可保留 principle、退役冗余实现 |
| 失效 | skill/API 失效沿 `instantiates/operationalizes` 向上汇总，定位哪些 principle 失去充分支持 |
| 冲突 | 冲突可以发生在 principle 声明、scope 或 exception 层，而不必从长文本中发现 |
| 迁移 | principle 可以跨 task family 复用，具体 skill 保留 embodiment-specific 实现 |

其核心价值不是增加五层类型，而是形成一个压缩映射：

```text
many local procedures
    -> fewer explicit decision rules
    -> selective access to local procedures
```

### 1.2 不能直接成立的部分

需要收紧以下主张：

1. 高层抽象不会自动减少原始知识量。为了可追溯，叶子 evidence 和 skill 仍需保留；总存储甚至会增加。
2. 抽象不必然降低图复杂度。如果每个 principle 与大量节点互连，edge 数和维护成本可能同样爆炸。
3. 高层并不天然更正确。错误 principle 会成为高连接度错误 hub，比单个错误 skill 传播更广。
4. Tree 不足以表达交叉抽象、例外和冲突；强制单父节点会制造错误归类。
5. “总结得更短”不等于“形成了 principle”。普通 summary 也能减少 token，必须用对照实验隔离。
6. principle 命中并不等于 operational usefulness。若不能可靠下钻到可执行 skill，Actor 只得到空泛建议。
7. 低层技能数量可能仍是线性的。真正应观察的是 active retrieval surface、维护检查量和性能退化斜率。

### 1.3 最危险的失败方式

错误抽象通常表现为：

- 把只在一个场景成立的参数提升为通用规律；
- 只归纳成功案例，不寻找反例；
- 丢失触发条件、适用域和 contraindication；
- 将 alternative implementations 错误合并成唯一规则；
- principle wording 很宽，导致几乎所有任务都命中；
- principle 成为 retrieval hub，向下展开整库；
- support evidence 大量重复但不多样，造成虚假的高置信度；
- 子节点失效后，principle 仍显示 validated；
- 上层声明相互冲突，但只在运行时由 Actor 自行调解。

### 1.4 可辩护的研究命题

本项目不试图证明“高层抽象让知识库不增长”，而验证：

> 在 skill-code instances 持续积累时，经重复性审计形成的纵向 principle trees 与跨树关系图，能否让任务所需的活跃知识集合、维护检查量和性能退化速度显著小于 flat、仅去重或仅分块的知识库，同时保持任务成功率不劣化。

这是可以被实验反驳的命题，也是蓝图的唯一主目标。

### 1.5 当前证据规模的限制

本地 LIBERO 共享库目前只有四个正文文件、431 行，单凭当前规模不足以证明“知识爆炸”。因此：

- 小规模真实库只能用于 schema、faithfulness 和 retrieval sanity check；
- synthetic stress 只能验证机制在受控扰动下是否成立，不能单独支持真实长期扩张的外部有效性；
- 主要结论必须同时依赖 organic snapshots 或后续真实 accumulation；
- 如果 organic library 的规模和多样性不足，论文结论应降级为“受控规模实验中的证据”，不能泛化为长期开放世界知识管理结论。

### 1.6 现有研究能支持到哪里

- [ASPIRE](https://arxiv.org/abs/2607.00272) 本身把 retrieval、ranking、pruning、re-validation 和长期 memory management 留作开放问题，说明问题真实存在，但没有证明 principle 是答案；
- [SkillRet](https://arxiv.org/abs/2605.05726) 表明大规模真实技能检索仍是独立难题，支持建立规模化 retrieval benchmark；
- [Graph of Skills](https://arxiv.org/abs/2604.05333) 支持 dependency-aware structural retrieval，但其结果不能直接等价为“向上 principle 抽象有效”；
- [HiSkill](https://arxiv.org/abs/2607.25853) 和 [SkillOps](https://arxiv.org/abs/2605.13716) 支持 typed graph、grounding 与 library maintenance 的价值，但不能替代本项目的 abstraction ablation；
- [SkillFlow](https://arxiv.org/abs/2604.17308) 提醒高使用率不等于高效用，错误知识可能造成 negative transfer，正是 principle hub 必须被严格约束的原因。

因此，现有工作提供设计动机和风险证据，但“向上抽象能否改变知识库规模退化斜率”仍需要 ASPIRE-specific 因果实验。

---

## 2. 研究假设与反证条件

### H1：检索表面压缩

随着 skill-code instance 数 `N_code` 增长，tree-first 检索的 actor context、候选评估数和 irrelevant exposure 的增长斜率低于 flat/canonical-skill retrieval。

反证：principle 数量与 `N` 同速增长，或下钻后仍需要读取接近全部叶子。

### H2：任务性能抗规模退化

在相同模型、任务、token budget 和 skill-code corpus 下，principle-tree 组的任务成功率随 `log(N_code)` 的下降斜率更平缓。

反证：收益只发生在小库，或在大库因错误抽象出现更强 negative transfer。

### H3：重复治理

新增语义重复和轻微变体时，principle graph 能把重复吸收到既有抽象下，减少 actor 可见的重复建议和人工 merge 检查量。

反证：重复只是从 code instances 转移为重复 canonical skills/principles，或者整合器持续创建近义上层节点。

### H4：冲突与失效局部化

当 code instance、canonical skill、API 或环境假设失效时，forest/graph 可以计算受影响 principle 和任务族，所需审查范围小于全库扫描，并且不会让 unsupported principle 继续进入 portfolio。

反证：高层 hub 造成更大的 blast radius，或支持聚合掩盖了关键失效。

### H5：例外与反例是必要机制

显式 exceptions、counterevidence 和 falsifiers 能显著减少 principle 造成的 negative transfer。

反证：移除这些字段不影响结果，说明 principle schema 可能过度设计；或即使保留也不能被 gate 正确执行。

### H6：收益来自抽象，而非仅来自短文本

在相同 token budget 和相同重复簇下，带 decision rule 和向下 grounding 的 principle tree 优于普通 summary tree，并且跨树 overlay graph 提供独立的组合收益。

反证：canonical-skill dedup 或 summary tree 与 principle tree 等价，说明收益主要来自去重/压缩，不来自 principle 抽象。

---

## 3. 知识本体：向上而不是向下

### 3.1 MVP 节点

v0.3 把四类对象作为研究核心，并严格区分“原始代码实例”和“去重后的 canonical skill”：

| 类型 | 产生时机 | 作用 | 是否直接进入 Actor |
|---|---|---|---|
| `skill-code-instance` | 每次 task 产生可复用代码后 | 原始、不可变的 task-specific 实现和结果 | 否 |
| `skill` | 重复性审计确认一簇代码实现同类能力后 | 去重、参数化的 canonical reusable skill | 下钻或 fallback 时 |
| `principle` | 多个 canonical skills 再次显示共同决策规律后 | 树中的高层不变量、选择规则和边界 | 是，优先进入 |
| `evidence` | trial/findings/promotion 发生时 | 支持、反驳和 provenance | 默认不进入 |

产生顺序只能是：

```text
skill-code-instance -> repeated cluster -> canonical skill
canonical skills    -> repeated invariant -> principle
```

`atomic-op` 保留为 grounding catalog，但不是首个实验的主要自变量；`strategy`、`method` 延后。

### 3.2 Principle 的严格定义

Principle 不是 topic、标签、摘要或口号。它必须是可执行决策能使用的规则：

```text
When <applicability / trigger>,
prefer | avoid | require <decision>,
because <invariant / causal rationale>,
expect <observable consequence>;
except when <exceptions>;
it is falsified when <falsifiers>.
```

例子：

```text
When a manipulation task contains sequential subtasks and arm configuration
drifts between them, return to a known home configuration and re-observe before
starting the next subtask, because stale camera geometry and accumulated joint
limits make downstream localization and IK unreliable; except when returning
home would collide with a currently grasped or constrained object.
```

这比“长任务要回 home”多出 trigger、why、expected effect 和 exception，因而可以验证和拒绝。

### 3.3 Principle 不承担的职责

- 不保存完整机器人控制代码；
- 不替代具体 skill 的参数、API 和 validator；
- 不从单个成功 seed、单个 skill-code instance 或未达到 consolidation checkpoint 的流式数据直接生成；
- 不声称超出 support scope 的普适性；
- 不自动决定安全关键动作；
- 不因 wording 更抽象就获得更高 rank。

### 3.4 纵向树内归纳、树间成图

每个 canonical skill 必须选择一个 primary vertical capability，例如：

- `localization`：观察、分割、消歧和三维定位；
- `grasp`：抓取姿态、接近、夹爪和抓取验证；
- `transport`：lift、transit、waypoint 和 placement；
- `manipulation`：drawer、knob、push、slide 和连续接触；
- 后续可增加 `long-horizon-control`、`safety` 等纵向树。

树内：

```text
root principle
  -> narrower principle / sub-principle
      -> canonical skill
          -> skill-code instances
```

树间：

- `localize` skill 可以被 `grasp` skill require；
- `grasp-preservation` constraint 可以约束 transport；
- long-horizon sequencing 可以连接多棵树；
- safety/exception 可以跨树生效。

因此 source of truth 不是一棵全局树，也不是完全自由的 DAG，而是：

1. 树内 `parent` 边构成有根 forest，每个非根抽象节点只有一个 primary parent；
2. 树间 relation edges 构成 overlay graph；
3. 跨树语义复用通过 reference edge 表达，不复制 skill-code instance；
4. overlay graph 不能改变节点在纵向树中的 primary identity。

一个可能的 `transport` 纵向树：

```text
transport (structural root; not actor-visible)
├── principle: preserve grasp while increasing clearance
│   ├── principle: escape laterally before vertical lift in clutter
│   │   ├── skill: safe-lateral-escape
│   │   │   ├── code-instance: goal-swap/task-03/attempt-2
│   │   │   └── code-instance: object-swap/task-11/attempt-1
│   │   └── skill: obstacle-aware-waypoint-escape
│   └── skill: lift-then-transit-in-open-space
└── principle: approach placement from a collision-safe direction
    ├── skill: vertical-placement-approach
    └── skill: staged-descent-and-release
```

这里的 root 是能力容器，不是 principle。只有重复性与 promotion gate 充分时才增加内部 principle；否则 canonical skills 直接挂在 root 下。

---

## 4. Forest + Overlay Graph 模型

### 4.1 核心关系

树内存储四种边/引用：

| 关系 | 方向 | 含义 |
|---|---|---|
| `parent-of` | principle → principle/skill | 纵向树中的唯一 primary abstraction parent |
| `instance-of` | skill-code-instance → skill | 原始代码实例属于哪个 canonical skill |
| `supported-by` | principle/skill → evidence | 正向证据 |
| `contradicted-by` | principle/skill → evidence/node | 反例或冲突声明 |

查询层可物化 `children-of` 和 `instances` 反向视图，不重复写入 source of truth。Principle 的 operational descendants 由 tree path 计算，不另存一套可能漂移的成员列表。

### 4.2 后续关系

跨树 overlay graph 在主实验中使用：

- `requires`：skill → skill/atomic-op；
- `can-follow`：一个纵向 skill 可在另一个之后执行；
- `exception-to`：节点在明确 guard 下例外于另一棵树的 principle；
- `contradicts`：跨树规则在重叠 scope 下冲突。

第二阶段再增加：

- `alternative-to`：同 goal 的不同实现；
- `recovers-with`：失败恢复；
- `supports`：非 primary tree 的交叉语义支持。

实验必须分别比较 tree-only 与 tree+overlay，防止把跨树组合收益误记为上层 principle 收益。

### 4.3 图不变量

- `parent-of` 在每个 vertical capability 内必须形成 tree/forest；
- 每个非根 principle/skill 只有一个 primary tree parent；
- 每个 skill-code instance 只能 `instance-of` 一个 canonical skill revision；
- 每棵树可有一个不进入 Actor 的 structural root container；证据不足时 canonical skills 可以直接挂在 container 下，不强行制造 principle；
- principle 至少有两个不同 logical children，validated 至少三个；
- `parent-of` 与跨树 `exception-to` 不能在同一 scope 下无 guard 冲突；
- support 和 contradiction evidence 不计入 abstraction depth；
- 每个 active principle 必须能沿 tree path 到达至少一个 active canonical skill 和可追溯 code instance；
- 每个 actor-visible principle 必须携带 exception/falsifier 信息；
- child 被 deprecated 不自动删除 parent，但触发 support sufficiency 重算；
- 一个 principle 的下钻 fan-out 有上限，超过阈值必须 split 或增加中间 principle；
- 图中所有路径、版本和证据可精确锁定到 snapshot。

### 4.4 Forest views

纵向树是权威组织结构，不再只是 UI projection。系统额外生成：

1. `vertical-forest`：所有能力树及节点数量、深度和 compression；
2. `task-family-view`：以 task family 过滤后的 forest；
3. `overlay-view`：仅显示跨树 requires/can-follow/exception/conflict；
4. `lineage-view`：从 principle 一直追到 code instances 和 evidence。

任何 task-family 或 overlay view 的编辑不能反向改写 primary vertical tree。

---

## 5. Principle Schema

### 5.1 文件示例

```yaml
schema_version: 2
id: principle.libero.long-horizon.reobserve-after-state-reset
kind: principle
version: 1.0.0
status: candidate
title: Re-observe after configuration-changing reset
summary: Reacquire visual state after returning home between subtasks.

rule:
  when:
    all:
      - {fact: task.remaining_subtasks, op: gt, value: 0}
      - {fact: robot.configuration_changed, op: eq, value: true}
  decision:
    mode: require
    action: reacquire_observation_before_next_localization
  because:
    invariant: Perception-dependent geometry must match the current camera and robot state.
  expect:
    - {fact: perception.geometry_fresh, value: true}

scope:
  suites: [libero]
  task_families: [long-horizon-pick-place]
  embodiments: [franka]
  confidence_boundary: Do not infer applicability to constrained in-hand manipulation.

exceptions:
  - id: constrained-object-collision-risk
    when:
      any:
        - {fact: state.object_grasped, op: eq, value: true}
        - {fact: state.object_constrained, op: eq, value: true}
    response: defer-home-or-use-local-reobservation

falsifiers:
  - Re-observation after reset does not reduce stale localization or IK failures.
  - The rule lowers task completion by interrupting necessary continuous contact.

abstraction:
  common_core: Re-establish observation-state consistency after a major configuration change.
  preserved_variations:
    - home pose differs by task
    - localization backend may be SAM3 or another perception system
  excluded_details:
    - object-specific prompts
    - hardcoded poses

quality_policy:
  min_supporting_skills: 3
  min_task_families: 2
  max_exception_rate: 0.30
  max_operational_fanout: 12
  leave_one_family_out_required: true

provenance:
  proposal_method: contrastive-abstraction
  source_snapshot: snapshot-N20
  created_at: 2026-08-21T00:00:00Z
  created_by: coordinator
```

### 5.2 结构字段

| 字段 | 必需 | 用途 |
|---|---:|---|
| `rule.when` | 是 | applicability gate |
| `rule.decision` | 是 | prefer/avoid/require 的具体选择 |
| `rule.because.invariant` | 是 | 共同不变量，不等同于解释性修辞 |
| `rule.expect` | 是 | 可观察结果 |
| `scope` | 是 | 防止过度泛化 |
| `exceptions` | 是，可为空 | 负向边界 |
| `falsifiers` | 是 | 明确如何推翻 principle |
| `abstraction.common_core` | 是 | children 的共同部分 |
| `preserved_variations` | 是 | 不应被上层抹平的差异 |
| `quality_policy` | 是 | promotion 和 hub 控制 |
| `provenance` | 是 | 可追溯性 |

### 5.3 Materialized metrics

以下指标由图和 evidence 计算，不手写进 principle revision：

```python
class PrincipleMetrics(BaseModel):
    support_count: int
    support_task_families: int
    support_diversity: float
    contradiction_count: int
    exception_rate: float
    operational_fanout: int
    abstraction_depth: int
    canonical_skill_coverage: float
    compression_ratio: float
    last_validated_at: datetime | None
    support_sufficiency: Literal["sufficient", "weak", "broken"]
```

不能用重复 trials 虚增 support diversity。多样性按 task family、failure signature、scene 和 implementation 去重后计算。

### 5.4 Principle quality dimensions

- faithfulness：是否保留 children 的共同语义；
- coverage：覆盖多少 intended children；
- purity：children 是否真的共享同一 decision rule；
- discriminativeness：是否能拒绝不适用任务；
- grounding：能否下钻到实际 skill；
- falsifiability：是否存在可执行或人工判定的反证条件；
- compression：减少多少重复 actor-visible content；
- transfer：对未参与归纳的 task family 是否有益；
- blast radius：错误时影响多少 task/skill。

任何单一 global confidence 都不能取代这些维度。

### 5.5 Consolidation Policy

Principle 生成由冻结 checkpoint 和显式门槛触发，而不是每次 promotion 触发：

```yaml
schema_version: 1
policy_id: libero-vertical-consolidation-v1
checkpoint:
  every_new_code_instances: 20
  min_distinct_tasks: 5
repetition_audit:
  min_cluster_instances: 3
  min_cluster_tasks: 3
  min_successful_instances: 2
  max_single_task_share: 0.50
principle_promotion:
  min_canonical_skills: 3
  min_task_families: 2
  leave_one_family_out_required: true
```

这些数字是首版默认值，不是自然定律。实验预注册后需要做 sensitivity analysis，例如 checkpoint 为 10/20/40、cluster threshold 为 2/3/5，确认结论不是某个门槛的偶然产物。

如果 checkpoint 到达但没有满足重复门槛的 cluster，正确结果是“不产生新的 canonical skill/principle”，而不是降低标准强行抽象。

---

## 6. 向上归纳流水线

### 6.1 输入

- Stage 1 产生的 task-specific skill code；
- 与每段 code 对应的 `findings.md`、task、seed、outcome 和 source hash；
- 当前四个 LIBERO shared skill 文件中的历史 operational patterns；
- promotion ledger 和 source hashes；
- development trial outcomes；
- 已知失败模式、反例和 task scope；
- 现有 snapshot-N0/N5/... 的库演化轨迹。

held-out seeds 不参与当前 snapshot 的 principle 生成、修改或 ranking。

### 6.2 Step A：积累 SkillCodeInstance

每发现一段可复用代码，先保存原始实例，不立即抽象：

```yaml
id: skill-code.libero.goal-swap.task-17.home-reset.v1
kind: skill-code-instance
vertical_capability: long-horizon-control
task: libero_goal_swap/task-17
source_code_path: outputs/.../fix_code.py
source_code_sha256: sha256:...
code_span: {symbol: reset_between_subtasks}
goal: restore a known robot configuration between subtasks
observed_effect: stale localization failures reduced
development_outcomes:
  successes: [51, 52, 54]
  failures: [53]
provenance: {...}
```

Code instance 不要求通用，也不进入 Actor；它是后续重复性分析不可丢失的叶子。

这里的 instance 不是“每个 seed 计一次”，而是一个具有明确 goal/trigger 的函数或代码块：

- 相同 code hash 在多个 seeds 执行，只形成一个 logical instance 和多个 outcome events；
- 整个 task program 需要先按函数、API trace 或人工标注切出可复用代码块；
- 成功或明确改善 failure 的实例可以成为正向 support；
- 执行失败的变体仍保留，但只能作为 counterevidence/failure variant；
- 没有执行结果或 source hash 的片段不进入 repetition support count。

### 6.3 Step B：冻结 checkpoint 并做重复性审计

只有达到 ConsolidationPolicy 后才运行。重复性不等于文本或代码相似，审计使用多视角：

1. **Code structure**：AST/调用序列、控制流和 API usage fingerprint；
2. **Intent/contract**：goal、trigger、precondition、effect；
3. **Behavior**：在哪类 failure 上改善了哪些 observable outcomes；
4. **Variation**：不同对象、参数和 task 中哪些部分变化、哪些保持；
5. **Evidence diversity**：是否来自不同 task/seeds，而非同一代码复制多次。

候选 pair/cluster 的审计分数可写成：

```text
repeatability =
  0.25 * code_structure_similarity
+ 0.30 * contract_similarity
+ 0.25 * behavioral_effect_similarity
+ 0.20 * evidence_diversity
```

该分数只负责候选排序，不能自动判定等价。审计输出：exact duplicate、same canonical skill、same principle/different skill、alternative、conflict 或 unrelated。

### 6.4 Step C：提炼 CanonicalSkill

把确认重复的一簇 code instances 提炼为 canonical skill：

```yaml
id: skill.libero.long-horizon.home-between-subtasks
kind: skill
vertical_capability: long-horizon-control
goal: reset robot configuration before the next subtask
trigger: remaining subtasks and accumulated configuration drift
operation_template: goto_home_joint_position then reacquire state
parameters:
  invariant: [reset-before-next-subtask]
  variable: [home-configuration, observation-backend]
effect: known configuration restored
contraindications: [object currently constrained]
instances:
  - skill-code.libero.goal-swap.task-17.home-reset.v1
  - skill-code.libero.object-swap.task-04.home-reset.v2
scope: {...}
provenance: {...}
```

Canonical skill 必须保留 instance membership、共同 code skeleton 和被参数化掉的变化。Exact duplicates 可以折叠显示，但原始 code instance 仍保留。

### 6.5 Step D：评估跨 CanonicalSkill 的重复 invariant

在同一 vertical capability tree 内，对 canonical skills 再做第二层重复性分析：

- goal/effect 相似；
- trigger/failure signature 相似；
- code implementation 不同但保持同一决策规则；
- coordinator 在 consolidation review 时显式标注；
- 同一段通用 rationale 重复出现；
- 在多个 task family 中采用不同实现解决相同 failure class。

这一阶段的候选簇至少包含多个 canonical skills，而不是多个近乎相同的 code instances。只有 instance-level 重复时，最多生成 canonical skill，不能越级生成 principle。

### 6.6 Step E：对比式 Principle 抽象

对每个候选簇同时回答：

1. 哪一条 decision rule 对所有支持节点成立？
2. 哪些字段只是局部实现，必须保留在 child？
3. 哪些 canonical skills 实际是 alternative，而不是同一原则实例？
4. 哪些相似节点包含反例？
5. 如果移除对象、数值、API 名称，剩余 statement 是否仍有可操作性？
6. 哪种任务不应使用这个 principle？

输出 principle candidate、vertical parent/child placement、exceptions、counterevidence 和 unresolved questions。

### 6.7 Step F：反例搜索

在 promotion 前主动检索：

- 相同 trigger 但相反操作；
- 相同 operation 但失败 outcome；
- scope 邻近但 embodiment/task family 不同的记录；
- children 中被隐藏的 task-specific constants；
- principle 可能导致的 forbidden action；
- existing principle conflicts。

没有反例不代表正确；必须记录搜索范围和“未发现”的边界。

### 6.8 Step G：纵向树放置与跨树关系审查

候选 principle 可：

- 成为同一 vertical tree 内多个 canonical skills 的 parent；
- 成为现有 principle 的 child/sub-principle；
- 与现有 principle 合并；
- 被标记为 overlapping/conflicting；
- 因证据不足继续保持未激活 proposal。

树放置必须报告 primary parent、深度、fan-out、覆盖和潜在环。若该 principle 与其他纵向能力有关，只增加 overlay reference，不改变其 primary tree。

### 6.9 Step H：promotion gate

validated principle 至少满足：

- ≥3 个非重复 supporting skills；
- ≥2 个 task families；
- development partition 的 leave-one-family-out 检验；
- 至少一个被主动审查的 exception 或明确的空例外理由；
- 至少一个 falsifier；
- 可下钻到 active operational skill；
- 相比直接注入 children 有实际 token/redundancy compression；
- 无 unresolved high-severity contradiction；
- human/coordinator review；
- exact provenance 和 rollback。

只有一个 task family 的抽象可以保存为 narrow-scope `candidate`，但不能晋升为 v0.3 的 validated principle，也不能宣传为“跨技能通用原则”。

### 6.10 自动化边界

LLM 可以帮助：聚类说明、共同点提取、反例候选和 proposal drafting。

LLM 不可以单独：授予 validated、隐藏 counterevidence、删除 children、修改 held-out partition、把自然语言置信度当成 evidence。

---

## 7. 自顶向下检索

### 7.1 三层索引

维护三个独立检索面：

- principle index：statement、trigger、decision、scope、exceptions、falsifiers；
- canonical skill index：goal、failure signature、operation template、scope；
- code-instance index：AST/API fingerprint、task、outcome、provenance，仅供审计和 fallback explanation。

主路径先选择 relevant vertical trees，再从树根/中层 principle 下钻到 canonical skills。Code-instance index 不直接向 Actor 返回原始代码，除非实验组明确测试 flat-code baseline。

### 7.2 运行算法

```text
1. Normalize TaskContext
2. Select relevant vertical capability trees
3. Retrieve top-P principles within those trees
4. Applicability + exception + contradiction gate
5. Rank applicable principles
6. Descend each selected tree to minimum sufficient canonical skills
7. Traverse cross-tree overlay only for required sequence/dependency/exception
8. Run canonical-skill fallback for uncovered requirements
9. Pack tree-first portfolio under fixed token budget
10. Record tree path, overlay edges and rejected nodes
```

默认参数：`P=8`，最终 principle ≤4，每个 principle 最多下钻 3 个 skill，总 skill ≤8。参数进入 compiler version。

### 7.3 Minimum sufficient descent

下钻不是展开全部 children。选择满足：

- scope 与当前任务匹配；
- operation/API 可用；
- 合起来覆盖 task requirements；
- 保留必要 exception/recovery；
- 同一 invariant 下避免重复 implementation；
- 在预算内优先实例证据更多样、表述更短的 canonical skill。

### 7.4 Fallback

如果：

- 没有 applicable principle；
- principle support broken；
- 下钻无法覆盖任务需求；
- 发生 unresolved conflict；

则运行 canonical-skill-only retrieval。fallback 是重要观测指标，不应被视为系统错误，也不能静默隐藏。

### 7.5 Tree-first Portfolio

Actor 看到：

```markdown
## Governing principles

### Re-observe after configuration-changing reset
When: ...
Do: ...
Why: ...
Exception: ...

## Operational patterns selected for this task

### Home between subtasks
Trigger: ...
Procedure: ...
Validator: ...

## Explicitly rejected guidance

- Continuous-contact exception applies: false
- Scene-specific hardcoded waypoint: out of scope
```

完整 evidence 不进入 prompt，只保留短 provenance ref。

---

## 8. “知识库爆炸”的操作性定义

不能只用文件行数或节点数定义爆炸。至少测量六个维度：

### 8.1 Raw size

```text
N_code, N_skill, N_principle, N_tree, N_overlay_edge, bytes, tokens
```

高层抽象不要求 `N_code` 下降。它应该使 `N_skill << N_code`，并在重复真实存在时使 `N_principle << N_skill`；如果两个比例都接近 1，说明没有形成有效 consolidation。

### 8.2 Active retrieval surface

单任务检索、gate、rank 和注入的节点数/token：

```text
S_active(task, N) = evaluated principles + descended leaves + context tokens
```

这是首要指标。

### 8.3 Redundancy exposure

Actor context 中具有同一 normalized decision rule 的重复建议比例。

### 8.4 Maintenance surface

完成一次 promotion、失效、冲突修复或剪枝需要 review 的节点/边/文本数量和人时。

### 8.5 Degradation slope

success、recall、latency、token 随 `log(N_code)` 的变化斜率，而不是只看某一个规模点。

### 8.6 Negative-transfer surface

因错误或过宽知识导致的任务失败比例、影响 task families 和最大 blast radius。

### 8.7 管理有效的判据

只有以下条件同时成立，才能说 principle 抑制了爆炸：

1. raw skill-code instance library 可增长；
2. active surface 和 maintenance surface 的增长显著更慢；
3. task performance 的退化斜率更平缓或保持不变；
4. negative transfer 不增加；
5. abstraction 自身的构建/维护成本没有抵消收益。

---

## 9. 因果实验设计

### 9.1 处理组与强对照

| 组 | 知识组织与检索 | 控制目的 |
|---|---|---|
| A Flat-Code | 原始 skill-code instances/当前整库 | ASPIRE 近似现状与未整合基线 |
| B Canonical-Skill | 只做重复审计和 canonical skill 去重 + BM25 | 控制“重复整合本身” |
| C Summary-Tree | 使用相同 vertical clusters，内部节点为普通摘要 | 控制“树 + 文本压缩” |
| D Principle-Tree | 每个纵向能力族形成 rule/scope/exception tree，无跨树 overlay | 测 principle tree 本身 |
| E Principle-Forest+Graph | D 加 requires/can-follow/exception/conflict overlay | 测完整主方案与跨树组合增益 |
| F Principle-No-Exception | E 去掉 exception/counterevidence gate | 验证安全边界必要性 |
| G Oracle-Principle | 少量专家人工 principle | 估计抽象质量上限，可选 |

所有组使用相同 skill-code instances、consolidation checkpoints、任务、模型、执行 API 和总 token budget。B–F 必须在同一个冻结 checkpoint 上构建，不能让 principle 组看到更多后续 skill code。

为避免“重复聚类质量”成为混杂变量，B–F 使用相同的 code-instance clusters 和 canonical skills；C–F 使用相同 vertical tree membership。C 只输出普通摘要；D 使用 principle rule；E 只比 D 多 overlay graph；F 与 E 选择相同 principles/skills，但移除 exception/counterevidence，并把空出的预算用于更完整的 canonical-skill procedure。

### 9.2 Library scale

使用两类规模序列：

#### Organic snapshots

ASPIRE 已有 snapshot-N0/N5/... 的演化轨迹。它们反映真实 acquisition，但规模点较少、内容分布同时变化。

#### Controlled stress libraries

从真实 skill-code instances 构建 1x、4x、16x、64x，并在每个预注册 checkpoint 独立运行 repetition audit：

- paraphrase duplicate；
- same principle / different implementation；
- narrow-scope specialization；
- contradictory advice；
- stale API pattern；
- irrelevant domain distractor；
- rare but safety-critical exception；
- over-broad false principle。

Stress data 必须标明 synthetic，不与真实成功率证据混合。

### 9.3 任务划分

- abstraction-build：只使用 development evidence；
- principle-validation：development 中 leave-one-task-family-out；
- frozen evaluation：LIBERO-Pro Long held-out，禁止回写；
- adversarial evaluation：专门触发 exceptions、conflicts 和 stale nodes；
- maintenance simulation：删除/变更叶子和 API 后测影响定位。

### 9.4 固定变量

- 同一 LLM/model/version/temperature；
- 同一 task prompt 除知识上下文外的全部文字；
- 同一 simulator/API/perception backend；
- 同一 task seeds；
- 同一总 token budget；
- 同一 skill-code source checkpoint；
- 同一最大运行/重试次数；
- 同一 retrieval lexical normalization；
- 同一 held-out contamination guard。

### 9.5 主指标

#### 任务层

- success rate / reward；
- crash、forbidden API、negative transfer；
- development 与 held-out 分开报告。

#### 检索层

- relevant principle precision/recall；
- relevant canonical-skill recall；
- requirement coverage；
- irrelevant exposure；
- fallback rate；
- context tokens；
- p50/p95 compile latency。

#### 抽象层

- principle faithfulness/purity；
- support diversity；
- compression ratio；
- exception precision/recall；
- grounding success；
- operational fan-out；
- unsupported principle rate。

#### 维护层

- duplicate triage precision；
- nodes reviewed per promotion；
- invalidation impact-analysis recall；
- false affected nodes；
- stale/conflict escape rate；
- review time；
- tree/overlay edits per new code instance。

### 9.6 统计模型

核心不是单点均值，而是 treatment 与规模的交互：

```text
metric = beta0
       + beta1 * log(N_code)
       + beta2 * treatment
       + beta3 * treatment * log(N_code)
       + task/random effects
       + error
```

`beta3` 衡量方法是否改变规模退化斜率。对 success 使用分层 logistic/mixed model 或按任务 bootstrap；同时报告 effect size 和置信区间。

### 9.7 预注册判断规则

支持主命题需同时满足：

- D 相对 B/C 的 active-context slope 显著更平缓，证明 principle tree 的增益；
- E 相对 D 在跨能力任务上进一步改善 requirement coverage 或 task success，证明 overlay graph 的增益；
- D/E 的 held-out success 对 B 非劣，margin 3 个百分点；
- D/E 的 irrelevant/redundancy exposure 更低；
- stale/conflict hard violation escape 不高于 B；
- E 的总维护成本（含 principle 构建）在中大规模低于 B；
- F 显著更差或更易 negative transfer，支持 exceptions 的必要性；
- 优势在至少两个 library scale 和多个 task families 存在，而非单点偶然。

如果 B 已获得全部收益，只能得出“重复整合有效”；如果 C 与 D 等价，只能得出“树和摘要压缩有效”；只有 D 明显优于 B/C 才支持 principle abstraction，只有 E 优于 D 才支持跨树 graph。

---

## 10. 工程架构

### 10.1 目录

```text
aspire/sim/
├── cap/knowledge/
│   ├── models.py
│   ├── repository.py
│   ├── predicates.py
│   ├── graph.py
│   ├── abstraction/
│   │   ├── accumulate.py
│   │   ├── repetition.py
│   │   ├── canonicalize.py
│   │   ├── cluster.py
│   │   ├── contrast.py
│   │   ├── counterexample.py
│   │   ├── propose.py
│   │   └── validate.py
│   ├── retrieval/
│   │   ├── principle_index.py
│   │   ├── skill_index.py
│   │   ├── instance_index.py
│   │   ├── topdown.py
│   │   ├── fallback.py
│   │   └── portfolio.py
│   ├── lifecycle/
│   │   ├── support.py
│   │   ├── invalidation.py
│   │   ├── conflict.py
│   │   └── pruning.py
│   ├── projection.py
│   ├── telemetry.py
│   └── cli.py
├── knowledge/
│   ├── manifests/
│   ├── skill-code-instances/<vertical>/<id>.yaml
│   ├── principles/<id>/<version>.yaml
│   ├── skills/<id>/<version>.yaml
│   ├── trees/<vertical>/<version>.yaml
│   ├── edges/<id>/<version>.yaml
│   ├── evidence/*.jsonl
│   ├── proposals/<proposal-id>/
│   ├── projections/
│   └── experiment/
│       ├── corpora/
│       ├── task-contexts/
│       ├── relevance-labels/
│       └── preregistration.yaml
├── scripts/knowledge/
└── tests/knowledge/
```

YAML/JSONL/Git 是 source of truth；SQLite/FTS 是可重建索引；Markdown 是生成视图。

### 10.2 SQLite 重点表

```sql
CREATE TABLE skill_code_instances (
  id TEXT PRIMARY KEY,
  vertical_capability TEXT NOT NULL,
  task TEXT NOT NULL,
  source_code_path TEXT NOT NULL,
  source_code_hash TEXT NOT NULL,
  ast_fingerprint TEXT NOT NULL,
  contract_json TEXT NOT NULL,
  outcome_json TEXT NOT NULL,
  canonical_skill_id TEXT,
  checkpoint_id TEXT NOT NULL
);

CREATE TABLE nodes (
  id TEXT NOT NULL,
  version TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  scope_json TEXT NOT NULL,
  rule_json TEXT,
  content_hash TEXT NOT NULL,
  active INTEGER NOT NULL,
  token_estimate INTEGER NOT NULL,
  PRIMARY KEY (id, version)
);

CREATE TABLE edges (
  id TEXT NOT NULL,
  version TEXT NOT NULL,
  kind TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_version TEXT NOT NULL,
  target_id TEXT NOT NULL,
  target_version TEXT NOT NULL,
  guard_json TEXT NOT NULL,
  confidence REAL,
  active INTEGER NOT NULL,
  PRIMARY KEY (id, version)
);

CREATE TABLE vertical_trees (
  tree_id TEXT NOT NULL,
  version TEXT NOT NULL,
  vertical_capability TEXT NOT NULL,
  root_node_id TEXT NOT NULL,
  checkpoint_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  PRIMARY KEY (tree_id, version)
);

CREATE TABLE principle_metrics (
  principle_id TEXT NOT NULL,
  principle_version TEXT NOT NULL,
  support_count INTEGER NOT NULL,
  support_families INTEGER NOT NULL,
  support_diversity REAL NOT NULL,
  contradiction_count INTEGER NOT NULL,
  exception_rate REAL NOT NULL,
  operational_fanout INTEGER NOT NULL,
  compression_ratio REAL NOT NULL,
  support_sufficiency TEXT NOT NULL,
  PRIMARY KEY (principle_id, principle_version)
);

CREATE VIRTUAL TABLE principle_fts USING fts5(
  id UNINDEXED, version UNINDEXED, title, statement,
  trigger, decision, invariant, scope, exceptions, falsifiers
);

CREATE VIRTUAL TABLE skill_fts USING fts5(
  id UNINDEXED, version UNINDEXED, title, goal,
  trigger, operation, failure_modes, scope
);
```

### 10.3 核心接口

```python
class AbstractionEngine(Protocol):
    def audit_repetition(
        self, instances: list[SkillCodeInstance], checkpoint: Checkpoint
    ) -> RepetitionReport: ...
    def canonicalize(self, cluster: RepetitionCluster) -> CanonicalSkillProposal: ...
    def propose_principle(
        self, skills: list[CanonicalSkill], tree: VerticalSkillTree
    ) -> PrincipleProposal: ...
    def search_counterexamples(self, proposal, forest) -> CounterexampleReport: ...
    def place_in_tree(self, proposal, tree) -> PlacementReport: ...

class PrincipleValidator(Protocol):
    def validate_schema(self, principle) -> ValidationReport: ...
    def validate_support(self, principle, graph, evidence) -> ValidationReport: ...
    def validate_leave_family_out(self, principle, corpus) -> ValidationReport: ...

class TopDownRetriever(Protocol):
    def select_trees(self, context) -> list[VerticalSkillTree]: ...
    def retrieve_principles(self, context, limit: int) -> list[Candidate]: ...
    def gate_principles(self, candidates, context) -> list[Decision]: ...
    def descend(self, principles, context, budget) -> list[CanonicalSkill]: ...
    def traverse_overlay(self, skills, context) -> list[CanonicalSkill]: ...
    def fallback(self, context, uncovered_requirements) -> list[CanonicalSkill]: ...

class ImpactAnalyzer(Protocol):
    def invalidate_instance(self, ref) -> ImpactReport: ...
    def invalidate_skill(self, ref) -> ImpactReport: ...
    def support_sufficiency(self, principle_ref) -> SupportReport: ...
    def affected_tasks(self, ref) -> list[str]: ...
```

### 10.4 CLI

```bash
akl instance ingest --task <task> --code <fix_code.py> --findings <findings.md>
akl checkpoint freeze --after-instances 20 --id snapshot-N20
akl repetition audit --checkpoint snapshot-N20 --by-vertical
akl skill canonicalize --cluster <cluster-id> --output knowledge/proposals
akl principle cluster-skills --tree <vertical-tree> --checkpoint snapshot-N20
akl principle propose --cluster <id> --contrastive --search-counterexamples
akl principle review <proposal-id>
akl principle promote <proposal-id> --status validated
akl forest validate --manifest libero-active
akl forest show --vertical localization
akl overlay validate --manifest libero-active
akl retrieve topdown --context <task.json> --budget 2400 --explain
akl retrieve canonical-only --context <task.json> --budget 2400
akl impact invalidate <skill-or-instance-ref>
akl experiment build-corpus --scale 1,4,16,64
akl experiment run --preregistration knowledge/experiment/preregistration.yaml
akl experiment report --compare A,B,C,D,E,F
```

---

## 11. ASPIRE 接入

### 11.1 Promotion 流程

现有每任务 promotion 扩展为两个不同节奏：

```text
fast path（每个 task）
skill code + findings -> append immutable code instance -> evidence ledger

slow path（达到 consolidation checkpoint）
code instances -> repetition audit -> canonical skills
               -> cluster canonical skills within vertical tree
               -> principle proposals -> counterexample search
               -> coordinator review -> leave-family-out validation
               -> tree/overlay promotion
```

禁止每个 task 都即时生成 canonical skill 或 validated principle；否则“整合层”会和代码实例一样爆炸。

### 11.2 Principle consolidation cadence

默认在预注册的 `N_code` checkpoint 或新增 code instances 达到阈值时运行：

- 先评估 instances 是否属于现有 canonical skill；
- 再评估 canonical skills 是否应挂到现有 principle；
- 评估现有 principle 是否需 split/merge/refine；
- 只有无法由现有 principle 解释且达到 gate 才新增；
- 记录 `instances -> skills -> principles` compression ratio、tree edits 和 overlay edits。

### 11.3 Actor 接入模式

```yaml
knowledge:
  mode: off            # off | shadow | canonical | principle-tree | principle-graph
  manifest: libero-active
  token_budget: 2400
  max_principles: 4
  max_skills: 8
  fallback: canonical
```

- `off`：现有整文件；
- `shadow`：Actor 仍看整文件，后台编译所有实验组；
- `canonical`：B 组；
- `principle-tree`：D 组；
- `principle-graph`：E 组。

实验组 C/D/F 通过 evaluation config 启用，不作为生产 mode。

### 11.4 Partition 防污染

- principle content 仅由 development evidence 产生；
- held-out 只评价冻结 manifest；
- 同一 experimental run 中 held-out outcome 不得写回 status/score；
- 下一研究迭代若使用旧 held-out 作为历史 evidence，必须建立新的外层 test set；
- 每个 portfolio 记录 manifest、corpus、retriever、prompt 和 task context hash。

---

## 12. 生命周期与爆炸控制

### 12.1 Principle 状态

```text
proposal -> candidate -> validated -> stable
               |            |          |
               v            v          v
            rejected     weakened   deprecated
                            |
                            v
                          blocked
```

`weakened` 可先作为 materialized condition，而非持久 status：support 不充分但尚未被反驳。weakened principle 不进入默认 runtime。

### 12.2 新代码实例入库

每个新 skill-code instance 只追加到 evidence/instance corpus。到 checkpoint 后才依次尝试：

1. exact duplicate of existing instance；
2. member of existing canonical skill；
3. member of a new repeated cluster，提出 canonical skill；
4. counterevidence/exception to an existing skill/principle；
5. remain an unabstracted code instance；
6. 只有多个 canonical skills 再次呈现共同 invariant 时才提出 principle。

这才是从组织机制上抑制“principle 同步爆炸”的关键。

### 12.3 Principle merge/split

Merge 条件：rule、scope、exceptions 和 observed effects 等价；不能只凭 embedding。

Split 信号：

- exception rate 超阈值；
- operational fan-out 超阈值；
- children 形成两个不同 failure/effect cluster；
- 一个 statement 需要大量 `or` 才能覆盖；
- 不同 task family 的 transfer outcome 相反。

### 12.4 Invalidation propagation

Code instance、canonical skill 或 API 失效时：

1. 标记具体 support edge；
2. 重算 principle support sufficiency；
3. 找到依赖该 principle 的 portfolios/task families；
4. 若仍有多样、充分支持，principle 保留；
5. 若 support weak/broken，从 runtime 移除并排队重验证；
6. 不因一个实现失效就删除仍成立的 invariant。

### 12.5 Hub control

- active principle operational fan-out 默认 ≤12；
- top-down descent 每次最多访问 3 children/principle；
- 超阈值 principle 进入 split audit；
- 所有 hub 记录 task-family distribution，防止单一 broad principle 吞并全库；
- safety principle 可超过阈值，但其 runtime 表达是 constraint，不展开所有 children。

### 12.6 Pruning

优先剪：

- redundant actor-visible canonical variants，但保留 code instances/evidence/provenance；
- unsupported/rejected principle proposals；
- 被更精确 principle supersede 的上层节点；
- 不再 active 的 forest/overlay view。

不因低使用率剪：safety constraints、rare exceptions、negative evidence。

---

## 13. 测试与质量门

### 13.1 Unit / property tests

- principle schema、predicate 和 falsifier；
- `parent-of` vertical-tree cycle 和 single-parent validation；
- `instance-of` membership validation；
- repetition checkpoint 不提前触发；
- exact duplicate / canonical skill / principle-level repetition 分类；
- bidirectional edge materialization；
- support diversity 去重；
- exception guard；
- support sufficiency；
- hub/fan-out limits；
- vertical forest 与 overlay view deterministic；
- top-down descent bounds；
- canonical-skill fallback coverage；
- same input -> same portfolio hash；
- held-out evidence rejected from promotion path。

### 13.2 Golden corpus

手工建立 10–20 个 principle：

- 每个有正支持、相似但不支持的 hard negative、exception 和至少一个 falsifier；
- 覆盖 localize、grasp、transport、manipulation 和 long-horizon；
- 由两名 reviewer 独立判断 principle relevance 和 child relations；
- disagreement 留存，不用强行消失；
- golden 用于 abstraction faithfulness 和 retrieval evaluation。

### 13.3 Stress tests

- broad principle 误命中；
- exception 被删除；
- support code instance/canonical skill 失效；
- duplicate principle proposal；
- principle cycle；
- 1000 个 children 的 hub；
- contradictory evidence；
- same wording/different rule；
- different wording/same invariant；
- overlay edge 改变但 vertical primary parent 不变。

### 13.4 工程 gate

进入 shadow：

- vertical forest 无 cycle、多父或 dangling membership；
- overlay graph 无 dangling edge；
- 每个 validated principle 有 grounding、exception/falsifier；
- source/evidence partition 完整；
- golden faithfulness ≥0.85；
- tree/index/portfolio 可确定性重建。

进入 principle runtime：

- relevant principle recall@8 ≥0.90；
- operational canonical-skill recall ≥ B baseline - 0.03；
- unsupported principle escape = 0；
- exception stress hard violation escape = 0；
- shadow fallback <10%；
- p95 compile latency ≤300 ms。

支持研究结论：按第 9.7 节预注册规则，而非单一工程阈值。

---

## 14. 里程碑

### M0：预注册与基线（3–4 人日）

- PA-001：冻结主命题、H1–H6 和反证条件；
- PA-002：定义 explosion metrics；
- PA-003：实现 A/B baseline；
- PA-004：选择 organic snapshots 与任务划分；
- PA-005：冻结统计分析和 non-inferiority margin。

退出条件：在写 principle 系统前，基线、指标和判断规则已锁定。

### M1：Skill-code corpus 与纵向森林（6–8 人日）

- PA-101：定义并导入 SkillCodeInstance；
- PA-102：实现 AST/API/contract fingerprints；
- PA-103：CanonicalSkill/Principle/Tree/Overlay/Evidence schema；
- PA-104：vertical forest repository/validator；
- PA-105：support diversity 和 sufficiency；
- PA-106：10–20 个专家 canonical skills/principles golden set。

退出条件：原始 code instance、canonical skill 和 principle 三层 lineage 可审计、可重建。

### M2：向上抽象工作流（5–8 人日）

- PA-201：checkpoint manager；
- PA-202：重复性审计与分类；
- PA-203：canonical skill proposal；
- PA-204：contrastive principle proposal；
- PA-205：counterexample search；
- PA-206：vertical tree placement + overlay review；
- PA-207：promotion/merge/split/hub audit。

退出条件：工具可产生 proposal，但不能未经 review 激活。

### M3：自顶向下检索（5–7 人日）

- PA-301：principle/canonical-skill/code-instance 三层索引；
- PA-302：vertical tree selector；
- PA-303：applicability/exception gate；
- PA-304：minimum sufficient tree descent；
- PA-305：overlay traversal + canonical fallback；
- PA-306：tree-first portfolio/telemetry；
- PA-307：A–F treatment configs。

退出条件：相同 context 可生成全部实验组的预算匹配 portfolio。

### M4：ASPIRE shadow 与实验（6–10 人日 + GPU）

- PA-401：fix-loop/Long-Pro context adapter；
- PA-402：snapshot contamination guard；
- PA-403：1x/4x/16x/64x code-instance corpus 与固定 checkpoints；
- PA-404：A–F evaluation harness；
- PA-405：retrieval/abstraction human labels；
- PA-406：mixed-effect/bootstrap analysis；
- PA-407：negative-transfer case review。

退出条件：完成预注册实验，无边跑边改 principle。

### M5：生命周期与论文结论（4–6 人日）

- PA-501：invalidation propagation；
- PA-502：maintenance workload simulation；
- PA-503：total cost accounting；
- PA-504：claim audit；
- PA-505：go/no-go 与下一版设计。

退出条件：明确得到支持、部分支持或不支持，而不是默认宣布成功。

### 14.1 首个两周切片

只做：

1. 预注册 H1–H6；
2. SkillCodeInstance corpus 和至少两个冻结 checkpoint；
3. 重复性审计 golden labels；
4. 10–20 个 canonical skill/principle golden set；
5. vertical forest/overlay schema 与 validator；
6. A/B/C/D/E 离线 portfolio compiler；
7. 20 个 TaskContext 的 retrieval + token 对照；
8. 不接入机器人执行，不自动生成 validated principle。

这个切片能最早回答：principle 是否真的形成有区分力的压缩层，而不是漂亮但无用的总结。

---

## 15. Definition of Done

### 研究设计

- [ ] 主命题和 H1–H6 已预注册；
- [ ] A–F 强对照全部可运行；
- [ ] token budget、模型、skill-code corpus、checkpoints 和 seeds 公平固定；
- [ ] organic 与 synthetic stress 结果分开报告；
- [ ] 分析规模退化斜率，而非只看最大规模单点；
- [ ] 失败结论有明确判据。

### Skill consolidation forest

- [ ] principle 只能由 checkpoint 后的 canonical skills 提炼，不能由单条 code/findings 直接产生；
- [ ] 每个 canonical skill 都能追溯到重复性审计和多个 code instances；
- [ ] principle 不是 summary，均包含 rule/scope/exception/falsifier；
- [ ] validated principle 有多样 support 和 operational grounding；
- [ ] 每棵 vertical tree 无环、无多父、无 dangling membership；
- [ ] overlay graph 无 dangling edge 且不改写 primary tree identity；
- [ ] support 失效能传播为 weak/broken；
- [ ] hub、merge、split 和 contradiction 可审计；
- [ ] 所有 revision/evidence 可回滚。

### Retrieval

- [ ] flat-code、canonical-skill、summary-tree、principle-tree 和 forest+graph 共享可比接口；
- [ ] top-down descent 有严格 fan-out/token bounds；
- [ ] fallback 显式记录；
- [ ] portfolio 版本锁定、确定性、无 held-out 泄漏；
- [ ] exceptions 和 rejected guidance 能进入 Actor context。

### 结论质量

- [ ] principle-tree/graph 成功率非劣于 canonical-skill baseline；
- [ ] active/maintenance surface slope 更平缓；
- [ ] negative transfer 没有增加；
- [ ] principle 构建成本计入总成本；
- [ ] 若仅优于 Flat-All，不夸大为 abstraction 优势；
- [ ] 所有 claim 能对应实验组、指标和置信区间。

---

## 16. 最终推荐

最终方向是 skill-code-first，而不是 principle-first 或 atomic-op-first：

> 先生成并保留一定量的 `skill-code-instance`，在冻结 checkpoint 评估重复性；把重复代码整合为 `canonical skill`，再把同一纵向能力族中的重复 invariant 提炼为 `principle tree`；最后以跨树 overlay graph 连接能力之间的依赖与冲突。

但不要把项目表述为“高层抽象减少知识库规模”。更准确的目标是：

> 在保留全部原始 skill code 和证据的前提下，用纵向抽象树压缩重复实现、用少量可证伪 principle 管理 Actor 的活跃决策表面，并用跨树 graph 管理组合关系，使这些表面随代码实例增长得更慢。

最终应接受三种可能结论：

1. **支持**：Canonical dedup 有基础收益，Principle-Tree 还有独立增益，Forest+Graph 在跨能力任务上继续改善；
2. **部分支持**：收益主要来自代码去重或 summary tree，principle 只在冲突、迁移或少数纵向能力中有额外价值；
3. **不支持**：抽象错误和维护成本抵消收益，应停在 canonical-skill retrieval，只保留少量人工 safety principles。

能够严谨地区分这三种结果，比预设 principle 一定有效更有研究价值。
