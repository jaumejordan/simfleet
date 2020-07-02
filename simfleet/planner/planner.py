"""
Develops a plan for a TransportAgent
"""
import heapq
from generators_utils import has_enough_autonomy, calculate_km_expense

# heapq.heappush(customers, (2, "Harry"))
# heapq.heappush(customers, (3, "Charles"))
# heapq.heappush(customers, (1, "Riya"))
# heapq.heappush(customers, (4, "Stacy"))

SPEED = 2000  # km/h


def meters_to_seconds(distance_in_meters):
    # km/h to m/s
    speed = SPEED / 3.6
    time = distance_in_meters / speed
    return time


# Given two lists of actions, returns the pick_up / move-to-dest tuple for the same customer
def get_couples(pick_up_actions, move_to_dest_actions):
    res = []
    for a in pick_up_actions:
        customer_id = a.get('attributes').get('customer_id')
        for b in move_to_dest_actions:
            if b.get('attributes').get('customer_id') == customer_id:
                res.append((a,b))
    return res


class Node:
    def __init__(self, parent):
        self.parent = parent
        self.agent_pos = None
        self.agent_autonomy = None
        self.init_time = 0.0
        self.end_time = None
        self.actions = []
        self.value = None
        self.children = []

    def print_node(self):
        print(
            f'(\tposition:\t{self.agent_pos}\n\tautonomy:\t{self.agent_autonomy}\n\tactions:\t{self.actions}\t),\t{self.value}')
        if self.children:
            print(f'children -----------------------')
            for n in self.children:
                n.print_node()
            print(f'--------------------------------')


class Planner:
    def __init__(self, actions_dic, routes_dic, agent_id, agent_pos, agent_autonomy, joint_plan=None):

        # Precalculated routes and actions
        self.actions_dic = actions_dic
        self.routes_dic = routes_dic

        # Transport agent attributes
        self.agent_id = agent_id
        self.agent_pos = agent_pos
        self.agent_autonomy = agent_autonomy

        # Table of goals
        self.table_of_goals = {}
        # Node heap
        self.open_nodes = []
        # Joint plan
        if joint_plan is None:
            joint_plan = []
        self.joint_plan = joint_plan
        # Best solution to prune tree
        self.best_solution = None

    def create_table_of_goals(self):
        return

    def fill_statistics(self, action, current_pos=None):
        if action.get('type') == 'PICK-UP':
            # distance from transport position to customer origin
            p1 = current_pos
            p2 = action.get('attributes').get('customer_origin')
            route = self.get_route(p1, p2)
            dist = route.get('distance')
            time = meters_to_seconds(dist)
            action['statistics']['dist'] = dist
            action['statistics']['time'] = time

        elif action.get('type') == 'MOVE-TO-DEST':
            # distance from customer_origin to customer_destination
            p1 = action.get('attributes').get('customer_origin')
            p2 = action.get('attributes').get('customer_dest')
            route = self.get_route(p1, p2)
            dist = route.get('distance')
            time = meters_to_seconds(dist)
            action['statistics']['dist'] = dist
            action['statistics']['time'] = time

        elif action.get('type') == 'MOVE-TO-STATION':
            # distance from transport position to station position
            p1 = current_pos
            p2 = action.get('attributes').get('station_position')
            route = self.get_route(p1, p2)
            dist = route.get('distance')
            time = meters_to_seconds(dist)
            action['statistics']['dist'] = dist
            action['statistics']['time'] = time

        elif action.get('type') == 'CHARGE':
            # time to complete the charge
            #   esta per a més endavant, que té més chicha

        return action

    def get_route(self, p1, p2):
        key = str(p1) + ":" + str(p2)
        route = self.routes_dic.get(key)
        if route is None:
            # En el futur, demanar la ruta al OSRM
            print("ERROR:: There is no route for key ", key, " in the routes_dic")
            exit()
        return route

    def reachable_goal(self, customer_id, pick_up_time):
        return self.table_of_goals.get(customer_id) > pick_up_time

    # Returns the f value of a node
    def evaluate_node(self):
        # Calculate g value w.r.t Joint plan + node actions
        # taking into account charging congestions (implementar a futur)
        g = 0
        # Calculate h value w.r.t Table of Goals + node end time
        h = 0
        return g+h

    def run(self):
        # CREATION OF INITIAL NODES
        #   We assume that autonomy is full at beginning, so initially we'll just consider one pick up action per every possible goal
        agent_actions = self.actions_dic.get(self.agent_id)

        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")
        # Fill actions statistics
        #   Calculates the time and distance according to agent's current pos/autonomy
        pick_up_actions = [self.fill_statistics(a) for a in pick_up_actions]
        move_to_dest_actions = [self.fill_statistics(a) for a in move_to_dest_actions]

        # Create the corresponding node per action
        #   Create node, fill values, evaluate, add to priority queue if possible
        for tup in get_couples(pick_up_actions, move_to_dest_actions):
            node = Node()
            node.agent_pos = self.agent_pos
            node.agent_autonomy = self.agent_autonomy
            node.actions = list(tup)

            # Calculate pick_up time and check table of goals
            pick_up_time = node.init_time + node.actions[-2].get('statistics').get('time')
            customer_id = node.actions[-2].get('attributes').get('customer_id')
            if not self.reachable_goal(customer_id, pick_up_time):
                # delete node object
                node = None
                break

            # Check autonomy
            #   only if initial autonomy is not full (implementar a futur)

            # Evaluate node
            value = self.evaluate_node(node)
            # Push node in the priority queue
            heapq.heappush(self.open_nodes, (value, node))

        # BUCLE PRINCIPAL
        while self.open_nodes:
            node = self.open_nodes.pop()
            self.generate_children(node)
        # TO BE CONTINUED...


if __name__ == '__main__':
    n1 = Node(None)
    n1.agent_pos = -90
    n1.agent_autonomy = 32

    n2 = Node(n1)
    n1.children.append(n2)

    n1.print_node()
