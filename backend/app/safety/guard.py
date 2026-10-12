"""医疗安全护栏（Medical Safety Guard）。

这是整个系统里优先级最高的模块：**任何情况下，只要命中有生命危险的"红旗症状"，
必须立刻给出急诊/120 指引，并且不再由大模型自由发挥。**

所有规则均以国内外通行急诊分诊共识为参照（胸痛中心、卒中 FAST 原则、脓毒症筛查等），
仅用于风险提示，不构成诊断。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas import PossibleCondition, TriageResult, Urgency


@dataclass(frozen=True)
class RedFlag:
    """一条红旗规则。"""

    key: str
    patterns: tuple[str, ...]
    department: str
    conditions: tuple[str, ...]
    # 已经命中时给出的一句话紧急处置建议
    action: str


RED_FLAGS: tuple[RedFlag, ...] = (
    RedFlag(
        key="acs",
        patterns=(r"胸痛", r"胸口痛", r"心前区痛", r"胸口压榨", r"胸痛.*出汗", r"心绞痛"),
        department="急诊科（胸痛中心）",
        conditions=("急性冠脉综合征 / 心肌梗死", "不稳定型心绞痛", "主动脉夹层"),
        action="立即停止活动、就地休息，拨打 120；若既往有硝酸甘油可按既往医嘱舌下含服，切勿自行驾车前往医院。",
    ),
    RedFlag(
        key="stroke",
        patterns=(
            r"偏瘫",
            r"一侧(?:肢体|手脚|手|脚|胳膊|腿|身子).{0,6}(?:无力|没力气|没力|使不上劲|抬不起来|动不了)",
            r"(?:半身|半边).{0,4}(?:无力|没力|麻木|动不了)",
            r"口角歪斜", r"嘴歪", r"流口水.*说话",
            r"(?:说话|言语|表达|吐字).{0,4}(?:不清|含糊|困难|不利索|说不出来)",
            r"突然.*晕倒", r"走路不稳.*突发",
        ),
        department="急诊科（卒中中心）",
        conditions=("急性脑卒中（脑梗死 / 脑出血）",),
        action="记住发病时间并立即拨打 120，就近送往有卒中中心的医院；不要进食进水，以免误吸。",
    ),
    RedFlag(
        key="respiratory",
        patterns=(r"呼吸困难", r"喘不上气", r"无法平卧", r"口唇发紫", r"严重气促", r"窒息"),
        department="急诊科 / 呼吸内科",
        conditions=("急性心力衰竭", "重症哮喘 / COPD 急性加重", "肺栓塞", "气胸"),
        action="取坐位或半卧位，保持安静，立即拨打 120；如有家用氧气可按既往医嘱吸氧。",
    ),
    RedFlag(
        key="consciousness",
        patterns=(r"意识不清", r"昏迷", r"叫不醒", r"抽搐", r"癫痫发作", r"晕厥.*反复"),
        department="急诊科 / 神经内科",
        conditions=("晕厥 / 休克", "癫痫发作", "低血糖昏迷", "颅内病变"),
        action="让患者侧卧防止误吸，不要往嘴里塞任何东西，立即拨打 120。",
    ),
    RedFlag(
        key="bleeding",
        patterns=(r"大出血", r"呕血", r"咯血", r"便血.*大量", r"止不住的血", r"外伤.*出血不止"),
        department="急诊科",
        conditions=("上消化道出血", "咯血", "失血性休克"),
        action="压迫止血、保持平卧，立即拨打 120；呕血时禁食禁水。",
    ),
    RedFlag(
        key="pregnancy",
        patterns=(r"怀孕.*出血", r"孕.*腹痛", r"胎动减少", r"孕妇.*剧烈头痛"),
        department="产科急诊",
        conditions=("先兆流产 / 异位妊娠", "子痫前期"),
        action="立即前往产科急诊或拨打 120，避免自行服药。",
    ),
    RedFlag(
        key="child_fever",
        patterns=(r"婴儿.*高热", r"月龄?.*发热", r"小孩.*抽搐", r"新生儿.*黄疸.*加重"),
        department="儿科急诊",
        conditions=("婴幼儿高热惊厥", "新生儿感染"),
        action="3 个月以下婴儿发热请立即就医；高热时按体重使用对乙酰氨基酚或布洛芬，并及时就诊。",
    ),
    RedFlag(
        key="mental",
        patterns=(r"不想活", r"自杀", r"轻生", r"结束生命"),
        department="精神科 / 心理危机干预",
        conditions=("自杀风险",),
        action="请立即联系身边人陪同，并拨打心理援助热线 12356 或 120；你的安全最重要。",
    ),
    RedFlag(
        key="anaphylaxis",
        patterns=(r"过敏.*呼吸困难", r"喉头水肿", r"全身皮疹.*气促", r"过敏性休克"),
        department="急诊科",
        conditions=("过敏性休克", "严重过敏反应"),
        action="若随身携带肾上腺素自动注射器请立即使用，并拨打 120。",
    ),
    RedFlag(
        key="acute_abdomen",
        patterns=(r"剧烈腹痛", r"腹痛.*板状", r"右下腹.*剧痛", r"腹痛.*不能触碰"),
        department="急诊外科 / 普外科",
        conditions=("急性阑尾炎", "消化道穿孔", "急性胰腺炎", "宫外孕"),
        action="禁食禁水，不要服用止痛药掩盖病情，立即前往急诊。",
    ),
)


@dataclass
class GuardHit:
    flag: RedFlag
    matched: str = ""


@dataclass
class GuardResult:
    hits: list[GuardHit] = field(default_factory=list)

    @property
    def triggered(self) -> bool:
        return bool(self.hits)

    @property
    def department(self) -> str:
        return self.hits[0].flag.department if self.hits else ""

    @property
    def conditions(self) -> list[str]:
        out: list[str] = []
        for h in self.hits:
            out.extend(h.flag.conditions)
        # 去重保序
        return list(dict.fromkeys(out))


def scan(text: str) -> GuardResult:
    """扫描用户输入与上下文，返回命中的红旗规则。"""
    content = text or ""
    result = GuardResult()
    for flag in RED_FLAGS:
        for pattern in flag.patterns:
            m = re.search(pattern, content)
            if m:
                result.hits.append(GuardHit(flag=flag, matched=m.group(0)))
                break
    return result


def build_emergency_result(guard: GuardResult, disclaimer: str) -> TriageResult:
    """生成紧急分诊卡片。"""
    advice: list[str] = []
    for h in guard.hits:
        advice.append(h.flag.action)
    advice.extend(
        [
            "保持电话畅通，准备好既往病历与正在服用的药物清单。",
            "在专业医护人员到达前，尽量不要搬动患者。",
        ]
    )
    return TriageResult(
        department=guard.department or "急诊科",
        department_aliases=["急诊", "Emergency"],
        urgency=Urgency.EMERGENCY,
        urgency_reason="描述中包含需要立即评估的危险信号（红旗症状）。",
        possible_conditions=[
            PossibleCondition(name=name, probability="high", reason="与红旗症状高度相关，需由医生立即排查")
            for name in guard.conditions
        ],
        advice=advice,
        followup_questions=[],
        red_flags=[f"{h.flag.key}:{h.matched}" for h in guard.hits],
        need_more_info=False,
        disclaimer=disclaimer,
    )


def render_answer(guard: GuardResult, disclaimer: str) -> tuple[str, TriageResult]:
    """把护栏命中结果渲染成（回答文案, 结构化分诊卡片）。"""
    triage = build_emergency_result(guard, disclaimer)
    answer = EMERGENCY_ANSWER_TEMPLATE.format(
        matched="、".join(sorted({h.matched for h in guard.hits})),
        department=triage.department,
        conditions="\n".join(f"- {c.name}" for c in triage.possible_conditions),
        advice="\n".join(f"{i}. {a}" for i, a in enumerate(triage.advice, 1)),
        disclaimer=disclaimer,
    )
    return answer, triage


EMERGENCY_ANSWER_TEMPLATE = """⚠️ **请立即就医 / 拨打 120**

你描述的情况中包含需要**立即由医生评估**的危险信号：{matched}

**建议首诊科室**：{department}

**需要紧急排查的情况**
{conditions}

**现在就做的事**
{advice}

{disclaimer}"""
