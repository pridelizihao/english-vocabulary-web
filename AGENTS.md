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
    models.py                  Dictionary / Word / UserDictionary / UserWordProgress / AnswerLog
    services.py                复习调度 schedule() 与导入解析、批量写库
    views.py                   HTTP 层（函数视图为主 + 一个 ModelViewSet）
    serializers.py             输出结构，含每个词的 preview 间隔文案
    urls.py                    路由（显式路由必须写在 router 之前）
    admin.py                   已配 list_display / search_fields，别再退回裸 register
    management/commands/       seed_dictionaries / seed_wordlists / import_dictionary / enrich_examples
    tests.py                   后端用例（当前 31 个）
    migrations/0002_*.py       注意：含大小写去重逻辑，不要随手删
frontend/
  src/api.ts                   唯一请求入口：ApiError、CSRF、超时、中文错误
  src/lib/study.ts             纯函数：填空遮罩、队列、格式化（node 可直接测）
  src/lib/profile.ts           学习面板的纯函数（热力图分档、按周分列）
  src/lib/router.ts            hash 路由：/ · /auth · /profile · /study/:id · /done/:id
  src/composables/useSession.ts 全局学习会话状态与动作
  src/views/*.vue              Auth / Dictionaries / Study / Done / Profile
  src/App.vue                  壳层 + 路由同步 + 错误/提示条
  tests/*.test.mjs             node:test，纯逻辑
data/
  sources/                     原始词表（CET.json、definitions.json）
  imports/                     可直接导入的 3500/5000 词 CSV
  examples.json                例句 + 中文翻译（enrich_examples 的数据源）
  samples/words.csv            CSV 导入模板
  scripts/build_wordlists.py   从 sources + examples 生成 imports
docs/                          设计说明与审查报告
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
npm run build       # vite build，构建产物在 dist/（已 gitignore）
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
- **个人词典**：`Dictionary.owner` 非空即个人词典；列表/详情/enroll/统计/答题共用同一可见性判断（官方 + 自己的）。
- **单词唯一**：`(dictionary, Lower(spelling))`，`Abandon` 与 `abandon` 是同一个词，导入时合并。
- **例句**：`Word.example` 是英文例句，`Word.example_translation` 是中文翻译；批量填充只走 `enrich_examples`（数据源 `data/examples.json`），不要在教学流程里现生成。
- **写进度**：必须在事务中 `select_for_update()` 后调用 `services.schedule()`，不要在视图里重算间隔。
- **每日计时**：所有「今天」都用 `timezone.localdate()`，时区固定 `Asia/Shanghai`。

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
| GET | `/api/dictionaries/` | 可见词典 + 当前用户的 learned/due 计数 |
| GET | `/api/dictionaries/{id}/` | 词典详情 |
| DELETE | `/api/dictionaries/{id}/` | 删除自己的词典（staff 可删官方） |
| POST | `/api/dictionaries/{id}/enroll` | 开始学习（幂等） |
| POST | `/api/dictionaries/import` | 导入个人词典（同名幂等，仅自己可见） |
| POST | `/api/admin/dictionaries/import` | 管理员导入到指定词典 |
| GET | `/api/study/today?dictionary_id=&order=alpha\|random` | 今日新词（受预算限制） |
| GET | `/api/review/today?dictionary_id=` | 到期复习 |
| GET | `/api/review/early?dictionary_id=&order=weak\|due\|random&limit=` | 提前复习（练习，不改 SRS） |
| POST | `/api/study/{word_id}/answer` | 提交 `{rating, practice?}`，practice 只记录不改间隔 |
| GET | `/api/profile/summary?days=371` | 个人学习面板：每日/连续天数/按词典（days 支持 7–371） |
| GET | `/api/statistics?dictionary_id=` | 进度、掌握数、待复习、下次复习时间 |

## 7. 前端约定

- 组件里不直接 `fetch`，一律走 `src/api.ts`；请求超时、401 跳登录、中文兜底都在那一层。
- 纯逻辑放 `src/lib/`，并在 `frontend/tests/` 里用 node 直接测（不引 Vue、不引 DOM）。
- 视图只管展示；共享状态和异步动作放 `useSession()`。新增视图先加路由解析 `lib/router.ts`。
- 快捷键是产品的一部分：`空格` 看答案、`1`–`4` 评分、`回车` 确认。改交互时别弄丢。
- 填空模式的遮罩与判分必须共用 `lib/study.ts` 的 `clozeSlots / buildClozeAnswer / checkCloze`，不要在组件和模板里各算一套（历史 bug 就是这么来的）。
- 长单词必须可换行：`h3` 用 `clamp()`，`overflow-wrap: anywhere`，填空行 `flex-wrap: wrap`。
- 热力图的格子边长由 `ProfileView` 的 `measureHeatmap()` 按容器宽度算（`--heat-cell` / `--heat-gap`），显示周数也随宽度在 13–53 周之间自适应；不要写死像素或加横向滚动容器，格子必须保持正方形。
- 文案全中文；错误优先用后端 `detail`。

## 8. 测试与提交

- 改后端业务规则 → 在 `backend/vocabulary/tests.py` 补用例（当前 31 个）。
- 改填空/SRS/热力图 → 改 `frontend/tests/*.test.mjs`（当前 23 个）。
- 提交前：`manage.py test` + `npm run typecheck` + `npm run test` + `npm run build`。
- 提交信息：`feat|fix|chore|test|docs(scope): 中文摘要`。

## 9. 已知限制 / 待办

- 例句与中文翻译来自 `data/examples.json`（项目生成，非第三方词典语料）；要换成授权语料，按同格式替换后跑 `enrich_examples --force` 与 `build_wordlists.py`。
- 释义仍是 ECDICT 原始多义项文本，卡片/填空只显示 `primaryMeaning()` 截出的主释义，完整内容可展开。
- 没有「撤销上一题」和错词本；`wrong_count` 在攒但没有入口。
- Docker 配置（gunicorn + collectstatic + nginx 托管 `/static/`）已写好，但开发机没有 Docker，**未实测**。
- 单词发音优先用 `audio_url`，缺失时用浏览器 Web Speech API；卡片和填空都有「🔊 朗读」按钮，需要一次真实点击，没有英文语音时会显示提示。
- 词表来源见 `data/sources/README.md`，商用前需确认上游授权。
- SQLite 单文件；要上多实例/高并发前先换 PostgreSQL，并把 `db.sqlite3` 从仓库外备份策略里接进来。

## 10. 踩坑清单

- `.venv/` 是虚拟环境；`docker compose` 会自动读取根目录的 `.env`，如果那里放的是目录会直接报错——所以虚拟环境已经改名成 `.venv`。
- migration `0002` 里有 `march/March`、`may/May` 去重逻辑；改模型前先备份 `backend/db.sqlite3`（用 `manage.py dumpdata` 或直接复制）。
- Django 的 `APPEND_SLASH` 不会为 POST 重定向：新增无斜杠接口必须写在 `include(router.urls)` 之前。
- 前端 hash 路由刷新会重新拉取学习队列（服务端进度已保存，不会丢数据）。
- `localStorage` / `speechSynthesis` 可能被浏览器禁用，相关调用都已包 `try/catch`，不要改成裸调用。
- 导入文件会整块读进内存，单文件上限 10 MB、单次 20000 行；要放宽先改 `services.py` 的常量并补测试。
