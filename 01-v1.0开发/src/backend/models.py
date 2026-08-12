"""数据库模型定义"""
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Float, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

# 数据库文件存本项目目录下
DB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(DB_DIR, "workreport.db")

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ========== 用户表 ==========
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)          # 姓名
    role = Column(String(50), nullable=False)           # 职能：COE / HRBP
    business_line = Column(String(50), default="")       # 业务板块：营销/产研/运营
    is_manager = Column(Integer, default=0)              # 是否管理者 0=否 1=是
    avatar_color = Column(String(20), default="#534AB7") # 头像颜色

    work_items = relationship("WorkItem", back_populates="owner")
    annotations = relationship("Annotation", back_populates="manager")


# ========== 年度目标表 ==========
class AnnualGoal(Base):
    __tablename__ = "annual_goals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)           # 目标名称
    weight = Column(Float, default=0.0)                   # 权重百分比
    category = Column(String(20), default="业务")         # 业务 / 管理
    kpis = Column(Text, default="")                      # 衡量标准/关键举措
    year = Column(Integer, default=2026)                  # 年份

    work_items = relationship("WorkItem", back_populates="goal")


# ========== 工作事项表 ==========
class WorkItem(Base):
    __tablename__ = "work_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)            # 事项名称
    category = Column(String(20), nullable=False)         # 年度重点工作 / 自主专项工作 / 常规工作
    owner_id = Column(Integer, ForeignKey("users.id"))    # 负责人
    goal_id = Column(Integer, ForeignKey("annual_goals.id"), nullable=True)  # 关联年度目标
    target_desc = Column(Text, default="")                # 工作目标/背景描述
    status = Column(String(20), default="进行中")         # 进行中 / 已完成 / 已暂停
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    owner = relationship("User", back_populates="work_items")
    goal = relationship("AnnualGoal", back_populates="work_items")
    weekly_progress = relationship("WeeklyProgress", back_populates="work_item", order_by="WeeklyProgress.week_start.desc()")


# ========== 周报进展表 ==========
class WeeklyProgress(Base):
    __tablename__ = "weekly_progress"

    id = Column(Integer, primary_key=True, index=True)
    work_item_id = Column(Integer, ForeignKey("work_items.id"))
    week_start = Column(String(20), nullable=False)       # 周起始日期 如 "2026-08-10"
    progress = Column(Text, default="")                   # 本周进展描述
    next_plan = Column(Text, default="")                  # 下阶段计划
    blockers = Column(Text, default="")                   # 遇到的问题/需要支持
    status_before_ai = Column(String(20), default="draft") # draft / ai_reviewed / submitted
    ai_suggestions = Column(Text, default="")              # AI审阅建议（JSON）
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    work_item = relationship("WorkItem", back_populates="weekly_progress")


# ========== 管理者批注表 ==========
class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True, index=True)
    manager_id = Column(Integer, ForeignKey("users.id"))   # 管理者
    work_item_id = Column(Integer, ForeignKey("work_items.id"))
    week_start = Column(String(20), nullable=False)
    content = Column(Text, default="")                     # 批注内容
    created_at = Column(DateTime, default=datetime.now)

    manager = relationship("User", back_populates="annotations")


# ========== 周报提交状态表 ==========
class WeeklySubmitStatus(Base):
    __tablename__ = "weekly_submit_status"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    week_start = Column(String(20), nullable=False)
    status = Column(String(20), default="draft")           # draft / submitted / overdue
    submitted_at = Column(DateTime, nullable=True)


def init_db():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)


def seed_data():
    """初始化种子数据：用户、目标、示例工作事项"""
    db = SessionLocal()
    try:
        # 检查是否已有数据
        if db.query(User).count() > 0:
            return

        # 创建用户
        users = [
            User(name="肖凌华", role="管理者", is_manager=1, avatar_color="#534AB7"),
            User(name="程宇欣", role="COE", business_line="", avatar_color="#378ADD"),
            User(name="李微微", role="HRBP", business_line="营销板块", avatar_color="#0F6E56"),
            User(name="高丽茹", role="HRBP", business_line="产研板块", avatar_color="#BA7517"),
            User(name="李雯", role="HRBP", business_line="运营板块", avatar_color="#D4537E"),
        ]
        db.add_all(users)
        db.flush()

        # 创建年度目标（6项）
        goals = [
            AnnualGoal(name="聚焦经营战略推动组织和人才规划布局", weight=20, category="业务",
                       kpis="招聘保障≥90%；人才布局形成全景图", year=2026),
            AnnualGoal(name="严控人力预算成本+季度人效分析+合规零风险", weight=20, category="业务",
                       kpis="全年人力成本不超预算；季度人效分析；零重大劳动风险", year=2026),
            AnnualGoal(name="深入业务一线，推动组织/人才/激励专项方案", weight=30, category="业务",
                       kpis="三大板块差异化赋能；营销学习地图；产研任职资格重构；运营灵活用工", year=2026),
            AnnualGoal(name="高效协同COE完成人力资源政策100%落地", weight=15, category="业务",
                       kpis="上半年组织目标/激励/评优/晋升调薪；下半年组织能力调研/干部盘点/年度考核", year=2026),
            AnnualGoal(name="夯实基础设施建设+AI提效探索", weight=5, category="业务",
                       kpis="招聘数字化2.0上线；招聘IP全渠道推广；AI主题分享≥4次", year=2026),
            AnnualGoal(name="加强COE与HRBP协同+团队绩优骨干保留≥80%", weight=10, category="管理",
                       kpis="业务洞察分析报告；协作指引输出；季度回溯复盘", year=2026),
        ]
        db.add_all(goals)
        db.flush()

        # 创建示例工作事项
        sample_items = [
            # 肖凌华 - 管理者
            WorkItem(name="团队周报管理机制搭建", category="年度重点工作", owner_id=1, goal_id=6,
                     target_desc="建立高效的工作汇报系统，实现自动化催办和AI辅助审阅"),
            # 程宇欣 - COE
            WorkItem(name="招聘数字化工具2.0版本建设", category="年度重点工作", owner_id=2, goal_id=5,
                     target_desc="重构招聘底层架构，完成系统2.0上线"),
            WorkItem(name="招聘制度修订", category="常规工作", owner_id=2,
                     target_desc="完成2026年招聘制度的更新和发布"),
            # 李微微 - HRBP营销
            WorkItem(name="营销板块招聘交付", category="年度重点工作", owner_id=3, goal_id=1,
                     target_desc="确保营销板块关键岗位需求达成率不低于90%"),
            WorkItem(name="营销板块员工访谈", category="常规工作", owner_id=3,
                     target_desc="定期进行员工访谈，关注人才动态"),
            # 高丽茹 - HRBP产研
            WorkItem(name="产研板块招聘交付", category="年度重点工作", owner_id=4, goal_id=1,
                     target_desc="确保产研板块关键岗位需求达成率不低于90%"),
            WorkItem(name="产研任职资格重构", category="自主专项工作", owner_id=4, goal_id=3,
                     target_desc="实现产研侧人才标签化"),
            # 李雯 - HRBP运营
            WorkItem(name="运营板块招聘交付", category="年度重点工作", owner_id=5, goal_id=1,
                     target_desc="确保运营板块关键岗位需求达成率不低于90%"),
            WorkItem(name="运营板块岗职序列优化", category="年度重点工作", owner_id=5, goal_id=3,
                     target_desc="优化运营板块的岗位职级序列，推动阶段性灵活用工"),
        ]
        db.add_all(sample_items)

        db.commit()
        print("种子数据初始化完成")
    except Exception as e:
        db.rollback()
        print(f"种子数据初始化失败: {e}")
    finally:
        db.close()
