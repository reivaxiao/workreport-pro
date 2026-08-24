"""数据库模型定义"""
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, Float
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
    username = Column(String(50), default="")            # 登录账号
    password_hash = Column(String(128), default="")      # 密码哈希
    role = Column(String(50), nullable=False)           # 职能：COE / HRBP
    business_line = Column(String(50), default="")       # 业务板块：营销/产研/运营
    is_manager = Column(Integer, default=0)              # 业务管理者：看全员汇报视图、批注 0=否 1=是
    is_sysadmin = Column(Integer, default=0)             # 系统管理员：重置密码、成员管理 0=否 1=是
    avatar_color = Column(String(20), default="#534AB7") # 头像颜色

    work_items = relationship("WorkItem", back_populates="owner")
    annotations = relationship("Annotation", back_populates="manager", foreign_keys="Annotation.manager_id")


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
    importance = Column(String(10), default="中")          # 重要性标签：高 / 中 / 低
    owner_id = Column(Integer, ForeignKey("users.id"))    # 负责人
    goal_id = Column(Integer, ForeignKey("annual_goals.id"), nullable=True)  # 关联年度目标
    target_desc = Column(Text, default="")                # 工作目标/背景描述
    due_date = Column(String(20), default="")             # 预计完成时间 "2026-09-30"
    is_cumulative = Column(Integer, default=0)             # 是否累计制 0=否 1=是
    cum_metrics = Column(Text, default="[]")               # 累计指标定义(JSON) 如 [{"key":"offer","label":"Offer数","unit":"个"}]
    status = Column(String(20), default="进行中")         # 进行中/已完成/暂停(手动)；临期/延期系统算
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    owner = relationship("User", back_populates="work_items")
    goal = relationship("AnnualGoal", back_populates="work_items")
    weekly_progress = relationship("WeeklyProgress", back_populates="work_item")
    attachments = relationship("Attachment", back_populates="work_item")


# ========== 周报进展表 ==========
class WeeklyProgress(Base):
    __tablename__ = "weekly_progress"

    id = Column(Integer, primary_key=True, index=True)
    work_item_id = Column(Integer, ForeignKey("work_items.id"))
    week_start = Column(String(20), nullable=False)       # 周起始日期 如 "2026-08-10"
    progress = Column(Text, default="")                   # 本周进展描述
    next_plan = Column(Text, default="")                  # 下阶段计划
    blockers = Column(Text, default="")                   # 遇到的问题/需要支持
    cum_data = Column(Text, default="{}")                 # 本周累计数据(JSON) 如 {"offer":3,"onboard":2}
    status_before_ai = Column(String(20), default="draft") # draft / ai_reviewed / submitted
    ai_suggestions = Column(Text, default="")              # AI审阅建议（JSON）
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    work_item = relationship("WorkItem", back_populates="weekly_progress")


# ========== 附件表 ==========
class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    work_item_id = Column(Integer, ForeignKey("work_items.id"))
    filename = Column(String(200), nullable=False)         # 原始文件名（展示用）
    stored_name = Column(String(200), default="")           # 磁盘存储文件名（唯一）
    week_start = Column(String(20), default="")            # 关联周（哪周上传的）
    uploaded_by = Column(Integer, ForeignKey("users.id"))  # 上传人
    uploaded_at = Column(DateTime, default=datetime.now)

    work_item = relationship("WorkItem", back_populates="attachments")


# ========== 管理者批注表 ==========
class Annotation(Base):
    __tablename__ = "annotations"

    id = Column(Integer, primary_key=True, index=True)
    manager_id = Column(Integer, ForeignKey("users.id"))   # 管理者
    work_item_id = Column(Integer, ForeignKey("work_items.id"), nullable=True)  # 可为空（针对汇总/全员的批注）
    week_start = Column(String(20), nullable=False)
    content = Column(Text, default="")                     # 批注内容
    target_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 指定接收人（AI识别点名）；空=参与该事项的人或全员
    created_at = Column(DateTime, default=datetime.now)

    manager = relationship("User", back_populates="annotations", foreign_keys=[manager_id])


# ========== 待办表 ==========
class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)                 # 待办内容
    owner_id = Column(Integer, ForeignKey("users.id"))    # 责任人
    due_date = Column(String(20), default="")             # 截止时间
    status = Column(String(20), default="进行中")         # 进行中 / 已完成 / 已逾期
    week_start = Column(String(20), default="")           # 来源周
    created_at = Column(DateTime, default=datetime.now)


# ========== 反馈规则库（Agent进化） ==========
class FeedbackRule(Base):
    __tablename__ = "feedback_rules"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)                 # 规则内容
    source = Column(String(20), default="纠正")            # 纠正 / 认可
    agent = Column(String(50), default="")                 # 关联的Agent
    created_at = Column(DateTime, default=datetime.now)


# ========== 周报提交状态表 ==========
class WeeklySubmitStatus(Base):
    __tablename__ = "weekly_submit_status"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    week_start = Column(String(20), nullable=False)
    status = Column(String(20), default="draft")           # draft / submitted / overdue
    submitted_at = Column(DateTime, nullable=True)


# ========== 周汇报稿表（管理者编辑保存的向上汇报文字） ==========
class WeeklySummary(Base):
    __tablename__ = "weekly_summary"

    id = Column(Integer, primary_key=True, index=True)
    week_start = Column(String(20), nullable=False, unique=True)
    content = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


def init_db():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)


def hash_password(password: str) -> str:
    """密码哈希（sha256）"""
    import hashlib
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def seed_data():
    """初始化种子数据：用户、目标、示例工作事项"""
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return

        users = [
            User(name="肖凌华", username="xlinghua", password_hash=hash_password("123456"), role="管理者", is_manager=1, is_sysadmin=1, avatar_color="#7c3aed"),
            User(name="程宇欣", username="cyuxin", password_hash=hash_password("123456"), role="COE", business_line="", is_manager=0, is_sysadmin=1, avatar_color="#2563eb"),
            User(name="李微微", username="lweiwei", password_hash=hash_password("123456"), role="HRBP", business_line="营销板块", avatar_color="#16a34a"),
            User(name="高丽茹", username="gliru", password_hash=hash_password("123456"), role="HRBP", business_line="产研板块", avatar_color="#f97316"),
            User(name="李雯", username="lwen", password_hash=hash_password("123456"), role="HRBP", business_line="运营板块", avatar_color="#eab308"),
        ]
        db.add_all(users)
        db.flush()

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

        # 示例工作事项（含累计制）
        sample_items = [
            WorkItem(name="团队周报管理机制搭建", category="年度重点工作", importance="高",
                     owner_id=1, goal_id=6, target_desc="建立高效的工作汇报系统，实现自动化催办和AI辅助审阅",
                     due_date="2026-12-31"),
            WorkItem(name="招聘数字化工具2.0版本建设", category="年度重点工作", importance="高",
                     owner_id=2, goal_id=5, target_desc="重构招聘底层架构，完成系统2.0上线",
                     due_date="2026-12-31"),
            WorkItem(name="招聘制度修订", category="常规工作", importance="中",
                     owner_id=2, target_desc="完成2026年招聘制度的更新和发布", due_date="2026-10-31"),
            # 累计制：招聘（Offer数 + 入职数）
            WorkItem(name="营销板块招聘交付", category="年度重点工作", importance="高",
                     owner_id=3, goal_id=1, target_desc="确保营销板块关键岗位需求达成率不低于90%",
                     due_date="2026-09-30", is_cumulative=1,
                     cum_metrics='[{"key":"offer","label":"Offer数","unit":"个"},{"key":"onboard","label":"入职数","unit":"人"}]'),
            # 累计制：访谈（人次）
            WorkItem(name="营销板块员工访谈", category="常规工作", importance="中",
                     owner_id=3, target_desc="定期进行员工访谈，关注人才动态",
                     is_cumulative=1, cum_metrics='[{"key":"count","label":"访谈人次","unit":"人次"}]'),
            WorkItem(name="产研板块招聘交付", category="年度重点工作", importance="高",
                     owner_id=4, goal_id=1, target_desc="确保产研板块关键岗位需求达成率不低于90%",
                     due_date="2026-09-30", is_cumulative=1,
                     cum_metrics='[{"key":"offer","label":"Offer数","unit":"个"},{"key":"onboard","label":"入职数","unit":"人"}]'),
            WorkItem(name="产研任职资格重构", category="自主专项工作", importance="中",
                     owner_id=4, goal_id=3, target_desc="实现产研侧人才标签化", due_date="2026-10-15"),
            WorkItem(name="运营板块招聘交付", category="年度重点工作", importance="高",
                     owner_id=5, goal_id=1, target_desc="确保运营板块关键岗位需求达成率不低于90%",
                     due_date="2026-09-30", is_cumulative=1,
                     cum_metrics='[{"key":"offer","label":"Offer数","unit":"个"},{"key":"onboard","label":"入职数","unit":"人"}]'),
            WorkItem(name="运营板块岗职序列优化", category="年度重点工作", importance="高",
                     owner_id=5, goal_id=3, target_desc="优化运营板块的岗位职级序列，推动阶段性灵活用工",
                     due_date="2026-10-31"),
        ]
        db.add_all(sample_items)

        db.commit()
        print("种子数据初始化完成")
    except Exception as e:
        db.rollback()
        print(f"种子数据初始化失败: {e}")
    finally:
        db.close()
