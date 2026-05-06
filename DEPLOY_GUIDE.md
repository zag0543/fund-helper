# 基金智管家 - Streamlit Cloud 部署指南

## 前提条件

- GitHub 账号
- 稳定的网络连接（访问 GitHub 和 Streamlit Cloud）

## 部署步骤

### 第一步：创建 GitHub 账号（如果有请跳过）

1. 访问 [GitHub](https://github.com)
2. 点击 "Sign up" 注册账号
3. 选择免费计划（Free）

### 第二步：创建代码仓库

1. 登录 GitHub
2. 点击右上角 "+" → "New repository"
3. 填写仓库信息：
   - **Repository name**: `fund-helper`（或其他喜欢的名字）
   - **Description**: 基金智管家
   - **Private/Public**: 选择 Public（Streamlit Cloud 可访问公开仓库）
4. 点击 "Create repository"

### 第三步：上传代码

**方法一：网页上传（推荐新手）**

1. 在新建的仓库页面，点击 "uploading an existing file"
2. 将本文件夹内的**所有文件和文件夹**拖拽到上传区域，包括：
   - `app.py`
   - `requirements.txt`
   - `README.md`
   - `DEPLOY_GUIDE.md`
   - `.streamlit/config.toml`
   - `utils/fund_data.py`
   - `data/.gitkeep`
3. 注意目录结构要完整，尤其是 `utils/` 子文件夹
4. 点击 "Commit changes"

**方法二：Git 命令行上传**

```bash
# 克隆仓库
git clone https://github.com/你的用户名/fund-helper.git

# 复制文件
cp -r 基金助手Streamlit/* fund-helper/
cp -r 基金助手Streamlit/.* fund-helper/   # 复制隐藏文件 (.streamlit)

# 推送
cd fund-helper
git add .
git commit -m "Initial commit"
git push
```

### 第四步：注册 Streamlit Cloud

1. 访问 [Streamlit Cloud](https://streamlit.io/cloud)
2. 点击 "Get Started"
3. 使用 GitHub 账号登录/注册
4. 授权 Streamlit 访问你的 GitHub 仓库

### 第五步：部署应用

1. 在 Streamlit Cloud 页面，点击 "New app"
2. 配置部署：
   - **Repository**: 选择你的仓库（如 `你的用户名/fund-helper`）
   - **Branch**: `main`
   - **Main file path**: `app.py`
3. 点击 "Deploy!"

### 第六步：等待部署

1. 首次部署需要安装依赖（约 3-5 分钟）
2. 部署成功后会显示应用 URL
3. 可以在 "Manage app" 中查看日志

## 访问你的应用

部署成功后，你将获得一个类似这样的链接：
```
https://你的用户名-fund-helper-main-xxx.streamlit.app
```

分享给家人即可使用！

## 重要提醒

### ⚠️ 数据备份

Streamlit Cloud **免费版重启后数据会丢失**！

每次使用后请：
1. 点击 **「一键导出持仓」** 按钮
2. 下载 JSON 文件保存到本地

### 数据恢复

应用重启后，会自动弹出导入引导页面：
1. 点击 **「恢复备份」** 区域
2. 上传之前导出的 JSON 文件
3. 点击「确认导入」
4. 应用会自动加载数据

> 💡 如果选择「全新开始」，也可以先进入主界面，之后随时通过持仓页面的「恢复备份」功能导入数据。

### 数据文件位置

部署后数据存储在容器中：
```
/app/data/holdings.json      # 持仓数据
/app/data/watchlist.json     # 关注列表
```

## 常见问题

### Q: 部署失败怎么办？
A: 查看 Streamlit Cloud 的日志（Manage app → Logs）。常见原因：
- 网络超时导致依赖安装失败 → 重试即可
- 目录结构不对 → 确认 `utils/fund_data.py` 在正确位置

### Q: 估值数据获取不到？
A: Streamlit Cloud 服务器在国外，访问国内 API 可能较慢或失败，这是正常现象。可以稍后重试。

### Q: 如何更新代码？
A: 在 GitHub 仓库中修改代码后提交，Streamlit Cloud 会自动重新部署。

### Q: 可以设置私有仓库吗？
A: Streamlit Cloud 免费版可以连接私有仓库，需要额外授权。

## 进阶配置

### 自定义域名
Streamlit Cloud Pro 版本支持自定义域名。

### 团队协作
Pro 版本支持邀请团队成员共同管理应用。

## 联系与支持

如有问题，可以提交 GitHub Issue 或查看 Streamlit 官方文档。
