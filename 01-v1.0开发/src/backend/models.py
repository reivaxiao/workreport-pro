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


# ========== 工作分类字典表（职能 / 一级模块 / 二级模块） ==========
class WorkCategory(Base):
    __tablename__ = "work_categories"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(Integer, nullable=False)              # 1=职能 2=一级模块 3=二级模块
    name = Column(String(100), nullable=False)           # 名称
    parent_id = Column(Integer, ForeignKey("work_categories.id"), nullable=True)  # 上级分类
    sort_order = Column(Integer, default=0)              # 排序

    children = relationship("WorkCategory")


# ========== 工作事项表 ==========
class WorkItem(Base):
    __tablename__ = "work_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)            # 事项名称
    category = Column(String(20), nullable=False)         # 工作性质：年度重点工作 / 年度专项工作 / 日常常规工作
    importance = Column(String(10), default="中")          # 重要性标签：高 / 中 / 低
    function = Column(String(100), default="")            # 职能（如 招聘COE、KA-HRBP）
    module1 = Column(String(100), default="")             # 一级模块（工作模块，如 制度管理、渠道管理）
    module2 = Column(String(100), default="")             # 二级模块（具体工作事项，如 内部推荐、内部招聘）
    owner_id = Column(Integer, ForeignKey("users.id"))    # 负责人
    goal_id = Column(Integer, ForeignKey("annual_goals.id"), nullable=True)  # 关联年度目标
    target_desc = Column(Text, default="")                # 工作目标/背景描述
    due_date = Column(String(20), default="")             # 预计完成时间 "2026-09-30"
    is_cumulative = Column(Integer, default=0)             # 是否累计制 0=否 1=是
    cum_metrics = Column(Text, default="[]")               # 累计指标定义(JSON) 如 [{"key":"offer","label":"Offer数","unit":"个"}]
    status = Column(String(20), default="进行中")         # 进行中/已完成/暂停(手动)；临期/延期系统算
    completed_week = Column(String(20), default="")        # 完成周（管理者例会确认办结时记录）
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
    content = Column(Text, nullable=False)                 # 待办内容（下阶段计划）
    owner_id = Column(Integer, ForeignKey("users.id"))    # 责任人
    work_item_name = Column(String(200), default="")       # 所属工作事项名（按工作汇总用）
    due_date = Column(String(20), default="")             # 截止时间
    status = Column(String(20), default="进行中")         # 进行中 / 已完成 / 已取消
    week_start = Column(String(20), default="")           # 来源周
    created_at = Column(DateTime, default=datetime.now)


# ========== 重点工作汇报文字表（管理者修改后的提炼文字，不动员工原始周报） ==========
class KeyWorkText(Base):
    __tablename__ = "key_work_text"

    id = Column(Integer, primary_key=True, index=True)
    work_item_id = Column(Integer, ForeignKey("work_items.id"))  # 关联重点工作项
    week_start = Column(String(20), nullable=False)              # 周
    content = Column(Text, default="")                           # 管理者修改后的汇报文字
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ========== 个人待办表（私人便利贴，仅本人可见，完成即消失） ==========
class PersonalTodo(Base):
    __tablename__ = "personal_todos"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))     # 归属人（仅本人可见）
    content = Column(Text, nullable=False)                 # 待办内容
    done = Column(Integer, default=0)                      # 0=未完成 1=已完成（完成后不展示）
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

        # 工作分类字典（职能 → 一级模块 → 二级模块）
        category_dict = {
            "招聘COE": {
                "招聘系统管理": ["招聘系统运营"],
                "招聘赋能": ["BP/面试官赋能"],
                "制度管理": ["制度更新"],
                "招聘预算管理": ["预算统计/预警"],
                "供应商管理": ["商务管理"],
                "内部渠道管理": ["内部推荐", "内部招聘"],
                "外包管理": ["人员管理", "供应商管理"],
                "校园招聘": ["秋季校园招聘"],
                "雇主品牌运营管理": ["外部舆情监控", "公众号运营"],
                "校企关系": ["校企合作"],
            },
            "KA-HRBP": {
                "常规招聘交付": ["招聘交付"],
                "人力成本/人效": ["管控成本/监控人效"],
                "激励方案": ["激励方案"],
                "COE侧工作": ["年度目标", "年度晋升"],
                "常规/日常工作": ["培训支持", "干部/员工访谈", "劳动合同续签", "劳动争议", "组织及人员异动"],
            },
        }
        for func_name, modules in category_dict.items():
            func = WorkCategory(level=1, name=func_name)
            db.add(func)
            db.flush()
            for m1_name, m2_list in modules.items():
                m1 = WorkCategory(level=2, name=m1_name, parent_id=func.id)
                db.add(m1)
                db.flush()
                for m2_name in m2_list:
                    db.add(WorkCategory(level=3, name=m2_name, parent_id=m1.id))

        # 示例工作事项（含累计制）
        sample_items = [
            WorkItem(name="团队周报管理机制搭建", category="年度重点工作", importance="高",
                     owner_id=1, goal_id=6, target_desc="建立高效的工作汇报系统，实现自动化催办和AI辅助审阅",
                     due_date="2026-12-31", function="KA-HRBP", module1="COE侧工作", module2="年度目标"),
            WorkItem(name="招聘数字化工具2.0版本建设", category="年度重点工作", importance="高",
                     owner_id=2, goal_id=5, target_desc="重构招聘底层架构，完成系统2.0上线",
                     due_date="2026-12-31", function="招聘COE", module1="招聘系统管理", module2="招聘系统运营"),
            WorkItem(name="招聘制度修订", category="日常常规工作", importance="中",
                     owner_id=2, target_desc="完成2026年招聘制度的更新和发布", due_date="2026-10-31",
                     function="招聘COE", module1="制度管理", module2="制度更新"),
            # 累计制：招聘（Offer数 + 入职数）—— 三个板块的招聘交付，module2 相同以便汇报视图聚合
            WorkItem(name="营销板块招聘交付", category="年度重点工作", importance="高",
                     owner_id=3, goal_id=1, target_desc="确保营销板块关键岗位需求达成率不低于90%",
                     due_date="2026-09-30", is_cumulative=1,
                     cum_metrics='[{"key":"offer","label":"Offer数","unit":"个"},{"key":"onboard","label":"入职数","unit":"人"}]',
                     function="KA-HRBP", module1="常规招聘交付", module2="招聘交付"),
            # 累计制：访谈（人次）
            WorkItem(name="营销板块员工访谈", category="日常常规工作", importance="中",
                     owner_id=3, target_desc="定期进行员工访谈，关注人才动态",
                     is_cumulative=1, cum_metrics='[{"key":"count","label":"访谈人次","unit":"人次"}]',
                     function="KA-HRBP", module1="人力成本/人效", module2="管控成本/监控人效"),
            WorkItem(name="产研板块招聘交付", category="年度重点工作", importance="高",
                     owner_id=4, goal_id=1, target_desc="确保产研板块关键岗位需求达成率不低于90%",
                     due_date="2026-09-30", is_cumulative=1,
                     cum_metrics='[{"key":"offer","label":"Offer数","unit":"个"},{"key":"onboard","label":"入职数","unit":"人"}]',
                     function="KA-HRBP", module1="常规招聘交付", module2="招聘交付"),
            WorkItem(name="产研任职资格重构", category="年度专项工作", importance="中",
                     owner_id=4, goal_id=3, target_desc="实现产研侧人才标签化", due_date="2026-10-15",
                     function="KA-HRBP", module1="激励方案", module2="激励方案"),
            WorkItem(name="运营板块招聘交付", category="年度重点工作", importance="高",
                     owner_id=5, goal_id=1, target_desc="确保运营板块关键岗位需求达成率不低于90%",
                     due_date="2026-09-30", is_cumulative=1,
                     cum_metrics='[{"key":"offer","label":"Offer数","unit":"个"},{"key":"onboard","label":"入职数","unit":"人"}]',
                     function="KA-HRBP", module1="常规招聘交付", module2="招聘交付"),
            WorkItem(name="运营板块岗职序列优化", category="年度重点工作", importance="高",
                     owner_id=5, goal_id=3, target_desc="优化运营板块的岗位职级序列，推动阶段性灵活用工",
                     due_date="2026-10-31", function="KA-HRBP", module1="激励方案", module2="激励方案"),
        ]
        db.add_all(sample_items)

        db.commit()
        print("种子数据初始化完成")
    except Exception as e:
        db.rollback()
        print(f"种子数据初始化失败: {e}")
    finally:
        db.close()
