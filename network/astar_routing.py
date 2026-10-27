import heapq
import itertools
import math


class AStarRouter:
    """Graph-based A* router with support for link failures."""

    def __init__(self, positions):
        # positions: {node: (x, y)}
        self.positions = positions
        self.graph = {node: {} for node in positions}
        self._failed_links = set()
        self._failed_nodes = set()
        self._route_requests = {}
        self.active_routes = {}

    def add_link(self, node_a, node_b, cost=None):
        """Add a bidirectional link between two nodes."""
        if node_a not in self.graph or node_b not in self.graph:
            raise ValueError("Both nodes must exist in positions")

        if cost is None:
            cost = self.distance(node_a, node_b)

        if not math.isfinite(cost) or cost <= 0:
            raise ValueError("Link cost must be a finite positive number")

        self.graph[node_a][node_b] = cost
        self.graph[node_b][node_a] = cost

    def distance(self, node_a, node_b):
        x1, y1 = self.positions[node_a]
        x2, y2 = self.positions[node_b]
        return math.hypot(x2 - x1, y2 - y1)

    def heuristic(self, node, goal):
        """Return an admissible distance estimate for the current graph."""
        return self._heuristic_scale() * self.distance(node, goal)

    def _link_key(self, node_a, node_b):
        return frozenset((node_a, node_b))

    def _link_is_available(self, node_a, node_b):
        return (
            self._link_key(node_a, node_b) not in self._failed_links
            and node_a not in self._failed_nodes
            and node_b not in self._failed_nodes
        )

    def _heuristic_scale(self):
        scale = float("inf")
        for source, neighbors in self.graph.items():
            for target, cost in neighbors.items():
                if not self._link_is_available(source, target):
                    continue
                distance = self.distance(source, target)
                if distance > 0:
                    scale = min(scale, cost / distance)
        return 0 if math.isinf(scale) else scale

    def find_path(self, start, goal):
        """Return the lowest-cost path and its cost, or ([], inf) if unreachable."""
        if start not in self.graph or goal not in self.graph:
            raise ValueError("Unknown start or destination node")
        if start in self._failed_nodes or goal in self._failed_nodes:
            return [], float("inf")

        heuristic_scale = self._heuristic_scale()
        sequence = itertools.count()
        frontier = [
            (heuristic_scale * self.distance(start, goal), 0, next(sequence), start)
        ]
        parent = {}
        best_cost = {start: 0}
        closed = set()

        while frontier:
            _, cost_so_far, _, current = heapq.heappop(frontier)

            if current in closed:
                continue

            if current == goal:
                path = [goal]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                return path, cost_so_far

            closed.add(current)

            for neighbor, link_cost in self.graph[current].items():
                if not self._link_is_available(current, neighbor):
                    continue
                if neighbor in closed:
                    continue

                new_cost = cost_so_far + link_cost

                if new_cost < best_cost.get(neighbor, float("inf")):
                    best_cost[neighbor] = new_cost
                    parent[neighbor] = current
                    estimate = new_cost + heuristic_scale * self.distance(
                        neighbor, goal
                    )
                    heapq.heappush(
                        frontier, (estimate, new_cost, next(sequence), neighbor)
                    )

        return [], float("inf")

    def request_route(self, start, goal):
        """Track a route request so failures automatically recalculate its path."""
        if start not in self.graph or goal not in self.graph:
            raise ValueError("Unknown start or destination node")
        key = (start, goal)
        self._route_requests[key] = (start, goal)
        self.active_routes[key] = self.find_path(start, goal)
        return self.active_routes[key]

    def _refresh_active_routes(self):
        for key, (start, goal) in self._route_requests.items():
            self.active_routes[key] = self.find_path(start, goal)

    def fail_link(self, node_a, node_b):
        """Mark a bidirectional link failed and recalculate active routes."""
        if node_b not in self.graph.get(node_a, {}):
            return False

        link = self._link_key(node_a, node_b)
        if link in self._failed_links:
            return False
        self._failed_links.add(link)
        self._refresh_active_routes()
        return True

    def recover_link(self, node_a, node_b):
        """Restore a failed bidirectional link and recalculate active routes."""
        if node_b not in self.graph.get(node_a, {}):
            return False

        link = self._link_key(node_a, node_b)
        if link not in self._failed_links:
            return False
        self._failed_links.remove(link)
        self._refresh_active_routes()
        return True

    def fail_node(self, node):
        """Mark a node unavailable and recalculate active routes."""
        if node not in self.graph:
            raise ValueError("Unknown node")
        if node in self._failed_nodes:
            return False
        self._failed_nodes.add(node)
        self._refresh_active_routes()
        return True

    def recover_node(self, node):
        """Restore a node and recalculate active routes."""
        if node not in self.graph:
            raise ValueError("Unknown node")
        if node not in self._failed_nodes:
            return False
        self._failed_nodes.remove(node)
        self._refresh_active_routes()
        return True
