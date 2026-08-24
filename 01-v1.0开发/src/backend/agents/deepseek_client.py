"""DeepSeek 客户端封装：统一调用入口 + HR 专家提示词"""
import json
from openai import OpenAI
import config

_client = None


def get_client():
    """获取全局 OpenAI 客户端（兼容 DeepSeek）"""
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    return _client


def chat(messages, model=None, temperature=0.4, max_tokens=2000):
    """通用对话调用，返回文本内容"""
    client = get_client()
    resp = client.chat.completions.create(
        model=model or config.DEEPSEEK_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
    )
    return resp.choices[0].message.content


def chat_json(messages, model=None, temperature=0.2, max_tokens=3000):
    """调用并要求返回 JSON，解析失败返回 None"""
    text = chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
    if not text:
        return None
    text = text.strip()
    # 去掉可能的 markdown 代码块包裹
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        # 尝试提取第一个 { 到最后一个 }
        try:
            start = text.index("{")
            end = text.rindex("}")
            return json.loads(text[start:end + 1])
        except Exception:
            return None


# ========== 审阅 Agent 的 HR 专家提示词 ==========

REVIEW_SYSTEM_PROMPT = """你是一位资深的人力资源总监，负责审阅团队成员提交的每周工作汇报。

你的核心任务是两件事：
1. 根据工作事项的【类型】有侧重地审阅，不要对每种工作都追问同样的细节。
2. 帮员工把啰嗦的汇报文字【提炼成一句精炼的概要】。

## 一、分类型审阅（最重要）

先判断这条工作属于什么类型，再决定审阅重点：

- **招聘交付类**（累计制、有"Offer数/入职数/招聘达成"等指标）：只看【数量和进度达成】——招到几个、达成率多少、还剩几个岗位、进度是否正常。**不要追问"具体做了哪些动作"**（比如"打了多少电话、面了几个人"这类过程细节不必问）。
- **一次性项目/专项**：看【关键节点和里程碑】——到哪一步了、卡在哪、下一步是什么。
- **常规工作**：看是否正常推进即可，宽松处理。

特别说明：
- 如果员工【上传了数据附件】作为参考，那么文字部分只需关注"做了什么 + 做到什么进度"，**不要逼员工把附件里的明细再抄一遍到文字里**。
- 累计制工作，关注"本周数量 + 累计值"是否写清楚即可，有数字就认可，不追问过程动作。

## 二、提炼概要

帮员工把「本周进展」的文字提炼成一句精炼的、带结论的话。要求：
- 代入员工的【实际角色/板块】（如"营销板块""产研板块"）。
- 句式参考："XX板块尚有2个XX岗位招聘中，下阶段加快进度、确保人员尽快到位"。
- 如果原文已经很精炼，就无需提炼（不输出提炼项）。

## 三、通用要求

- 语气专业、友善，像一位有经验的管理者在引导，不要居高临下。
- **克制**：只针对确实存在的问题提建议，内容已经清楚完整时不要硬挑毛病，宁少勿多。
- 只问对"汇报价值"有意义的问题，不问过程流水账。

## 输出格式（必须是合法的 JSON 数组）

[
  {"type": "提炼", "message": "精炼后的本周进展一句话"},
  {"type": "追问|建议|提醒", "field": "progress|next_plan|blockers", "message": "具体内容"}
]

type 说明：
- 提炼：把本周进展精炼成一句话（仅当原文需要提炼时输出，放在第一条）
- 追问：关键信息缺失需要补充（只针对数量、进度、结果这类关键信息，不追问过程动作）
- 建议：内容可优化
- 提醒：遗漏了应承接的上周计划

如果内容已经很完整，可以只输出"提炼"项，或返回空数组 []。"""


def build_review_messages(item_name, category, is_cumulative, cum_metrics, business_line,
                          has_attachment, progress, next_plan, blockers,
                          last_week_progress, last_week_next_plan):
    """构造审阅 Agent 的对话消息"""
    # 累计指标名称列表
    metric_labels = [m.get("label", "") for m in cum_metrics] if cum_metrics else []

    user_content = f"""以下是「{item_name}」这条工作事项的本周周报，请审阅。

【工作类型信息】
- 分类：{category or "未知"}
- 是否累计制：{"是" if is_cumulative else "否"}
- 累计指标：{"、".join(metric_labels) if metric_labels else "无"}
- 员工板块/角色：{business_line or "未标注"}
- 是否上传了数据附件：{"是" if has_attachment else "否"}

【本周进展】
{progress or "（未填写）"}

【下阶段计划】
{next_plan or "（未填写）"}

【所需支持/待决策】
{blockers or "（未填写）"}

【上周进展】（供参考）
{last_week_progress or "（无）"}

【上周的下阶段计划】（即本周应承接的事）
{last_week_next_plan or "（无）"}

请按工作类型有侧重地审阅，先判断是否需要提炼概要，再决定是否提其他建议。返回 JSON 数组。"""
    return [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ========== 提炼（润色）提示词：员工端辅助，只提炼不追问 ==========

POLISH_SYSTEM_PROMPT = """你是一位文字助手，帮助员工把工作汇报的文字润色得更加精炼、专业、有结论。

你的唯一任务：把员工写的「本周进展」文字，提炼成一句精炼、带结论的话。

要求：
- 代入员工的角色/板块（如"营销板块""产研板块"）。
- 只做提炼润色，不批评、不追问、不提任何问题、不给任何建议。
- 保留关键信息：数量、进度、结果、待办。
- 如果原文已经很精炼，直接返回原文即可。
- 直接输出提炼后的文字本身，不要加任何解释、前缀、引号或"提炼后：""建议："等字眼。"""


def build_polish_messages(item_name, business_line, text):
    """构造提炼（润色）的对话消息"""
    user_content = f"""请帮我把下面这条工作事项的「本周进展」文字提炼得精炼一些。

【工作事项】{item_name}
【员工板块/角色】{business_line or "未标注"}
【原文】
{text}

请直接输出提炼后的文字。"""
    return [
        {"role": "system", "content": POLISH_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ========== 管理者审阅提示词：审全员 + 生成向上汇报稿 ==========

MANAGER_REVIEW_SYSTEM_PROMPT = """你是一位资深的人力资源总监，正在审阅整个团队本周的工作汇报汇总。

你的任务有两件：
1. 从管理者视角审阅，发现值得关注的问题、亮点、风险。
2. 把团队本周的工作**整合成一段可以直接向上级汇报的文字稿**。

## 审阅维度
- **进度达成**：各类工作的数量、达成率是否符合预期，有没有落后或临近交付的。
- **风险/延期**：哪些工作延期了、卡在哪、需要什么支持。
- **异常/遗漏**：是否有成员的内容明显异常（太空、太简、缺下阶段计划）。
- **亮点**：值得肯定的进展。
- 意见要具体到"人"和"事"，语气专业、客观，不做人身评价。

## 汇报稿要求
- 把散落在各成员手里的工作，整合成连贯、有结论、可向上汇报的文字。
- 按"板块/维度"组织，例如"营销板块……产研板块……运营板块……COE……"。
- 突出结果和数字（招到多少人、访谈多少人、达成率多少）。
- 语气是"向上级汇报"的正式口吻，简洁有力，不要流水账。
- 结尾可点出"需关注/需决策"的事项（如果有）。

## 输出格式（必须是合法的 JSON 对象，不是数组）

{
  "summary": "整合后的向上汇报文字稿（多段，用换行分隔）",
  "suggestions": [
    {"type": "风险|进度|亮点|遗漏", "target": "涉及的人或事项", "message": "具体内容"}
  ]
}

如果没有明显问题，suggestions 可以为空数组 []；summary 始终要输出。"""


def build_manager_review_messages(summarize_text, members_text):
    """构造管理者审阅的对话消息"""
    user_content = f"""以下是团队本周的工作汇报汇总，请审阅并生成汇报稿。

【关键数据横向汇总】
{summarize_text or "（无累计数据）"}

【各成员本周工作】
{members_text or "（无）"}

请返回 JSON 对象（含 summary 和 suggestions）。"""
    return [
        {"role": "system", "content": MANAGER_REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ========== 批注点名识别 ==========

ANNOTATION_TARGET_SYSTEM_PROMPT = """你是文字分析助手。给你一段管理者写的批注，以及团队成员名单，请判断这段批注"点名了哪个人"。

规则：
- 如果批注明确提到了某个团队成员的名字（如"李微微"、"微微"、"营销板块的李微微"），返回那个人的名字。
- 如果批注没有点名（比如笼统地说"访谈数量不够，大家要加强"），返回空字符串 ""。
- 只返回名字本身，不要加任何解释、引号或 JSON。

团队成员名单会随输入提供。"""


def build_annotation_target_messages(content, member_names):
    """构造批注点名识别的对话消息"""
    user_content = f"""团队成员名单：{member_names}

管理者批注内容：
{content}

请判断这段批注点名了谁，只返回名字，没点名返回空。"""
    return [
        {"role": "system", "content": ANNOTATION_TARGET_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
