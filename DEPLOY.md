# Deployment

## Front end

GitHub Pages publishes the `gh-pages` branch:
https://tsusinai.github.io/TextToCad/

## Geometry backend

Run the CadQuery/OCCT service from `backend/` with Uvicorn or Docker:

    cd backend
    pip install -r requirements.txt
    uvicorn app:app --host 0.0.0.0 --port 8787

or:

    docker build -t texttocad-backend ./backend
    docker run --rm -p 8787:8787 -v texttocad-artifacts:/data texttocad-backend

Set `CORS_ORIGINS` to the deployed Pages origin and pass the API URL to the UI with `?backend=https://your-api.example.com`.

## 本机 Docker + DeepSeek 配置

1. 复制配置模板：

    cp backend/.env.example backend/.env

2. 编辑 backend/.env，填写真实密钥：

    LLM_API_KEY=你的_DEEPSEEK_API_KEY
    LLM_API_URL=https://api.deepseek.com/chat/completions
    LLM_MODEL=deepseek-chat

如果你的 DeepSeek Flash 服务使用不同的兼容地址或模型名，只修改 LLM_API_URL 和 LLM_MODEL。不要把 backend/.env 提交到 Git。

3. 构建并启动 CadQuery/OCCT 服务：

    docker compose up --build -d

4. 检查服务：

    curl http://localhost:8787/health

返回 cadquery_available=true 后，将前端打开为：

    http://localhost:5173/?backend=http://localhost:8787

GitHub Pages 前端也可以连接本机后端，但浏览器访问本机时应使用：

    https://tsusinai.github.io/TextToCad/?backend=http://localhost:8787

这只适合本机调试；云端发布时应把 backend URL 换成 HTTPS 地址，并将 CORS_ORIGINS 限制为实际前端域名。
