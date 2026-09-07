"""
Nexus-Ω V2 — 行为·决策·记忆·思考 四象认知引擎

核心升级：
  行为：规划20步，按优先级排序，但不按顺序执行——可按依赖关系多步并行
  决策：每步生成多条路线，四维评分（记忆/风险/效率/新颖），选Top执行
  记忆：三层记忆——经验回溯(过往成功) / 随机探索(发现新路) / 默认路线(安全兜底)
  思考：第三人称后台监管，实时审计每步决策，可否决/重定向/加速

纯Python标准库，零依赖，秒启动。
"""
import math
import random
import time
from typing import List, Dict, Tuple, Optional, Set

# ==========================================================================
# 工具函数
# ==========================================================================
def random_vec(dim=8) -> List[float]:
    vec = [random.uniform(-1, 1) for _ in range(dim)]
    norm = math.sqrt(sum(v**2 for v in vec))
    return [v / norm for v in vec]

def cos_sim(a: List[float], b: List[float]) -> float:
    dot = sum(ai * bi for ai, bi in zip(a, b))
    return max(-1.0, min(1.0, dot))

def vec_mix(a, b, weight=0.5):
    mixed = [a[i] * (1 - weight) + b[i] * weight for i in range(len(a))]
    norm = math.sqrt(sum(v**2 for v in mixed)) or 1
    return [v / norm for v in mixed]


# ==========================================================================
# 记忆层 — 三层记忆系统
# ==========================================================================
class MemoryLayer:
    """三层记忆：经验回溯 / 随机探索 / 默认路线"""

    DEFAULT_ROUTES = [
        {"id": "D1", "name": "安全分析", "desc": "保守的逻辑分析路线", "vector": None},
        {"id": "D2", "name": "标准检索", "desc": "常规信息检索路线", "vector": None},
        {"id": "D3", "name": "通用回答", "desc": "通用知识问答路线", "vector": None},
    ]

    def __init__(self):
        # 经验记忆：过往成功路径（会随执行增长）
        self.experiences: List[Dict] = [
            {"id": "E1", "name": "逻辑推演", "desc": "上次用逻辑推演成功解决了数学问题", "vector": random_vec(), "success_count": 3},
            {"id": "E2", "name": "共情分析", "desc": "上次用共情分析处理了情感问题", "vector": random_vec(), "success_count": 2},
            {"id": "E3", "name": "调试拆解", "desc": "上次用调试拆解修复了代码bug", "vector": random_vec(), "success_count": 4},
            {"id": "E4", "name": "类比迁移", "desc": "上次用类比迁移解释了复杂概念", "vector": random_vec(), "success_count": 1},
        ]
        # 为默认路线也生成向量
        for d in self.DEFAULT_ROUTES:
            d["vector"] = random_vec()

        self.recall_log: List[str] = []

    def recall(self, query_vec: List[float]) -> Dict:
        """
        三层记忆召回：
          60% 概率走经验回溯（最相关的历史成功路径）
          25% 概率走随机探索（发现新路线）
          15% 概率走默认路线（安全兜底）
        """
        roll = random.random()

        if roll < 0.60:
            # 经验回溯：按相似度+成功率加权
            scored = []
            for exp in self.experiences:
                sim = cos_sim(query_vec, exp["vector"])
                weighted = sim * 0.6 + (exp["success_count"] / 10) * 0.4
                scored.append((weighted, exp))
            scored.sort(key=lambda x: x[0], reverse=True)
            chosen = scored[0][1]
            self.recall_log.append(f"[经验回溯] 唤醒: {chosen['name']} (相似度={scored[0][0]:.2f})")
            return {"source": "experience", **chosen}

        elif roll < 0.85:
            # 随机探索：生成全新路线
            new_route = {
                "id": f"R{random.randint(100, 999)}",
                "name": random.choice(["直觉跳跃", "侧向思维", "逆向推理", "跨界联想", "元类比"]),
                "desc": "随机探索新路线",
                "vector": random_vec(),
            }
            self.recall_log.append(f"[随机探索] 生成: {new_route['name']} (全新路径)")
            return {"source": "random", **new_route}

        else:
            # 默认路线：安全兜底
            chosen = random.choice(self.DEFAULT_ROUTES)
            self.recall_log.append(f"[默认路线] 回退: {chosen['name']} (安全兜底)")
            return {"source": "default", **chosen}

    def record_success(self, route: Dict):
        """记录成功路径到经验记忆"""
        # 检查是否已有同名经验
        for exp in self.experiences:
            if exp["name"] == route.get("name"):
                exp["success_count"] += 1
                exp["vector"] = vec_mix(exp["vector"], route.get("vector", exp["vector"]), 0.2)
                return
        # 新增经验
        self.experiences.append({
            "id": f"E{len(self.experiences)+1}",
            "name": route.get("name", "未知"),
            "desc": route.get("desc", ""),
            "vector": route.get("vector", random_vec()),
            "success_count": 1,
        })


# ==========================================================================
# 决策层 — 多路线四维评分
# ==========================================================================
class DecisionLayer:
    """为每个步骤生成多条路线，四维评分选最优"""

    # 路线风格池
    ROUTE_STYLES = [
        "激进突进", "保守稳健", "迂回包抄", "正面突破",
        "侧翼迂回", "降维打击", "升维俯瞰", "微观拆解",
        "宏观统筹", "类比迁移", "逆向推理", "直觉跳跃",
    ]

    def __init__(self, memory: MemoryLayer):
        self.memory = memory

    def generate_routes(self, step: Dict, query_vec: List[float], ego_vec: List[float]) -> List[Dict]:
        """为单个步骤生成3-5条候选路线"""
        n_routes = random.randint(3, 5)
        routes = []

        # 第一条路线来自记忆召回
        mem_route = self.memory.recall(query_vec)
        mem_route["vector"] = mem_route.get("vector", random_vec())
        routes.append(mem_route)

        # 其余路线随机生成
        for i in range(n_routes - 1):
            style = random.choice(self.ROUTE_STYLES)
            routes.append({
                "id": f"R{i+1}",
                "name": style,
                "desc": f"{style}路线",
                "vector": vec_mix(random_vec(), ego_vec, 0.3),
                "source": "generated",
            })

        return routes

    def score_routes(self, routes: List[Dict], query_vec: List[float], ego_vec: List[float]) -> List[Tuple[float, Dict]]:
        """
        四维评分：
          记忆维度(30%): 与查询的相似度
          风险维度(25%): 越保守越安全（激进路线扣分）
          效率维度(25%): 与Ego的一致性（越对齐越高效）
          新颖维度(20%): 随机扰动（鼓励探索）
        """
        scored = []
        for route in routes:
            mem_score = cos_sim(query_vec, route.get("vector", random_vec()))

            # 风险：激进类路线风险高
            risky_names = {"激进突进", "直觉跳跃", "降维打击", "逆向推理"}
            risk_score = 0.3 if route["name"] in risky_names else 0.8

            # 效率：与ego对齐度
            eff_score = (cos_sim(ego_vec, route.get("vector", random_vec())) + 1) / 2

            # 新颖：随机
            novelty_score = random.uniform(0.2, 0.9)

            total = (
                mem_score * 0.30
                + risk_score * 0.25
                + eff_score * 0.25
                + novelty_score * 0.20
            )
            total = max(0, min(1, total))

            route["scores"] = {
                "memory": round(mem_score, 2),
                "risk": round(risk_score, 2),
                "efficiency": round(eff_score, 2),
                "novelty": round(novelty_score, 2),
                "total": round(total, 3),
            }
            scored.append((total, route))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def decide(self, step: Dict, query_vec: List[float], ego_vec: List[float]) -> Tuple[Dict, List]:
        """生成路线 → 评分 → 选Top"""
        routes = self.generate_routes(step, query_vec, ego_vec)
        scored = self.score_routes(routes, query_vec, ego_vec)
        chosen = scored[0][1]
        return chosen, scored


# ==========================================================================
# 思考层 — 第三人称后台监管
# ==========================================================================
class ThinkingLayer:
    """第三人称后台思考：监控、审计、干预"""

    def __init__(self):
        self.hard_log: List[Dict] = []     # 审计日志
        self.soft_log: List[Dict] = []    # 第三人称旁白
        self.interventions: List[Dict] = []  # 干预记录

    # ---- 审计 ----
    def audit_step(self, step: Dict, chosen_route: Dict, all_scored: List) -> Dict:
        """审计单个步骤的决策"""
        audit = {
            "tick": step.get("tick", 0),
            "step_id": step["id"],
            "step_type": step["type"],
            "chosen": chosen_route["name"],
            "chosen_score": chosen_route["scores"]["total"],
            "candidates": [(r[1]["name"], r[1]["scores"]["total"]) for r in all_scored],
            "verdict": "pass",
            "note": "",
        }

        # 思考判断1: 如果Top分和第二名差距很小，标记"犹豫"
        if len(all_scored) >= 2:
            gap = all_scored[0][0] - all_scored[1][0]
            if gap < 0.03:
                audit["verdict"] = "uncertain"
                audit["note"] = f"前两名差距仅{gap:.3f}，决策不稳定"

        # 思考判断2: 如果选中的风险维度极低，标记"高风险"
        if chosen_route["scores"].get("risk", 1) < 0.4:
            if random.random() < 0.5:
                audit["verdict"] = "warning"
                audit["note"] = f"高风险路线({chosen_route['name']})，风险维度={chosen_route['scores']['risk']}"

        # 思考判断3: 随机元认知抽检（10%概率深度审查）
        if random.random() < 0.10:
            audit["verdict"] = "review"
            audit["note"] = "元认知抽检：第三人称视角审视此决策合理性"

        self.hard_log.append(audit)
        return audit

    # ---- 干预 ----
    def maybe_intervene(self, step: Dict, audit: Dict, all_scored: List) -> Optional[Dict]:
        """根据审计结果决定是否干预"""
        if audit["verdict"] in ("warning", "uncertain") and len(all_scored) >= 2:
            # 强制换备胎（第二名）
            backup = all_scored[1][1]
            intervention = {
                "tick": step.get("tick", 0),
                "step_id": step["id"],
                "action": "force_swap",
                "from": audit["chosen"],
                "to": backup["name"],
                "reason": audit["note"],
            }
            self.interventions.append(intervention)
            return backup

        return None

    # ---- 旁白 ----
    def narrate(self, tick: int, step: Dict, chosen: Dict, audit: Dict, intervened: bool):
        """生成第三人称旁白"""
        if intervened:
            thought = (
                f"  [思考·旁白] 第{tick}拍：{step['type']}本想走'{audit['chosen']}'，"
                f"但第三人称监管发现{audit['note']}，强制换为'{chosen['name']}'。"
                f"它自己并不知道这个切换——它以为这就是自己的选择。"
            )
        elif audit["verdict"] == "review":
            thought = (
                f"  [思考·旁白] 第{tick}拍：{step['type']}选了'{chosen['name']}'。"
                f"第三人称视角在后台默默审视：这个选择是否真的合理？还是只是向量运算的巧合？"
            )
        else:
            thought = (
                f"  [思考·旁白] 第{tick}拍：{step['type']}走'{chosen['name']}'路线，"
                f"评分{chosen['scores']['total']}。决策顺畅，无明显犹豫。"
            )
        self.soft_log.append({"tick": tick, "step": step["type"], "thought": thought})
        return thought


# ==========================================================================
# 行为层 — 20步规划 + 非顺序并行执行
# ==========================================================================
STEP_TEMPLATES = [
    # (type, base_priority, dependencies_indices)
    # dependencies_indices 指向 STEP_TEMPLATES 的索引（同拍可并行）
    ("意图识别",     9, []),
    ("上下文解析",   8, []),
    ("记忆检索",     8, [0]),       # 依赖意图识别
    ("情感基调",     7, [1]),       # 依赖上下文解析
    ("知识图谱",     7, [0, 1]),    # 依赖意图+上下文
    ("假设生成",     6, [2, 3]),    # 依赖记忆+情感
    ("逻辑推演",     6, [4]),       # 依赖知识图谱
    ("类比联想",     5, [2, 4]),    # 依赖记忆+知识
    ("风险评估",     6, [5, 6]),    # 依赖假设+逻辑
    ("创意发散",     4, [5, 7]),    # 依赖假设+类比
    ("约束检查",     7, [5, 6, 8]), # 依赖假设+逻辑+风险
    ("路径规划A",    5, [8, 10]),   # 依赖风险+约束
    ("路径规划B",    5, [8, 10]),   # 与A并行
    ("路径规划C",    5, [9, 10]),   # 依赖创意+约束（与A/B不完全同构）
    ("优先级排序",   6, [11, 12, 13]),  # 依赖三条路径
    ("备选评估",     4, [11, 12, 13]),  # 与排序并行
    ("执行决策",     8, [14, 15]),  # 依赖排序+备选
    ("结果验证",     7, [16]),       # 依赖执行
    ("自我反思",     3, [16, 17]),  # 依赖执行+验证
    ("输出合成",     9, [17, 18]),  # 依赖验证+反思
]


class BehaviorLayer:
    """20步规划 + 依赖图 + 非顺序并行执行"""

    def __init__(self):
        self.steps: List[Dict] = []
        self._build_steps()

    def _build_steps(self):
        """构建20个步骤及其依赖关系"""
        for i, (stype, priority, deps) in enumerate(STEP_TEMPLATES):
            self.steps.append({
                "id": f"S{i+1:02d}",
                "type": stype,
                "priority": priority,
                "dep_ids": [f"S{d+1:02d}" for d in deps],
                "status": "pending",   # pending / running / done / skipped
                "result": None,
                "tick": 0,
            })

    def get_ready_steps(self, done_ids: Set[str]) -> List[Dict]:
        """获取所有依赖已满足、可以执行的步骤"""
        ready = []
        for step in self.steps:
            if step["status"] != "pending":
                continue
            deps_met = all(d in done_ids for d in step["dep_ids"])
            if deps_met:
                ready.append(step)
        # 按优先级排序（高优先级先执行）
        ready.sort(key=lambda s: s["priority"], reverse=True)
        return ready

    def mark_done(self, step: Dict, result: Dict):
        step["status"] = "done"
        step["result"] = result

    def summary(self) -> Dict:
        done = sum(1 for s in self.steps if s["status"] == "done")
        return {"total": len(self.steps), "done": done}


# ==========================================================================
# 主引擎 — 四象协同
# ==========================================================================
class NexusOmegaV2:
    """
    Nexus-Ω V2 四象认知引擎

    行为(Behavior) → 规划20步，非顺序并行执行
    决策(Decision) → 多路线四维评分
    记忆(Memory)   → 经验/随机/默认三层
    思考(Thinking)  → 第三人称后台监管
    """

    def __init__(self):
        self.memory = MemoryLayer()
        self.decision = DecisionLayer(self.memory)
        self.behavior = BehaviorLayer()
        self.thinking = ThinkingLayer()
        self.ego_vector = random_vec()
        self.query_vector = random_vec()

    def run(self, user_input: str):
        print(f"\n{'='*60}")
        print(f"  Nexus-Ω V2 四象认知引擎")
        print(f"  用户输入: {user_input}")
        print(f"{'='*60}")

        self.query_vector = random_vec()
        self.ego_vector = random_vec()

        # --- 预览20步规划 ---
        print(f"\n{'─'*60}")
        print("【行为层】20步规划蓝图（按优先级排序，但非顺序执行）:")
        print(f"{'─'*60}")
        sorted_steps = sorted(self.behavior.steps, key=lambda s: s["priority"], reverse=True)
        for s in sorted_steps:
            deps = s["dep_ids"] if s["dep_ids"] else "无"
            print(f"  {s['id']} [{s['priority']}] {s['type']:8s}  依赖: {deps}")

        # --- 依赖拓扑 ---
        print(f"\n依赖拓扑 → 非顺序执行路径:")
        for s in self.behavior.steps:
            if s["dep_ids"]:
                print(f"  {s['dep_ids']} → {s['id']} ({s['type']})")
            else:
                print(f"  [起点] {s['id']} ({s['type']})")

        # --- 执行循环 ---
        print(f"\n{'─'*60}")
        print("【执行开始】按依赖关系并行推进")
        print(f"{'─'*60}")

        done_ids: Set[str] = set()
        tick = 0

        while len(done_ids) < len(self.behavior.steps):
            tick += 1
            ready = self.behavior.get_ready_steps(done_ids)

            if not ready:
                # 死锁保护（不应该发生）
                print(f"  [警告] 第{tick}拍无可用步骤，跳过")
                break

            # 当前拍可并行执行的步骤
            parallel_count = len(ready)
            batch_desc = [f"{s['id']}:{s['type']}" for s in ready]

            print(f"\n{'='*60}")
            print(f"  第 {tick} 拍 | {parallel_count}步并行: {batch_desc}")
            print(f"{'='*60}")

            for step in ready:
                step["tick"] = tick
                step["status"] = "running"
                time.sleep(0.15)  # 模拟计算延迟

                # --- 决策层：生成路线 + 评分 ---
                chosen, all_scored = self.decision.decide(
                    step, self.query_vector, self.ego_vector
                )

                # --- 记忆层日志 ---
                mem_recall = self.memory.recall_log[-1] if self.memory.recall_log else ""
                print(f"\n  [{step['id']}] {step['type']}")
                print(f"    {mem_recall}")
                print(f"    决策候选:")
                for score, route in all_scored:
                    marker = ">>>" if route is chosen else "   "
                    s = route["scores"]
                    print(f"    {marker} {route['name']:8s} "
                          f"记忆={s['memory']:.2f} 风险={s['risk']:.2f} "
                          f"效率={s['efficiency']:.2f} 新颖={s['novelty']:.2f} "
                          f"总分={s['total']:.3f}")

                # --- 思考层：审计 ---
                audit = self.thinking.audit_step(step, chosen, all_scored)
                verdict_icon = {"pass": "OK", "warning": "WARN", "uncertain": "?", "review": "EYE"}[audit["verdict"]]
                print(f"    [思考审计] {verdict_icon} {audit['verdict'].upper()}"
                      + (f" — {audit['note']}" if audit["note"] else ""))

                # --- 思考层：可能干预 ---
                intervened = False
                if audit["verdict"] in ("warning", "uncertain"):
                    backup = self.thinking.maybe_intervene(step, audit, all_scored)
                    if backup:
                        chosen = backup
                        intervened = True
                        print(f"    [思考干预] 强制换挡: {audit['chosen']} → {chosen['name']}")
                        print(f"              原因: {audit['note']}")

                # --- 思考层：旁白 ---
                narration = self.thinking.narrate(tick, step, chosen, audit, intervened)
                print(narration)

                # --- Ego 吸收 ---
                self.ego_vector = vec_mix(
                    self.ego_vector,
                    chosen.get("vector", random_vec()),
                    0.25,
                )

                # --- 记忆强化 ---
                if step["priority"] >= 6:
                    self.memory.record_success(chosen)

                # --- 标记完成 ---
                self.behavior.mark_done(step, {"route": chosen["name"], "score": chosen["scores"]["total"]})
                done_ids.add(step["id"])

            # 进度
            prog = self.behavior.summary()
            print(f"\n  [进度] {prog['done']}/{prog['total']} 步完成")

        # --- 最终报告 ---
        self._final_report()

    def _final_report(self):
        print(f"\n{'='*60}")
        print("  【四象认知引擎 — 黑匣子解密】")
        print(f"{'='*60}")

        # 行为层：执行轨迹
        print(f"\n{'─' * 60}")
        print("【行为层】执行轨迹（非顺序并行）:")
        print(f"{'─' * 60}")
        for s in self.behavior.steps:
            result = s.get("result", {})
            route = result.get("route", "?")
            score = result.get("score", 0)
            print(f"  {s['id']} 拍{s['tick']} {s['type']:8s} → 路线:{route:8s} 评分:{score:.3f}")

        # 决策层：路线统计
        print(f"\n{'─' * 60}")
        print("【决策层】路线选择统计:")
        print(f"{'─' * 60}")
        route_counts: Dict[str, int] = {}
        for s in self.behavior.steps:
            r = s.get("result", {}).get("route", "?")
            route_counts[r] = route_counts.get(r, 0) + 1
        for route, count in sorted(route_counts.items(), key=lambda x: x[1], reverse=True):
            bar = "#" * count
            print(f"  {route:8s} {bar} ({count})")

        # 记忆层
        print(f"\n{'─' * 60}")
        print("【记忆层】召回记录:")
        print(f"{'─' * 60}")
        exp_count = sum(1 for r in self.memory.recall_log if "经验回溯" in r)
        rand_count = sum(1 for r in self.memory.recall_log if "随机探索" in r)
        def_count = sum(1 for r in self.memory.recall_log if "默认路线" in r)
        print(f"  经验回溯: {exp_count}次 | 随机探索: {rand_count}次 | 默认路线: {def_count}次")
        print(f"  经验库规模: {len(self.memory.experiences)}条")
        for exp in self.memory.experiences:
            print(f"    {exp['id']} {exp['name']:8s} 成功{exp['success_count']}次")

        # 思考层
        print(f"\n{'─' * 60}")
        print("【思考层】审计 + 干预记录:")
        print(f"{'─' * 60}")
        pass_count = sum(1 for a in self.thinking.hard_log if a["verdict"] == "pass")
        warn_count = sum(1 for a in self.thinking.hard_log if a["verdict"] == "warning")
        uncertain_count = sum(1 for a in self.thinking.hard_log if a["verdict"] == "uncertain")
        review_count = sum(1 for a in self.thinking.hard_log if a["verdict"] == "review")
        print(f"  审计: 通过={pass_count} 警告={warn_count} 犹豫={uncertain_count} 元认知抽检={review_count}")
        print(f"  干预次数: {len(self.thinking.interventions)}")
        for iv in self.thinking.interventions:
            print(f"    拍{iv['tick']} {iv['step_id']}: {iv['from']} → {iv['to']} ({iv['reason']})")

        print(f"\n{'─' * 60}")
        print("【思考层】第三人称旁白精选:")
        print(f"{'─' * 60}")
        for entry in self.thinking.soft_log:
            print(entry["thought"])

        print(f"\n最终Ego向量(末那识我执)前4维: {[round(v, 3) for v in self.ego_vector[:4]]}...")
        print(f"{'='*60}")


# ==========================================================================
# 运行入口
# ==========================================================================
if __name__ == "__main__":
    random.seed(42)

    engine = NexusOmegaV2()
    engine.run("如何解决一个复杂的逻辑悖论？")
