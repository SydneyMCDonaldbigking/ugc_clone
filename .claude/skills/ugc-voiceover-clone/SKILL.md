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

- **本地 Windows**:编排、ffmpeg 轻量检查、写脚本、标注节拍表、写稿。**不装 Python 环境**
- **服务器 `doubleflow`**:转写、yt-dlp、H3。只能走国内镜像。工作目录 `/opt/ugc_clone`

```
/opt/ugc_clone/
  scripts/              prep.sh、transcribe.py(从本地 scripts/ 同步过去,记得去掉 \r)
  asr_venv/             转写环境
  jobs/<job>/inputs     参考视频、商品图
  jobs/<job>/work       audio.wav、frames、cuts.json、words.json
  jobs/<job>/assets     presenter.jpg
  jobs/<job>/prompts    segments.json
```

本地:`inputs/<job>/product.json`、`work/<job>/{labels,beats,script,segments}.json`、`out/<job>/`。

## S1 取素材 + S2 转写

```bash
# 服务器
/opt/ugc_clone/scripts/prep.sh jobs/<job>/inputs/ref_video.mp4 jobs/<job>/work
/opt/ugc_clone/asr_venv/bin/python /opt/ugc_clone/scripts/transcribe.py \
    jobs/<job>/work/audio.wav jobs/<job>/work/words.json
```

`prep.sh` 产出 probe、16k 音频、1fps 帧、拼图和切点。`transcribe.py` 是 faster-whisper large-v3 加逐词时间戳。

**转写环境为什么长这样。** 本来要用 WhisperX,但装不上:3.7.4 以后锁死 torch 2.8,更早的版本依赖 pyannote 3,
和 `h3director` 的 torchaudio 2.9 冲突。单独装 cu124 torch 要从阿里源下 908MB,只有 0.3MB/s。
最后的做法是:

```bash
/home/node/anaconda3/envs/h3director/bin/python -m venv --system-site-packages /opt/ugc_clone/asr_venv
/opt/ugc_clone/asr_venv/bin/python -m pip install faster-whisper yt-dlp -i https://pypi.tuna.tsinghua.edu.cn/simple
```

这样复用 `h3director` 的 torch 和 nvidia 库,又不改动它。脚本自己预加载 cuBLAS/cuDNN。

**两个环境变量缺一不可**(脚本里已设置):

- `HF_ENDPOINT=https://hf-mirror.com`:huggingface.co 直连不通,镜像约 14MB/s
- `HF_HUB_DISABLE_XET=1`:新版 huggingface_hub 默认走 Xet 直连 hf.co,会绕过镜像报 401

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

转写完先出一张带台词标注的宫格,再对可疑的句子单独加密抽帧(`scripts/tile.py`,照 hypit `media tile --transcript` 写的,
hypit 本身不装):

```bash
asr_venv/bin/python scripts/tile.py $W/../inputs/ref_video.mp4 $W/words.json $W/tile_all.jpg --every 1
asr_venv/bin/python scripts/tile.py $W/../inputs/ref_video.mp4 $W/words.json $W/tile_x.jpg --around "一定要看好配料表" --every 0.25
```

**转写认数字和同音词很差,拿烧录字幕来纠正。** 实测把"0 蔗糖 0 代糖 0 乳糖"认成"淋着糖淋带糖淋乳糖",
"希腊酸奶"认成"西纳酸"。修正写进 `ref_text_corrected`;反过来,字幕会省字,台词以转写为准。

**切点要分两种。** `scene > 0.3` 测出来的切点里,有些是同机位跳剪(只是剪掉停顿),
有些是真正的插入镜头。只有插入镜头算结构。umall_test 共 6 个切点,2.07 和 4.17 是跳剪;
6.73 俯拍整箱、9.40 杯盖特写是插入镜头,**两个都在给新信息**。

**最值钱的招式要写进 `structure_notes`。** 这条参考片的核心招式是"把自家卖点包装成挑选标准":
先说"选的时候一定要看好配料表",再把卖点当答案念。换商品时这一招要保留,只换答案。

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

## S6 分段和 H3 提示词

每段 5 秒一个连续动作,段内不切镜。**单任务不超过 20 秒 / 4 段**(25 秒会爆内存,见 HANDOFF)。

**原片的插入镜头放不进一段里。** 要么单独占一段,要么舍弃。
umall_test 把杯盖特写单独做成第 3 段(旁白是画外音,手指逐项点标签);0.8 秒的俯拍整箱并进了第 2 段的中景。

**出镜人参考图。** 服务器上没有文生图模型,只有 H3 的 ref2va / fl2va。先用文生视频出 5 秒,再截一帧:

```bash
cc_submit.py --job-id <job>-presenter-001 --prompt-file presenter_prompt.txt \
    --profile fl2va_8step --duration 5 --orientation portrait --direct-720p --seed <n>
ffmpeg -ss 4.2 -i review_ready/<id>/<id>.mp4 -frames:v 1 -q:v 2 assets/presenter.jpg
```

提示词里让人物最后两秒正对镜头不动,桌面保持空着。约 4 分钟出 768x1344,截帧可以直接用。
**4 段都绑这同一张图**,人物才能一致。这是自己要用的输入图,截出来后看一眼再用。

**参考图编号。** 实际顺序是"顶层共享图 → 上一段尾帧 → 本段图",编号从 1 连续往下排(见 `src/workflow.py`)。
开了 `first_frame_mode: previous_tail`,尾帧就变成 `<Picture 1>`,本段的图全部往后顺延。
原片是硬切的地方不要接尾帧,编号也就不会乱。

每段绑两张图,迁移范围分开写:

- `<Picture 1>` 出镜人:`identity_preserved`。特写段只写 `attribute_transfer`,只迁移手和袖子
- `<Picture 2>` 商品图:`attribute_transfer`。杯子材质、标签、奶皮质地、木勺迁移过去;
  布景布和水果**不**迁移。标签特写段改成 `fully_preserved`,并写明字不许糊、不许改写

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
  流水线目前**不支持自定义首帧**(`src/workflow.py` 里 `first_frame` 写死为空,只有 `previous_tail`)。
  不改代码的前提下有两条路:
  1. 这一段只绑商品图一张,设 `fully_preserved`,画面里只写"一只手握住把手、全程不动"。
     **a2_test 实测有效**(`a2-replica-004`,人工确认通过),保底方案没用上
  2. 保底:`scripts/packshot_clip.sh <图> <out.mp4>` 用原图做 5.2 秒慢推,1440x2560,字 100% 清楚,
     但画面里没有手;声音另外配上

改提示词不换参考图时,用 `cc_rerun.py --prompts-file '{"3": …, "4": …}'` 一次重跑多段,其余段沿用,合并后照样超分。

台词只能用 `(S1) <d>[Chinese] …</d>`。旁白也一样,描述里写明"画外音"就行。
写好后本地用占位符(`__PRESENTER__`),提交前替换成服务器路径,另存为 `segments.server.json`。

```bash
cc_submit.py --job-id <job>-replica-001 --segments-file prompts/segments.json \
    --profile ref2va_4step --orientation portrait --seed <n> --metadata '{"mode":"replica"}'
cc_status.py --job-id <id> --wait --timeout 5400 --deliver
```

umall_test 实测:4 段二采加超分,出 1440x2560、20.67 秒,耗时约 25 分钟,GPU 约 0.84 元,文件 35MB。

## S7 取回 + S8 验收

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
- 服务器上的中文字体只有 Noto Serif CJK 和 AR PL UMing,`tile.py` 会通过 `fc-match :lang=zh` 自动找到
- 转写和 H3 可以同时跑:H3 常驻约 16.5GB 显存,faster-whisper large-v3 再占约 4GB,24GB 放得下
- 耗时参考(a2_test):公钥装好后 6 分钟内完成拉起服务、转写、宫格、出镜人、节拍表、写稿、提示词并提交正片
- 不要去改 `h3director` 环境
