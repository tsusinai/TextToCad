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
