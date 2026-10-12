"""规则分诊知识表（降级引擎 & 冷启动兜底）。

覆盖门诊最常见的主诉，用于：
1. 无大模型 Key 时的完整分诊输出
2. 大模型返回异常时的兜底
3. 对模型输出做一致性校验（科室是否落在候选集内）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas import PossibleCondition, Urgency


@dataclass
class TriageRule:
    department: str
    aliases: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    urgency: Urgency = Urgency.ROUTINE
    conditions: tuple[PossibleCondition, ...] = ()
    advice: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    weight: int = 1  # 命中多条时取权重高者


RULES: tuple[TriageRule, ...] = (
    TriageRule(
        department="心血管内科",
        aliases=("心内科",),
        patterns=(r"心悸", r"心慌", r"心跳快", r"心律不齐", r"早搏", r"心跳漏拍"),
        urgency=Urgency.URGENT,
        conditions=(
            PossibleCondition(name="心律失常", probability="high", reason="以心悸、心跳节律异常为主诉"),
            PossibleCondition(name="甲状腺功能亢进", probability="low", reason="可伴消瘦、多汗、易怒"),
            PossibleCondition(name="贫血", probability="low", reason="可伴乏力、头晕"),
        ),
        advice=(
            "记录发作时间与诱因（咖啡、浓茶、熬夜、情绪）",
            "就近做心电图，必要时做 24 小时动态心电图（Holter）",
            "伴胸痛、晕厥、持续心悸应立即急诊",
        ),
        questions=("每次持续多久？是突然开始突然停止吗？", "有没有伴胸痛、头晕或晕厥？"),
        weight=3,
    ),
    TriageRule(
        department="呼吸内科",
        aliases=("呼吸科",),
        patterns=(r"咳嗽", r"咳痰", r"气喘", r"咳血", r"咯血", r"肺炎"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="急性支气管炎", probability="high", reason="咳嗽伴咳痰，常继发于上呼吸道感染"),
            PossibleCondition(name="咳嗽变异性哮喘", probability="medium", reason="夜间或遇冷空气加重的干咳"),
            PossibleCondition(name="肺炎", probability="medium", reason="伴发热、脓痰时需排查"),
        ),
        advice=(
            "多饮温水，避免油烟与冷空气刺激",
            "发热超过 3 天或脓痰、胸痛、咯血需拍胸片",
            "咳嗽超过 8 周属慢性咳嗽，需系统评估",
        ),
        questions=("咳嗽多久了？干咳还是有痰、什么颜色？", "夜间或活动后是否加重？"),
    ),
    TriageRule(
        department="消化内科",
        aliases=("消化科",),
        patterns=(r"腹痛", r"腹泻", r"恶心", r"呕吐", r"反酸", r"烧心", r"腹胀", r"便血", r"黑便", r"便秘"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="急性胃肠炎", probability="high", reason="腹痛伴腹泻、恶心呕吐，常有不洁饮食史"),
            PossibleCondition(name="胃食管反流病", probability="medium", reason="反酸烧心，餐后或平卧加重"),
            PossibleCondition(name="功能性消化不良", probability="medium", reason="腹胀早饱，检查无明显器质性病变"),
        ),
        advice=(
            "清淡饮食，少量多次补充口服补液盐",
            "黑便、呕血、剧烈腹痛需立即急诊",
            "避免自行服用止痛药掩盖病情",
        ),
        questions=("疼痛在哪个位置？持续还是阵发性？", "大便次数、性状、有无血或黏液？"),
    ),
    TriageRule(
        department="神经内科",
        aliases=("神内科",),
        patterns=(r"头痛", r"头晕", r"眩晕", r"手麻", r"脚麻", r"抽搐", r"记忆力减退", r"失眠多梦"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="紧张型头痛", probability="medium", reason="双侧压迫感，休息可缓解"),
            PossibleCondition(name="偏头痛", probability="medium", reason="单侧搏动性，伴恶心畏光"),
            PossibleCondition(name="良性阵发性位置性眩晕", probability="medium", reason="与体位改变相关的短暂眩晕"),
        ),
        advice=(
            "记录发作频率、诱因与持续时间",
            "突发最剧烈头痛、伴发热颈硬或神经功能缺损需立即急诊",
            "保证规律作息与睡眠",
        ),
        questions=("是天旋地转还是头昏沉？", "有没有视物模糊、肢体无力或言语不清？"),
    ),
    TriageRule(
        department="耳鼻咽喉科",
        aliases=("耳鼻喉科", "ENT"),
        patterns=(r"咽痛", r"喉咙痛", r"鼻塞", r"流鼻涕", r"耳鸣", r"听力下降", r"耳痛", r"打鼾", r"鼻炎"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="急性咽炎 / 扁桃体炎", probability="high", reason="咽痛伴吞咽不适"),
            PossibleCondition(name="过敏性鼻炎", probability="high", reason="阵发喷嚏、清水样涕、鼻痒"),
            PossibleCondition(name="分泌性中耳炎", probability="medium", reason="耳闷、听力下降"),
        ),
        advice=(
            "温盐水漱口，避免辛辣刺激食物",
            "呼吸/吞咽困难、张口受限需急诊",
            "症状超过 1 周不缓解需复诊",
        ),
        questions=("有无发热、扁桃体化脓？", "症状持续几天了？"),
    ),
    TriageRule(
        department="骨科",
        aliases=("骨伤科",),
        patterns=(r"腰痛", r"颈椎", r"关节痛", r"扭伤", r"骨折", r"腿疼", r"肩膀痛", r"膝盖痛", r"腰椎间盘"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="腰肌劳损 / 肌筋膜疼痛", probability="high", reason="久坐或姿势相关酸痛"),
            PossibleCondition(name="腰椎间盘突出", probability="medium", reason="伴下肢放射痛、麻木"),
            PossibleCondition(name="膝骨关节炎", probability="medium", reason="中老年，活动后加重"),
        ),
        advice=(
            "急性期避免久坐久站与负重，48 小时内可冷敷",
            "肢体畸形、不能活动、大小便障碍需急诊",
            "影像上的突出需与症状对应，不必过度恐慌",
        ),
        questions=("是酸痛、刺痛还是触电样放射痛？", "有没有外伤史？"),
    ),
    TriageRule(
        department="皮肤科",
        aliases=("皮肤",),
        patterns=(r"皮疹", r"瘙痒", r"湿疹", r"荨麻疹", r"痘痘", r"痤疮", r"脱发", r"皮肤红"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="荨麻疹", probability="high", reason="风团样皮疹，时起时消伴瘙痒"),
            PossibleCondition(name="湿疹 / 皮炎", probability="high", reason="红斑丘疹伴渗出或苔藓化"),
            PossibleCondition(name="药物疹", probability="medium", reason="用药后新发皮疹需警惕"),
        ),
        advice=(
            "避免搔抓与热水烫洗，记录可疑接触物或新用药",
            "皮疹伴呼吸困难、面部肿胀属急症，立即急诊",
            "慢性反复者建议做过敏原与斑贴试验",
        ),
        questions=("皮疹出现多久了？是否伴发热？", "最近有更换药物或接触新物品吗？"),
    ),
    TriageRule(
        department="泌尿外科",
        aliases=("泌尿科",),
        patterns=(r"尿频", r"尿急", r"尿痛", r"血尿", r"肾结石", r"腰痛.*尿", r"前列腺"),
        urgency=Urgency.URGENT,
        conditions=(
            PossibleCondition(name="尿路感染", probability="high", reason="尿频尿急尿痛，女性多见"),
            PossibleCondition(name="泌尿系结石", probability="medium", reason="腰部绞痛伴血尿"),
            PossibleCondition(name="前列腺增生", probability="medium", reason="中老年男性夜尿增多、排尿费力"),
        ),
        advice=(
            "多饮水，避免憋尿",
            "发热伴腰痛需警惕上尿路感染，应尽快就诊",
            "肉眼血尿无论是否疼痛都需检查",
        ),
        questions=("尿液颜色如何？有无发热、腰痛？", "一天排尿多少次？"),
        weight=2,
    ),
    TriageRule(
        department="内分泌科",
        aliases=("内分泌",),
        patterns=(r"血糖", r"糖尿病", r"甲亢", r"甲减", r"甲状腺", r"尿酸", r"痛风", r"肥胖", r"血脂"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="2 型糖尿病", probability="high", reason="空腹血糖或 HbA1c 升高"),
            PossibleCondition(name="甲状腺功能异常", probability="medium", reason="需结合 TSH、FT3、FT4"),
            PossibleCondition(name="高尿酸血症 / 痛风", probability="medium", reason="血尿酸升高伴关节红肿痛"),
        ),
        advice=(
            "携带近期化验单就诊，便于对比趋势",
            "控制总热量摄入，规律运动",
            "血糖持续 > 16.7 或伴恶心呕吐需急诊排查酮症",
        ),
        questions=("最近一次化验的具体数值是多少？", "有没有多饮多尿、体重变化？"),
    ),
    TriageRule(
        department="妇科",
        patterns=(r"月经", r"白带", r"阴道", r"外阴", r"乳腺", r"乳房", r"怀孕", r"避孕", r"盆腔"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="月经失调", probability="high", reason="周期或经量改变"),
            PossibleCondition(name="阴道炎", probability="medium", reason="白带性状改变伴异味或瘙痒"),
            PossibleCondition(name="乳腺增生 / 结节", probability="medium", reason="需超声与 BI-RADS 评估"),
        ),
        advice=(
            "记录末次月经日期与周期长度",
            "育龄期腹痛伴停经必须排查异位妊娠",
            "定期做宫颈筛查与乳腺检查",
        ),
        questions=("末次月经是什么时候？", "白带颜色、气味、有无瘙痒？"),
    ),
    TriageRule(
        department="儿科",
        patterns=(r"孩子", r"宝宝", r"小孩", r"儿童", r"婴儿", r"幼儿", r"发烧.*孩子", r"疫苗"),
        urgency=Urgency.URGENT,
        conditions=(
            PossibleCondition(name="上呼吸道感染", probability="high", reason="儿童发热最常见原因"),
            PossibleCondition(name="手足口病 / 幼儿急疹", probability="medium", reason="伴特征性皮疹时需鉴别"),
            PossibleCondition(name="急性胃肠炎", probability="medium", reason="呕吐腹泻伴脱水风险"),
        ),
        advice=(
            "3 个月以下婴儿发热立即就医",
            "观察精神状态、尿量、呼吸与皮肤弹性判断脱水",
            "抽搐、嗜睡、拒食、呼吸急促需急诊",
        ),
        questions=("孩子多大了？体温最高多少？", "精神状态和吃奶/进食情况怎么样？"),
        weight=4,
    ),
    TriageRule(
        department="眼科",
        patterns=(r"眼睛", r"眼红", r"眼痛", r"视力", r"眼干", r"眼睛痒", r"飞蚊"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="结膜炎", probability="high", reason="眼红分泌物增多"),
            PossibleCondition(name="干眼症", probability="medium", reason="眼干涩、用眼疲劳后加重"),
        ),
        advice=(
            "避免揉眼与共用毛巾",
            "突发视力下降、眼痛伴头痛恶心需立即急诊",
        ),
        questions=("有无分泌物？视力是否受影响？",),
    ),
    TriageRule(
        department="口腔科",
        patterns=(r"牙痛", r"牙疼", r"牙龈", r"蛀牙", r"智齿", r"口腔溃疡"),
        urgency=Urgency.ROUTINE,
        conditions=(PossibleCondition(name="牙髓炎 / 龋齿", probability="high", reason="冷热刺激痛或自发痛"),),
        advice=("避免用患侧咀嚼", "面部肿胀伴发热需及时就诊"),
        questions=("疼痛是持续性还是刺激性？",),
    ),
    TriageRule(
        department="精神心理科",
        aliases=("心理科", "精神科"),
        patterns=(r"焦虑", r"抑郁", r"情绪低落", r"压力大", r"睡不着", r"紧张.*心慌", r"强迫"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="焦虑障碍", probability="medium", reason="过度担心伴躯体症状"),
            PossibleCondition(name="抑郁障碍", probability="medium", reason="持续情绪低落、兴趣减退"),
        ),
        advice=(
            "规律作息与有氧运动有助于改善情绪",
            "若出现伤害自己的想法，请立即联系 12356 心理援助热线或急诊",
            "建议做规范的量表评估",
        ),
        questions=("这种状态持续多久了？", "有没有影响到工作或睡眠？"),
    ),
    TriageRule(
        department="普通外科",
        aliases=("普外科", "外科"),
        patterns=(r"肿块", r"外伤", r"伤口", r"烫伤", r"痔疮", r"疝气", r"阑尾"),
        urgency=Urgency.URGENT,
        conditions=(PossibleCondition(name="软组织外伤 / 体表肿物", probability="high", reason="外伤或可触及肿物"),),
        advice=("伤口及时清创，注意破伤风预防", "肿块短期内增大、固定、质硬需尽快就诊"),
        questions=("受伤/发现多久了？有无红肿热痛？",),
    ),
    TriageRule(
        department="全科医学科",
        aliases=("全科", "普通内科"),
        patterns=(r"发热", r"发烧", r"乏力", r"没力气", r"消瘦", r"体重下降", r"水肿", r"体检"),
        urgency=Urgency.ROUTINE,
        conditions=(
            PossibleCondition(name="感染性疾病", probability="medium", reason="发热最常见病因"),
            PossibleCondition(name="代谢 / 内分泌紊乱", probability="low", reason="乏力伴体重变化需筛查"),
        ),
        advice=(
            "记录体温曲线与伴随症状",
            "发热超过 3 天或体温 ≥ 39.5℃ 应就诊",
            "可先做血常规、CRP 等基础筛查",
        ),
        questions=("体温多少？持续几天了？", "还有其他不舒服吗？"),
    ),
)


def match_rules(text: str) -> list[TriageRule]:
    """返回按权重降序命中的规则列表。"""
    hits: list[TriageRule] = []
    content = text or ""
    for rule in RULES:
        for pattern in rule.patterns:
            if re.search(pattern, content):
                hits.append(rule)
                break
    hits.sort(key=lambda r: r.weight, reverse=True)
    return hits
