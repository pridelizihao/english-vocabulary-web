# English Vocabulary Web

英语单词背诵应用：Django REST 后端 + Vue 3 单页前端。每天 20 个新词，答错的词 10 分钟后再来一遍，答对的词按 1 / 3 / 7 天逐步拉开间隔。

## 功能

- 词典列表：显示总词数、已学数量、到期复习数；官方词典和个人词典分开标识
- 学习：卡片（看答案后评分）和填空（按中文释义补全）两种模式，`M` 键随时切换（在填空输入框里按 `Alt+M`，避免把 m 打进空格）；卡片和填空都有「🔊 朗读」按钮，会提前缓冲音频并复用播放器，优先系统英文语音，没有语音包或启动超时时自动改用有道在线发音；填空默认显示遮罩后的例句和翻译，可一键隐藏
- 复习调度：`again / hard / good / easy` 四档评分，间隔递增，间隔满 21 天才算「已掌握」
- 每日预算：新词每天最多 20 个，复习优先；预算用完会提示而不是继续塞词
- 新词顺序：默认「考试核心」——按 CEFR 等级先 B1/B2，再 C1、Oxford 未收录词，最后才是 A2/A1 和专有名词；也可以切回字母序或乱序
- 已经会了：每个词都能一键标记为掌握（一年后再复习），标错了 10 分钟内还能撤销
- 词表浏览：点词典卡片上的「查看词表」进入词表页，可按拼写或中文释义搜索，按 全部 / 未学 / 学习中 / 已掌握 / 待复习 / 易错 筛选，按字母、最近学习、最快到期或错得最多排序，分页浏览
- 单词详情：每个词都有独立页面，显示音标、词性、完整释义、例句、朗读、记忆状态（间隔、下次复习、复习次数、答错次数）和最近 10 条作答记录
- 个人词表：导入 CSV / JSON / XLSX，自动去重，只有自己可见，可删除
- 学习面板：点右上角用户名查看 GitHub 风格答题热力图（按周分列、格子铺满宽度不滚动，屏幕越窄显示的周数越少）、今日/7 天汇总、连续天数和按词典分布，并能从面板直接进入某本词典的错词练习
- 额度与复习：新词学完可以「再来 20 个」（每天额外最多 60 个）；复习可以选到期复习或提前复习（练习，不改变间隔）
- 错词练习：答错过的词可以一键组成练习队列，只记录答题不改复习间隔
- 撤销上一题：评错档后 10 分钟内可以撤销最近一次作答，间隔和统计会一起回退（按钮或 `U` 键）

## 技术栈

Django 5 · Django REST Framework · SQLite · Vue 3 · Vite · TypeScript
生产镜像：gunicorn + nginx（`/api` 反代、`/static` 托管后台静态资源）

```
backend/    Django 项目（api、admin、管理命令）
frontend/   Vue 3 + Vite 前端
data/       词表来源、可导入 CSV、CSV 模板
docs/       审查报告与设计说明
AGENTS.md   给后续开发/代理的约定与踩坑清单
```

## 本地运行

后端（虚拟环境在仓库根目录的 `.venv/`）：

```bash
cd backend
../.venv/Scripts/python.exe manage.py migrate        # Windows
# Linux/macOS: ../.venv/bin/python manage.py migrate
../.venv/Scripts/python.exe manage.py seed_dictionaries
../.venv/Scripts/python.exe manage.py seed_wordlists  # 导入 3500/5000 词并发布
../.venv/Scripts/python.exe manage.py createsuperuser
../.venv/Scripts/python.exe manage.py runserver
```

前端：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`，注册后即可学习。Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`，后台是 `http://127.0.0.1:8000/admin/`。

## 测试

```bash
cd backend && ../.venv/Scripts/python.exe manage.py test   # 57 个用例
cd frontend
npm run typecheck   # tsc --noEmit
npm run test        # 纯逻辑测试（node:test）
npm run build
```

## 导入自己的词表

前端「选择词典」页底部的导入框，或：

```bash
curl -X POST http://127.0.0.1:8000/api/dictionaries/import \
  -b cookies.txt -H "X-CSRFToken: ..." \
  -F "name=我的词表" -F "file=@data/samples/words.csv"
```

字段至少包含 `word` 和 `meaning`，可选 `phonetic / part_of_speech / example / example_translation / audio_url`。
支持 UTF-8 与 GBK 编码的 CSV、JSON 数组、XLSX；同一个词（忽略大小写）只会保留一条。

官方词典的导入（需要 staff 账号）用 `python manage.py import_dictionary --dictionary "词典名" --file data/imports/xxx.csv --publish`。

## 例句

`data/examples.json` 存着每个词的例句和中文翻译（约 5000 条），卡片作答后会显示，填空模式里有「例句提示」（目标词会先遮住）。

```bash
# 换了词表或想覆盖已有例句时
python manage.py enrich_examples              # 只补空的
python manage.py enrich_examples --force      # 覆盖全部
python data/scripts/build_wordlists.py        # 把例句写回可导入的 CSV
```

例句由项目生成（短句、贴合释义、带中文翻译），不是从受版权保护的词典抓取的；如果要换成正式授权的语料，按同样格式重写 `data/examples.json` 再执行上面的命令即可。

## 发布

原生部署（nginx + gunicorn + systemd，已在 Ubuntu 24.04 实测）见 [`docs/deploy.md`](docs/deploy.md)，配置模板在 `deploy/`。

也可以用 Docker：

```bash
cp .env.example .env    # 填写 DJANGO_SECRET_KEY 等
docker compose up --build
```

访问 `http://localhost:8080`。容器启动时会自动 migrate、创建官方词典、导入 `data/imports` 词表并执行 collectstatic。

> 本机开发环境没有 Docker，镜像配置尚未实机验证；如果启动失败，优先检查卷挂载与 `DJANGO_ALLOWED_HOSTS`。

## 数据来源

`data/sources/README.md` 记录了词表来源与授权提示。`data/imports/` 的 3500 / 5000 词是按字母序截取的核心子集，不代表官方考纲词量；商用或再分发前请确认上游许可。

朗读优先用设备本地的英文语音；系统里没有英文语音包时，会请求有道发音接口（`dict.youdao.com`）在线播放，只发送当前这一个单词，不涉及账号或学习数据。
