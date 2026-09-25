import math
from typing import List, Dict, Tuple, Set, Any, Optional
from collections import deque
from app.core.logging import logger
from app.services.adag_assembler import adag_assembler


class CPMPacingService:
    """
    Critical Path Method (CPM) and Learner Capacity Constraint Pruner.
    Computes Earliest/Latest schedule bounds, slack/float, critical paths,
    and deterministically prunes elective/advanced topics to fit hard time budgets.
    """

    def calculate_capacity_hours(
        self, days_until_deadline: int, daily_budget_minutes: int
    ) -> float:
        """
        Calculates maximum learner capacity in hours:
        Capacity = (Days * Daily Budget) / 60
        """
        if days_until_deadline <= 0 or daily_budget_minutes <= 0:
            return 0.0
        return round((days_until_deadline * daily_budget_minutes) / 60.0, 2)

    def calculate_critical_path(
        self, nodes: List[Dict[str, Any]], edges: List[Tuple[str, str]]
    ) -> Dict[str, Any]:
        """
        Computes CPM schedules for all nodes:
        - Earliest Start (ES) and Earliest Finish (EF)
        - Latest Start (LS) and Latest Finish (LF)
        - Slack / Float (S = LS - ES)
        - Identifies Critical Path nodes (S == 0) and total critical path duration.
        """
        if not nodes:
            return {
                "earliest_start": {},
                "earliest_finish": {},
                "latest_start": {},
                "latest_finish": {},
                "slack": {},
                "critical_node_ids": [],
                "critical_path_chain": [],
                "total_duration_minutes": 0,
                "total_duration_hours": 0.0,
            }

        # Step 0: Ensure nodes are topologically sorted
        sorted_ids = adag_assembler.verify_and_sort_dag(nodes, edges)
        node_map = {n["id"]: n for n in nodes}

        # Build adjacency and predecessor maps
        succ_map: Dict[str, List[str]] = {nid: [] for nid in sorted_ids}
        pred_map: Dict[str, List[str]] = {nid: [] for nid in sorted_ids}

        for src, dst in edges:
            if src in succ_map and dst in pred_map:
                succ_map[src].append(dst)
                pred_map[dst].append(src)

        # Durations in minutes
        duration: Dict[str, int] = {
            nid: int(node_map[nid].get("estimated_minutes", 30)) for nid in sorted_ids
        }

        # Step 1: Forward Pass (ES, EF)
        es: Dict[str, int] = {}
        ef: Dict[str, int] = {}

        for nid in sorted_ids:
            preds = pred_map[nid]
            if not preds:
                es[nid] = 0
            else:
                es[nid] = max(ef[p] for p in preds)
            ef[nid] = es[nid] + duration[nid]

        # Total duration is the maximum EF among all nodes
        total_duration_minutes = max(ef.values()) if ef else 0

        # Step 2: Backward Pass (LS, LF)
        ls: Dict[str, int] = {}
        lf: Dict[str, int] = {}

        for nid in reversed(sorted_ids):
            succs = succ_map[nid]
            if not succs:
                lf[nid] = total_duration_minutes
            else:
                lf[nid] = min(ls[s] for s in succs)
            ls[nid] = lf[nid] - duration[nid]

        # Step 3: Slack / Total Float (S = LS - ES)
        slack: Dict[str, int] = {}
        critical_node_ids: List[str] = []

        for nid in sorted_ids:
            s = ls[nid] - es[nid]
            slack[nid] = s
            if s == 0:
                critical_node_ids.append(nid)

        # Step 4: Trace the primary critical path chain
        critical_chain: List[str] = []
        curr_crit = [nid for nid in sorted_ids if es[nid] == 0 and slack[nid] == 0]
        if curr_crit:
            curr = curr_crit[0]
            critical_chain.append(curr)
            while succ_map[curr]:
                crit_succs = [s for s in succ_map[curr] if slack[s] == 0 and es[s] == ef[curr]]
                if not crit_succs:
                    # Alternative critical path branch
                    crit_succs = [s for s in succ_map[curr] if slack[s] == 0]
                if crit_succs:
                    curr = crit_succs[0]
                    critical_chain.append(curr)
                else:
                    break

        return {
            "earliest_start": es,
            "earliest_finish": ef,
            "latest_start": ls,
            "latest_finish": lf,
            "slack": slack,
            "critical_node_ids": critical_node_ids,
            "critical_path_chain": critical_chain,
            "total_duration_minutes": total_duration_minutes,
            "total_duration_hours": round(total_duration_minutes / 60.0, 2),
        }

    def prune_to_fit_capacity(
        self,
        nodes: List[Dict[str, Any]],
        edges: List[Tuple[str, str]],
        target_deadline_days: int,
        daily_budget_minutes: int,
    ) -> Dict[str, Any]:
        """
        Prunes elective and non-critical advanced topics when total curriculum duration
        exceeds learner capacity.
        Preserves mandatory critical path nodes and compresses durations if needed.
        """
        if not nodes:
            return {
                "pruned_nodes": [],
                "pruned_edges": [],
                "archived_node_ids": [],
                "pacing_metrics": {
                    "capacity_hours": 0.0,
                    "total_duration_hours": 0.0,
                    "compression_factor": 1.0,
                    "is_pruned": False,
                    "projected_completion_days": 0,
                },
            }

        capacity_hours = self.calculate_capacity_hours(target_deadline_days, daily_budget_minutes)
        total_minutes = sum(n.get("estimated_minutes", 30) for n in nodes)
        total_hours = total_minutes / 60.0

        # If already within budget, return untouched
        if total_hours <= capacity_hours or capacity_hours <= 0:
            return {
                "pruned_nodes": nodes,
                "pruned_edges": edges,
                "archived_node_ids": [],
                "pacing_metrics": {
                    "capacity_hours": capacity_hours,
                    "total_duration_hours": round(total_hours, 2),
                    "compression_factor": 1.0,
                    "is_pruned": False,
                    "projected_completion_days": math.ceil(total_minutes / max(daily_budget_minutes, 1)),
                },
            }

        # Calculate CPM metrics
        cpm = self.calculate_critical_path(nodes, edges)
        slack = cpm["slack"]
        critical_ids = set(cpm["critical_node_ids"])

        node_map = {n["id"]: dict(n) for n in nodes}
        active_ids = set(node_map.keys())
        archived_node_ids: List[str] = []

        # Build adjacency maps for dependency bridging
        pred_map: Dict[str, Set[str]] = {nid: set() for nid in active_ids}
        succ_map: Dict[str, Set[str]] = {nid: set() for nid in active_ids}
        for u, v in edges:
            if u in active_ids and v in active_ids:
                succ_map[u].add(v)
                pred_map[v].add(u)

        current_minutes = total_minutes
        target_minutes = capacity_hours * 60.0

        # Step 1: Prune elective nodes first (electives are never mandatory)
        elective_candidates = [
            nid for nid in active_ids
            if node_map[nid].get("tier") == "elective"
        ]
        # Sort electives by largest slack first (non-critical before critical)
        elective_candidates.sort(key=lambda nid: slack.get(nid, 0), reverse=True)

        for nid in elective_candidates:
            if current_minutes <= target_minutes:
                break
            active_ids.remove(nid)
            archived_node_ids.append(nid)
            current_minutes -= node_map[nid].get("estimated_minutes", 30)

        # Step 2: Prune advanced nodes (sort by non-zero slack first, then critical advanced)
        if current_minutes > target_minutes:
            advanced_candidates = [
                nid for nid in active_ids
                if node_map[nid].get("tier") == "advanced"
            ]
            advanced_candidates.sort(key=lambda nid: slack.get(nid, 0), reverse=True)

            for nid in advanced_candidates:
                if current_minutes <= target_minutes:
                    break
                active_ids.remove(nid)
                archived_node_ids.append(nid)
                current_minutes -= node_map[nid].get("estimated_minutes", 30)

        # Step 3: Prune core nodes with non-zero slack (S > 0) if still exceeding capacity
        if current_minutes > target_minutes:
            core_slack_candidates = [
                nid for nid in active_ids
                if node_map[nid].get("tier") == "core" and slack.get(nid, 0) > 0
            ]
            core_slack_candidates.sort(key=lambda nid: slack.get(nid, 0), reverse=True)

            for nid in core_slack_candidates:
                if current_minutes <= target_minutes:
                    break
                active_ids.remove(nid)
                archived_node_ids.append(nid)
                current_minutes -= node_map[nid].get("estimated_minutes", 30)

        # Step 4: Duration compression for remaining nodes if still over budget
        compression_factor = 1.0
        if current_minutes > target_minutes:
            # Compress practical objectives up to max factor 0.80
            compression_factor = max(0.80, target_minutes / max(current_minutes, 1))
            current_minutes = 0
            for nid in active_ids:
                orig = node_map[nid].get("estimated_minutes", 30)
                compressed = max(15, int(round(orig * compression_factor)))
                node_map[nid]["estimated_minutes"] = compressed
                current_minutes += compressed

        # Step 5: Dependency bridging for removed nodes
        # If node P is pruned: for all u in Pred(P) and v in Succ(P), add bridge (u, v)
        bridged_edges: Set[Tuple[str, str]] = set()
        for u, v in edges:
            if u in active_ids and v in active_ids:
                bridged_edges.add((u, v))

        for pruned_id in archived_node_ids:
            preds = [u for u in pred_map.get(pruned_id, set()) if u in active_ids]
            succs = [v for v in succ_map.get(pruned_id, set()) if v in active_ids]
            for p in preds:
                for s in succs:
                    bridged_edges.add((p, s))

        # Step 6: Topological verification and transitive reduction
        retained_nodes = [node_map[nid] for nid in active_ids]
        sorted_retained_ids = adag_assembler.verify_and_sort_dag(retained_nodes, list(bridged_edges))
        reduced_edges_set = adag_assembler.transitive_reduction(sorted_retained_ids, bridged_edges)
        pruned_edges = sorted(list(reduced_edges_set))

        # Step 7: Contiguous order_index assignment
        retained_node_map = {n["id"]: n for n in retained_nodes}
        pruned_nodes: List[Dict[str, Any]] = []

        for idx, nid in enumerate(sorted_retained_ids):
            n = retained_node_map[nid]
            n["order_index"] = idx
            pruned_nodes.append(n)

        logger.info(
            f"CPM Pacing Pruner: pruned {len(archived_node_ids)} nodes. "
            f"Capacity: {capacity_hours}h, New Total: {round(current_minutes / 60.0, 2)}h "
            f"(Compression: {compression_factor:.2f})"
        )

        return {
            "pruned_nodes": pruned_nodes,
            "pruned_edges": pruned_edges,
            "archived_node_ids": archived_node_ids,
            "pacing_metrics": {
                "capacity_hours": capacity_hours,
                "total_duration_hours": round(current_minutes / 60.0, 2),
                "compression_factor": round(compression_factor, 2),
                "is_pruned": len(archived_node_ids) > 0 or compression_factor < 1.0,
                "projected_completion_days": math.ceil(current_minutes / max(daily_budget_minutes, 1)),
            },
        }


    prune_to_capacity = prune_to_fit_capacity


cpm_pacing_service = CPMPacingService()
