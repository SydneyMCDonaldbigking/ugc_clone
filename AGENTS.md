# ugc_clone — 给 Codex 的接手说明

这个仓库做一件事:拿一条别人跑通的带货口播视频,拆出节拍表,换成我们自己的商品、价格和 AI 出镜人,
再用服务器上的本地 MiniMax H3 重新生成视频。

先按这个顺序读:

1. `HANDOFF.md`:为什么做结构复用,不逐字照搬(平台查重、广告法),以及服务器的基础设施
2. `.claude/skills/ugc-voiceover-clone/SKILL.md`:完整做法和所有踩过的坑。**这是主文档**
3. `WORKFLOW.md`:阶段定义、schema、两次测试的实测记录

## 仓库里有什么

| 路径 | 内容 |
|---|---|
| `scripts/prep.sh` | 服务器:探测、抽音频、抽帧、切点 |
| `scripts/transcribe.py` | 服务器:faster-whisper 逐词时间戳(有背景音乐时加 `--vad`,见 skill) |
| `scripts/tile.py` | 服务器:带台词标注的抽帧宫格 |
| `scripts/build_beats.py` | 本地:labels.json → beats.json |
| `scripts/check_script.py` | 本地:口播稿硬检查(结构、字数、重合、禁用词、宣称证据) |
| `scripts/packshot_clip.sh` | 服务器:商品原图慢推的保底插入镜头 |
| `scripts/gen_keyframe.py` | 本地:OpenRouter 图像模型出分镜参考帧(**新任务,见下**) |
| `inputs/<job>/product.json` | 商品参数表,每条事实都带证据 |
| `work/<job>/` | labels / beats / script / segments / 提示词 |

**音视频和图片不进仓库**(见 `.gitignore`):参考视频和抽帧里是原博主的脸和作品,成片太大,
品牌产品图是别人的商标图。需要时由人在本地提供。

## 现在要你接手的:用图像模型出每段的参考帧

**问题**:H3 用的是 ref2va 多参考图模式,每段只绑"出镜人中景图 + 白底产品图"两张,构图全靠文字描述。
a2_test 的第 3 段(背标特写)因此四项全错:字糊成乱码、瓶型变了、没拍成特写、多出一只手。
另外,H3 文生视频出来的出镜人不够真实。

**做法**:

1. 用图像模型生成一个真实感更强的虚构出镜人
2. 每段先出一张参考帧,构图、手的数量、产品摆法都由图片定死,H3 只负责让画面动起来
3. 标签有密集小字的镜头,出图后把原始标签图贴回瓶身,保证字是原图像素

**模型**:OpenRouter 的 `openai/gpt-5.4-image-2`(也可以试 `google/gemini-3-pro-image`)。
key 只从环境变量 `OPENROUTER_API_KEY` 或 `~/.config/openrouter/key` 读,不要写进仓库。

**第一个测试**:`work/a2_test/keyframes/seg03_prompt.txt`,输入是 `presenter.jpg` 和 a2 背标图。

```bash
python scripts/gen_keyframe.py --prompt-file work/a2_test/keyframes/seg03_prompt.txt \
    --image inputs/a2_test/presenter.jpg --image target_A2_2.png \
    --out work/a2_test/keyframes/seg03.png --n 2
```

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
  "model": "openai/gpt-5.4-image-2",
  "created_by": "codex"
}
```

- `source_job_id`:在哪一轮成片的基础上重跑(a2_test 目前是 `a2-replica-004`)
- `keyframe` 会作为该段的 `<Picture 1>`,`extra_refs` 按顺序排在后面(路径相对仓库根目录)
- 只列有新参考帧的段,其余段沿用原片
- 画面需要调整时,可以在该段加 `"prompt_hint": "..."`,Claude 会据此改写该段的 H3 提示词

## 红线(任何模式都一样)

- 不拿原片的帧当参考图,不克隆原博主的声音
- 原稿里我们拿不出证据的宣称必须换掉;每条卖点都要挂 `product.json` 里的证据
- 出镜人是虚构的,不编亲身经历("又囤了一箱")
- `replica` 模式的稿子只做测试,不能批量发布
