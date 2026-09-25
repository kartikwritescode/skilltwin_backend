from typing import List, Dict, Tuple, Set, Any, Optional
from collections import deque
from app.core.logging import logger
from app.core.db_models import MicroSubgraphModel


class CyclicDependencyError(Exception):
    """Raised when a topological cycle is detected in the curriculum graph."""
    pass


class MissingPrerequisiteError(Exception):
    """Raised when an edge references a non-existent antecedent node."""
    pass


class DisconnectedGraphError(Exception):
    """Raised when a required graph component is disconnected or unreachable."""
    pass


class TopologicalAssembler:
    """
    Deterministic, 0-token Directed Acyclic Graph (DAG) Assembly Engine.
    Implements Kahn's Algorithm for cycle verification, transitive reduction,
    and multi-subgraph topological stitching.
    """

    def verify_and_sort_dag(
        self, nodes: List[Dict[str, Any]], edges: List[Tuple[str, str]]
    ) -> List[str]:
        """
        Validates graph acyclicity using Kahn's Algorithm.
        Returns a topologically sorted list of node IDs.
        Raises CyclicDependencyError if any directed cycle exists.
        Raises MissingPrerequisiteError if edges reference unknown node IDs.
        """
        node_ids = {n["id"] if isinstance(n, dict) else str(n) for n in nodes}
        in_degree = {nid: 0 for nid in node_ids}
        adj_list: Dict[str, List[str]] = {nid: [] for nid in node_ids}

        for src, dst in edges:
            if src not in node_ids:
                raise MissingPrerequisiteError(f"Prerequisite source node '{src}' does not exist in graph")
            if dst not in node_ids:
                raise MissingPrerequisiteError(f"Prerequisite target node '{dst}' does not exist in graph")
            in_degree[dst] += 1
            adj_list[src].append(dst)

        # Queue of nodes with no incoming dependencies (in-degree == 0)
        # Sort queue deterministically
        queue = deque(sorted([nid for nid, deg in in_degree.items() if deg == 0]))
        sorted_order: List[str] = []

        while queue:
            curr = queue.popleft()
            sorted_order.append(curr)

            # Sort neighbors for deterministic topological ordering
            for neighbor in sorted(adj_list[curr]):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(sorted_order) != len(node_ids):
            # Graph has cycles! Extract the cycle path for diagnostic precision
            unresolved = {nid for nid, deg in in_degree.items() if deg > 0}
            cycle_path = self._find_cycle_path(unresolved, adj_list)
            cycle_str = " -> ".join(cycle_path) if cycle_path else str(list(unresolved)[:5])
            raise CyclicDependencyError(f"Curriculum graph contains cyclic dependencies: {cycle_str}")

        return sorted_order

    def _find_cycle_path(
        self, unresolved: Set[str], adj_list: Dict[str, List[str]]
    ) -> List[str]:
        """Traces and extracts a concrete directed cycle path among unresolved nodes."""
        visited: Set[str] = set()
        stack: List[str] = []
        stack_set: Set[str] = set()

        def dfs(node: str) -> Optional[List[str]]:
            visited.add(node)
            stack.append(node)
            stack_set.add(node)

            for neighbor in adj_list.get(node, []):
                if neighbor in unresolved:
                    if neighbor in stack_set:
                        # Found cycle
                        idx = stack.index(neighbor)
                        return stack[idx:] + [neighbor]
                    if neighbor not in visited:
                        res = dfs(neighbor)
                        if res:
                            return res

            stack.pop()
            stack_set.remove(node)
            return None

        for n in sorted(unresolved):
            if n not in visited:
                cycle = dfs(n)
                if cycle:
                    return cycle
        return list(unresolved)

    def transitive_reduction(
        self, nodes: List[str], edges: Set[Tuple[str, str]]
    ) -> Set[Tuple[str, str]]:
        """
        Eliminates redundant prerequisite edges in a DAG.
        An edge (u, v) is redundant if there exists an alternate path of length >= 2 from u to v.
        """
        node_set = set(nodes)
        adj: Dict[str, Set[str]] = {n: set() for n in node_set}
        for u, v in edges:
            if u in node_set and v in node_set:
                adj[u].add(v)

        # Precompute reachability from each node via BFS
        def get_reachable(start_node: str) -> Set[str]:
            reachable: Set[str] = set()
            q = deque([start_node])
            while q:
                curr = q.popleft()
                for nxt in adj.get(curr, set()):
                    if nxt not in reachable:
                        reachable.add(nxt)
                        q.append(nxt)
            return reachable

        reduced_edges: Set[Tuple[str, str]] = set()

        for u in node_set:
            neighbors = adj[u]
            if not neighbors:
                continue

            for v in neighbors:
                # Direct edge (u, v) is redundant if v is reachable from any neighbor w in neighbors \ {v}
                is_redundant = False
                for w in neighbors:
                    if w == v:
                        continue
                    # Check if v is reachable from w
                    if v in get_reachable(w):
                        is_redundant = True
                        break

                if not is_redundant:
                    reduced_edges.add((u, v))

        return reduced_edges

    def stitch_subgraphs(
        self, subgraphs: List[MicroSubgraphModel]
    ) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
        """
        Stitches an arbitrary list of MicroSubgraphModel entities into a single, unified DAG.
        Resolves inter-subgraph prerequisites, enforces acyclicity, applies transitive reduction,
        and assigns contiguous 0..N order_index.
        Returns: (nodes, reduced_edges)
        """
        if not subgraphs:
            return [], []

        slug_to_sg: Dict[str, MicroSubgraphModel] = {sg.slug: sg for sg in subgraphs}
        raw_nodes: List[Dict[str, Any]] = []
        raw_edges: Set[Tuple[str, str]] = set()

        # Build milestone nodes for each micro-subgraph
        for sg in subgraphs:
            node_id = f"{sg.slug}__core"
            concept_id = f"concept_{sg.slug}"
            raw_nodes.append({
                "id": node_id,
                "subgraph_id": sg.id,
                "concept_id": concept_id,
                "title": sg.title,
                "tier": sg.tier,
                "estimated_minutes": sg.estimated_minutes,
                "subgraph_slug": sg.slug,
                "state": "LOCKED",
            })

        # Connect inter-subgraph edges based on prerequisites
        for sg in subgraphs:
            target_node_id = f"{sg.slug}__core"
            for prereq_slug in (sg.prerequisites or []):
                if prereq_slug in slug_to_sg:
                    source_node_id = f"{prereq_slug}__core"
                    raw_edges.add((source_node_id, target_node_id))

        # 1. Cycle Verification & Topological Sort
        sorted_ids = self.verify_and_sort_dag(raw_nodes, list(raw_edges))

        # 2. Transitive Reduction
        reduced_edges_set = self.transitive_reduction(sorted_ids, raw_edges)
        reduced_edges = sorted(list(reduced_edges_set))

        # 3. Contiguous Order Index Assignment & Initial State Resolution
        node_map = {n["id"]: n for n in raw_nodes}
        topological_nodes: List[Dict[str, Any]] = []

        # Find initial available nodes (zero in-degree in reduced edges)
        target_ids = {dst for _, dst in reduced_edges}

        for idx, nid in enumerate(sorted_ids):
            node = node_map[nid].copy()
            node["order_index"] = idx
            # If node has no prerequisites, mark AVAILABLE initially
            if nid not in target_ids:
                node["state"] = "AVAILABLE"
            else:
                node["state"] = "LOCKED"
            topological_nodes.append(node)

        logger.debug(
            f"ADAG stitched {len(topological_nodes)} nodes with {len(reduced_edges)} reduced edges"
        )
        return topological_nodes, reduced_edges


adag_assembler = TopologicalAssembler()
