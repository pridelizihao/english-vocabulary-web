# AGENTS.md

给在这个仓库里写代码的人（以及 AI 代理）的一份说明。动手前先读这一页。

## 1. 项目是什么

英语单词背诵 Web 应用：Django 5 + DRF 提供 JSON API，Vue 3 + Vite 提供单页前端，数据存在 SQLite。
核心闭环是「选词典 → 每日新词 + 到期复习 → 卡片/填空作答 → 按记忆曲线安排下次复习」。

## 2. 目录结构

```
backend/                       Django 项目
  config/                      settings / urls / wsgi
  vocabulary/                  唯一的业务 app
    models.py                  Dictionary / Word / UserDictionary / UserWordProgress / AnswerLog / EmailAddress / EmailVerification
    services.py                复习调度 schedule() 与导入解析、批量写库
    email_codes.py             邮箱验证码：生成/加盐哈希/冷却与频率限制/发信/核销
    views.py                   HTTP 层（函数视图为主 + 一个 ModelViewSet）
    serializers.py             输出结构，含每个词的 preview 间隔文案
    urls.py                    路由（显式路由必须写在 router 之前）
    admin.py                   已配 list_display / search_fields，别再退回裸 register
    management/commands/       seed_dictionaries / seed_wordlists / import_dictionary / enrich_examples / annotate_cefr
    tests.py                   后端用例（当前 62 个）
    migrations/0002_*.py       注意：含大小写去重逻辑，不要随手删
frontend/
  src/api.ts                   唯一请求入口：ApiError、CSRF、超时、中文错误
  src/lib/study.ts             纯函数：填空遮罩、队列、格式化（node 可直接测）
  src/lib/profile.ts           学习面板的纯函数（热力图分档、按周分列）
  src/lib/chart.ts             图表纯函数（柱子/折线坐标、保持率与校准结论文案）
  src/lib/words.ts             词表浏览的纯函数（查询串、分页、幂等 token、时间格式）
  src/lib/router.ts            hash 路由：/ · /auth · /words/:id · /words/:id/:wordId · /profile · /study/:id · /done/:id
  src/composables/useSession.ts 全局学习会话状态与动作
  src/composables/useSpeech.ts  朗读链路（词典音频 → 本地英文语音 → 有道兜底）
  src/views/*.vue              Auth / Dictionaries / Words / WordDetail / Study / Done / Profile
  src/App.vue                  壳层 + 路由同步 + 错误/提示条
  tests/*.test.mjs             node:test，纯逻辑
data/
  sources/                     原始词表（CET.json、definitions.json）
  imports/                     可直接导入的 3500/5000 词 CSV
  examples.json                例句 + 中文翻译（enrich_examples 的数据源）
  samples/words.csv            CSV 导入模板
  scripts/build_wordlists.py   从 sources + examples 生成 imports
deploy/                        systemd unit + nginx 站点配置（原生部署用）
docs/                          设计说明、审查报告、部署说明（deploy.md）
```

## 3. 环境

- Python 虚拟环境在 `.venv/`（**不是** `.env`；`.env` 已被 `.gitignore` 留给真正的环境变量文件）。
- Node.js 22+，前端依赖已 vendored 在 `frontend/node_modules`。
- 默认端口：Django `8000`，Vite `5173`，nginx 容器 `8080`。

```bash
# 后端
cd backend
../.venv/Scripts/python.exe manage.py migrate        # Windows
# Linux/macOS: ../.venv/bin/python manage.py migrate
../.venv/Scripts/python.exe manage.py seed_dictionaries
../.venv/Scripts/python.exe manage.py seed_wordlists # 导入 3500/5000 并发布
../.venv/Scripts/python.exe manage.py enrich_examples # 从 data/examples.json 补例句
../.venv/Scripts/python.exe manage.py runserver

# 前端（另开一个终端）
cd frontend
npm run dev
```

## 4. 常用命令

```bash
# 后端测试（提交前必须全绿）
cd backend && ../.venv/Scripts/python.exe manage.py test

# 前端
cd frontend
npm run typecheck   # tsc --noEmit，只覆盖 .ts（没有 vue-tsc）
npm run test        # node --test --test-isolation=none，纯逻辑，不需要浏览器
npm run build       # vite build，产物在 frontend/dist（已入库：部署机不装 Node，pull 即可用）
```

## 5. 业务规则（改之前务必确认）

- **间隔**：`good` 第 1/2/3 次分别 1/3/7 天，之后 `interval × ease`；`easy` 前两次 4/9 天，之后 `interval × ease × 1.3`；`hard` 至少 1 天，`×1.2`；`again` 归零、10 分钟后、`streak` 清零。
- **掌握**：`interval_days >= 21` 才算 `mastered`（不是答对一次就算）。
- **ease**：初始 2.5，区间 `[1.3, 3.2]`。
- **每日新词预算**：`NEW_WORD_LIMIT = 20`，按 `first_learned_at` 当天计数；预算用完后 `/api/study/today` 返回空数组，前端据此显示「今日额度用完」。
- **复习队列**：`next_review_at <= now`，上限 `REVIEW_LIMIT = 50`。
- **额外新词**：每日基础 20 个，用户可主动要「再来 20 个」，每天额外上限 `EXTRA_NEW_LIMIT = 60`；额外新词在 `AnswerLog.is_extra` 里标记。
- **练习**：`practice: true` 的作答只写 `AnswerLog`，绝不改动 `UserWordProgress`（间隔、streak 都不变）。
- **答题流水**：每次作答写一条 `AnswerLog`（新词/额外/练习/间隔前后），个人面板和后续统计都基于它。
- **撤销**：只能撤销**最近一条未撤销**的作答，且必须在 10 分钟内；`AnswerLog.state_before` 保存作答前的进度快照，撤销时按快照恢复（新词直接删进度行）；撤销后清空 `client_token`，允许用同一个请求标识重新作答。
- **幂等**：作答可带 `client_token`（前端每次作答生成），同一用户同一 token 只落一条流水，重复请求返回 `duplicate: true` 且不再推进间隔。
- **统计口径**：`statistics.today_completed` = 今日**非练习**答题条数；所有统计（个人面板、额外新词用量、答题历史）都必须排除 `undone_at` 非空的记录。
- **错词**：`wrong_count > 0` 即错词；错词练习走 `practice` 通道，只记录不改间隔。
- **新词顺序**：默认 `core`：CEFR 等级 B1 → B2 → C1 → 未收录 → A2 → A1，`is_proper`（月份、人名、缩写）永远最后；同档内按 `(id * 1103515245 + 每天种子) mod 2^31-1` 打乱（同一天刷新顺序不变，隔天变），避免读成字母表；另外支持 `alpha` / `random`。CEFR 来自 `data/sources/Oxford.json`，CSV 的 `cefr` 列或 `annotate_cefr` 命令写入。
- **标记已会**：作答时带 `known: true` 直接把词设为 `mastered`、间隔 365 天，日志记 `is_skip=True`（rating 固定 `easy`）；撤销同样按快照恢复。
- **个人词典**：`Dictionary.owner` 非空即个人词典；列表/详情/enroll/统计/答题共用同一可见性判断（官方 + 自己的）。
- **单词唯一**：`(dictionary, Lower(spelling))`，`Abandon` 与 `abandon` 是同一个词，导入时合并。
- **例句**：`Word.example` 是英文例句，`Word.example_translation` 是中文翻译；批量填充只走 `enrich_examples`（数据源 `data/examples.json`），不要在教学流程里现生成。
- **写进度**：必须在事务中 `select_for_update()` 后调用 `services.schedule()`，不要在视图里重算间隔。
- **每日计时**：所有「今天」都用 `timezone.localdate()`，时区固定 `Asia/Shanghai`。

### 邮箱验证码 / 找回密码

- **三种用途**：`login`（登录+注册二合一）、`reset`（重置密码）、`bind`（已登录时绑定邮箱）；**`reset`/`bind` 不能互用**，`verify_code` 按 purpose 取码。
- **只存哈希**：`EmailVerification.code_hash = sha256(salt + code)`，盐每次随机；比对用 `secrets.compare_digest`，不要拿明文比。
- **生命周期**：6 位数字，`EMAIL_CODE_TTL_MINUTES = 10` 分钟；发送同邮箱同用途要等 `EMAIL_CODE_COOLDOWN_SECONDS = 60` 秒；每邮箱每小时 5 封、每 IP 每小时 20 封（`EMAIL_CODE_EMAIL_HOURLY_LIMIT` / `EMAIL_CODE_IP_HOURLY_LIMIT`）。
- **一次性**：核销即写 `consumed_at`；重发会把同邮箱同用途的旧码一起作废（最后一个收到的才有效）；输错 `EMAIL_CODE_MAX_ATTEMPTS = 5` 次直接作废。
- **不发信不占冷却**：投递失败时删掉这行再返回 502，否则用户要白等一分钟。
- **防枚举**：`send` 一律回同一句「如果这个邮箱可以使用…」；`reset` 遇到未绑定邮箱也回成功但不发信。只有已登录的 `bind` 会明说「已被占用」。
- **账号归属**：邮箱身份在 `EmailAddress`（`email` 唯一），不在 `auth.User.email`（那列不唯一）。首次验证自动建号：`username` 由邮箱前缀生成（不足 3 位或含非法字符就 `u_<hex>`），密码 `set_unusable_password()`。
- **绑定邮箱**：`bind` 成功后同步写 `auth.User.email`（仅在原值为空时），这样 `/api/auth/me` 能显示。

### 面板指标（`/api/profile/insights`）

- **保持率**：只看 `interval_before > 0` 的非练习、非 skip 作答——第一次见词不是回忆测试；练习挑的是弱词，会把曲线拉低，必须排除。分档边界在 `views.RETENTION_BUCKETS`。
- **已掌握时间**：没有单独字段，用「第一次出现 `interval_after >= 21` 的作答时间」近似。
- **评分校准**：同一个词相邻两次作答配对，要求第二次 `interval_before > 0` 且间隔 ≥ 1 小时（同一轮重新排队不算），第二次答 `again`/`hard` 视为「高估了」。
- 前端只做展示与文案：分档、坐标、结论文案都在 `lib/chart.ts`，不要在组件里重算。

## 6. API 约定

- 错误统一 `{"detail": "中文文案"}`，前端直接展示，不要在前端再拼英文。
- 认证是 session + CSRF：写操作带 `X-CSRFToken`；`/api/auth/csrf` 负责下发 cookie；登录/注册后 token 会轮换，前端 `resetCsrf()` 已处理。
- 返回的单词对象带 `preview`：`{again, hard, good, easy}` → 下次间隔文案，评分按钮直接显示它。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/auth/csrf` | 下发 CSRF cookie |
| POST | `/api/auth/register` | 注册（密码 ≥ 8 位、有强度校验） |
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/logout` | 退出 |
| GET | `/api/auth/me` | 当前用户，未登录 401 |
| POST | `/api/auth/email/send` | 发验证码 `{email, purpose}`，purpose = `login`\|`reset`\|`bind`；bind 需登录 |
| POST | `/api/auth/email/verify` | 验证码登录/注册（`login`）或绑定邮箱（`bind`），未注册的邮箱验证后自动建账号 |
| POST | `/api/auth/password/reset` | 用验证码重置密码并直接登录 |
| GET | `/api/dictionaries/` | 可见词典 + 当前用户的 learned/due 计数 |
| GET | `/api/dictionaries/{id}/` | 词典详情 |
| GET | `/api/dictionaries/{id}/words?q=&filter=&sort=&page=&page_size=` | 词表分页/搜索（filter: all/new/learning/mastered/due/wrong） |
| GET | `/api/words/{word_id}` | 单词详情：preview + progress + 最近 10 条答题记录 |
| GET | `/api/words/{word_id}/example-audio` | 例句语音（edge-tts 生成后缓存到 `AUDIO_CACHE_DIR`） |
| DELETE | `/api/dictionaries/{id}/` | 删除自己的词典（staff 可删官方） |
| POST | `/api/dictionaries/{id}/enroll` | 开始学习（幂等） |
| POST | `/api/dictionaries/import` | 导入个人词典（同名幂等，仅自己可见） |
| POST | `/api/admin/dictionaries/import` | 管理员导入到指定词典 |
| GET | `/api/study/today?dictionary_id=&order=core\|alpha\|random` | 今日新词（受预算限制，默认 core） |
| GET | `/api/review/today?dictionary_id=` | 到期复习 |
| GET | `/api/review/early?dictionary_id=&order=weak\|due\|random&limit=` | 提前复习（练习，不改 SRS） |
| GET | `/api/review/wrong?dictionary_id=&limit=&order=wrong\|recent` | 错词列表（练习用） |
| POST | `/api/study/{word_id}/answer` | 提交 `{rating, practice?, client_token?, known?}`；practice 只记录，known 直接标掌握（365 天） |
| POST | `/api/answers/{log_id}/undo` | 撤销最近一次作答（10 分钟内） |
| GET | `/api/profile/summary?days=371` | 个人学习面板：每日/连续天数/按词典（days 支持 7–371） |
| GET | `/api/profile/insights?days=180` | 保持率曲线、累计进度、评分校准（days 支持 7–371） |
| GET | `/api/statistics?dictionary_id=` | 进度、掌握数、待复习、下次复习时间 |

## 7. 前端约定

- 组件里不直接 `fetch`，一律走 `src/api.ts`；请求超时、401 跳登录、中文兜底都在那一层。
- 纯逻辑放 `src/lib/`，并在 `frontend/tests/` 里用 node 直接测（不引 Vue、不引 DOM）。
- 视图只管展示；共享状态和异步动作放 `useSession()`。新增视图先加路由解析 `lib/router.ts`。
- 快捷键是产品的一部分：`空格` 看答案、`1`–`4` 评分、`回车` 确认、`M` 切换卡片/填空（填空输入框内必须用 `Alt+M`，否则 m 会被当成字母输入）、`U` 撤销（仅在有可撤销作答时）。改交互时别弄丢。
- 词表页的筛选状态放在 URL（`?q=&filter=&sort=&page=`）：`lib/words.ts` 的 `buildWordsQuery / clampPage` 是唯一实现，`browseMemory` 记住每本词典的查询串，详情页据此返回。
- 朗读统一走 `useSpeech()`，不要在视图里重写播放/降级链（词典音频 → 本地英文语音 → 有道）。换词时调用 `prefetch()` 预热音频；不是每次 `new Audio()`，播放器按 URL 缓存复用（最多 8 个）。
- 填空模式的例句默认可见（目标词已遮罩），`hintVisible` 默认 `true`，不要再改回「点一下才显示」。
- 填空模式的遮罩与判分必须共用 `lib/study.ts` 的 `clozeSlots / buildClozeAnswer / checkCloze`，不要在组件和模板里各算一套（历史 bug 就是这么来的）。
- 长单词必须可换行：`h3` 用 `clamp()`，`overflow-wrap: anywhere`，填空行 `flex-wrap: wrap`。
- 热力图的格子边长由 `ProfileView` 的 `measureHeatmap()` 按容器宽度算（`--heat-cell` / `--heat-gap`），显示周数也随宽度在 13–53 周之间自适应；不要写死像素或加横向滚动容器，格子必须保持正方形。
- 登录页有四种形态（密码登录 / 注册 / 邮箱验证码 / 重置密码），状态在 `AuthView` 的 `mode` 里；发码按钮的 60 秒冷却由 `retry_after` 驱动，别写死。
- 图表不引第三方库：坐标计算与结论文案都在 `lib/chart.ts`，模板只画 SVG；新增图表先加纯函数 + `tests/chart.test.mjs` 用例。
- 文案全中文；错误优先用后端 `detail`。

## 8. 测试与提交

- 改后端业务规则 → 在 `backend/vocabulary/tests.py` 补用例（当前 81 个）。
- 改填空/SRS/热力图/朗读/词表/图表 → 改 `frontend/tests/*.test.mjs`（当前 49 个）。
- 提交前：`manage.py test` + `npm run typecheck` + `npm run test` + `npm run build`。
- 提交信息：`feat|fix|chore|test|docs(scope): 中文摘要`。

## 9. 已知限制 / 待办

- 例句与中文翻译来自 `data/examples.json`（项目生成，非第三方词典语料）；要换成授权语料，按同格式替换后跑 `enrich_examples --force` 与 `build_wordlists.py`。
- 释义仍是 ECDICT 原始多义项文本，卡片/填空只显示 `primaryMeaning()` 截出的主释义，完整内容可展开。
- 没有「导出/分享」；撤销只覆盖 10 分钟内的最近一次作答，不做任意历史回滚。
- Docker 配置（gunicorn + collectstatic + nginx 托管 `/static/`）已写好，但开发机没有 Docker，**未实测**；生产走的是原生部署（nginx + gunicorn + systemd），步骤见 `docs/deploy.md`，已在 Ubuntu 24.04 上跑通。
- 单词发音顺序是「词典自带 `audio_url` → 系统英文语音（Web Speech API）→ 有道在线发音」；本地语音最多等 900ms，失败就切在线。整句朗读先试系统英文语音，失败才请求 `/api/words/{id}/example-audio`（首次 2–3 秒）。换词时 `prefetch()` 预载音频，播放器按 URL 缓存，第二次播放基本瞬时。卡片、填空和词详情都有「🔊 朗读」按钮；在线发音会把单词发到 `dict.youdao.com`，没有英文语音包时靠它兜底。
- 词表来源见 `data/sources/README.md`，商用前需确认上游授权。
- 例句语音用 edge-tts（`en-US-AriaNeural`）在服务器上生成，句子会发给 Microsoft 的语音服务；缓存在 `DJANGO_AUDIO_DIR`（生产 `/var/lib/english-vocabulary/audio`），删掉缓存目录会重新生成。
- CEFR 只覆盖 Oxford 3000/5000 的 5062 个词；CET 词表里约 1/3 查不到等级，这些词在 core 顺序里排在 C1 之后、A2 之前。要更准的顺序需要引入词频数据。
- SQLite 单文件；要上多实例/高并发前先换 PostgreSQL，并把 `db.sqlite3` 从仓库外备份策略里接进来。
- 邮箱验证码默认走控制台邮件（开发期把码打到 runserver 终端）；生产必须配 SMTP，否则 `send` 返回 502。国内服务器别用 25 端口（基本被封，实测出站 25 全部超时），用 465(SSL)/587(TLS)，并配 SPF/DKIM 免进垃圾箱。
- **SMTP 返回 250 ≠ 用户收到**：服务商会先收下再校验发件人/额度，被拒的记录只在服务商后台的事件日志里。排障顺序是「事件日志 → 发件人是否验证 → IP 是否在授权列表」，不要只看 `send_mail` 返回值。Brevo 的具体坑见 `docs/deploy.md` 4.2。
- 忘记密码只覆盖「已绑定邮箱」的账号：老账号要先在个人面板/接口里绑定邮箱（`/api/auth/email/send` + `verify`，purpose=bind），否则 `reset` 只会静默成功但收不到信。
- `/api/profile/insights` 的评分校准是「相邻两次作答配对」的简化模型：它衡量的是「自评后隔一段时间还想得起来」，不是严格的记忆强度估计；样本少于 8 次的档位前端只显示「样本还少」。
- 保持率与校准都依赖 `AnswerLog`，所以练习（practice）和撤销（undone）必须继续排除，否则曲线会失真。

## 10. 踩坑清单

- `.venv/` 是虚拟环境；`docker compose` 会自动读取根目录的 `.env`，如果那里放的是目录会直接报错——所以虚拟环境已经改名成 `.venv`。
- migration `0002` 里有 `march/March`、`may/May` 去重逻辑；改模型前先备份 `backend/db.sqlite3`（用 `manage.py dumpdata` 或直接复制）。
- Django 的 `APPEND_SLASH` 不会为 POST 重定向：新增无斜杠接口必须写在 `include(router.urls)` 之前。
- 前端 hash 路由刷新会重新拉取学习队列（服务端进度已保存，不会丢数据）。
- `localStorage` / `speechSynthesis` 可能被浏览器禁用，相关调用都已包 `try/catch`，不要改成裸调用。
- 导入文件会整块读进内存，单文件上限 10 MB、单次 20000 行；要放宽先改 `services.py` 的常量并补测试。
- `crypto.randomUUID()` 只在安全上下文可用，公网 HTTP 下是 `undefined`；幂等 token 必须用 `crypto.getRandomValues`（`lib/words.ts` 的 `randomToken()`）。
- 开发时 `npm run dev` 的 watcher 会占用 `frontend/src` 文件句柄（Windows 上表现为 `ReplaceFileW EIO`），改不动文件时先停掉 dev server，或改用写回整文件的方式。
- 词表接口的 6 个 `counts` 是 6 次 count 查询；词表到十万级再合并成单次聚合。
