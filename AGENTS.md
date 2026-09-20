# ugc_clone — 两个 agent 的共同说明(Codex 读本文件,Claude Code 通过 CLAUDE.md 读同一份)

## 谁负责什么(以这张表为准,其他文档冲突时照这里)

**原则:生成视频之前的本地准备默认全部由 Codex 连续完成;服务器只拿已验收的稿子和参考图出 H3 视频。**
默认负责人如下;用户明确指派时可以换人,换人的一方在 `events.en.jsonl` 里写 `"actor"`。

| # | 阶段 | 负责 | 在哪 | 怎么做 | 产出 | 做完的信号 |
|---|---|---|---|---|---|---|
| 0 | 给素材 | **用户** | — | 参考视频、商品图、价格、卖法、目标语言 | `inputs/<job>/` 原始文件 | 用户在对话里说"开始" |
| 1 | 建档 + 转写 | **Codex** | 本地(conda `ugc_asr`) | `python scripts/reference_archive.py init <视频> <ref_id> --transcribe [--vad]` | `references/<ref_id>/` 事实、证据宫格、文档骨架 | 命令跑完 |
| 2 | 写原片档案 | **Codex** | 本地 | 看宫格写 `ANALYSIS.md`、`TIMELINE.md`,补看用 `reference_archive.py tile`;**事实表里判断出镜方式** | 两份档案 | `reference_archive.py check <ref_id>` 显示 READY |
| 3 | 商品参数表 | **Codex**(事实只能来自用户和包装图) | 本地 | 每条事实挂证据,拿不到的填 null | `inputs/<job>/product.en.json` | `validate` 通过 |
| 4 | 节拍表 + 稿子 | **Codex** | 本地 | `build_beats.py`,英文稿按节拍表写 | `beats.json`、`variants/vNNN/script.en.json` | `validate` 通过 |
| 5 | 分镜 + 出图请求 | **Codex** | 本地 | `job.presenter.mode` 照档案的出镜方式填,选对应模板;`camera` 照 TIMELINE 的镜头行,`first_frame` / `intention` / `accents` 照 TIMELINE 写,`build_keyframe_prompts.py` 生成提示词;`shot_for_shot` 同时生成 `h3_clip_plan.json` | `shot_plan.json`、`keyframes/REQUEST.json`、`h3_clip_plan.json`、`segNN_prompt.txt` | `validate` 通过后直接进入第 6 步 |
| 6 | 定妆照 + 参考帧 + H3 提交包 | **Codex** | 本地(Codex 自带 ImageGen) | 见下方"Codex 的出图规矩";READY 后用确定性编译器生成 `segments.json` | `presenter_master.png`、`keyframes/segNN.png`、`QC.json`、`READY.json`、`segments.json` | `keyframe-status` 和 `preflight` 均通过 |
| 7 | H3 渲染 | **Claude** | 服务器 | 先跑 `preflight --actor claude`,只上传已封存的 `segments.json` 和引用资产,再执行 `cc_submit`、单段 `cc_rerun` | 成片 | `cc_status` 出片 |
| 8 | 验收 | **Claude**(技术 + 台词)、**用户**(画面) | 本地 | 成片再转写对台词;画面交给用户看 | 验收结论 | 用户说"通过" |

几条边界:

- **Codex 默认连续完成第 1–6 步**,包括本地转写、档案、事实表、英文稿、分镜、出图和 QC;第 1–5 步不再等待 Claude 交接
- Codex 在第 6 步发现前序输入有问题时,应在证据范围内直接修正对应稿子或分镜,重新运行 `validate`,并把变更记进 `events.en.jsonl`
- **Claude 默认从第 7 步开始**,只在 `keyframes/READY.json` 存在、`keyframe-status` 已封存输入且最新 `PREFLIGHT.json.status = pass` 时接手 H3 生成、重跑和成片验收
- **服务器只在第 7 步出现**。服务器掉线只影响第 7 步,前面的步骤照常做
- 每一步都有"做完的信号";没看到上一步的信号,下一步不开始
- **出镜方式跟原片走,不默认有人**。原片有人对镜头说话才用 `generated_fictional`(出定妆照、做真人出镜);
  只有手用 `hands_only`,只有商品用 `none`,这两种**不出定妆照、画面里不出现人脸**。`validate` 会拦:

  | `presenter.mode` | 原片 | 定妆照 | 出图模板 |
  |---|---|---|---|
  | `generated_fictional` | 有人对镜头说话 | 要 | `templates/keyframe_prompt.en.txt` |
  | `hands_only` | 只有手和商品 | 不要 | `templates/keyframe_prompt.hands-only.en.txt` |
  | `none` | 只有商品,画外音 | 不要 | `templates/keyframe_prompt.product-only.en.txt` |
- 本地脚本和测试统一用 conda 环境 `ugc_asr` 的 Python(`D:/anaconda/envs/ugc_asr/python.exe`),
  里面有 numpy、Pillow、faster-whisper;系统自带的 Python 缺 numpy,跑测试会误报

这个仓库做一件事:拿一条别人跑通的带货口播视频,拆出节拍表,换成我们自己的商品、价格和 AI 出镜人,
再用服务器上的本地 MiniMax H3 重新生成视频。

先按这个顺序读:

1. `HANDOFF.md`:为什么做结构复用,不逐字照搬(平台查重、广告法),以及服务器的基础设施
2. `.claude/skills/ugc-voiceover-clone/SKILL.md`:完整做法和所有踩过的坑。**这是主文档**
3. `WORKFLOW.md`:阶段定义、schema、两次测试的实测记录
4. `PIPELINE_DESIGN.md`:英文量产流水线的完整状态机、数据契约、Codex/Claude 分工、重试和验收设计

## 仓库里有什么

| 路径 | 内容 |
|---|---|
| `scripts/prep.sh` | 旧:探测、抽音频、抽帧、切点(已被 `reference_archive.py init` 取代) |
| `scripts/transcribe.py` | 本地(conda `ugc_asr`):faster-whisper 逐词时间戳(有背景音乐时加 `--vad`,见 skill) |
| `scripts/media.py` | 看原片:带台词标注的宫格、按台词定位、切点候选、截帧、截片段(移植自 hypit `media`) |
| `scripts/reference_archive.py` | 原片档案:`init` 建档出证据和骨架,`check` 检查写完没有 |
| `scripts/build_beats.py` | 本地:labels.json → beats.json |
| `scripts/check_script.py` | 本地:口播稿硬检查(结构、字数、重合、禁用词、宣称证据) |
| `scripts/packshot_clip.sh` | 服务器:商品原图慢推的保底插入镜头 |
| `scripts/gen_keyframe.py` | 旧的 OpenRouter 参考帧脚本,保留作备用;当前默认不用 |
| `inputs/<job>/product.json` | 商品参数表,每条事实都带证据 |
| `work/<job>/` | labels / beats / script / segments / 提示词 |

**音视频和图片不进仓库**(见 `.gitignore`):参考视频和抽帧里是原博主的脸和作品,成片太大,
品牌产品图是别人的商标图。需要时由人在本地提供。

## Codex 默认负责的本地流程(第 1–6 步)

Codex 收到用户的“开始”信号后,按表格从建档和转写一路做到参考帧验收,中途不因等待另一个 agent 停下。
第 1–5 步的命令、数据契约和门禁见主 skill 与 `WORKFLOW.md`;第 6 步使用 Codex 内置 ImageGen,规则如下。

**问题**:H3 用的是 ref2va 多参考图模式,每段只绑"出镜人中景图 + 白底产品图"两张,构图全靠文字描述。
a2_test 的第 3 段(背标特写)因此四项全错:字糊成乱码、瓶型变了、没拍成特写、多出一只手。
另外,H3 文生视频出来的出镜人不够真实。

**Codex 的出图规矩(第 6 步)**:

1. 读取现有人物图、商品图和该段分镜要求
2. 使用 Codex 当前会话自带的 ImageGen 生成或编辑真实感更强的虚构出镜人与分镜参考帧
3. 检查人物一致性、构图、手的数量、商品形态和原品牌残留。不合格时**重新生成,不要在失败的图上继续改**
4. 出图的四条规矩(`validate` 会拦后三条):
   - 每次都从原图出发:参考图只用已确认的定妆照和商品原图,每次尝试都是一次全新生成
   - 除定妆照外,生成过的图(`keyframes/` 下的任何图)不能再当参考,包括上一段的参考帧
   - 商品的**朝向**和原图一致:正面或背面对着镜头,不转到原图没有的侧面。拿在手里还是放在桌上、
     镜头角度,都照分镜的 `camera` 和原片(例如原片是第一人称高位俯拍、手握瓶子,就照这样出);
     倾斜、倒奶这些动作交给 H3
   - 提示词用 `build_keyframe_prompts.py` 生成,约 150 词、只写正面描述;不要自己往里加"不要 XX"
5. 标签有密集小字时,不得让生成模型重画文字;改用原商品图像素或交给 Claude 走已验证的 `fully_preserved` / 慢推保底路径
6. 全部图片完成后写 `work/<job>/keyframes/READY.json`;`shot_for_shot` 随后运行 `build_timed_h3_prompts.py` 生成确定性的 `segments.json`,再用 `keyframe-status` 同时校验并封存图片、逐切点计划和 H3 提交包,最后跑 `preflight`;两条门禁都通过后停止

**明确不做**:

- 不接 OpenAI Image API,不接 OpenRouter,不读取或配置任何图像 API key
- 不上传服务器,不提交 H3,不重跑视频,不做最终成片验收
- 不改 Claude 的监听、服务器和 H3 编排逻辑

Claude Code 只在看到 `READY.json` 且重新运行 `preflight --actor claude` 通过后接手第 7–8 步。

**6a 定妆照(只在 `presenter.mode = generated_fictional` 时做;自动,不用等用户)**

1. 出 3 张候选定妆照:虚构出镜人在和原视频同类型的场景里(看 `video_analysis/` 的宫格,用文字描述场景),
   **画面里没有任何商品**,中景、自然光,人要比现在的 `presenter.jpg` 更真实
2. 自己按验收标准挑最好的一张,运行
   `python scripts/set_presenter_master.py inputs/a2_test/job.en.json <选中的图> --note "best of 3"`,
   然后直接继续。它会记下文件指纹,并把分镜和出图请求里的人物参考都换成这张
3. 之后每一段都只用"定妆照 + 商品原图"两张当参考。定妆照是唯一允许当参考的生成图;
   登记后文件被改动过,`validate` 会报错

**先读任务关联的原片档案 `references/<ref_id>/ANALYSIS.md` 和 `TIMELINE.md`**:原片为什么有效、每一段的表情和动作跟哪个词对齐。分镜的 `intention` / `accents` / `performance` 照这两份写。

**模仿原视频的表情和场景:用文字,不用截图。** 可以看 `video_analysis/` 的宫格,把原片每个镜头的表情、
姿态、场景写进分镜的 `performance` 和 `first_frame`(例如"眉毛上扬、嘴张开说到一半、身体前倾靠近镜头";
"明亮的开放式客厅、大理石桌面、背景绿植")。截图本身不能交给 ImageGen:会把原博主的脸和原片产品一起带进来。

**当前交接状态(2026-09-20)**:

- `a2_test_en`:定妆照、5 张参考帧、`QC.json` 和 `READY.json` 均已完成;不要重复出图。下一步由 Claude 执行第 7 步英文 H3 渲染
- `a2_milk_clone_en`:`hands_only` 模式的 6 张参考帧、`QC.json` 和 `READY.json` 均已完成;不要补定妆照或人物脸。下一步同样是第 7 步
- 只有用户或 Claude 明确退回某段、删除/作废对应 READY 信号时,Codex 才重新进入第 6 步

出好的参考帧交给 H3 前要注意:

- **参考帧数不等于 H3 视频数。** 优先把连续的镜头节拍编进同一条 5 秒左右的 H3 视频,每条绑定 2–3 张 Picture;
  prompt 必须逐行写清 `<Picture N>` 在 `x–y seconds` 内负责的构图、动作和切点,不能把每张参考帧都单独渲染后再二次拼接
- 每条 H3 视频的**总参考图数**是 2–3 张。使用 1–2 张生成参考帧时可把商品原图放在最后一张补身份;
  已经使用 3 张生成参考帧时不再额外绑定商品图
- 只有一条视频塞不下时长、动作冲突明显或需要隔离重试时才拆成下一条 H3 视频;拆分依据写入 `h3_clip_plan` / `timed_shots`,不按关键帧数量机械拆分
- **参考帧里不能有原博主的脸或原片里的产品**
- 出镜人必须是虚构人物,每段都用同一个人

## 做完图怎么交给 Claude Code(自动交接)

Claude Code 在同一个文件夹里读取 `work/<job>/keyframes/READY.json` 和 `work/<job>/PREFLIGHT.json`。
**图全部写完之后再写 READY.json**,不要先写。`shot_for_shot` 先编译最终 H3 提交包,随后再封存和预检:

```powershell
D:/anaconda/envs/ugc_asr/python.exe -B scripts/build_timed_h3_prompts.py inputs/<job>/job.en.json
D:/anaconda/envs/ugc_asr/python.exe -B -m ugc_pipeline keyframe-status inputs/<job>/job.en.json --actor codex
D:/anaconda/envs/ugc_asr/python.exe -B -m ugc_pipeline preflight inputs/<job>/job.en.json --actor codex
```

确定性编译、封存、预检全部通过后才算交接完成。Claude 接手时再运行同一条 `preflight` 命令并把 actor 改为 `claude`,通过后只能消费已封存的 `segments.json`,不能在上传前手改 prompt、图片顺序或秒数。
如果封存后的稿子、分镜、商品图、QC、READY 或参考帧发生变化,预检会把当前 `READY.json` 可恢复地改名为
`READY.invalidated.<UTC>.json`,状态退回 `awaiting_keyframes`;修好后重新执行 `keyframe-status` 和 `preflight`。

```
work/<job>/keyframes/
  seg03.png            每段一张参考帧,9:16 竖图,文件名 segNN.png(NN 是分镜号)
  READY.json           图片和 QC 完成后写;门禁通过前不授权渲染
work/<job>/PREFLIGHT.json  最后一次本地预检报告
```

`READY.json` 的格式:

```json
{
  "job": "a2_test",
  "source_job_id": null,
  "segments": {
    "3": {
      "keyframe": "seg03.png",
      "extra_refs": ["target_A2_2.png"],
      "notes": "一只手握瓶,背标朝镜头;背标已用原图贴回"
    }
  },
  "generator": "codex-imagegen",
  "created_by": "codex"
}
```

- `source_job_id`:在哪一轮成片的基础上重跑。全新的英文片填 `null` 并列出全部参考帧;只有明确基于已有 H3 任务做局部重跑时才填任务 ID
  (中文版 `a2-replica-004` 的片段不能沿用到英文版)
- `keyframe` 和 `extra_refs` 是已验收的参考图资产,不是“一张图生成一条视频”的指令。H3 编译层可按
  `h3_clip_plan` / `timed_shots` 把相邻资产重新编号为同一条视频的 `<Picture 1>`–`<Picture 3>`
- `READY.json` 必须与同目录 `REQUEST.json` 的分镜集合完全一致。局部重跑可以沿用上一轮 H3 的其他已生成片段,但绝不能沿用参考原片画面
- 画面需要调整时,把调整写回 `shot_plan` 的上游分镜规格,重新生成 `h3_clip_plan` 和 `segments.json`,再执行 `keyframe-status`、`preflight`;不能直接手改两份派生产物或已封存的 H3 提示词

## 红线(任何模式都一样)

- 不拿原片的帧当参考图,不克隆原博主的声音。`video_analysis/` 下的 anchor、storyboard、cuts 图**同样算原片的帧**,
  不能以任何角色(包括"只借构图")交给 ImageGen 或 H3;构图只用文字写进分镜。`validate` 会拦
- 原稿里我们拿不出证据的宣称必须换掉;每条卖点都要挂 `product.json` 里的证据
- 出镜人是虚构的,不编亲身经历("又囤了一箱")
- `replica` 模式的稿子只做测试,不能批量发布
- 今后新生成的目标口播、H3 台词、字幕和 CTA 只用英文;历史中文转写与测试产物仅作内部证据,不得流入新成片
