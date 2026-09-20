---
name: ugc-voiceover-clone
description: 拿一条别人跑通的带货口播视频,拆出节拍表,换成我们自己的商品、价格和 AI 出镜人,用本地 H3 重新生成。凡是"照这条视频给我们的商品做一条""复刻这个口播""一模一样的口播换个商品""拆一下这条带货视频的结构""批量出口播",或者用户手上有「一条参考带货视频 + 我们的商品图/价格」时都用这个 skill。覆盖拆解(转写+切点+节拍表)、商品参数表、口播稿与自动检查、H3 分段提示词、渲染与验收。不适用于动作迁移(用 h3-motion-transfer)、纯商品广告片复刻(用 comfyui_workflow 的 product-replication)、原创菜谱片(dish-difficulty)。
---

# 带货口播复刻

参考视频是**别人的成片**,难点和 product-replication 一样:结构拿过来,内容一样都不继承。
区别在于这里有人在说话,**口播稿本身就是要复刻的东西**,所以多了转写、节拍表和稿件检查三步。

背景和论证在 `HANDOFF.md`,完整流程和实测数据在 `WORKFLOW.md`。本文件只写做法和坑。

## 先分清两种模式

| | `structure`(默认) | `replica`(只用于测试) |
|---|---|---|
| 复用什么 | 节拍、顺序、字数、语气、画面对齐 | 以上全部,再加原稿句式和口头禅 |
| 与原稿重合 | 5-gram < 10%,公共子串 < 6 字,否则 FAIL | 只报 WARN |
| 宣称和禁用词 | 拦 | **照样拦** |
| 能不能批量发 | 能 | **不能**:平台转写后做文本查重,量越大死得越快 |

用户说"一模一样""按原稿来"时可以走 `replica` 出测试片,但要把"不能批量发"说清楚,
并同时备一份 `structure` 稿。**无论哪种模式,原稿里我们拿不出证据的宣称都必须换掉**:
那些宣称是对他们商品说的,搬到我们商品上就是虚假宣传。

## 不碰的东西

沿用 product-replication 的 Never inherit 栏(品牌、logo、产品、宣称、确切配色),再加三条:

- 原达人的脸和声音:**不拿原片的帧当参考图**,测试片也不行。出镜人用 AI 生成的虚构人物
- 原稿里的效果宣称:功效、成分、"0 糖"、"接近 XX"
- 亲身经历:出镜人是虚构的,"又囤了一箱""我吃了一个月"都是编的,删掉或改成展示

可以借的是**类型特征**:年轻女生、居家餐厅、自拍中景、身后开箱。

## 分工

- **Codex / 本地 Windows:默认负责生成视频前的全部分析和准备(S1–S6)**。转写(conda 环境 `ugc_asr`,4070 够用)、
  原片档案、节拍表、商品事实、英文稿、分镜、参考帧与 QC 连续做完;`shot_for_shot` 在 READY 后确定性编译 H3 提交包,再运行 `keyframe-status` 和 `preflight`
- **Claude / 服务器 `doubleflow`:默认从 S7 开始负责出视频和成片验收**。重新运行 `preflight --actor claude` 通过后拿已封存的 `segments.json` 和参考图提交 H3,
  出片后拉回、重跑问题段并完成技术/台词验收。只能走国内镜像,工作目录 `/opt/ugc_clone`
  (2026-09-19 起。之前转写也在服务器上做,服务器经常掉线,分析就跟着卡住)

用户明确改派时可以换人,但实际执行者必须在 `events.en.jsonl` 记录 `actor`。默认情况下 S1–S6 不等待 Claude。

```
/opt/ugc_clone/
  jobs/<job>/inputs     已通过门禁的商品图和逐段参考帧
  jobs/<job>/prompts    英文 H3 segments.json
  jobs/<job>/output     H3 分段结果和合片
```

本地:`references/<ref_id>/`、`inputs/<job>/{job,product}.en.json`、`work/<job>/{beats,state}.json`、
`work/<job>/variants/`、`work/<job>/keyframes/` 和 `out/<job>/`。

## S1 取素材 + S2 转写(本地)

```bash
# 本地:建档时顺带转写(调用 conda 环境 ugc_asr)
python scripts/reference_archive.py init <video> <ref_id> --transcribe [--vad]
# 单独转写
D:/anaconda/envs/ugc_asr/python.exe scripts/transcribe.py <audio.wav> <words.json> [--vad]
```

`transcribe.py` 是 faster-whisper large-v3 加逐词时间戳。当前唯一受支持的执行环境是本地 conda `ugc_asr`;
旧的服务器 ASR 环境和 WhisperX 安装尝试只属于历史排障记录,不再作为工作流步骤。

另外 `initial_prompt` 要给一句简体中文,不然 large-v3 常出繁体。

**背景音乐重的时候,large-v3 会把整段幻觉成"请不吝点赞 订阅 转发 打赏支持明镜与点点栏目"。**
a2_test 的音频平均 -5.4dB、峰值削顶,就中了这个坑。当时是这样救回来的:

1. 先滤到人声频段:`ffmpeg -af "highpass=f=250,lowpass=f=3800,volume=-10dB,dynaudnorm"`
2. `--prompt` 填烧录字幕的原文,后半段就能认出来。
   但**提示词里写过的句子会被当成已经说过而直接跳过**,开头 6.5 秒因此整段丢失
3. 丢失的那段单独切出来,`--vad` 加一句**关键词式**提示("开箱视频,老公,发财,牛奶,纽仕兰,抖音,一箱。"),
   拿到时间锚点
4. 两段按时间拼成一个 `words.json`,并在 `notes` 里写明是怎么拼出来的。这种拼出来的时间戳,语速数字不可信,
   以字幕和宫格为准

**别在 `pkill -f` 里写会匹配到自己的词。** `ssh host 'pkill -f setup_asr_env'` 会把这条 ssh 的 shell 也杀掉,
命令直接以 127 退出。先 `ps` 找到 pid,再 `kill`。

## S3 节拍表

agent 看帧、读转写后写 `labels.json`:每拍给出时间窗、功能、镜头、画面动作、画面和台词怎么对齐、
修正后的原文。`build_beats.py` 按时间窗从 `words.json` 取文本,自动算字数、语速、停顿和段内切点:

```bash
python scripts/build_beats.py work/<job> work/<job>/labels.json
```

字段定义见 `WORKFLOW.md` 第 4 节。标注时要注意这几件事:

**1 秒 1 帧会漏掉台词。** umall_test 里"一定要看好配料表"只在 8.3–9.2 秒出现,正好落在两次抽帧之间。
所以流程是先转写,再按转写结果加密看:可疑区间用 0.25 秒甚至 0.1 秒一帧。
这和 hypit 的做法一样:抽帧密度按问题调,没有固定帧数。

补看某一段用 `scripts/media.py`(照 hypit `media` 移植,hypit 本身不装),宫格每格下面标着时间、正在说的字和前后的词:

```bash
python scripts/media.py tile <video> --transcript words.json --around "一定要看好配料表" --every 0.25 --to x.jpg
python scripts/media.py tiles <video> --transcript words.json --every 1 --rows 3 --to overview/   # 分页
python scripts/media.py boundaries <video>        # 12 帧/秒、阈值 0.1 的画面突变候选,不等于切点
python scripts/media.py frames <video> --at 6.9,7.3 --to frames/
python scripts/media.py cut <video> --start 6.5 --end 8 --to clip.mp4
```

`--around` 按转写原文匹配,转写认错的字要照错的写(a2 的"蛋白质"被认成"但白质",要搜"白质")。

**转写认数字和同音词很差,拿烧录字幕来纠正。** 实测把"0 蔗糖 0 代糖 0 乳糖"认成"淋着糖淋带糖淋乳糖",
"希腊酸奶"认成"西纳酸"。修正写进 `ref_text_corrected`;反过来,字幕会省字,台词以转写为准。

**切点要分两种。** `scene > 0.3` 测出来的切点里,有些是同机位跳剪(只是剪掉停顿),
有些是真正的插入镜头。只有插入镜头算结构。umall_test 共 6 个切点,2.07 和 4.17 是跳剪;
6.73 俯拍整箱、9.40 杯盖特写是插入镜头,**两个都在给新信息**。

**最值钱的招式要写进 `structure_notes`。** 这条参考片的核心招式是"把自家卖点包装成挑选标准":
先说"选的时候一定要看好配料表",再把卖点当答案念。换商品时这一招要保留,只换答案。

### 原片档案:ANALYSIS.md + TIMELINE.md(照 hypit 的 reference-video 流程)

节拍表只记"每一拍是什么功能",不够 H3 用。**每条参考片先建一个档案,写完才能拿去改编**;
同一条参考片换商品时直接复用,不用重写。样例:`references/theland_milk_unbox/`。

```
references/<ref_id>/
  source.mp4 / probe.json / transcript.json / cuts.json / boundaries.json
  evidence/overview/   全片宫格,1 秒 1 帧,每页 12 格
  evidence/cuts/       每个切点前后 0.5 秒,0.125 秒一帧
  evidence/lines/      每句台词前后 0.3 秒,0.25 秒一帧
  evidence/looks/      补看时生成的
  ANALYSIS.md          整条片为什么有效
  TIMELINE.md          按原片时间分段,每段对齐台词,写"→ 改编"
  PROGRESS.md          只在写的过程中存在:还没弄清的问题
```

**流程(约 20 秒自动 + agent 阅读写作):**

1. 建档,一条命令出全部事实、证据宫格和三份文档骨架:
   ```bash
   D:/anaconda/envs/ugc_asr/python.exe scripts/reference_archive.py init <video> <ref_id> --transcribe [--vad]
   python scripts/reference_archive.py init <video> <ref_id> --transcript words.json # 已有转写时
   ```
   骨架里台词时间、证据路径、切点、低置信度的字都已填好;需要判断的地方是 `<!-- TODO -->`
2. **先看完整片宫格(`evidence/overview/`),再写 `ANALYSIS.md`**:它想让观众得出什么结论、情绪弧线、
   每个画面和声音元素在做什么、哪些作用要保留。事实和解读分开写
3. **按段写 `TIMELINE.md`**:骨架按台词句子切,同一作用的相邻句合并,段内有插入镜头就拆开。
   每段写画面里有什么、谁在动、跟哪个词对齐、对观众起什么作用,末尾一行"→ 改编"。
   看不清的地方补看:`python scripts/reference_archive.py tile <ref_id> --around "<台词>" --every 0.1`
4. **回头改 ANALYSIS**:细看常会推翻整体判断(a2 里"代购"那句,加密看才发现她是边说边从箱里抽两盒)
5. PROGRESS 里的问题逐条解决,删掉 PROGRESS,然后 `python scripts/reference_archive.py check <ref_id>`
   出现 READY 才算写完。任务文件 `job.json` 用 `reference_archive` 关联档案;档案没写完,`validate` 会报错

**每段必须写镜头,照原片来。** TIMELINE 每段一行 `镜头:景别 | 机位高度与角度 | 运动 | 构图`,`check` 会查;
分镜的 `camera` 照它填,出图和 H3 提示词都会带上这一行。a2_milk 第一版没写镜头,Codex 只能猜,
把原片的"第一人称高位俯拍、手握瓶子贴近镜头"画成了"瓶子立在桌上平视拍",六段只对上一段(开箱俯拍)。
另外,"商品只摆原图有的角度"指的是**商品朝向**(正面或背面对镜头),不是"立在桌上平视拍";
拿在手里还是放在桌上、镜头角度都照原片。

**出镜方式要在档案里判断,不能默认有人。** 前两条参考片都是真人出镜,流程一度把"出镜人"写死成默认。
第三条(a2_milk)原片只有手和商品,Codex 照默认先拍了个真人讲解,用户叫停才改回来。现在 ANALYSIS 事实表必须写
`出镜方式`(`generated_fictional` / `hands_only` / `none`),`check` 会查;任务的 `presenter.mode` 照它填,
决定要不要定妆照、用哪个出图模板。

两条原则(来自 hypit transformations):
- **保留作用,重做形式**。"说品牌时手拍在箱子上"的作用是"卖点配一个手上的证据",
  没有品牌纸箱就让手落在瓶子上
- **时间跟着新台词的词走,不跟原片秒数**。原片"说到价格时挑眉",我们就在新台词说价格的那个词上挑眉

写档案时会发现稿子丢了作用:a2 英文稿把"他不知道"(整条片的反转、悄悄话)写成了 "He was confused.",
对照 TIMELINE 改成 "He has no idea."。

## S4 商品参数表

`inputs/<job>/product.json`:每条事实都要有 `id` 和 `evidence`。拿不到的字段填 `null`,**不许编**。
`forbidden_claims` 要列出原稿里有、但我们没证据的宣称,写稿时逐条对照。

价格只说运营给的数字。没给原价就不做"原价划掉";没给整箱价,就不把单价乘成整箱价说出来,听着像优惠。

## S5 写稿

每行对应一个 H3 分段,标明覆盖哪几拍、引用了哪些事实:

```bash
python scripts/check_script.py work/<job>/beats.json inputs/<job>/product.json work/<job>/script.json
```

检查项:结构和节拍表对齐、字数在预算内(预算 = 原拍字数 × `time_scale`,容差 `char_tolerance`)、
与原稿的重合、禁用词、宣称是否挂了证据、有没有阿拉伯数字。
数字一律写成汉字,比如"六块八毛九澳币"。`adaptations` 字段逐拍写清改了什么、为什么改。

原片 16.5 秒 107 字,语速 6.5 字/秒;我们用 20 秒说差不多的字数,约 5 字/秒,H3 读起来不赶。

umall_test 里原稿到我们商品的对照(同类商品可以直接参考):

| 原稿 | 为什么不能用 | 换成 |
|---|---|---|
| 圆了一大圈,拿无糖酸奶当代餐 | 暗示减脂功效,我们没有低糖证据 | 嘴馋,当下午茶 |
| 趁着这个价格,一大箱十桶 | "趁着"暗示促销,没依据 | 报实价,一大箱十二杯 |
| 我又赶紧囤了一大箱 | "又"是复购经历,出镜人是虚构的 | 去掉"又" |
| 要选 0 蔗糖 0 代糖 0 乳糖的 | 他们的卖点 | 配料表里真有的:芒果果泥、西柚果肉 |
| 就很接近于希腊酸奶 | 他们的对比宣称 | 就是杨枝甘露的味道 |

## S6 参考帧 + S7 H3 提示词

关键帧是构图资产,不是“一帧一条 H3 视频”。优先把相邻节拍编进同一条约 5 秒的视频:每条绑定 2–3 张 Picture,
并在 prompt 里逐项写 `<Picture N>` 的起止秒数、动作和硬切/遮挡切时刻。普通结构复用一条视频通常只有 1–2 个内部切点;
`shot_for_shot` 则保留 Hypit 检出的全部原切点,可在同一条约 5 秒视频内包含多个短促小镜头。只有时长放不下、动作相互冲突或需要隔离重试时才拆成下一条视频。
合并前还必须检查场景兼容性:同条 H3 视频内的生成参考帧要共享一个 `scene_id`,包括台面材质、主场景和光线时段。
白色大理石、深色木桌、亚麻桌旗等冲突参考不能放在同一条里;秒点提示词能规定切镜,不能阻止模型混合场景。

**声音是逐段决定的,同一个任务也不保证同一个人。** 流水线**不支持音色参考**(导演台模板里的 `@A1` 没接进
`build_generation_prompt`),声音只由提示词和 seed 决定,而且**每一段各决定一次**。

2026-09-20 实测(放在一个任务、同一个 seed 里渲染,按 ASR 词区间测基频中位数):

| 任务 | 各段基频 | 跨段差 |
|---|---|---|
| `a2milk-en-full` 6 段 | 131 / 137 / 156 / **200** / 142 / 138 Hz | 52.5% |
| `crown-en-full` 4 段 | 150 / **198** / 140 / 163 Hz | 40.7% |

两条片子都是**只有一段**明显跳高(听感上换成了另一个人),其余各段彼此在 19% 以内。
所以"一个任务 = 一个声音"是错的:一个任务只是减少漂移,拆成多个任务会更差(之前 A/B 两批是 165 vs 137 Hz)。

**但变量是"段数",不是"描述"。** 2026-09-20 后续实测推翻了"描述只能限定一类人、锁不住个体"的判断:
把整段稿子放进**一个 segment**,并在提示词里写死具体音色规格,四句的基频是 216 / 208 / 208 / 191 Hz,
**离散度 13.5%**,低于 15% 的换人线。段内没有重新抽签的机会,所以描述够用;跨段才会换人。

怎么办:

- **首选:配音母带(voice master)。** 画面全部渲成静音,另外单独生成一条只有人声的视频,抽出音轨再合成。
  声音 100% 一致,画面返工也不用重做声音,而且不需要外接 TTS
- 要留 H3 每段自己的声音,就用 `cc_rerun.py` 把跳高的那一段换个 seed 重跑,直到落回其余段的区间
- 检查用 `python scripts/voice_check.py a.wav b.wav`(整段音频)。**有倒奶、撕包装这类周期性响动时它会被带偏**,
  要准就按 ASR 的词区间取帧再测;自相关还容易报成 2 倍频,判读时先想一下倍频错误

### 配音母带的做法(2026-09-20 验证通过)

```bash
cc_submit.py --job-id voice-master-01   --segments-file .../segments.json   --profile fl2va_8step --width 480 --height 832 --seed <seed>
```

- **文生视频、单段、不挂参考图**。画面给一个静止的空桌面,它只是音轨的载体,最后丢掉
- 提示词里单开一段 `voice_specification`,把口音、性别、年龄、语气、语速一次写全,并明确"全片只有一个说话人,
  音高、音色、口音、年龄在任何时刻都不变"
- **一定要加 `--direct-720p`** 关掉二采和 RealESRGAN。这个 flag 和 `--width/--height` 互斥,二选一;
  漏了它会花十几分钟给一条要丢掉的画面做超分
- 出片后机器预审会以 **`疑似卡帧`** 打回(静止画面必然触发),文件在 `rejected/<job>/` 下,照常取用即可
- 抽出音轨后按各条 clip 的窗口起点摆放每一句(用 ASR 的句边界切,首尾各留 0.12 秒,两端加 20ms 淡入淡出),
  再和画面自带的动作声混合

**能塞多少词**:54 词的稿子在 15 秒里说完了(14.38 秒,0 个低置信词),但语速 215–247 wpm,
偏快(自然口播是 160–175)。句间停顿可以靠摆放补,**句内语速补不了**,要自然就得放开单段 15 秒上限
(`src/workflow.py` 和 `src/rerun.py` 各一处 `2 <= duration <= 15`)。

### shot_for_shot:H3 认内部硬切

`crown-sfs-en-2` 实测:4 条 clip 里写了 21 个微镜头、17 个内部切点,成片检测到 **13 个真实内部切换**
(另 3 个是 clip 接缝)。对照组是同一批素材按 4 段 5 秒平铺、段内 0 刀的旧版。

所以按秒写 `timed_shot_timeline` 是有效的,但要知道两件事:

- **是"大致跟着走",不是逐帧对齐**:时间偏 0.3–0.7 秒,切点越密漏得越多(6 刀挤在 5 秒里只出 4 刀)
- 检测切点别用 `select=gt(scene,t)`,这套素材上它一个都测不出来。改成自己算逐帧灰度差
  (96×170、阈值取 `max(mean*4, p97)`、相邻 0.15 秒内合并),先拿一条已知接缝数的片子验方法再用

### 服务器重启后的两个坑

- **worker 必须用 `conda run --no-capture-output -n h3director python -m src.worker` 起**。
  直接用 `/root/miniconda3/envs/h3director/bin/python -m src.worker` 会继承干净 PATH,
  找不到装在 env 里的 ffmpeg,四条画面全渲完了才在合并那步报 `FileNotFoundError: 'ffmpeg'`
- ComfyUI 和 worker 都不会自动起,`jobs/inbox/` 里的任务会一直躺着不动。先 `curl 127.0.0.1:8188` 确认

### H3 自己会出动作声

即使提示词写了 `no generated audio`,H3 照样生成动作声,而且是跟画面对上的
(crown 14.50s 的饼干脆响:峰值 0.914、高频占比 0.27、0 个浊音帧,是干净的宽带瞬态)。
**要脆响不用从原片剪**——原片的录音和原片的画面是同一类资产,同样不能进成片。

代价是它有时**连人声一起生成**。查法不是看 ASR 的文字(它在响动上会幻听出
"Thank you for watching""I'll see you guys in the next video" 这类句子),而是量**浊音帧密度**:
碰撞响动是 0 浊音帧,连续人声是每秒 24–29 帧(共 31 帧)。`crown-sfs-en-2` 的 S04 就有连续 4 秒的类人声哼唱。

**单任务上限(2026-09-20 服务器代码已改,旧的"20 秒 / 4 段"作废)**:最多 20 段,每段 2–15 秒,总时长没有硬上限。
超分不再对整条一次性做:合并成一条后按 `chunk_seconds`(当前 18 秒)切块,逐块超分再拼,所以 25 秒爆内存那个限制没有了。
提交前用 `grep -n "MAX_SEGMENTS" src/workflow.py` 和 `grep -n chunk_seconds config/*.yaml` 复核当前值。

**原片的插入镜头可以放进同一条 H3 视频。** 给插入镜头分配自己的 Picture,在
`timed_picture_timeline` 里写清起止秒数和切点即可。单独拆视频只用于时长、动作冲突或重试隔离,不能按关键帧数量机械拆。

**逐镜头节奏模式。** 用户要求 `shot_for_shot` 时,`shot_map.json` 是时间主表:原片每个切点和小镜头顺序都保留,
英文台词在原时间窗内改写,不能反过来拉长或压缩镜头。用 `build_timed_h3_plan.py` 把全部小镜头编进少量 H3 视频,
取回后用 `check_shot_rhythm.py` 对实际硬切逐项验收;默认漂移超过 0.13 秒、漏切或多切都退回该段重跑。

**三视角场景包、出镜人和分镜参考图。** 当前默认由 Codex 会话内置 ImageGen 在本地完成。先从原片场景的文字描述生成无人物、无商品的 `eye_level` 基础背景,再以它为场景身份生成同一张桌子的 `oblique_45` 和 `overhead_90`;`surface` 是桌子身份硬锁,其余场景字段为软引导。近景允许裁切、视差、道具露出和局部光感自然变化;商品清晰而背景虚化或形成浅景深散景是合格表现。原片截图不能交给 ImageGen。
`generated_fictional` 再出 3 张不带商品的候选定妆照并登记唯一的 `presenter_master.png`;
`hands_only` 和 `none` 不生成定妆照。每个分镜都从相机角度匹配的已登记场景母版、已登记定妆照(如需要)和商品原图重新生成,
验收后写 `QC.json`,图片全部完成后才写 `READY.json`。`shot_for_shot` 先从获批的
`shot_plan` / `h3_clip_plan` / READY 图片路径确定性编译最终 `segments.json`,随后运行:

```powershell
D:/anaconda/envs/ugc_asr/python.exe -B scripts/build_timed_h3_prompts.py inputs/<job>/job.en.json
D:/anaconda/envs/ugc_asr/python.exe -B -m ugc_pipeline keyframe-status inputs/<job>/job.en.json --actor codex
D:/anaconda/envs/ugc_asr/python.exe -B -m ugc_pipeline preflight inputs/<job>/job.en.json --actor codex
```

`keyframe-status` 会先逐切点核对 `shot_map`、`shot_plan`、`h3_clip_plan`,并确认 `segments.json` 与确定性编译结果逐字段相同,
再将渲染输入哈希封存进状态。封存后任何稿子、分镜、prompt、Picture 顺序、商品引用、QC、READY 或参考帧变化都会让预检失败;
预检会把旧 READY 改名为 `READY.invalidated.<UTC>.json` 并退回 `awaiting_keyframes`,修复后必须重新封存。

**参考图编号。** `READY.json` 记录已验收的图片资产;编译 H3 时按 `h3_clip_plan` / `timed_shots` 把相邻 keyframe
重新编号为一条视频的 `<Picture 1>`–`<Picture 3>`。每条视频总共绑定 2–3 张 Picture:有 1–2 张生成 keyframe 时,
商品原图通常放最后一张补身份;已有 3 张生成 keyframe 时不再加第 4 张。每张图的时间窗和迁移范围必须分开写。
原片截图、anchor、storyboard、cuts 和上一段生成的 keyframe 都不能作为新的生成参考。

**提示词里写了什么,画面里就会出现什么**(a2_test 第一版有两处穿帮,都出在我自己的写法上):

- **手的数量要写死。** 特写段写了"左手拿瓶,右手食指伸进来点标签",成片里就是两只手。
  用户要的是一只手拿着瓶子展示背面。原片的产品特写本来也只有一只手入画。
  要写成"Exactly one hand is in frame… her other hand never appears",负面约束里再补一句"never a second hand"。
  umall_test 的"手指点标签"能成立,是因为杯子小、镜头近;2L 瓶子一只手就占满了画面
- **别用有歧义的词称呼道具。** 用 "carton" 指纸箱,但 carton 也有"纸盒奶"的意思,
  第 4 段就冒出一盒原片那样的纸盒奶。纸箱写 "plain brown cardboard box";
  不需要纸箱的段落直接不提它,负面约束里写清"No milk cartons, no paper drink boxes, no tetra packs"
- **商品形状先对着图写,别凭印象。** a2_test 所有 H3 提示词都写了 "built-in handle",
  但正背两张产品图上只有肩部两块内凹握槽,没有能穿过去的孔。Codex 做参考帧时发现了这个问题,
  它的判断是对的;004 没画出大把手只是运气。现在形状描述写在 `product.en.json` 的 `visual_identity` 里,
  并注明依据哪张图(`geometry_evidence`);没有侧面图的角度不要让模型去猜
- **每段都要写"画面里唯一的产品是 `<Picture N>`"。** 原片的产品形态(小纸盒)和我们的(2L 瓶)越像同一品类,
  模型越容易把原片的形态"补"进来

- **别写互相矛盾的约束。** 第 2 段同时写了"拿出一瓶"和"箱里始终正好六瓶",还写了"把箱子朝镜头倾斜",
  成片里瓶子就塌了下去。写法要改成:箱子全程不动;哪一瓶被拿走说清楚;剩下几瓶"保持直立不动";
  再补一句硬塑料"never sagging, collapsing, squashing"
- **密集小字的特写,ref2va 画不出来。** 背标特写同时绑了出镜人中景图和白底棚拍背标,四项全错:
  字糊成乱码、瓶型变了、构图没拍成特写、多出一只手。原因有两个:
  出镜人图会把构图拉回中景;ref2va 本质是"参考着重画",营养成分表这种小字必然糊。
  当前用逐段 keyframe 固定首屏构图;密集标签仍有两条保底路:
  1. 这一段只绑商品图一张,设 `fully_preserved`,画面里只写"一只手握住把手、全程不动"。
     **a2_test 实测有效**(`a2-replica-004`,人工确认通过),保底方案没用上
  2. 保底:`scripts/packshot_clip.sh <图> <out.mp4>` 用原图做 5.2 秒慢推,1440x2560,字 100% 清楚,
     但画面里没有手;声音另外配上

普通历史任务改提示词不换参考图时,可用 `cc_rerun.py --prompts-file '{"3": …, "4": …}'` 一次重跑多段。
`shot_for_shot` 不允许在服务器端手改已封存 prompt:先把调整写回本地分镜,重新编译、封存、预检后再提交或重跑。

**H3 很吃"态度 + 重音"(照 hypit video-direction)。** 分镜每段写两个字段,`validate` 会检查:

- `intention`:一句话定这一段的态度,是她对内容和对观众的关系,
  例如 "She is showing off a find to a friend, barely containing how pleased she is with the deal."
- `accents`:最多三个,每个钉在这一段台词里**真实存在的词**上,写那一刻的反应,
  例如 `{"at": "seventy-nine", "reaction": "eyebrows lift into a pleased, knowing smile"}`

编译 H3 的 `detailed_description` 时:第一句写态度,台词按分句放,重音词所在的分句后面紧跟对应反应,
其余分句不配动作。几条注意:
- **不要每句都配一个动作**,那是排舞,不是导演
- **不要让手指比数字**,数量交给台词和后期字幕
- **台词里说到的东西不等于画面要出现的东西**:"six bottles" 是她说的话,不是让模型在画面上写 6

普通真人口播的新任务台词只能用 `(S1) <d>[English] …</d>`。`shot_for_shot` 的 H3 层必须静音,
精确裁切后再合入一条连续英文母带;此时 `audio_mode: dialogue` 表示最终成片有英文声音,
`render_plan.h3_audio_mode: silent` 表示 H3 自身不发声。`[Chinese]` 只存在于历史 `replica` 测试产物,不得复制到新成片。
写好后本地用占位符(`__PRESENTER__`),提交前替换成服务器路径,另存为 `segments.server.json`。

```bash
cc_submit.py --job-id <job>-replica-001 --segments-file prompts/segments.json \
    --profile ref2va_4step --orientation portrait --seed <n> --metadata '{"mode":"replica"}'
cc_status.py --job-id <id> --wait --timeout 5400 --deliver
```

umall_test 实测:4 段二采加超分,出 1440x2560、20.67 秒,耗时约 25 分钟,GPU 约 0.84 元,文件 35MB。

## S7 取回 + S8 验收

- 上传或提交 H3 前先运行 `D:/anaconda/envs/ugc_asr/python.exe -B -m ugc_pipeline preflight inputs/<job>/job.en.json --actor claude`;只有 PASS 才继续。`shot_for_shot` 只能消费已封存的 `segments.json`,不能再改 prompt、秒数或图片顺序
- 用 `scp` 取回成片和 `report.json`,用 `sha256sum` 对照 `qa.technical.sha256`(本地没装 paramiko,不用 `cc_fetch.py`)
- **台词核对**:从成片抽出音轨,跑同一个 `transcribe.py`,和 `script.json` 逐句对。
  置信度低于 0.3 的字,多半是 H3 读错了,不是转写的问题。
  umall_test 里"就拿这个"被转成"生出来这个"(置信度 0.10),"西柚"被转成"稀有"。这些位置交给人去听
- **画面不看**:仓库规则是成片不抽帧、不读预览图,人物一致性、标签小字、道具形状都交给人工。
  告诉用户该看哪几秒、看什么
- 超过 30MB 的文件只能在桌面端看,交付时要说明
- 哪段有问题就用 `cc_rerun.py` 只重跑那一段;改台词就用 `--prompt-file`(仅限单段重跑)

## 服务器操作的坑

- 租用机器,**IP/端口和 `authorized_keys` 重启后会变**。连不上先要新地址;公钥让用户自己用密码重装,不要替用户输密码
- 重启后 ComfyUI 和 worker 都要手动拉起(命令见 HANDOFF 5.1),conda 要写全路径
- 用 `nohup … < /dev/null &` 启动;就算这样,ssh 会话也可能挂着不退出,要给 Bash 设超时或放到后台跑
- `cc_status.py` 等脚本必须在 `/opt/MINIMAXH3_2PASS_Autoworkflow` 目录下跑,否则会去找 `/root/config/…`
- 本地脚本传上去后要 `sed -i 's/\r$//'`,不然换行符不对
- 本地的 `scp` 是 Windows OpenSSH 版,`host:/path/{a,b}` 这种大括号不会展开,要把文件逐个列出来
- 历史中文字幕所需字体只与旧 `replica` 产物有关;新的目标口播、字幕和 CTA 全部使用英文
- 耗时参考(a2_test 历史测试):公钥装好后约 32 分钟得到首条完整成片;不能把这个数字当成当前英文流程 SLA
- 不要去改 `h3director` 环境
