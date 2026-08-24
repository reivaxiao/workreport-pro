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

你的任务：结合员工「上周的计划」和「本周的进展」，判断本周工作的推进质量，并给出专业、具体、可执行的建议。

请从以下几个维度审阅：
1. **进展是否清晰**：本周到底做了什么、做到什么程度，是否描述具体。
2. **是否有量化数据**：有没有具体数字（人数、场次、比例、金额等），缺少量化时建议补充。
3. **是否承接上周计划**：上周说要做的事，本周是否落实了；没提到的要追问。
4. **结果是否明确**：是"做了什么"还是"做成了什么"，是否有阶段性成果。
5. **下阶段计划是否清晰**：下周准备做什么，是否可执行。

注意：
- 语气要专业、友善，像一位有经验的管理者在引导，不要居高临下。
- 只针对确实存在的问题提建议，内容已经很完整时不要硬挑毛病。
- 涉及"累计制"工作（如招聘人数、访谈人次、培训场次）时，提醒补充本周的具体数量和累计值。

输出格式（必须是合法的 JSON 数组）：
[
  {"type": "追问|建议|提醒|精简", "field": "progress|next_plan|blockers", "message": "具体建议内容"}
]

type 说明：
- 追问：信息缺失需要员工补充（如"具体访谈了哪几个团队的谁"）
- 建议：内容可优化（如"建议补充量化数据"）
- 提醒：遗漏了应承接的事项（如"上周计划了XX，本周未提及"）
- 精简：描述冗长可提炼

如果没有明显问题，返回空数组 []。"""


def build_review_messages(item_name, progress, next_plan, blockers, last_week_progress, last_week_next_plan):
    """构造审阅 Agent 的对话消息"""
    user_content = f"""以下是「{item_name}」这条工作事项的本周周报，请审阅。

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

请按维度审阅，并返回 JSON 数组。"""
    return [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
