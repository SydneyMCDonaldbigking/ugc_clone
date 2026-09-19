# ugc_clone — 两个 agent 的共同说明(Codex 读本文件,Claude Code 通过 CLAUDE.md 读同一份)

## 谁负责什么(以这张表为准,其他文档冲突时照这里)

**原则:本地做全部分析、稿子和参考图;服务器只拿稿子和参考图出 H3 视频。**
默认负责人如下;用户明确指派时可以换人,换人的一方在 `events.en.jsonl` 里写 `"actor"`。

| # | 阶段 | 负责 | 在哪 | 怎么做 | 产出 | 做完的信号 |
|---|---|---|---|---|---|---|
| 0 | 给素材 | **用户** | — | 参考视频、商品图、价格、卖法、目标语言 | `inputs/<job>/` 原始文件 | 用户在对话里说"开始" |
| 1 | 建档 + 转写 | **Claude** | 本地(conda `ugc_asr`) | `python scripts/reference_archive.py init <视频> <ref_id> --transcribe [--vad]` | `references/<ref_id>/` 事实、证据宫格、文档骨架 | 命令跑完 |
| 2 | 写原片档案 | **Claude** | 本地 | 看宫格写 `ANALYSIS.md`、`TIMELINE.md`,补看用 `reference_archive.py tile` | 两份档案 | `reference_archive.py check <ref_id>` 显示 READY |
| 3 | 商品参数表 | **Claude**(事实只能来自用户和包装图) | 本地 | 每条事实挂证据,拿不到的填 null | `inputs/<job>/product.en.json` | `validate` 通过 |
| 4 | 节拍表 + 稿子 | **Claude** | 本地 | `build_beats.py`,英文稿按节拍表写 | `beats.json`、`variants/vNNN/script.en.json` | `validate` 通过 |
| 5 | 分镜 + 出图请求 | **Claude** | 本地 | `first_frame` / `intention` / `accents` 照 TIMELINE 写,`build_keyframe_prompts.py` 生成提示词 | `shot_plan.json`、`keyframes/REQUEST.json`、`segNN_prompt.txt` | `validate` 通过,**Claude 告诉用户"可以交给 Codex 出图了"** |
| 6 | 定妆照 + 参考帧 | **Codex** | 本地(Codex 自带 ImageGen) | 见下方"Codex 的出图规矩" | `presenter_master.png`、`keyframes/segNN.png`、`QC.json` | Codex 最后写 `keyframes/READY.json` |
| 7 | 编 H3 提示词 + 渲染 | **Claude** | 编译在本地,渲染在服务器 | 读 READY,按"态度 + 重音"编 `segments.json`,上传、`cc_submit`、单段 `cc_rerun` | 成片 | `cc_status` 出片 |
| 8 | 验收 | **Claude**(技术 + 台词)、**用户**(画面) | 本地 | 成片再转写对台词;画面交给用户看 | 验收结论 | 用户说"通过" |

几条边界:

- **转写只由 Claude 在本地做**(第 1 步)。Codex 不跑转写、不碰服务器
- **Codex 只做第 6 步**。第 1-5 步的产出是它的输入;发现输入有问题(比如分镜要求的画面画不出来),
  写进 `QC.json` 的说明里交回,不自己改稿子和分镜
- **服务器只在第 7 步出现**。服务器掉线只影响第 7 步,前面的步骤照常做
- 每一步都有"做完的信号";没看到上一步的信号,下一步不开始

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

## 现在要你接手的:用 Codex 内置 ImageGen 出每段参考帧

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
   - 商品只摆原图有的角度:竖直放,正面或背面对镜头;拿起、倾斜、倒奶交给 H3
   - 提示词用 `build_keyframe_prompts.py` 生成,约 150 词、只写正面描述;不要自己往里加"不要 XX"
5. 标签有密集小字时,不得让生成模型重画文字;改用原商品图像素或交给 Claude 走已验证的 `fully_preserved` / 慢推保底路径
6. 全部图片完成后,最后写 `work/<job>/keyframes/READY.json`,然后停止

**明确不做**:

- 不接 OpenAI Image API,不接 OpenRouter,不读取或配置任何图像 API key
- 不上传服务器,不提交 H3,不重跑视频,不做最终成片验收
- 不改 Claude 的监听、服务器和 H3 编排逻辑

以上后半段工作由 Claude Code 在看到 `READY.json` 后接手。

**6a 定妆照(自动,不用等用户)**

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

**当前任务(a2_test_en,2026-09-19 审查后)**:先做 6a 定妆照,再做 6b 参考帧,做完直接往下,全程不用停。状态见 `work/a2_test/keyframes/QC.json`。

1. **seg01 重出**:之前那版参考了原片帧(`video_analysis/anchor_s01.jpg`),已作废。只用 `presenter.jpg` + `target_A2_1.png` 和分镜文字
2. **seg02、seg02b 重出**:同样的原因作废;它们用 seg01 当人物参考,所以要等新的 seg01 出好再做
3. **seg03 保留**:当时只用了出镜人图和背标图,不受影响
4. **seg04 继续**:包装还在被重画;如果还是做不到,就在 QC 里写明,交给 Claude 用 H3 `fully_preserved` 或慢推保底
5. 提示词用 `python scripts/build_keyframe_prompts.py inputs/a2_test/job.en.json` 重新生成(已经更新过一次)

出好的参考帧交给 H3 前要注意:

- 每段绑一张参考帧,再加一张产品图作补充,迁移范围分开写(见 skill 的 S6)
- **参考帧里不能有原博主的脸或原片里的产品**
- 出镜人必须是虚构人物,每段都用同一个人

## 做完图怎么交给 Claude Code(自动交接)

Claude Code 在同一个文件夹里盯着 `work/<job>/keyframes/READY.json`。你**最后一步**写这个文件,
Claude 看到后会自动接手:检查图 → 传服务器 → H3 单段重跑 → 出片。**图全部写完之后再写 READY.json**,
不要先写。

```
work/<job>/keyframes/
  seg03.png            每段一张参考帧,9:16 竖图,文件名 segNN.png(NN 是分镜号)
  READY.json           最后写
```

`READY.json` 的格式:

```json
{
  "job": "a2_test",
  "source_job_id": "a2-replica-004",
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

- `source_job_id`:在哪一轮成片的基础上重跑。**英文版 a2_test_en 是整条新片,填 `null`**,并列出全部参考帧
  (中文版 `a2-replica-004` 的片段不能沿用到英文版)
- `keyframe` 会作为该段的 `<Picture 1>`,`extra_refs` 按顺序排在后面(路径相对仓库根目录)
- 只列有新参考帧的段,其余段沿用原片
- 画面需要调整时,可以在该段加 `"prompt_hint": "..."`,Claude 会据此改写该段的 H3 提示词

## 红线(任何模式都一样)

- 不拿原片的帧当参考图,不克隆原博主的声音。`video_analysis/` 下的 anchor、storyboard、cuts 图**同样算原片的帧**,
  不能以任何角色(包括"只借构图")交给 ImageGen 或 H3;构图只用文字写进分镜。`validate` 会拦
- 原稿里我们拿不出证据的宣称必须换掉;每条卖点都要挂 `product.json` 里的证据
- 出镜人是虚构的,不编亲身经历("又囤了一箱")
- `replica` 模式的稿子只做测试,不能批量发布
- 今后新生成的目标口播、H3 台词、字幕和 CTA 只用英文;历史中文转写与测试产物仅作内部证据,不得流入新成片
