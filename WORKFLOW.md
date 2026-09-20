# 带货口播结构复用 — 工作流

日期:2026-09-17 起草,2026-09-20 更新
状态:本地规划、ImageGen 参考帧和历史中文 H3 测试已跑通;新的英文任务已到 `keyframes_ready`,尚未完成英文 H3 成片。职责冲突时以 `AGENTS.md` 为准。第 4 节以后保留 v0.1 数据和测试记录,只作历史证据。

原则:**抽结构,不抽文案**。一张节拍表 + 一张商品参数表 → N 条不重样的口播。

---

## 0. 分工

默认所有权:Codex 在本地连续完成 S1–S6;Claude 只在 `READY.json` 完成封存且 `PREFLIGHT.json.status = pass` 后进入 S7–S8。
用户明确改派时可以换人,但必须在 `events.en.jsonl` 记录实际 `actor`。

| 在哪跑 | 做什么 |
|---|---|
| 本地(Windows,默认 Codex) | 建档、faster-whisper 转写、证据宫格、节拍表、商品事实、英文稿、分镜、ImageGen 参考帧与参考帧 QC。统一使用 `D:/anaconda/envs/ugc_asr/python.exe` |
| 服务器 `doubleflow`(默认 Claude) | 只接收已通过门禁的英文稿和参考图,执行 H3 渲染、局部重跑与交付。**模型和包只能走镜像源** |

镜像源约定(服务器):

```bash
export HF_ENDPOINT=https://hf-mirror.com
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple <pkg>
```

服务器状态不影响本地第 1–6 步;只有第 7 步依赖服务器。

---

## 1. 目录结构

```
ugc_clone_pipeline/
  HANDOFF.md / WORKFLOW.md
  inputs/<job>/
    job.en.json            英文任务入口与路径契约
    product.en.json        商品参数表(人填/agent 校验,带证据)
    product_*.jpg/png      商品原图
    presenter_master.png   仅 generated_fictional 模式需要
  references/<ref_id>/
    FACTS.json / ANALYSIS.md / TIMELINE.md / evidence/
  work/<job>/
    beats.json             节拍表(核心产物)
    variants/vNNN/script.en.json
    variants/vNNN/shot_plan.json
    keyframes/REQUEST.json / QC.json / READY.json
    keyframes/READY.invalidated.<UTC>.json  失效交接信号的可恢复审计副本
    PREFLIGHT.json                         最新渲染前门禁报告
    state.en.json / events.en.jsonl
  out/<job>/               成片
  scripts/                 各阶段脚本
  skill/SKILL.md           蒸馏出的 skill
```

---

## 2. 流程总览

```
S1 建档+转写 ─▶ S2 原片档案 ─▶ S3 节拍表 ─┐
                                            ├─▶ S5 英文稿+分镜 ─▶ S6 ImageGen 参考帧 ─▶ S7 H3 渲染 ─▶ S8 验收
                         S4 商品参数表 ─────┘
```

每个阶段有明确的输入、输出、通过条件。没过条件不进下一阶段。

---

## 3. 各阶段

### S1 建档 + 转写(本地,默认 Codex)

- 输入:用户提供的参考视频文件
- 做:
  - `D:/anaconda/envs/ugc_asr/python.exe scripts/reference_archive.py init <video> <ref_id> --transcribe [--vad]`
  - 自动探测媒体、抽音频、生成逐词时间戳、证据宫格和档案骨架
- 通过条件:命令完成,音频能听清,证据文件齐全

抽帧密度不固定,按问题调(借鉴 hypit `media tile/frames/boundaries`):

| 用途 | 做法 |
|---|---|
| 总览 | 1 秒 1 帧,宫格,**每格下方标出那一刻正在说的字**(S2 之后补) |
| 看交接 | 缩到关键区间,0.1 秒 1 帧,例如卖点点选、开盖挖取 |
| 读细节 | `--at` 指定时刻,原分辨率单帧 |
| 切点 | 每秒采 12 帧、阈值 0.1 的结果只算候选,要人看确认;本流程默认阈值 0.3 |

### S2 写原片档案(本地,默认 Codex)

- 先看 `references/<ref_id>/evidence/overview/`,再完成 `ANALYSIS.md` 和 `TIMELINE.md`
- `TIMELINE.md` 每段必须写镜头、动作、表情、话画同步和改编意图;事实与解读分开
- 看不清时用 `reference_archive.py tile`,但原片截图只能用于分析,不能交给 ImageGen 或 H3
- 通过条件:`reference_archive.py check <ref_id>` 输出 `READY`

### S3 节拍表(本地,默认 Codex 标注)

- 输入:参考档案中的逐词时间戳、切点和 `labels.json`
- 做:
  1. 脚本按"停顿 > 250ms"和"镜头切点"两种边界,切出骨架
  2. agent 看帧、读文本,给每一拍填功能标签
  3. **原文只存在 `ref_text` 字段做对照,下游生成禁止读取**
- 输出:`beats.json`;第 4 节是历史 v0.1 示例,当前契约同时受 `schemas/` 和 `ugc_pipeline.validation` 约束
- 通过条件:每拍都有 `function`;时间窗首尾相接,覆盖整条视频

### S4 商品参数表(用户供事实,默认 Codex 整理和校验)

- 输入:商品图、包装、详情页、运营给的价格
- 输出:`product.en.json`,schema 见 `schemas/product.schema.json`
- 硬规则:**每条卖点和宣称必须挂 `evidence`**,即证据出处(包装配料表、检测报告、详情页截图)。没证据的不能进口播

### S5 写口播稿(本地,默认 Codex)

- 输入:`beats.json`(生成阶段不得读取 `ref_text`)+ `product.en.json`
- 做:逐拍生成新台词,一次出 N 个变体
- 硬约束(脚本自动检查,不过就重写):

| 检查 | 规则 |
|---|---|
| 结构对齐 | 拍数、顺序、功能标签跟节拍表一致 |
| 字数 | 每拍字数在 `char_count × 语速系数 ± 15%` 内 |
| 与原稿不重合 | 跟 `ref_text` 的字符 5-gram 重合率 < 10%,且没有 ≥ 6 字的公共子串 |
| 变体之间不重合 | 同批变体两两 5-gram 重合率 < 30% |
| 宣称可背书 | 每条卖点/数字/效果都能映射到 `product.json` 里某条带证据的内容 |
| 广告法 | 禁用词表:最、第一、国家级、治疗、减肥、代餐……(按品类扩展) |

- 输出:`script.json`,结构 `[{beat_id, text, claim_refs[]}]`
- 两种模式(`script.json` 的 `mode` 字段):
  - `structure`(默认,量产用):重合检查不过就 FAIL
  - `replica`(测试用):句式贴原稿,只换商品、价格、卖点,重合只报 WARN。
    **宣称检查和禁用词检查照常拦**:原稿里我们没证据的宣称(0 糖、代餐、希腊酸奶、复购)必须换成真实内容。
    这个模式的稿子不能批量发布
  - umall_test 先跑 `replica`(2026-09-17 老板要求先按原稿做、看测试结果);结构版备份在 `script_structure_v1.json`

无台词参考片走 `audio_mode: silent`:建档可不运行 ASR;`beats.json` 只记录镜头节拍;`script.en.json`
每段 `text` 必须为空并填写 `visual_direction`;`shot_plan.json` 的 `dialogue` 为空、`accents` 为空。
H3 生成保持静音,不得为了满足口播字段而编造台词或字幕。

### S6 分镜 + ImageGen 参考帧(本地,默认 Codex)

- Codex 根据 `ANALYSIS.md` / `TIMELINE.md` 写英文稿、`shot_plan.json` 和 `REQUEST.json`,再用 `build_keyframe_prompts.py` 编译只含正面描述的提示词
- Codex 只使用商品原图和已登记定妆照生成 9:16 参考帧;不得使用原片帧或上一张生成图
- 密集小字用 `pixel_preserve` 贴回原商品像素,或交给 H3 `fully_preserved` / 静态慢推保底
- QC 全通过后写 `READY.json`,再依次执行 `keyframe-status --actor codex` 和 `preflight --actor codex`;只有最新 `PREFLIGHT.json.status = pass` 才授权 Claude 进入 S7
- `keyframe-status` 会封存稿子、分镜、商品引用、QC、READY 与全部参考帧的 SHA256;之后任何一项漂移都会使预检失败、隔离旧 READY 并退回 `awaiting_keyframes`
- H3 台词使用 `(S1) <d>[English] ...</d>`。历史 `[Chinese]` 提示词只作为测试记录,不得用于新任务
- H3 仍遵守**单任务 ≤ 20s / 4 段**;需要插入镜头时在分镜里拆成 subshot 或独立段
  - 服务器重启后 ComfyUI 和 worker 都要手动拉起;`cc_status.py` 必须在仓库目录下跑,否则找不到 config

### S7 渲染取回(服务器)

Claude 在任何上传或付费渲染前先运行:

```powershell
D:/anaconda/envs/ugc_asr/python.exe -B -m ugc_pipeline preflight inputs/<job>/job.en.json --actor claude
```

只有 PASS 才能继续;失败时按报告修复或退回 Codex,不得沿用已经隔离的 READY。

`cc_submit.py --segments-file` → `cc_status.py --wait --deliver` → 本地 `cc_fetch.py`
单段有问题就用 `cc_rerun.py` 只重跑那一段。

### S8 验收(本地)

- 对成片在本地用同一个 faster-whisper 流程转写,确认说出来的就是获批英文稿(防模型乱改台词)
- 抽帧看:商品标签可读、没有原品牌元素、出镜人不是原达人
- 文件 > 30MB 的要注明只能在桌面端看

---

### 首次跑通记录(umall_test,2026-09-17)

| 步骤 | 结果 |
|---|---|
| 出镜人 `umall-presenter-001` | fl2va 720p 直出 5 秒,耗时 259 秒,取 4.2 秒处截帧 → `inputs/umall_test/presenter.jpg` |
| 正片 `umall-replica-001` | ref2va 4 段 × 5 秒,二采 + 超分,1440x2560,20.67 秒,35MB,耗时 1509 秒,GPU 约 0.84 元 |
| 台词核对(S8) | 成片转写后基本一致。可疑处:1.5–3.0 秒"就拿这个"识别成"生出来这个"(置信 0.10),14.4 秒"西柚"识别成"稀有"。需要人工听,判断是 H3 读错还是转写错 |
| 交付 | 35MB 超过 30MB,只能在桌面端看 |

第二条(a2_test,2026-09-17):公钥 21:22 装好 → 21:28 正片提交 → 21:54 出片,全程 32 分钟。
`a2-replica-001` 1440x2560、20.67s、28MB、1510s、约 0.84 元;成片转写和稿子逐字一致,无低置信度字。
转写遇到背景音乐幻觉,处理方法写在 skill 里。
人工看片发现第 2/3/4 段穿帮,改提示词后经 002→003→004 链式单段重跑修复,`a2-replica-004` 人工确认通过(2026-09-19)。

按仓库规则,成片不抽帧;画面(人物一致性、标签小字、挖起那块的形状)交给人工看。

## 4. 节拍表 schema(v0.1)

```json
{
  "schema": "beats/v0.1",
  "source": {"file": "ref_video.mp4", "duration": 16.47, "fps": 30, "size": "720x1280"},
  "speech_rate_cps": 4.8,
  "beats": [
    {
      "id": "B1",
      "t_start": 0.0,
      "t_end": 2.0,
      "function": "hook",
      "hook_type": "body_anxiety",
      "char_count": 14,
      "intensity": "low→mid",
      "pause_after_ms": 150,
      "shot": {"type": "medium_selfie", "cut_in": false},
      "visual_action": "手拿一杯产品对镜头,身后开箱",
      "visual_sync": "无",
      "proof_category": null,
      "ref_text": "(仅对照,生成阶段不可见)"
    }
  ]
}
```

`function` 的取值:

| 取值 | 含义 |
|---|---|
| `hook` | 开头钩子 |
| `pain` | 痛点 |
| `solution` | 产品作为解决方案 |
| `use_case` | 使用场景 |
| `price_anchor` | 价格锚定 |
| `quantity` | 分量 |
| `urgency` | 紧迫感 |
| `social_proof` | 社会证明 |
| `criteria` | 教观众怎么挑 |
| `feature` | 卖点 |
| `sensory_proof` | 感官证明:质地、口感 |
| `comparison` | 对比 |
| `cta` | 引导下单 |

`hook_type` 的取值:

| 取值 | 含义 |
|---|---|
| `body_anxiety` | 身体焦虑 |
| `counter_intuitive` | 反常识 |
| `identity` | 身份认同 |
| `craving` | 馋 |
| `deal` | 捡便宜 |
| `question` | 提问 |

`visual_sync` 记"说到 X 时画面出现 X",这是卖点和画面对齐的关键。

---

## 5. 商品参数表 schema(v0.1)

```json
{
  "schema": "product/v0.1",
  "name": "杨枝甘露奶皮子酸奶",
  "brand": "UMALL 优选",
  "spec": {"unit": "杯", "pack_qty": 12, "volume_ml": 220},
  "price": {"currency": "AUD", "unit_price": 6.89, "list": null, "box_price": null, "promo_window": null},
  "storage": "冷藏 2-6°C",
  "facts": [
    {"id": "F1", "text": "配料:全脂牛奶、增稠剂(果胶)、芒果果泥、西柚果肉、酸奶发酵菌", "evidence": "包装配料表"},
    {"id": "F2", "text": "奶皮子口味,上层有奶皮", "evidence": "包装品名 + 产品图"},
    {"id": "F3", "text": "芒果果泥 + 西柚果肉,杨枝甘露风味", "evidence": "包装配料表"}
  ],
  "forbidden_claims": ["低糖/无糖", "代餐", "减脂", "希腊酸奶同款"],
  "visual_assets": ["target_umall.jpg"]
}
```

`null` 表示还没拿到,要人来补,**不能让 agent 编**。

本次已确认(2026-09-17):220ml/杯,6.89 澳元/杯,一箱 12 杯。
- 没有原价,**不能做"原价划掉"式锚定**
- 没给整箱价,口播只说"一杯 6.89",不说"一箱只要 82.68"这类折算后像优惠的话
- 该条只描述 2026-09-17 的历史中文 `replica` 测试;新生成任务必须使用英文

---

## 6. 示例:本次参考视频的节拍表初稿

说明:根据烧录字幕和 1fps 抽帧手工拆的,时间精度只到秒,S2 跑完后校准。

| 拍 | 时间 | 功能 | 镜头 | 画面动作 / 对齐 |
|---|---|---|---|---|
| B1 | 0–2s | hook(body_anxiety)+ pain | 中景自拍,身后开箱 | 手拿一杯对镜头 |
| B2 | 2–4s | solution + use_case | 中景,吃一口 | 说到"这个"时勺子入口 |
| B3 | 4–6s | price_anchor + quantity + urgency | 中景,手伸进箱子 | 说到"一大箱"时手指向箱子,强调字幕 |
| B4 | 6–8s | social_proof(复购) | 7s **硬切**俯拍整箱 | 画面给出"量" |
| B5 | 8–11s | criteria(教观众挑,标准正好是自家卖点) | 8s 中景掀盖;9s **硬切**杯盖特写 | 手指逐个点杯盖上的卖点字,**说到哪个点哪个** |
| B6 | 12–16s | sensory_proof + comparison | 中景,勺子挖 | 挖起一大块、展示挖出的坑,以对比收尾 |

结构结论:

- 没有明确的引导下单,结尾停在感官证明
- 价格只说"这个价格",没报数字,靠"一箱 10 桶"表达量
- 最值钱的一招是 B5:**把自家卖点包装成挑选标准**,观众以为在学知识,其实在看卖点
- 两次硬切都用来给新信息(整箱的量、杯盖卖点),符合 product-replication 的"有新信息才切"

## 7. 套到 UMALL 杨枝甘露奶皮子酸奶上的问题

以下几拍**不能直接迁移**,需要先定下来:

1. **B1/B2 钩子**:原片是"胖了 → 无糖酸奶当代餐"。我们的商品含芒果果泥、西柚果肉,没有低糖证据,**减脂和代餐都不能说**。建议钩子改成 `craving`(想喝杨枝甘露)或 `identity`(甜品党)
2. **B3 价格**:已给,6.89 澳元/杯、一箱 12 杯。原片"一大箱 10 桶"的量感改成"一箱 12 杯"
3. **B4 复购**:"又囤了一大箱"是亲身经历宣称。出镜人是我们生成的,**这句属于编造体验**。建议改成对"量"的展示,或者删掉
4. **B5 挑选标准**:只能用包装上真有的内容,比如配料表里的真芒果果泥、真西柚果肉、冷藏。原片的"0 蔗糖 / 0 代糖 / 0 乳糖"一个都不能用
5. **B6 对比**:"接近希腊酸奶"是原片的宣称。我们换成可展示的:奶皮层、果肉颗粒、挖起不塌
6. **出镜人**:AI 生成一个虚构人物,出一张 `presenter.jpg`,**所有分段都绑这同一张图**,保持同一个人。
   可以借原片的类型特征(年轻女性、居家餐厅、自拍中景、开箱),但**不能用原达人的帧做参考、不能写得像她本人**。
   声音也用 H3 自己生成的,不克隆原声

---

## 8. 蒸馏计划

skill 已落在 `.claude/skills/ugc-voiceover-clone/SKILL.md`(v0.1,依据 umall_test 一次跑通)。
之后每跑完一个阶段,往里面补三样:

- 这一步实际的命令
- 踩到的坑
- 通过条件

体例照 `comfyui_workflow/.claude/skills/product-replication/SKILL.md`。

第 4、5 节的 schema 每次改动就升版本号(`beats/v0.2` …),**先用 2–3 条参考视频验证 schema,再定版写 skill**。

## 9. 待确认

- [x] 老板确认做结构复用(本条为测试视频)
- [x] 价格规格:220ml/杯,6.89 AUD/杯,12 杯/箱
- [x] 出镜人:AI 生成虚构人物,全片同一张参考图
- [x] 转写环境:服务器 `/opt/ugc_clone/asr_venv`(faster-whisper,见 S2)
- [ ] 出镜人参考图怎么出:服务器上只有 H3 视频模型(ref2va / fl2va),没有文生图模型
- [ ] 成片目标时长(原片 16.5s,暂定 4 段 × 5s = 20s,一个任务)
- [x] 服务器:`doubleflow`(地址见本机 ssh config),公钥已重装。工作目录 `/opt/ugc_clone`
