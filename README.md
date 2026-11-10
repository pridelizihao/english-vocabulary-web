# English Vocabulary Web

英语单词背诵网站初版，包含 Django REST 后端和 Vue 3 前端。

## 后端

```bash
cd backend
# 如果使用 Conda：conda activate base
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py createsuperuser
python manage.py runserver
```

## 前端

```bash
cd frontend
npm install
npm run dev
```

CSV 示例位于 `data/samples/words.csv`。导入接口支持 CSV、JSON 和 XLSX。

前端开发服务器通过 Vite 将 `/api` 代理到 `http://127.0.0.1:8000`。启动后访问 `http://localhost:5173`，先注册账号即可学习示例词典。管理员可访问 `http://127.0.0.1:8000/admin/` 管理词典。

## 发布

生产环境先设置 `.env` 中的 `DJANGO_SECRET_KEY` 和 `DJANGO_ALLOWED_HOSTS`，再执行：

```bash
docker compose up --build
```

容器化页面访问 `http://localhost:8080`。3500 词和 5000 词典入口会由 `python manage.py seed_demo` 创建为草稿，导入拥有授权的词表后，在 Django Admin 中发布。
