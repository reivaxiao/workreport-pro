"""WorkReport HR-Pro - 主应用程序"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from models import init_db, seed_data

# 创建应用
app = FastAPI(title="WorkReport HR-Pro", description="智能工作汇报系统", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局禁用缓存（开发期，确保浏览器总是拿到最新代码和数据）
@app.middleware("http")
async def no_cache(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# 注册路由
from routers import users, goals, items, reports, annotations, agents, attachments, auth, categories
app.include_router(users.router, prefix="/api", tags=["用户"])
app.include_router(goals.router, prefix="/api", tags=["年度目标"])
app.include_router(items.router, prefix="/api", tags=["工作事项"])
app.include_router(reports.router, prefix="/api", tags=["周报"])
app.include_router(annotations.router, prefix="/api", tags=["批注"])
app.include_router(agents.router, prefix="/api", tags=["AI智能体"])
app.include_router(attachments.router, prefix="/api", tags=["附件"])
app.include_router(auth.router, prefix="/api", tags=["登录"])
app.include_router(categories.router, prefix="/api", tags=["分类字典"])

# 静态文件（前端页面）
frontend_dir = Path(__file__).parent.parent / "frontend"
frontend_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


@app.on_event("startup")
def startup():
    init_db()
    seed_data()


@app.get("/")
def root():
    """返回前端首页"""
    from fastapi.responses import FileResponse
    return FileResponse(str(frontend_dir / "index.html"))


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
