# 葡萄树认养平台

基于 Flask 的小型网站，包含两类用户：
- 工作人员：发布葡萄树、处理买家问题
- 买家用户：认养葡萄树、提交问题反馈

## 功能
- 用户注册/登录（角色：工作人员、买家）
- 工作人员发布葡萄树信息（支持图片上传）
- 工作人员上传每日农事记录（含阶段、健康、巡检图、直播链接）
- 买家认养葡萄树并实时查看生长状态（前端定时刷新）
- 买家提交“认养问题”，工作人员闭环处理
- 电商模块：成熟后可提交发货订单，工作人员更新物流状态
- 体验模块：买家可预约线下采摘，工作人员确认/完成

## 本地运行
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

打开浏览器访问：`http://127.0.0.1:5000`

## 上传到 GitHub
```bash
git init
git add .
git commit -m "feat: 葡萄树认养与问题处理平台"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

## 部署（Render）
1. 在 Render 新建 `Web Service`
2. 连接你的 GitHub 仓库
3. 构建命令：`pip install -r requirements.txt`
4. 启动命令：`gunicorn app:app`
5. 部署完成后即可得到访问链接

## 注意
- 数据库使用 SQLite（`adoption.db`），默认保存在项目目录
- `static/uploads` 用于图片上传，生产环境建议改为对象存储
